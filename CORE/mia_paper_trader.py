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
import threading
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

# Integration DTC Sim3 (22/04 soir - Jackson : visibilite Sierra Chart +
# test pipeline bout-en-bout). Feature flag MIA_DTC_ENABLE=1 pour activer.
# Sinon comportement paper pur memoire (inchange).
DTC_ENABLED = os.environ.get("MIA_DTC_ENABLE", "0") == "1"
_DTC_IMPORT_OK = False
if DTC_ENABLED:
    try:
        # BOT/ contient le dtc_connector eprouve (teste 02/04/2026 OCO manuel)
        _BOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "BOT")
        if _BOT_DIR not in sys.path:
            sys.path.insert(0, _BOT_DIR)
        from dtc_connector import DTCConnector, OrderFill, BUY as DTC_BUY, SELL as DTC_SELL
        from bot_config import DTCConfig, INSTRUMENTS as DTC_INSTRUMENTS
        _DTC_IMPORT_OK = True
    except Exception as _e:
        print(f"  !!! DTC import failed : {_e} — fallback paper pur memoire")
        _DTC_IMPORT_OK = False

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
    # 22/04 soir Jackson : PAS de limite trades/jour en paper (collecte max
    # de donnees). Cooldown 15min post-close + circuit breaker 3 SL gardent
    # la safety. Reactivation cap en mode LIVE capital reel plus tard.
    "max_trades_per_day": 9999,
    "cooldown_post_close_sec": 900,         # 15 min
    "circuit_breaker_losses": 3,            # 3 SL consec
    "circuit_breaker_pause_sec": 3600,      # 60 min pause
    "estimated_wr_initial": 0.45,           # conservateur avant 30 trades empiriques (review R4)
    "estimated_wr_rolling_min": 30,         # apres N trades, switch vers WR rolling reel
}

# Config DTC (valide Phase 1 paper uniquement, pas de compte LIVE)
TRADE_ACCOUNT = os.environ.get("MIA_TRADE_ACCOUNT", "Sim3")
_SIM_WHITELIST_PREFIX = ("SIM", "Sim", "sim")


# Fix CRITIQUE (22/04 soir) : sans auth, /api/dashboard retourne tier=free
# avec conseil_global.action toujours ATTENDRE → paper trader jamais ne trade.
# Solution : generer JWT owner interne (meme JWT_SECRET que le serveur, car
# meme process VPS/meme fichier .jwt_secret). Token regenere toutes les 13 min
# (access expiry 15 min, marge 2 min).
_SERVICE_TOKEN: str | None = None
_SERVICE_TOKEN_EXPIRY: float = 0.0


def _get_service_token() -> str:
    """JWT owner service pour fetch dashboard sans etre tier-gated."""
    global _SERVICE_TOKEN, _SERVICE_TOKEN_EXPIRY
    now = time.time()
    if _SERVICE_TOKEN is None or now >= _SERVICE_TOKEN_EXPIRY - 120:
        from DASHBOARD.api.auth import _create_token, ACCESS_EXPIRY
        _SERVICE_TOKEN = _create_token("paper_service@internal", "owner", "access")
        _SERVICE_TOKEN_EXPIRY = now + ACCESS_EXPIRY
    return _SERVICE_TOKEN


