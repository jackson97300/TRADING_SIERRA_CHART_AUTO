"""mia_paper_trader.py — Paper trading bot qui suit le dashboard (v2 22/04/2026).

Suit les recommandations du dashboard MIA en temps reel :
- Prend un trade quand Conseil Global = ACHAT/VENTE AVEC freshness == "NEW"
  (state machine v1.5 fix 22/04 — evite signal persistent / FOMO)
- SL/TP via SLTPEngine (Tier 1/2 derriere mur + TP1 premier obstacle)
- Filtre expected_payoff_$ >= $2 (audit ES vs NQ 22/04)
- 3 micros tracking (realistic futur bot live)
- Cooldown 15 min post-close par symbol
- Circuit breaker 3 SL consec → pause 60 min par symbol
- Ecrit state.json pour consommation dashboard (endpoint /api/paper_trades)

Usage :
    python CORE/mia_paper_trader.py            # lance le paper trader
    python CORE/mia_paper_trader.py --stats
    python CORE/mia_paper_trader.py --stats --symbol NQ
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

# Import SLTPEngine (audit Tier1/2/3 sur 1349 barres, 07/03/2026)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from CORE.mia_sltp import SLTPEngine

# Systeme logs V2 (22/04 session)
try:
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("paper_trader", process="paper")
except Exception:
    _v2log = None

# Config
DASHBOARD_URL = "http://localhost:8503/api/dashboard"
POLL_INTERVAL = 10  # secondes entre chaque check
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "DATA", "PAPER_TRADES")
STATE_FILE = os.path.join(DATA_DIR, "state.json")  # bridge pour dashboard endpoint
TICK_SIZE = 0.25

# Ticks values par instrument
TICK_VALUE = {"ES": 1.25, "NQ": 0.50}

# Regles v2 (22/04) — consolidees apres audits agents
ENTRY_RULES = {
    "min_confidence": 0.50,
    "min_mtf_bears": 3,
    "min_mtf_bulls": 3,
    "freshness_required": "NEW",            # state machine v1.5 : NEW uniquement (pas PERSISTENT/EXPIRED)
    "max_positions_per_symbol": 1,
    "n_micros": 3,                          # 3 micros (realistic bot live futur)
    "min_expected_payoff_usd": 2.0,         # filtre audit ES vs NQ (22/04)
    "max_trades_per_day": 10,
    "cooldown_post_close_sec": 900,         # 15 min
    "circuit_breaker_losses": 3,            # 3 SL consec
    "circuit_breaker_pause_sec": 3600,      # 60 min pause
    "estimated_wr_initial": 0.45,           # conservateur avant 30 trades empiriques (review R4)
    "estimated_wr_rolling_min": 30,         # apres N trades, switch vers WR rolling reel
}


def get_dashboard():
    """Fetch le dashboard API."""
    import urllib.request
    try:
        r = urllib.request.urlopen(DASHBOARD_URL, timeout=10)
        return json.loads(r.read())
    except Exception as e:
        print(f"  Erreur fetch dashboard: {e}")
        return None


class PaperTrader:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.positions = {}  # {symbol: position_dict}
        self.today_trades = []
        self.date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        self.log_file = os.path.join(DATA_DIR, f"{self.date_str}_trades.jsonl")
        self.snapshot_file = os.path.join(DATA_DIR, f"{self.date_str}_snapshots.jsonl")
        self.trade_count = 0

        # v2 (22/04) : SLTPEngine par instrument (Tier 1/2 murs audites)
        self.sltp_engines = {
            "ES": SLTPEngine(symbol="ES"),
            "NQ": SLTPEngine(symbol="NQ"),
        }

        # v2 (22/04) : state machine cooldown + circuit breaker par symbol
        self._last_close_ts = {}                # sym -> timestamp
        self._consec_losses = {"ES": 0, "NQ": 0}
        self._circuit_pause_until = {}          # sym -> timestamp fin pause

        # v2 (22/04) : tracker signal_ids deja consommes (dedup cross-restart VPS)
        # Persiste sur disque (review R3 : sinon restart = re-entry meme signal_id)
        self._traded_signals_file = os.path.join(DATA_DIR, f"{self.date_str}_traded_signals.txt")
        self._traded_signal_ids = set()

        # Cleanup state.json.tmp orphelin si crash mi-write (review R5)
        tmp_state = STATE_FILE + ".tmp"
        if os.path.exists(tmp_state):
            try:
                os.remove(tmp_state)
            except OSError:
                pass

        self._load_existing()

    def _load_existing(self):
        """Charge les trades + signal_ids existants du jour (robuste post-restart)."""
        if os.path.exists(self.log_file):
            with open(self.log_file, "r") as f:
                for line in f:
                    s = line.strip()
                    if s:
                        try:
                            self.today_trades.append(json.loads(s))
                        except json.JSONDecodeError:
                            pass
            self.trade_count = len(self.today_trades)

        # v2 (review R3) : reload signal_ids deja trades (cross-restart VPS)
        if os.path.exists(self._traded_signals_file):
            try:
                with open(self._traded_signals_file, "r") as f:
                    for line in f:
                        sid = line.strip()
                        if sid:
                            self._traded_signal_ids.add(sid)
            except OSError:
                pass

        # v2 (review R5) : reset consec_losses si changement de date
        # (si on relance a J+1, les SL de J ne comptent pas)
        current_date = datetime.now(timezone.utc).strftime("%Y%m%d")
        if current_date != self.date_str:
            self._consec_losses = {"ES": 0, "NQ": 0}
            self._circuit_pause_until = {}

    def check_entry(self, data, symbol):
        """Verifie si les conditions d'entree sont remplies (v2 22/04).

        Pipeline :
          1. Pas deja en position + max trades/jour
          2. Cooldown post-close + circuit breaker
          3. Conseil Global action != ATTENDRE
          4. freshness == "NEW" (state machine v1.5 fix)
          5. signal_id pas deja consomme (dedup)
          6. confidence + MTF passent
          7. SLTPEngine calcule SL/TP (mur Tier 1/2 derriere + TP1 avant obstacle)
          8. expected_payoff_$ >= seuil (filtre audit ES vs NQ)
        """
        sym = symbol.lower()
        instr = data.get(sym)
        if not instr:
            return None

        reg = instr.get("regime", {})
        banner = data.get("banner", {})
        price = banner.get(sym, {}).get("price", 0)
        if not price:
            return None

        # 1. Deja en position ? + max trades jour
        if symbol in self.positions:
            return None
        if self.trade_count >= ENTRY_RULES["max_trades_per_day"]:
            return None

        # 2. Cooldown post-close (anti re-entry contre-sens)
        now_ts = time.time()
        last_close = self._last_close_ts.get(symbol)
        if last_close and (now_ts - last_close) < ENTRY_RULES["cooldown_post_close_sec"]:
            return None

        # 2bis. Circuit breaker (3 SL consec → pause 60min)
        pause_until = self._circuit_pause_until.get(symbol)
        if pause_until and now_ts < pause_until:
            return None

        # 3. Conseil Global action
        conseil = data.get("conseil_global", {}).get(sym, {})
        action = conseil.get("action", "ATTENDRE")
        if action in ("ATTENDRE", "CONFLIT"):
            return None
        direction_int = 1 if "ACHAT" in action else -1
        direction = "LONG" if direction_int == 1 else "SHORT"
        prudent = "PRUDENT" in action

        # 4. freshness state machine v1.5 — NEW uniquement
        freshness_v15 = conseil.get("freshness", "IDLE")
        if freshness_v15 != ENTRY_RULES["freshness_required"]:
            return None

        # 5. Dedup via signal_id
        signal_id = conseil.get("signal_id")
        if signal_id and signal_id in self._traded_signal_ids:
            return None

        # 6. Confidence + MTF
        confidence = reg.get("bias_confidence", 0)
        min_conf = 0.40 if prudent else ENTRY_RULES["min_confidence"]
        if confidence < min_conf:
            return None
        mtf_bulls = reg.get("mtf_bulls", 0)
        mtf_bears = reg.get("mtf_bears", 0)
        if direction == "LONG" and mtf_bulls < ENTRY_RULES["min_mtf_bulls"]:
            return None
        if direction == "SHORT" and mtf_bears < ENTRY_RULES["min_mtf_bears"]:
            return None

        # 7. SLTPEngine — calcul intelligent Tier 1/2 murs + TP1
        # Bar DMP complete OBLIGATOIRE (review agent R2 : reconstruct dashboard omet
        # ~30 murs MenthorQ/gamma/BL → SL biaise, verdict paper invalide). Si absent,
        # lire directement le dernier JSONL DMP (last line).
        bot_data = data.get("bot", {})
        bar_row_dict = bot_data.get("last_bars", {}).get(sym, {})
        if not bar_row_dict:
            bar_row_dict = self._read_last_jsonl_bar(symbol)
        if not bar_row_dict:
            # Pas de bar complete → skip trade (pas de fallback reconstruction biaise)
            if _v2log:
                _v2log.emit("GENERIC_ALERTE",
                            msg=f"paper: skip {symbol} — bar DMP complete absente (bot.last_bars vide + JSONL unreadable)")
            return None

        engine = self.sltp_engines[symbol]
        sltp_result = engine.evaluate_single(bar_row_dict, direction_int)

        if not sltp_result.valid:
            # Rejete par SLTPEngine (pas de mur Tier 1/2, budget depasse, R:R insuffisant...)
            return None

        sl_ticks = sltp_result.sl_ticks
        tp_ticks = sltp_result.tp1_ticks  # Jackson choix : UN SEUL TP (pas trailing/runner)

        # 8. Filtre expected_payoff_$ (audit ES vs NQ 22/04) avec WR dynamique
        tv = TICK_VALUE[symbol]
        wr = self._get_dynamic_wr()   # 0.45 conservateur < 30 trades, puis rolling reel
        expected_payoff_usd = (wr * tp_ticks - (1 - wr) * sl_ticks) * tv * ENTRY_RULES["n_micros"]
        if expected_payoff_usd < ENTRY_RULES["min_expected_payoff_usd"]:
            return None

        # Calcul prix
        if direction == "LONG":
            sl_price = round(price - sl_ticks * TICK_SIZE, 2)
            tp_price = round(price + tp_ticks * TICK_SIZE, 2)
        else:
            sl_price = round(price + sl_ticks * TICK_SIZE, 2)
            tp_price = round(price - tp_ticks * TICK_SIZE, 2)

        return {
            "direction": direction,
            "entry_price": price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "sl_ticks": sl_ticks,
            "tp_ticks": tp_ticks,
            "sl_wall": sltp_result.sl_wall,
            "sl_tier": sltp_result.sl_wall_tier,
            "sl_reason": sltp_result.sl_reason,
            "tp_wall": sltp_result.tp1_wall,
            "tp_reason": sltp_result.tp1_reason,
            "rr_ratio": sltp_result.rr_ratio,
            "sl_usd": sltp_result.sl_usd,
            "expected_payoff_usd": expected_payoff_usd,
            "confidence": confidence,
            "mtf_bulls": mtf_bulls,
            "mtf_bears": mtf_bears,
            "freshness": freshness_v15,
            "signal_id": signal_id,
            "conseil_action": action,
            "conseil_bull_pts": conseil.get("bull_points", 0),
            "conseil_bear_pts": conseil.get("bear_points", 0),
        }

    def _get_dynamic_wr(self) -> float:
        """WR conservateur 0.45 avant N trades, sinon WR rolling empirique (review R4).

        Evite biais initialisation : sans historique, assume setup peu performant
        (0.45) ce qui force filtre expected_payoff strict. Quand N >= 30 trades,
        switch vers WR reel des 30 derniers trades (adaptatif edge reel).
        """
        min_n = ENTRY_RULES["estimated_wr_rolling_min"]
        if len(self.today_trades) < min_n:
            # Charger trades historiques globaux pour accelerer convergence
            from glob import glob
            all_files = sorted(glob(os.path.join(DATA_DIR, "*_trades.jsonl")))
            all_trades = []
            for fp in all_files[-10:]:  # max 10 derniers jours
                try:
                    with open(fp, "r") as f:
                        for line in f:
                            s = line.strip()
                            if s:
                                try:
                                    all_trades.append(json.loads(s))
                                except json.JSONDecodeError:
                                    pass
                except OSError:
                    continue
            if len(all_trades) >= min_n:
                recent = all_trades[-min_n:]
                wins = sum(1 for t in recent if t.get("pnl_ticks", 0) > 0)
                return wins / len(recent)
            # Pas assez d'historique → conservateur
            return ENTRY_RULES["estimated_wr_initial"]

        # Rolling WR des 30 derniers trades du jour
        recent = self.today_trades[-min_n:]
        wins = sum(1 for t in recent if t.get("pnl_ticks", 0) > 0)
        return wins / len(recent)

    def _read_last_jsonl_bar(self, symbol):
        """Lit la derniere ligne du JSONL DMP pour avoir bar complete (40+ features dist_*).

        Necessaire car dashboard expose seulement un sous-ensemble des features.
        SLTPEngine a besoin de tous les murs Tier 1/2/3 pour verdict fiable.
        """
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "DATA", symbol)
        if not os.path.isdir(data_dir):
            return None
        # Dernier JSONL par mtime
        try:
            files = sorted(
                (f for f in os.listdir(data_dir) if f.endswith(".jsonl")),
                key=lambda n: os.path.getmtime(os.path.join(data_dir, n)),
                reverse=True,
            )
            if not files:
                return None
            latest = os.path.join(data_dir, files[0])
            # Lire derniere ligne (efficacement en scannant depuis la fin)
            with open(latest, "rb") as f:
                try:
                    f.seek(-2, os.SEEK_END)
                    while f.read(1) != b"\n":
                        f.seek(-2, os.SEEK_CUR)
                except OSError:
                    f.seek(0)
                last_line = f.readline().decode("utf-8")
            if last_line.strip():
                return json.loads(last_line)
        except (OSError, json.JSONDecodeError):
            pass
        return None

    def enter_trade(self, data, symbol, signal):
        """Ouvre une position paper."""
        sym = symbol.lower()
        instr = data.get(sym, {})
        reg = instr.get("regime", {})
        now = datetime.now(timezone.utc)

        position = {
            "symbol": symbol,
            "direction": signal["direction"],
            "entry_price": signal["entry_price"],
            "entry_time": now.isoformat(),
            "entry_ts": now.timestamp(),
            "sl_price": signal["sl_price"],
            "tp_price": signal["tp_price"],
            "sl_ticks": signal["sl_ticks"],
            "tp_ticks": signal["tp_ticks"],
            # v2 (22/04) : enrichissement SL/TP intelligent
            "sl_wall": signal.get("sl_wall", ""),
            "sl_tier": signal.get("sl_tier", 0),
            "sl_reason": signal.get("sl_reason", ""),
            "tp_wall": signal.get("tp_wall", ""),
            "tp_reason": signal.get("tp_reason", ""),
            "rr_ratio": signal.get("rr_ratio", 0.0),
            "sl_usd": signal.get("sl_usd", 0.0),
            "expected_payoff_usd": signal.get("expected_payoff_usd", 0.0),
            "signal_id": signal.get("signal_id"),
            "n_micros": ENTRY_RULES["n_micros"],
            "mae": 0,  # max adverse excursion
            "mfe": 0,  # max favorable excursion
            "bars_held": 0,
            "current_price": signal["entry_price"],
            "unrealized_pnl_ticks": 0.0,
            "unrealized_pnl_usd": 0.0,
        }

        # Dedup signal_id consomme (in-memory + persiste disque cross-restart)
        if signal.get("signal_id"):
            sid = signal["signal_id"]
            self._traded_signal_ids.add(sid)
            try:
                with open(self._traded_signals_file, "a", encoding="utf-8") as f:
                    f.write(f"{sid}\n")
            except OSError:
                pass

        # Snapshot complet au moment de l'entree
        snapshot = {
            "trade_id": f"{self.date_str}_{self.trade_count + 1}",
            "symbol": symbol,
            "direction": signal["direction"],
            "entry_price": signal["entry_price"],
            "entry_time": now.isoformat(),
            "sl_price": signal["sl_price"],
            "tp_price": signal["tp_price"],
            # Dashboard state
            "confidence": signal["confidence"],
            "freshness": signal["freshness"],
            "bias": reg.get("bias"),
            "bias_score": reg.get("bias_score"),
            "mode": reg.get("mode"),
            "favor": reg.get("favor"),
            "favor_reason": reg.get("favor_reason"),
            "mtf_verdict": reg.get("mtf_verdict"),
            "mtf_bulls": signal["mtf_bulls"],
            "mtf_bears": signal["mtf_bears"],
            "div_grade": reg.get("div_grade"),
            "div_quality": reg.get("div_quality"),
            "range_pos": reg.get("range_pos"),
            "vol_regime": reg.get("vol_regime"),
            "mode_trend_votes": reg.get("mode_trend_votes"),
            "mode_range_votes": reg.get("mode_range_votes"),
            # Donnees brutes
            "vix": reg.get("vix"),
            "atr": reg.get("atr"),
            "sess_range_atr": reg.get("sess_range_atr"),
            # Order flow
            "rvol": instr.get("order_flow", {}).get("rvol"),
            "delta_day": instr.get("order_flow", {}).get("delta_day"),
            "cvd_day": instr.get("order_flow", {}).get("cvd_day"),
            "delta_pct": instr.get("order_flow", {}).get("delta_pct"),
            # Intermarket
            "smt_divergence": data.get("intermarket", {}).get("smt_divergence"),
            "smt_direction": data.get("intermarket", {}).get("smt_direction"),
            # Patterns
            "patterns_daily": bool(data.get("patterns", {}).get(sym, {}).get("detected")),
            "patterns_intraday": bool(data.get("patterns_intraday", {}).get(sym, {}).get("detected")),
            # Conseil Global
            "conseil_action": signal.get("conseil_action"),
            "conseil_bull_pts": signal.get("conseil_bull_pts"),
            "conseil_bear_pts": signal.get("conseil_bear_pts"),
        }

        self.positions[symbol] = position
        self.trade_count += 1

        # Ecrire le snapshot
        with open(self.snapshot_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")

        print(f"  >>> ENTREE {signal['direction']} {symbol} @ {signal['entry_price']:.2f} | "
              f"SL={signal['sl_price']:.2f} [{signal.get('sl_wall','?')} T{signal.get('sl_tier','?')}] "
              f"TP={signal['tp_price']:.2f} [{signal.get('tp_wall','?')}] "
              f"RR={signal.get('rr_ratio',0):.2f} Exp=${signal.get('expected_payoff_usd',0):.1f} | "
              f"Conf={signal['confidence']*100:.0f}%")

        # V2 log
        if _v2log:
            _v2log.emit("TRADE_OPEN", sym=symbol, direction=signal["direction"],
                        size=ENTRY_RULES["n_micros"], price=signal["entry_price"],
                        signal_id=signal.get("signal_id"))

        # Write state.json pour dashboard bridge
        self._write_state()

    def check_exit(self, data, symbol):
        """Verifie SL/TP sur la position ouverte."""
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]
        sym = symbol.lower()
        banner = data.get("banner", {})
        price = banner.get(sym, {}).get("price", 0)
        if not price:
            return

        pos["bars_held"] += 1

        # Calculer MAE/MFE + PnL unrealized
        if pos["direction"] == "LONG":
            excursion = (price - pos["entry_price"]) / TICK_SIZE
        else:
            excursion = (pos["entry_price"] - price) / TICK_SIZE

        if excursion > pos["mfe"]:
            pos["mfe"] = round(excursion, 1)
        if excursion < pos["mae"]:
            pos["mae"] = round(excursion, 1)

        # PnL unrealized (pour state.json live)
        tv = TICK_VALUE.get(symbol, TICK_SIZE)
        pos["current_price"] = price
        pos["unrealized_pnl_ticks"] = round(excursion, 1)
        pos["unrealized_pnl_usd"] = round(excursion * tv * pos.get("n_micros", 3), 2)

        # Check SL
        hit_sl = False
        hit_tp = False
        if pos["direction"] == "LONG":
            if price <= pos["sl_price"]:
                hit_sl = True
            if price >= pos["tp_price"]:
                hit_tp = True
        else:
            if price >= pos["sl_price"]:
                hit_sl = True
            if price <= pos["tp_price"]:
                hit_tp = True

        # Timeout — 120 barres (2h)
        timeout = pos["bars_held"] >= 120

        if hit_tp or hit_sl or timeout:
            self._close_trade(symbol, price, "TP" if hit_tp else "SL" if hit_sl else "TIMEOUT")

    def _close_trade(self, symbol, exit_price, outcome):
        """Ferme et enregistre le trade (v2 22/04 avec cooldown + circuit breaker)."""
        pos = self.positions.pop(symbol)
        now = datetime.now(timezone.utc)

        if pos["direction"] == "LONG":
            pnl_ticks = round((exit_price - pos["entry_price"]) / TICK_SIZE, 1)
        else:
            pnl_ticks = round((pos["entry_price"] - exit_price) / TICK_SIZE, 1)

        # PnL $ (3 micros)
        tv = TICK_VALUE.get(symbol, TICK_SIZE)
        n_mic = pos.get("n_micros", 3)
        pnl_usd = round(pnl_ticks * tv * n_mic, 2)

        trade = {
            "trade_id": f"{self.date_str}_{len(self.today_trades) + 1}",
            "symbol": symbol,
            "direction": pos["direction"],
            "entry_price": pos["entry_price"],
            "entry_time": pos["entry_time"],
            "exit_price": exit_price,
            "exit_time": now.isoformat(),
            "outcome": outcome,
            "pnl_ticks": pnl_ticks,
            "pnl_usd": pnl_usd,
            "mae": pos["mae"],
            "mfe": pos["mfe"],
            "bars_held": pos["bars_held"],
            # v2 enrichissement
            "sl_wall": pos.get("sl_wall", ""),
            "sl_tier": pos.get("sl_tier", 0),
            "tp_wall": pos.get("tp_wall", ""),
            "rr_ratio": pos.get("rr_ratio", 0.0),
            "n_micros": n_mic,
            "signal_id": pos.get("signal_id"),
            "duration_min": round(pos["bars_held"], 1),  # 1 bar = 1 min
        }

        self.today_trades.append(trade)

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(trade, ensure_ascii=False) + "\n")

        color = "WIN" if pnl_ticks > 0 else "LOSS"
        print(f"  <<< SORTIE {outcome} {symbol} @ {exit_price:.2f} | "
              f"PnL={pnl_ticks:+.1f}t ${pnl_usd:+.2f} | "
              f"MAE={pos['mae']:.1f} MFE={pos['mfe']:.1f} | {color}")

        # V2 log + state
        if _v2log:
            code_map = {"TP": "TRADE_CLOSE_TP", "SL": "TRADE_CLOSE_SL", "TIMEOUT": "TRADE_CLOSE_TIMEOUT"}
            _v2log.emit(code_map.get(outcome, "TRADE_CLOSE_MANUAL"),
                        sym=symbol, pnl=pnl_ticks, signal_id=pos.get("signal_id"))

        # Cooldown post-close (anti re-entry contre-sens)
        self._last_close_ts[symbol] = time.time()

        # Circuit breaker : 3 SL consec → pause 60 min
        if outcome == "SL":
            self._consec_losses[symbol] = self._consec_losses.get(symbol, 0) + 1
            if self._consec_losses[symbol] >= ENTRY_RULES["circuit_breaker_losses"]:
                self._circuit_pause_until[symbol] = time.time() + ENTRY_RULES["circuit_breaker_pause_sec"]
                print(f"  !!! CIRCUIT BREAKER {symbol} : 3 SL consec → pause 60 min")
                if _v2log:
                    _v2log.emit("VOLATILITY_SPIKE", ratio=999, limit=3)  # generic critique
                self._consec_losses[symbol] = 0  # reset
        else:
            self._consec_losses[symbol] = 0  # win = reset

        self._write_state()

    def _write_state(self):
        """Ecrit state.json pour bridge dashboard (endpoint /api/paper_trades).

        Overwrite a chaque tick (live view). Contient :
          - open_by_symbol : positions en cours (PnL unrealized live)
          - closed_today : trades fermes du jour (last 20)
          - stats_today : WR, PF, pnl total, count par instrument
          - cooldown_status : info cooldown post-close + circuit breaker
        """
        now_ts = time.time()

        # Open positions avec PnL live
        open_by_symbol = {}
        for sym, pos in self.positions.items():
            open_by_symbol[sym] = {
                "trade_id": pos.get("trade_id"),
                "signal_id": pos.get("signal_id"),
                "direction": pos["direction"],
                "entry_price": pos["entry_price"],
                "entry_time": pos["entry_time"],
                "entry_ts": pos.get("entry_ts", 0),
                "sl_price": pos["sl_price"],
                "tp_price": pos["tp_price"],
                "sl_ticks": pos["sl_ticks"],
                "tp_ticks": pos["tp_ticks"],
                "sl_wall": pos.get("sl_wall", ""),
                "sl_tier": pos.get("sl_tier", 0),
                "tp_wall": pos.get("tp_wall", ""),
                "rr_ratio": pos.get("rr_ratio", 0),
                "n_micros": pos.get("n_micros", 3),
                "bars_held": pos["bars_held"],
                "mae": pos["mae"],
                "mfe": pos["mfe"],
                "current_price": pos.get("current_price", pos["entry_price"]),
                "unrealized_pnl_ticks": pos.get("unrealized_pnl_ticks", 0),
                "unrealized_pnl_usd": pos.get("unrealized_pnl_usd", 0),
                "expected_payoff_usd": pos.get("expected_payoff_usd", 0),
            }

        # Closed trades today (last 20 recent first)
        closed_today = list(reversed(self.today_trades[-20:]))

        # Stats today
        wins = [t for t in self.today_trades if t.get("pnl_ticks", 0) > 0]
        losses = [t for t in self.today_trades if t.get("pnl_ticks", 0) <= 0]
        win_ticks = sum(t["pnl_ticks"] for t in wins) if wins else 0
        loss_ticks = sum(abs(t["pnl_ticks"]) for t in losses) if losses else 0
        total_pnl_usd = sum(t.get("pnl_usd", 0) for t in self.today_trades)
        stats_today = {
            "trades": len(self.today_trades),
            "wins": len(wins),
            "losses": len(losses),
            "wr": round(len(wins) / max(1, len(self.today_trades)) * 100, 1),
            "pf": round(win_ticks / loss_ticks, 2) if loss_ticks > 0 else None,
            "pnl_usd": round(total_pnl_usd, 2),
            "pnl_ticks": round(sum(t["pnl_ticks"] for t in self.today_trades), 1),
        }

        # Stats par instrument
        stats_by_sym = {}
        for sym in ("ES", "NQ"):
            subset = [t for t in self.today_trades if t.get("symbol") == sym]
            sw = [t for t in subset if t.get("pnl_ticks", 0) > 0]
            sl = [t for t in subset if t.get("pnl_ticks", 0) <= 0]
            stats_by_sym[sym] = {
                "trades": len(subset),
                "wins": len(sw),
                "losses": len(sl),
                "wr": round(len(sw) / max(1, len(subset)) * 100, 1) if subset else 0,
                "pnl_usd": round(sum(t.get("pnl_usd", 0) for t in subset), 2),
            }

        # Cooldown + circuit breaker status
        cooldown_status = {}
        for sym in ("ES", "NQ"):
            last_close = self._last_close_ts.get(sym, 0)
            cooldown_remaining = max(0, ENTRY_RULES["cooldown_post_close_sec"] - (now_ts - last_close)) if last_close else 0
            pause_until = self._circuit_pause_until.get(sym, 0)
            circuit_remaining = max(0, pause_until - now_ts) if pause_until else 0
            cooldown_status[sym] = {
                "cooldown_remaining_sec": int(cooldown_remaining),
                "circuit_breaker_remaining_sec": int(circuit_remaining),
                "consec_losses": self._consec_losses.get(sym, 0),
            }

        state = {
            "updated_ts": now_ts,
            "updated_iso": datetime.now(timezone.utc).isoformat(),
            "date": self.date_str,
            "open_by_symbol": open_by_symbol,
            "closed_today": closed_today,
            "stats_today": stats_today,
            "stats_by_symbol": stats_by_sym,
            "cooldown_status": cooldown_status,
            "trade_count_today": self.trade_count,
            "max_trades_per_day": ENTRY_RULES["max_trades_per_day"],
        }

        try:
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp, STATE_FILE)
        except Exception as e:
            if _v2log:
                _v2log.emit("GENERIC_MAJEUR", msg=f"write_state failed: {e}")

    def run(self):
        """Boucle principale du paper trader."""
        print(f"MIA Paper Trader - {self.date_str}")
        print(f"Regles v2: conf>{ENTRY_RULES['min_confidence']*100:.0f}% MTF>={ENTRY_RULES['min_mtf_bears']}/4 "
              f"freshness={ENTRY_RULES['freshness_required']} n_micros={ENTRY_RULES['n_micros']} "
              f"min_exp=${ENTRY_RULES['min_expected_payoff_usd']} "
              f"cooldown={ENTRY_RULES['cooldown_post_close_sec']//60}min "
              f"circuit_breaker={ENTRY_RULES['circuit_breaker_losses']}SL/{ENTRY_RULES['circuit_breaker_pause_sec']//60}min")
        print(f"Log: {self.log_file}")
        print(f"Poll: {POLL_INTERVAL}s")
        print("-" * 60)

        while True:
            try:
                data = get_dashboard()
                if not data:
                    time.sleep(POLL_INTERVAL)
                    continue

                now = datetime.now(timezone.utc).strftime("%H:%M:%S")

                for symbol in ("ES", "NQ"):
                    # Check exit sur positions ouvertes
                    self.check_exit(data, symbol)

                    # Check entree si pas en position
                    signal = self.check_entry(data, symbol)
                    if signal:
                        self.enter_trade(data, symbol, signal)

                # Write state.json pour dashboard (chaque tick, live PnL unrealized)
                self._write_state()

                # Status toutes les 5 min
                minute = datetime.now(timezone.utc).minute
                if minute % 5 == 0:
                    wins = sum(1 for t in self.today_trades if t["pnl_ticks"] > 0)
                    losses = sum(1 for t in self.today_trades if t["pnl_ticks"] <= 0)
                    total_pnl = sum(t["pnl_ticks"] for t in self.today_trades)
                    open_pos = ", ".join(f"{s} {p['direction']}" for s, p in self.positions.items()) or "aucune"
                    print(f"  [{now}] Trades: {len(self.today_trades)} ({wins}W/{losses}L) PnL: {total_pnl:+.1f}t | Positions: {open_pos}")

                time.sleep(POLL_INTERVAL)

            except KeyboardInterrupt:
                print("\nArret du paper trader.")
                self._print_stats()
                break

    def _print_stats(self):
        """Affiche les stats de la session."""
        if not self.today_trades:
            print("Aucun trade aujourd'hui.")
            return

        wins = [t for t in self.today_trades if t["outcome"] == "TP"]
        losses = [t for t in self.today_trades if t["outcome"] == "SL"]
        timeouts = [t for t in self.today_trades if t["outcome"] == "TIMEOUT"]
        total_pnl = sum(t["pnl_ticks"] for t in self.today_trades)
        win_pnl = sum(t["pnl_ticks"] for t in wins)
        loss_pnl = sum(abs(t["pnl_ticks"]) for t in losses)

        wr = len(wins) / len(self.today_trades) * 100
        pf = win_pnl / loss_pnl if loss_pnl > 0 else float("inf")
        ev = total_pnl / len(self.today_trades)

        print(f"\n{'='*50}")
        print(f"STATS SESSION {self.date_str}")
        print(f"{'='*50}")
        print(f"Trades: {len(self.today_trades)} ({len(wins)}W / {len(losses)}L / {len(timeouts)}T)")
        print(f"Win Rate: {wr:.1f}%")
        print(f"Profit Factor: {pf:.2f}")
        print(f"EV/trade: {ev:+.1f} ticks")
        print(f"Total PnL: {total_pnl:+.1f} ticks")
        if self.today_trades:
            avg_mae = sum(t["mae"] for t in self.today_trades) / len(self.today_trades)
            avg_mfe = sum(t["mfe"] for t in self.today_trades) / len(self.today_trades)
            print(f"MAE moyen: {avg_mae:.1f}t | MFE moyen: {avg_mfe:.1f}t")

        # Par instrument
        for sym in ("ES", "NQ"):
            subset = [t for t in self.today_trades if t["symbol"] == sym]
            if subset:
                w = sum(1 for t in subset if t["outcome"] == "TP")
                pnl = sum(t["pnl_ticks"] for t in subset)
                print(f"  {sym}: {len(subset)} trades, WR={w/len(subset)*100:.0f}%, PnL={pnl:+.1f}t")


def show_stats(symbol=None):
    """Affiche les stats de tous les jours."""
    import glob as g
    files = sorted(g.glob(os.path.join(DATA_DIR, "*_trades.jsonl")))
    if not files:
        print("Aucun trade enregistre.")
        return

    all_trades = []
    for f in files:
        with open(f, "r") as fh:
            for line in fh:
                s = line.strip()
                if s:
                    try:
                        t = json.loads(s)
                        if symbol and t.get("symbol") != symbol:
                            continue
                        all_trades.append(t)
                    except json.JSONDecodeError:
                        pass

    if not all_trades:
        print(f"Aucun trade{' pour ' + symbol if symbol else ''}.")
        return

    wins = [t for t in all_trades if t["outcome"] == "TP"]
    losses = [t for t in all_trades if t["outcome"] == "SL"]
    total_pnl = sum(t["pnl_ticks"] for t in all_trades)
    win_pnl = sum(t["pnl_ticks"] for t in wins)
    loss_pnl = sum(abs(t["pnl_ticks"]) for t in losses)

    wr = len(wins) / len(all_trades) * 100
    pf = win_pnl / loss_pnl if loss_pnl > 0 else float("inf")
    ev = total_pnl / len(all_trades)

    title = f"PAPER TRADING — {symbol or 'ALL'}"
    print(f"\n{'='*50}")
    print(title)
    print(f"{'='*50}")
    print(f"Sessions: {len(files)}")
    print(f"Trades: {len(all_trades)} ({len(wins)}W / {len(losses)}L)")
    print(f"Win Rate: {wr:.1f}%")
    print(f"Profit Factor: {pf:.2f}")
    print(f"EV/trade: {ev:+.1f} ticks")
    print(f"Total PnL: {total_pnl:+.1f} ticks")

    # Par jour
    print(f"\nPar jour:")
    dates = sorted(set(t.get("entry_time", "")[:10] for t in all_trades))
    for d in dates:
        day = [t for t in all_trades if t.get("entry_time", "").startswith(d)]
        w = sum(1 for t in day if t["outcome"] == "TP")
        pnl = sum(t["pnl_ticks"] for t in day)
        print(f"  {d}: {len(day)} trades, WR={w/len(day)*100:.0f}%, PnL={pnl:+.1f}t")


if __name__ == "__main__":
    if "--stats" in sys.argv:
        sym = None
        if "--symbol" in sys.argv:
            idx = sys.argv.index("--symbol")
            if idx + 1 < len(sys.argv):
                sym = sys.argv[idx + 1].upper()
        show_stats(sym)
    else:
        trader = PaperTrader()
        trader.run()