def get_dashboard():
    """Fetch le dashboard API avec JWT owner (bypass tier filter)."""
    import urllib.request
    try:
        token = _get_service_token()
        req = urllib.request.Request(DASHBOARD_URL)
        req.add_header("Authorization", f"Bearer {token}")
        r = urllib.request.urlopen(req, timeout=10)
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

        # Integration DTC Sim3 (22/04 soir) : thread safety + mapping orders
        # `_pos_lock` : RLock protege positions / cooldown / consec_losses /
        # _order_to_symbol car `_recv_loop` DTC (daemon thread) peut toucher
        # ces structures via `_handle_dtc_fill` pendant que main fait check_exit.
        self._pos_lock = threading.RLock()
        # Mapping order CID -> symbol pour callback fill
        # {parent_id: "ES", tp_cid: "ES", sl_cid: "ES", ...}
        self._order_to_symbol: dict = {}

        # DTC connector (None si MIA_DTC_ENABLE=0 ou import failed)
        self.dtc = None
        self.trade_account = TRADE_ACCOUNT
        if DTC_ENABLED and _DTC_IMPORT_OK:
            # Hard check whitelist : refuse comptes live accidentels
            if not self.trade_account.lower().startswith("sim"):
                raise RuntimeError(
                    f"MIA_TRADE_ACCOUNT={self.trade_account!r} non autorise. "
                    f"Paper trader accepte uniquement Sim1/Sim2/Sim3 (safety Phase 1). "
                    f"Set MIA_TRADE_ACCOUNT=Sim3 ou similaire."
                )
            print(f"  DTC enabled -> account={self.trade_account}")
            try:
                self.dtc = DTCConnector(DTCConfig())
                self.dtc.on_fill = self._handle_dtc_fill
                if not self.dtc.connect():
                    raise RuntimeError("DTC connect() returned False")
                # NOTE (22/04 soir) : pas de subscribe_market_data ici — Sierra Chart
                # DTC server refuse ("Market data request not allowed"). Le bot lit
                # les prix via dashboard API (/api/dashboard banner) qui vient du
                # JSONL DMP, pas du DTC. send_market_order fonctionne sans subscribe
                # (le serveur utilise le dernier prix marche cote SC automatiquement).
                print(f"  DTC connected OK (host={self.dtc.cfg.host}:{self.dtc.cfg.port})")
                if _v2log:
                    try:
                        _v2log.emit("BOOT_READY",
                                    dtc="connected",
                                    model="paper",
                                    data=self.trade_account)
                    except Exception:
                        pass
            except Exception as e:
                # Fail-loud au boot : si DTC_ENABLE=1 mais connect echoue,
                # on crash plutot que silencieusement fallback (ambiguite dangereuse)
                print(f"  !!! DTC connect FAILED : {e}")
                raise
        else:
            if DTC_ENABLED and not _DTC_IMPORT_OK:
                print(f"  !!! DTC_ENABLE=1 mais import KO -> fallback simu pure")
            else:
                print(f"  DTC desactive (simu pure memoire)")

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

    def _rotate_day_if_needed(self):
        """Fix B4 (code-reviewer 22/04) : rollover quotidien pour bot VPS 24/7.

        Si UTC date change depuis init, reset tout ce qui est quotidien :
          - trade_count_today, today_trades (nouveau fichier log)
          - consec_losses, circuit_pause_until (fresh start)
          - traded_signal_ids (nouveau fichier dedup)
          - log_file, snapshot_file, _traded_signals_file paths

        Appele en tete de boucle `run()` avant toute autre logique.
        """
        current_date = datetime.now(timezone.utc).strftime("%Y%m%d")
        if current_date == self.date_str:
            return
        prev_date = self.date_str
        print(f"  === ROLLOVER DATE {prev_date} -> {current_date} ===")
        # Reset quotidien
        self.today_trades = []
        self.trade_count = 0
        self.date_str = current_date
        self.log_file = os.path.join(DATA_DIR, f"{self.date_str}_trades.jsonl")
        self.snapshot_file = os.path.join(DATA_DIR, f"{self.date_str}_snapshots.jsonl")
        self._traded_signals_file = os.path.join(DATA_DIR, f"{self.date_str}_traded_signals.txt")
        self._traded_signal_ids = set()
        # Fix mineur #2 (code-reviewer 22/04) : ne PAS reset _last_close_ts ni
        # _circuit_pause_until — ce sont des timestamps absolus, le cooldown
        # expire naturellement sans devoir traverser la frontiere UTC. Seul
        # _consec_losses doit etre reset (compteur quotidien non-persistant).
        self._consec_losses = {"ES": 0, "NQ": 0}
        # NE PAS toucher aux positions ouvertes (overnight possible) — on flatten eventuel EOD ailleurs
        if _v2log:
            try:
                _v2log.emit("SESSION_OPEN", component="paper_trader",
                            prev_date=prev_date, new_date=current_date)
            except Exception:
                pass

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

    def _handle_dtc_fill(self, fill):
        """Callback DTC quand un ordre est Filled (status=7).

        Thread : daemon `_recv_loop` du DTCConnector. DOIT prendre le lock.

        3 cas :
          1. Fill parent : update position.entry_price avec vrai fill (slippage)
          2. Fill TP ou SL : close trade avec vrai exit price (broker-truth)
          3. CID inconnu : log, ignore
        """
        try:
            order_id = getattr(fill, "order_id", "")
            fill_price = getattr(fill, "fill_price", 0.0)
            if not order_id or not fill_price:
                return
            with self._pos_lock:
                symbol = self._order_to_symbol.get(order_id)
                if not symbol:
                    # CID inconnu (autre bot, anciens brackets, etc.)
                    return
                # Determiner le type de fill depuis le CID prefix
                is_parent = order_id.startswith("MIA_P_")
                is_tp = order_id.startswith("MIA_TP_")
                is_sl = order_id.startswith("MIA_SL_")

                pos = self.positions.get(symbol)

                if is_parent and pos:
                    # Update entry_price avec slippage reel broker
                    old_entry = pos["entry_price"]
                    pos["entry_price"] = fill_price
                    slip = (fill_price - old_entry) / TICK_SIZE
                    print(f"  >>> DTC FILL PARENT {symbol} @ {fill_price:.2f} (slip={slip:+.1f}t vs dashboard)")
                    if _v2log:
                        try:
                            _v2log.emit("ORDER_FILL", sym=symbol,
                                        fill_price=fill_price, slip_ticks=slip)
                        except Exception:
                            pass
                    return

                if (is_tp or is_sl) and pos:
                    # TP ou SL fill = close trade
                    outcome = "TP" if is_tp else "SL"
                    print(f"  >>> DTC FILL {outcome} {symbol} @ {fill_price:.2f} (broker-truth)")
                    # Relacher le lock avant _close_trade (qui reprend le lock)
                    # -> mais RLock permet reacquisition par meme thread
                    self._close_trade(symbol, fill_price, outcome, from_dtc_callback=True)
                    return

                # Fill pour symbol qui n'est plus en position (ex: close simu apres race)
                if (is_tp or is_sl) and not pos:
                    # Fix B3 (code-reviewer 22/04) : `outcome` pas defini si pos is None
                    outcome_dbg = "TP" if is_tp else "SL"
                    print(f"  !!! DTC fill {outcome_dbg} {symbol} "
                          f"mais position deja closed en simu — OK (OCO a deja tout nettoye)")
                    if _v2log:
                        try:
                            _v2log.emit("GENERIC_ALERTE",
                                        msg=f"desync_simu_broker_fill_{symbol}",
                                        order_id=order_id)
                        except Exception:
                            pass
        except Exception as e:
            import traceback
            print(f"  !!! _handle_dtc_fill error: {e}\n{traceback.format_exc()}")

    def enter_trade(self, data, symbol, signal):
        """Ouvre une position paper.

        Si DTC actif : envoie bracket Sim3 (sync, attend fill parent <2s).
        Si bracket echoue : abort, aucune position memoire (coherence stricte).
        """
        sym = symbol.lower()
        instr = data.get(sym, {})
        reg = instr.get("regime", {})
        now = datetime.now(timezone.utc)

        # Integration DTC (22/04) : envoi bracket Sim3 AVANT creation position memoire
        parent_id = ""
        tp_cid = ""
        sl_cid = ""
        if self.dtc is not None:
            # Fix B1 (code-reviewer 22/04) : is_alive est @property dans dtc_connector,
            # pas une methode. Appel sans parentheses.
            if not self.dtc.is_alive:
                print(f"  !!! DTC disconnected -> skip {symbol} (retry next poll)")
                if _v2log:
                    try:
                        _v2log.emit("DTC_DISCONNECT_SESSION",
                                    sym=symbol, reason="is_alive=False")
                    except Exception:
                        pass
                return
            try:
                contract = DTC_INSTRUMENTS[symbol].contract
            except KeyError:
                print(f"  !!! contract inconnu pour {symbol} -> skip")
                return
            dtc_side = DTC_BUY if signal["direction"] == "LONG" else DTC_SELL
            print(f"  >>> DTC SUBMIT {symbol} {signal['direction']} qty={ENTRY_RULES['n_micros']} "
                  f"SL={signal['sl_price']:.2f} TP={signal['tp_price']:.2f} contract={contract}")
            parent_id, tp_cid, sl_cid = self.dtc.send_market_order(
                symbol=contract,
                side=dtc_side,
                quantity=ENTRY_RULES["n_micros"],
                sl_price=signal["sl_price"],
                tp_price=signal["tp_price"],
                trade_account=self.trade_account,
            )
            if not parent_id:
                print(f"  !!! DTC bracket FAIL {symbol} (parent timeout ou reject)")
                if _v2log:
                    try:
                        _v2log.emit("ORDER_REJECT",
                                    sym=symbol,
                                    reason="bracket_fail_parent_timeout_or_reject",
                                    signal_id=signal.get("signal_id"))
                    except Exception:
                        pass
                return
            print(f"  >>> DTC BRACKET OK parent={parent_id} tp={tp_cid} sl={sl_cid}")

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
            # DTC bracket tracking
            "parent_id": parent_id,
            "tp_cid": tp_cid,
            "sl_cid": sl_cid,
            "dtc_enabled": self.dtc is not None,
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

        # Thread-safe update : positions + order_to_symbol mapping
        with self._pos_lock:
            self.positions[symbol] = position
            self.trade_count += 1
            # Mapping CID -> symbol pour callback _handle_dtc_fill
            for cid in (parent_id, tp_cid, sl_cid):
                if cid:
                    self._order_to_symbol[cid] = symbol

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

    def _close_trade(self, symbol, exit_price, outcome, from_dtc_callback=False):
        """Ferme et enregistre le trade (v2 22/04 avec cooldown + circuit breaker).

        Si from_dtc_callback=True : fill broker deja recu, les brackets OCO sont
        deja canceled par DTCConnector._handle_order_update. On fait juste la
        comptabilite memoire + state.json.

        Si from_dtc_callback=False : fermeture declenchee par simu (check_exit
        detecte hit_sl/hit_tp/timeout). Il faut cancel les brackets Sim3 + envoyer
        un close market sinon position reste ouverte cote Sierra Chart.
        """
        with self._pos_lock:
            if symbol not in self.positions:
                # Deja close (idempotent)
                return
            pos = self.positions.pop(symbol)
            # Cleanup mapping order_to_symbol
            for cid_key in ("parent_id", "tp_cid", "sl_cid"):
                cid = pos.get(cid_key)
                if cid:
                    self._order_to_symbol.pop(cid, None)

        # Fix B2 (code-reviewer 22/04) : race destructrice si simu declenche close
        # avant que le callback broker fill n'arrive → reverse market creait une
        # position inverse fantome si les brackets etaient deja fill.
        # Solution retenue (Option C) : TRUST OCO BROKER. Quand la simu detecte un
        # hit (banner price), on cancel les 2 brackets (idempotent si deja fill).
        # Si les brackets sont encore live → OCO cancel le oppose au prochain fill.
        # Si les brackets sont deja fill → cancel = no-op silencieux, rien d'envoye.
        # Aucun "reverse market" : on ne cree JAMAIS une position inverse Sim3.
        # La seule source de verite pour la sortie Sim3 = fill broker via on_fill.
        # Exception : outcome=TIMEOUT → on force fermeture via close market (no SL/TP)
        # car aucun bracket n'aurait declenche naturellement.
        if not from_dtc_callback and self.dtc is not None and pos.get("dtc_enabled"):
            try:
                # Cancel TP + SL (idempotent si deja fill broker)
                for cid_key in ("tp_cid", "sl_cid"):
                    cid = pos.get(cid_key)
                    if cid:
                        try:
                            self.dtc.cancel_order(cid, trade_account=self.trade_account)
                        except Exception as e:
                            print(f"  warn cancel {cid}: {e}")

                # SEULEMENT pour TIMEOUT : broker n'a rien fill, on force close market
                if outcome == "TIMEOUT":
                    try:
                        contract = DTC_INSTRUMENTS[symbol].contract
                        reverse_side = DTC_SELL if pos["direction"] == "LONG" else DTC_BUY
                        close_id, _, _ = self.dtc.send_market_order(
                            symbol=contract,
                            side=reverse_side,
                            quantity=pos.get("n_micros", 3),
                            sl_price=0, tp_price=0,
                            trade_account=self.trade_account,
                        )
                        print(f"  >>> DTC CLOSE TIMEOUT {symbol} market cid={close_id}")
                        if not close_id and _v2log:
                            try:
                                _v2log.emit("ORDER_REJECT",
                                            sym=symbol, reason="timeout_close_market_fail")
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"  !!! DTC TIMEOUT close FAIL {symbol}: {e}")
                else:
                    # TP/SL declenche par simu : on fait confiance au broker.
                    # Log descriptif pour traceabilite analyse desync ex-post.
                    print(f"  >>> DTC {outcome} simu-triggered {symbol}, brackets canceled, trust broker fill via on_fill")
            except Exception as e:
                print(f"  !!! DTC cleanup FAIL {symbol}: {e}")

        now = datetime.now(timezone.utc)

        if pos["direction"] == "LONG":
            pnl_ticks = round((exit_price - pos["entry_price"]) / TICK_SIZE, 1)
        else:
            pnl_ticks = round((pos["entry_price"] - exit_price) / TICK_SIZE, 1)

        # PnL $ (3 micros)
        tv = TICK_VALUE.get(symbol, TICK_SIZE)
        n_mic = pos.get("n_micros", 3)
        pnl_usd = round(pnl_ticks * tv * n_mic, 2)

        entry_ts_val = pos.get("entry_ts", 0) or now.timestamp()
        exit_ts_val = now.timestamp()
        duration_sec = round(max(0.0, exit_ts_val - entry_ts_val), 1)
        trade = {
            "trade_id": f"{self.date_str}_{len(self.today_trades) + 1}",
            "symbol": symbol,
            "direction": pos["direction"],
            "entry_price": pos["entry_price"],
            "entry_time": pos["entry_time"],
            "entry_ts": entry_ts_val,
            "exit_price": exit_price,
            "exit_time": now.isoformat(),
            "exit_ts": exit_ts_val,
            # Fix B2 (code-reviewer 22/04) : expose `exit_reason` pour frontend legacy,
            # en plus de `outcome` (mot historique backend)
            "outcome": outcome,
            "exit_reason": outcome,
            "pnl_ticks": pnl_ticks,
            "pnl_usd": pnl_usd,
            "mae": pos["mae"],
            "mfe": pos["mfe"],
            "bars_held": pos["bars_held"],
            "duration_sec": duration_sec,       # Fix B3 : frontend timer
            # v2 enrichissement
            "sl_wall": pos.get("sl_wall", ""),
            "sl_tier": pos.get("sl_tier", 0),
            "tp_wall": pos.get("tp_wall", ""),
            "rr_ratio": pos.get("rr_ratio", 0.0),
            "n_micros": n_mic,
            "signal_id": pos.get("signal_id"),
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
                    _v2log.emit("CIRCUIT_BREAKER_TRIP",
                                sym=symbol,
                                consec_losses=ENTRY_RULES["circuit_breaker_losses"],
                                pause_min=ENTRY_RULES["circuit_breaker_pause_sec"] // 60)
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

        self._last_status_minute = -1  # Fix R7 : anti-spam prints
        consec_errors = 0

        while True:
            try:
                # Fix B4 (code-reviewer 22/04) : rollover date UTC si bot tourne > 24h
                self._rotate_day_if_needed()

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

                # Status toutes les 5 min (anti-spam via _last_status_minute)
                minute = datetime.now(timezone.utc).minute
                if minute % 5 == 0 and minute != self._last_status_minute:
                    self._last_status_minute = minute
                    wins = sum(1 for t in self.today_trades if t["pnl_ticks"] > 0)
                    losses = sum(1 for t in self.today_trades if t["pnl_ticks"] <= 0)
                    total_pnl = sum(t["pnl_ticks"] for t in self.today_trades)
                    open_pos = ", ".join(f"{s} {p['direction']}" for s, p in self.positions.items()) or "aucune"
                    print(f"  [{now}] Trades: {len(self.today_trades)} ({wins}W/{losses}L) PnL: {total_pnl:+.1f}t | Positions: {open_pos}")

                consec_errors = 0  # reset sur tick OK
                time.sleep(POLL_INTERVAL)

            except KeyboardInterrupt:
                print("\nArret du paper trader.")
                self._print_stats()
                # Shutdown gracieux DTC (ne flatte PAS les positions Sim3 --
                # Jackson veut les garder visibles pour review visuelle)
                if self.dtc is not None:
                    try:
                        self.dtc.disconnect()
                        print("  DTC disconnected (positions Sim3 preservees)")
                    except Exception as e:
                        print(f"  warn DTC disconnect: {e}")
                break
            except Exception as e:
                # Fix B5 (code-reviewer 22/04) : cascade protection VPS 24/7
                consec_errors += 1
                import traceback
                print(f"  !!! ERREUR paper_trader (#{consec_errors}) : {type(e).__name__}: {e}")
                print(traceback.format_exc())
                if _v2log:
                    try:
                        _v2log.emit("GENERIC_MAJEUR",
                                    component="paper_trader",
                                    error_type=type(e).__name__,
                                    error_msg=str(e)[:200],
                                    consec=consec_errors)
                    except Exception:
                        pass
                if consec_errors >= 10:
                    print(f"  !!! 10 erreurs consecutives — arret paper_trader (watchdog nssm relance)")
                    if _v2log:
                        try:
                            _v2log.emit("BOT_CRASH", component="paper_trader", consec=consec_errors)
                        except Exception:
                            pass
                    raise
                time.sleep(POLL_INTERVAL)

    def _print_stats(self):
        """Affiche les stats de la session."""
        if not self.today_trades:
            print("Aucun trade aujourd'hui.")
            return

        # Fix mineur #3 (code-reviewer 22/04) : tolerance trades legacy sans `outcome`
        def _oc(t): return t.get("outcome") or t.get("exit_reason") or "?"
        wins = [t for t in self.today_trades if _oc(t) == "TP"]
        losses = [t for t in self.today_trades if _oc(t) == "SL"]
        timeouts = [t for t in self.today_trades if _oc(t) == "TIMEOUT"]
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
                w = sum(1 for t in subset if _oc(t) == "TP")
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

    # Fix mineur #3 (code-reviewer 22/04) : tolerance trades legacy
    def _oc(t): return t.get("outcome") or t.get("exit_reason") or "?"
    wins = [t for t in all_trades if _oc(t) == "TP"]
    losses = [t for t in all_trades if _oc(t) == "SL"]
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
