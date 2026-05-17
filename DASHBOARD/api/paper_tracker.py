"""Paper tracker bridge — lecture state.json + agregation stats historiques.

Source de verite : `DATA/PAPER_TRADES/state.json` ecrit par `CORE/mia_paper_trader.py`.
Ce module LIT SEULEMENT (aucune logique de trading). Expose endpoint API pour frontend.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from glob import glob
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).parent.parent.parent
PAPER_DIR = _ROOT / "DATA" / "PAPER_TRADES"
STATE_FILE = PAPER_DIR / "state.json"                              # BOT 1 DMP (mia_paper Sim3)
STATE_FILE_DB = PAPER_DIR / "databento_paper_state.json"           # BOT 2 DB V1 (databento_paper Sim2 — DEPRECATED)
STATE_FILE_DB_V2 = PAPER_DIR / "state_v6.json"                     # BOT 2 V6 (mia2_brain_v6_databento, V4 enriched 456 cols, Sim2, 05/05/2026)
STATE_FILE_BOT3 = PAPER_DIR / "databento_paper_v3_state.json"      # BOT 3 MP (Market Profile 13 niveaux, Sim1, 03/05/2026)

# Import CME trading day helper (rollover 18:00 ET, DST-aware) pour aligner
# le filtre dashboard "today" avec la convention bot.
# FIX 30/04 : avant, dashboard utilisait UTC midnight (00:00 UTC), bot utilise
# CME 18:00 ET → ecart de 4-6h ou les stats Bot 2 ne se reset pas en meme
# temps que le bot. Le dashboard affichait 15 trades/-318$ a Tokyo open
# alors que le bot avait deja roll au trading day suivant.
_CORE_DIR = _ROOT / "CORE"
if str(_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_CORE_DIR))
try:
    from constants import get_cme_trading_day, CME_TZ, CME_DAY_ROLLOVER_HOUR_ET
    from eco_calendar import is_blocked_combined as _eco_is_blocked_combined
except ImportError:
    from CORE.constants import get_cme_trading_day, CME_TZ, CME_DAY_ROLLOVER_HOUR_ET
    from CORE.eco_calendar import is_blocked_combined as _eco_is_blocked_combined

# 17/05 R1 Q3 review code-reviewer : hoist import + singleton logger pour eviter
# re-import dans except `_safe_read_state` (corrupt state -> 100 imports/min).
# Singleton module-level + fallback stderr robuste si get_logger echoue au boot.
try:
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _PAPER_TRACKER_LOG = _get_v2_logger("dashboard_paper_tracker", process="dashboard")
except Exception:
    _PAPER_TRACKER_LOG = None


def _cme_trading_day_start_utc(now_utc: Optional[datetime] = None) -> datetime:
    """Retourne le debut UTC du CME trading day courant.

    Le CME trading day commence a 18:00 ET et finit a 17:00 ET le lendemain.
    Cette fonction calcule le 18:00 ET le plus recent (= debut du day courant).

    Exemples (heure d'ete EDT, ET = UTC-4) :
      29/04 17:30 ET (21:30 UTC) → trading day "20260429" → start = 28/04 22:00 UTC
      29/04 18:00 ET (22:00 UTC) → trading day "20260430" → start = 29/04 22:00 UTC
      29/04 22:00 ET (02:00 UTC le 30) → trading day "20260430" → start = 29/04 22:00 UTC
    """
    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    et_dt = now.astimezone(CME_TZ)
    if et_dt.hour >= CME_DAY_ROLLOVER_HOUR_ET:
        # On est apres 18:00 ET → start = aujourd'hui 18:00 ET
        start_et = et_dt.replace(hour=CME_DAY_ROLLOVER_HOUR_ET,
                                  minute=0, second=0, microsecond=0)
    else:
        # On est avant 18:00 ET → start = hier 18:00 ET
        start_et = (et_dt - timedelta(days=1)).replace(
            hour=CME_DAY_ROLLOVER_HOUR_ET, minute=0, second=0, microsecond=0)
    return start_et.astimezone(timezone.utc)


def get_eco_status_payload() -> dict:
    """Retourne le statut eco/session pour le dashboard, avec timer.

    FIX 30/04 (Jackson "ON AURAIS DU A VOIR UN TIMER") : permet au frontend
    d'afficher "Bot reprend dans HH:MM" au lieu d'un simple "DOWN".

    Returns:
        {
          "blocked": bool,
          "reason": str | None,
          "blocked_until_utc": str ISO | None,
          "blocked_until_iso": str ISO | None,  # alias frontend
          "resume_in_sec": int | None,          # secondes avant reprise
        }
    """
    now_utc = datetime.now(timezone.utc)
    blocked, reason, until_utc = _eco_is_blocked_combined(now_utc)
    resume_in_sec = None
    until_iso = None
    if until_utc is not None:
        resume_in_sec = max(0, int((until_utc - now_utc).total_seconds()))
        until_iso = until_utc.isoformat()
    return {
        "blocked": blocked,
        "reason": reason,
        "blocked_until_utc": until_iso,
        "blocked_until_iso": until_iso,
        "resume_in_sec": resume_in_sec,
    }


def _safe_read_state(state_file: Path = STATE_FILE) -> dict:
    """Lit state.json (atomic read, fallback dict vide si absent).

    B4 audit 17/05 : fail-loud sur JSON corrompu via emit BOT3_STATE_CORRUPT
    (avant : except Exception: pass silencieux -> dashboard affiche
    "OBSERVE_ONLY" 0 positions sans signal).

    R3 review 17/05 (code-reviewer voyant flux) : retry 50ms sur JSONDecodeError
    + FileNotFoundError transitoires. Cause : _write_state ecrit tmp + os.replace
    atomique, mais cote lecture si dashboard tape pendant les ~5ms de rename ->
    JSONDecodeError ou FileNotFoundError transitoire -> bar_source manquant ->
    voyant tombe INIT alors que reellement V4. Retry simple eviter false negatif.
    """
    if not state_file.exists():
        return _empty_state()
    try:
        with state_file.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        # R3 17/05 : 1 retry 50ms pour absorber race rename atomique
        import time as _time
        _time.sleep(0.05)
        try:
            with state_file.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
        # Si encore fail apres retry, fall through fail-loud handler ci-dessous
        e = Exception("retry_failed_post_50ms")
        if _PAPER_TRACKER_LOG is not None:
            try:
                _PAPER_TRACKER_LOG.emit("BOT3_STATE_CORRUPT",
                                         state_file=str(state_file),
                                         err_type="RaceRetryFail",
                                         err_msg="JSONDecodeError + retry 50ms fail")
            except Exception:
                pass
        return _empty_state()
    except Exception as e:
        # B4 17/05 : fail-loud sur JSON corrompu/permissions/IO error.
        # Sans cet emit, on perdait toute trace d'un state corrompu.
        # R1 Q3 17/05 : logger singleton module-level (vs re-import dans except).
        if _PAPER_TRACKER_LOG is not None:
            try:
                _PAPER_TRACKER_LOG.emit("BOT3_STATE_CORRUPT",
                                         state_file=str(state_file),
                                         err_type=type(e).__name__,
                                         err_msg=str(e)[:200])
            except Exception:
                # Logger casse aussi -> fallback stderr.
                print(f"[BOT3_STATE_CORRUPT] {state_file} err={type(e).__name__}: {e}",
                      file=sys.stderr, flush=True)
        else:
            print(f"[BOT3_STATE_CORRUPT] {state_file} err={type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
        return _empty_state()


def _empty_state() -> dict:
    return {
        "updated_ts": 0,
        "updated_iso": None,
        "date": None,
        "open_by_symbol": {},
        "closed_today": [],
        "stats_today": {"trades": 0, "wins": 0, "losses": 0, "wr": 0, "pf": None, "pnl_usd": 0, "pnl_ticks": 0},
        "stats_by_symbol": {"ES": {}, "NQ": {}},
        "cooldown_status": {},
        "trade_count_today": 0,
        "max_trades_per_day": 9999,
    }


def _iter_trades_from_files(since_utc: datetime, pattern: str = "*_trades.jsonl"):
    """Yields trades from *_trades.jsonl files since a datetime.

    pattern accepted :
      - '*_trades.jsonl'          → BOT 1 DMP (mia_paper_trader.py Sim3)
      - '*_v6_trades.jsonl'       → BOT 2 V6 (mia2_brain_v6_databento.py Sim2)
      - '*_databento_trades.jsonl' → BOT 2 V1 ARCHIVE (databento_paper_trader.py — deprecated 11/05)
      - '*_databento_v3_trades.jsonl' → BOT 3 MP (databento_paper_trader_v2.py Sim1)

    FIX 29/04 soir (verdict code-reviewer NOGO) : le glob '*_trades.jsonl'
    matche AUSSI '*_databento_trades.jsonl' → Bot 1 stats incluaient les
    trades Bot 2 = double-comptage dashboard. Exclusion explicite des fichiers
    contenant 'databento' quand le pattern est Bot 1.

    FIX 11/05/2026 (audit Bot 2 V6 stats fausses -$2783 vs reel +$868) :
    le glob '*_trades.jsonl' matche AUSSI '*_v6_trades.jsonl' → Bot 1 stats
    polluees par trades Bot 2 V6. Exclusion explicite 'v6' du pattern Bot 1.
    Idem '*_databento_v3_trades.jsonl' Bot 3 (deja exclu par 'databento' match).
    """
    if not PAPER_DIR.exists():
        return
    is_bot1_pattern = "databento" not in pattern and "v6" not in pattern
    for path in sorted(glob(str(PAPER_DIR / pattern))):
        # Filter by filename date
        fname = os.path.basename(path)
        # FIX 29/04 + FIX 11/05 : exclure Bot 2 V1 + Bot 2 V6 + Bot 3 du glob Bot 1
        if is_bot1_pattern and ("databento" in fname or "v6" in fname):
            continue
        try:
            date_str = fname.split("_")[0]
            file_date = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
            if file_date.date() < (since_utc - timedelta(days=1)).date():
                continue
        except (ValueError, IndexError):
            pass
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        trade = json.loads(line)
                        # FIX 11/05/2026 (cleanup phantom trades DMP Gold pollution) :
                        # Skip les trades marques INVALIDATED via cleanup_phantom_paper_trades.py.
                        # 5 trades concernes : NQ 25/04 (2x) + ES 10/05 (3x DMP Gold pollute).
                        # Voir DOCS/INCIDENT_LOG.md cat VALIDATION_MISS.
                        if trade.get("invalidated"):
                            continue
                        exit_time_str = trade.get("exit_time", "")
                        try:
                            trade_ts = datetime.fromisoformat(exit_time_str.replace("Z", "+00:00"))
                            if trade_ts >= since_utc:
                                yield trade
                        except (ValueError, AttributeError):
                            continue
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue


def compute_stats_period(days: int, pattern: str = "*_trades.jsonl") -> dict:
    """Calcule stats sur N jours passes (WR, PF, PnL total, count par symbol).

    pattern :
      - '*_trades.jsonl'              (BOT 1 DMP, Sim3)
      - '*_databento_trades.jsonl'    (BOT 2 V1 ARCHIVE — deprecated 11/05)
      - '*_v6_trades.jsonl'           (BOT 2 V6 Sim2)
      - '*_databento_v3_trades.jsonl' (BOT 3 MP, Sim1)
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    trades_raw = list(_iter_trades_from_files(since, pattern))
    # 13/05 FIX (Jackson "ON VOIS TOUJOURS PAS DONNER DES TRADE") : Bot 3 v3
    # logge des entries RECOVERED_TIMEOUT (anti-zombie 2-stage boot) avec
    # pnl_ticks=None + pnl_usd=None → TypeError dans `t.get("pnl_ticks", 0) > 0`
    # car .get retourne None (cle existe mais valeur null), pas le default 0.
    # Bot 1/Bot 2 jamais affectes (jamais de pnl_ticks=None). Aligne sur la
    # protection _is_numeric_pnl de `_compute_stats_today_from_trades` (L267).
    trades = [
        t for t in trades_raw
        if isinstance(t.get("pnl_ticks"), (int, float))
        and t.get("pnl_ticks") == t.get("pnl_ticks")  # exclut NaN (NaN != NaN)
    ]
    if not trades:
        return {"trades": 0, "wr": 0, "pf": None, "pnl_usd": 0, "pnl_ticks": 0, "by_symbol": {}}

    wins = [t for t in trades if t.get("pnl_ticks", 0) > 0]
    losses = [t for t in trades if t.get("pnl_ticks", 0) <= 0]
    win_ticks = sum(t.get("pnl_ticks", 0) for t in wins) if wins else 0
    loss_ticks = sum(abs(t.get("pnl_ticks", 0)) for t in losses) if losses else 0
    total_usd = sum(t.get("pnl_usd", 0) for t in trades)

    by_sym = {}
    for sym in ("ES", "NQ"):
        subset = [t for t in trades if t.get("symbol") == sym]
        if not subset:
            by_sym[sym] = {"trades": 0, "wr": 0, "pnl_usd": 0, "pf": None}
            continue
        sw = [t for t in subset if t.get("pnl_ticks", 0) > 0]
        sl = [t for t in subset if t.get("pnl_ticks", 0) <= 0]
        sw_t = sum(t.get("pnl_ticks", 0) for t in sw) if sw else 0
        sl_t = sum(abs(t.get("pnl_ticks", 0)) for t in sl) if sl else 0
        by_sym[sym] = {
            "trades": len(subset),
            "wr": round(len(sw) / len(subset) * 100, 1),
            "pf": round(sw_t / sl_t, 2) if sl_t > 0 else None,
            "pnl_usd": round(sum(t.get("pnl_usd", 0) for t in subset), 2),
        }

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "wr": round(len(wins) / len(trades) * 100, 1),
        "pf": round(win_ticks / loss_ticks, 2) if loss_ticks > 0 else None,
        "pnl_usd": round(total_usd, 2),
        "pnl_ticks": round(sum(t.get("pnl_ticks", 0) for t in trades), 1),
        "by_symbol": by_sym,
    }


def _compute_stats_today_from_trades(pattern: str) -> dict:
    """Calcule stats_today + closed_today depuis trades.jsonl du CME trading day.

    FIX 29/04 soir (bug dashboard PnL Bot 2 = $0) : Bot 2 (databento_paper_state.json)
    n'ecrit PAS les champs stats_today/closed_today/trade_count_today que Bot 1
    fournit. Le frontend lisant state.stats_today trouvait null pour Bot 2 →
    affichage 0 trades / $0.00 / WR 0% alors que trades.jsonl contient X trades.

    FIX 30/04 (Jackson "BOT 2 NN remis a zero a Tokyo open") : avant, on
    filtrait par UTC midnight. Le bot rollover a 18:00 ET (convention CME)
    via get_cme_trading_day() → ecart 4-6h ou le dashboard montrait encore
    les stats du trading day precedent alors que le bot avait deja roll.
    Maintenant on aligne sur la meme convention : start = 18:00 ET du day
    courant.

    Solution : calculer ces champs cote backend a partir des trades.jsonl du
    CME trading day. Coherent avec stats_7d/30d (deja calcules a la volee).
    """
    today_start = _cme_trading_day_start_utc()
    trades_raw = list(_iter_trades_from_files(today_start, pattern))
    if not trades_raw:
        return {
            "stats_today": {"trades": 0, "wins": 0, "losses": 0, "wr": 0,
                             "pf": None, "pnl_usd": 0, "pnl_ticks": 0},
            "closed_today": [],
            "trade_count_today": 0,
            "stats_by_symbol": {"ES": {"trades": 0}, "NQ": {"trades": 0}},
        }

    # FIX 06/05 soir (P0 review code-reviewer) : DEDUP par signal_id.
    # Le fix Type 209 capture (cid_type='flatten') re-log une 2eme ligne JSONL
    # avec pnl_known=true APRES la 1ere ligne pnl=null logge a chaud par
    # _bot3_check_timeout ETAPE 8. Sans dedup, le dashboard double-compte
    # le trade dans `trade_count_today`.
    # Strategie : pour chaque signal_id, garder la ligne avec pnl_known=true
    # si dispo, sinon la 1ere. Bot 1/2 ne re-loggent jamais → comportement inchange.
    # `pos_snapshot` (envoye dans entry _bot3_cid_index) preserve le signal_id pour
    # que la 2eme ligne soit dedupable.
    def _is_numeric_pnl(t):
        v = t.get("pnl_ticks")
        return isinstance(v, (int, float)) and not (v != v)  # exclut NaN aussi

    def _is_official_pnl(t):
        """FIX 07/05 Solution A v2 : PnL utilisable pour metriques Lopez officielles
        (PF, Sharpe, DSR). Exclut les pnl approximatifs via close JSONL DMP
        (TIMEOUT Bot 3 sans fill Type 209 capture) marques pnl_estimated=True.

        Garde _is_numeric_pnl pour total $ informationnel dashboard.
        Bot 1 / Bot 2 V6 n'emettent pas pnl_estimated -> retro-compat OK.
        """
        return _is_numeric_pnl(t) and not t.get("pnl_estimated", False)

    # Dedup par signal_id : known_pnl gagne sur null, ordre conserve sinon
    seen: dict = {}
    for t in trades_raw:
        sig_id = t.get("signal_id")
        if not sig_id:
            # Pas de signal_id : conserver tel quel (ne peut pas etre dedup)
            seen[id(t)] = t  # cle unique ad-hoc pour preserver l'ordre
            continue
        prev = seen.get(sig_id)
        if prev is None:
            seen[sig_id] = t
        else:
            # Preferer la ligne avec pnl_known=true. Si les 2 sont known/unknown,
            # garder la plus recente (= ordre du fichier append-only).
            prev_known = _is_numeric_pnl(prev)
            curr_known = _is_numeric_pnl(t)
            if curr_known and not prev_known:
                seen[sig_id] = t  # promouvoir
            elif curr_known == prev_known:
                seen[sig_id] = t  # plus recente
            # else (prev known, curr unknown) : keep prev
    trades = list(seen.values())
    known_trades = [t for t in trades if _is_numeric_pnl(t)]
    # FIX 07/05 Solution A v2 : PF/Sharpe/wr OFFICIEL exclut pnl_estimated=True
    # (close JSONL DMP approximation TIMEOUT Bot 3). Total $ informationnel
    # garde tous les pnl numeriques (estim inclus pour visualisation).
    official_trades = [t for t in trades if _is_official_pnl(t)]

    wins = [t for t in official_trades if t.get("pnl_ticks", 0) > 0]
    losses = [t for t in official_trades if t.get("pnl_ticks", 0) <= 0]
    win_ticks = sum(t.get("pnl_ticks", 0) for t in wins)
    loss_ticks = sum(abs(t.get("pnl_ticks", 0)) for t in losses)
    # Total $ = tous les pnl numeriques (info dashboard, pas Lopez)
    pnl_usd = sum(t.get("pnl_usd", 0) or 0 for t in known_trades)
    pnl_ticks = sum(t.get("pnl_ticks", 0) for t in known_trades)

    by_sym = {}
    for sym in ("ES", "NQ"):
        sub = [t for t in known_trades if t.get("symbol") == sym]
        sub_all = [t for t in trades if t.get("symbol") == sym]  # tous (pour count)
        if not sub_all:
            by_sym[sym] = {"trades": 0, "wins": 0, "losses": 0, "wr": 0,
                            "pnl_usd": 0, "pnl_ticks": 0}
            continue
        sw = [t for t in sub if t.get("pnl_ticks", 0) > 0]
        sl = [t for t in sub if t.get("pnl_ticks", 0) <= 0]
        wr_pct = round(len(sw) / len(sub) * 100, 1) if sub else 0.0
        by_sym[sym] = {
            "trades": len(sub_all),
            "wins": len(sw),
            "losses": len(sl),
            "wr": wr_pct,
            "pnl_usd": round(sum(t.get("pnl_usd", 0) or 0 for t in sub), 2),
            "pnl_ticks": round(sum(t.get("pnl_ticks", 0) for t in sub), 1),
        }

    # FIX 06/05 : wr / count denominators bases sur known_trades pour ne pas
    # diluer les stats avec TIMEOUT pnl=None (Bot 3). Bot 1/2 : aucun TIMEOUT
    # pnl=None dans leurs schemas → known_trades == trades, comportement inchange.
    n_known = len(known_trades)
    return {
        "stats_today": {
            "trades": len(trades),                        # display total
            "trades_known_pnl": n_known,                  # for stats fairness
            "wins": len(wins),
            "losses": len(losses),
            "wr": round(len(wins) / n_known * 100, 1) if n_known else 0.0,
            "pf": round(win_ticks / loss_ticks, 2) if loss_ticks > 0 else None,
            "pnl_usd": round(pnl_usd, 2),
            "pnl_ticks": round(pnl_ticks, 1),
        },
        "closed_today": trades,
        "trade_count_today": len(trades),
        "stats_by_symbol": by_sym,
    }


def _build_bot_payload(state_file: Path, trades_pattern: str, bot_label: str) -> dict:
    """Construit payload pour 1 bot (BOT 1 DMP ou BOT 2 DB).

    bot_label : 'dmp' (Sim3) ou 'db' (Sim2)
    """
    state = _safe_read_state(state_file)
    stats_7d = compute_stats_period(7, trades_pattern)
    stats_30d = compute_stats_period(30, trades_pattern)

    # FIX 29/04 soir : si state n'a pas stats_today (cas Bot 2 DB), calculer
    # a la volee depuis trades.jsonl. Bot 1 DMP ecrit deja ces champs dans
    # state.json, donc le merge laisse le state intacte si present.
    if not state.get("stats_today") or not state.get("closed_today"):
        computed = _compute_stats_today_from_trades(trades_pattern)
        # Merge : ne pas overrider les champs deja presents (Bot 1)
        for key, val in computed.items():
            if not state.get(key):
                state[key] = val

    # Determine has_open selon format state (DMP utilise open_by_symbol, DB utilise active_positions)
    has_open = bool(state.get("open_by_symbol")) or bool(state.get("active_positions"))
    has_cooldown = any(
        (cs.get("cooldown_remaining_sec", 0) > 0 or cs.get("circuit_breaker_remaining_sec", 0) > 0)
        for cs in (state.get("cooldown_status") or {}).values()
    )

    # Age du state (DMP utilise updated_ts, DB Bot 2 utilise ts_utc, Bot 3 utilise updated_iso/ts)
    # Fix 04/05 soir : Bot 2 expose `ts_utc`, le code cherchait `ts` -> age_sec None ->
    # bouton ROUGE/INACTIF dashboard alors que Bot 2 tournait normalement.
    age_sec = None
    updated_ts = state.get("updated_ts")
    if updated_ts:
        age_sec = max(0, datetime.now(timezone.utc).timestamp() - updated_ts)
    else:
        # Tente plusieurs champs ISO selon format state (Bot 2 vs Bot 3 vs DMP)
        ts_iso = state.get("ts_utc") or state.get("updated_iso") or state.get("ts")
        if ts_iso:
            try:
                db_ts = datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00"))
                age_sec = max(0, (datetime.now(timezone.utc) - db_ts).total_seconds())
            except (ValueError, AttributeError):
                pass

    # 17/05 (Jackson "voyant flux source") : extraire bar_source state.json brain_v6
    # pour exposer cote dashboard. Critique apres avoir perdu 5 jours de fallback DMP
    # silencieux sur Bot 2 V6 (V4 stale -> fallback DMP 100%, invisible).
    # bar_source format : {"global": str, "per_symbol": {sym: source}, "ts_per_symbol": {...}}
    # sources possibles : "V4" / "DMP_BOT" / "DMP_JSONL" / "INIT"
    bar_source = state.get("bar_source") or {}

    return {
        "bot": bot_label,
        "state": state,
        "stats_7d": stats_7d,
        "stats_30d": stats_30d,
        "has_paper_active": has_open or has_cooldown,
        "state_age_sec": age_sec,
        "paper_trader_alive": age_sec is not None and age_sec < 120,
        # 17/05 Jackson : voyant flux source data Bot 2 V6 (V4 / DMP_BOT / DMP_JSONL)
        "bar_source": bar_source,
    }


def get_paper_trades_payload() -> dict:
    """Retourne payload BOT 1 DMP (compat existante : preserve schema). """
    return _build_bot_payload(STATE_FILE, "*_trades.jsonl", "dmp")


def _clean_nan_inf(obj):
    """Remplace recursivement NaN/Inf/-Inf par None pour serialisation JSON.

    FIX 30/04 (Jackson "TOUJOURS PAS RESOLUE") : /api/paper_trades_dual
    retournait 500 ValueError "Out of range float values are not JSON
    compliant" car state.json contient parfois NaN/Inf dans :
    - features at entry/exit (DMP bars)
    - last_cross_context (rare)
    - stats_by_symbol pf si edge case

    JSON strict (FastAPI default) refuse NaN/Inf → tout l'endpoint plante 500
    → frontend voit `paperData = {}` → "Aucune donnee (trader jamais demarre)"
    + closed_today vide alors que state a 20+ trades.

    Solution : nettoyage recursif post-build. Conserve types autres (int/str/
    bool/None/list/dict). Remplace float NaN/Inf par None (JSON-safe).
    """
    import math
    if obj is None:
        return None
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _clean_nan_inf(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nan_inf(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_clean_nan_inf(v) for v in obj)
    return obj


def get_dual_bots_payload() -> dict:
    """Retourne payload des DEUX bots (BOT 1 DMP Sim3 + BOT 2 DB Sim2).

    Structure :
      {
        "bot1_dmp": {state, stats_7d, stats_30d, has_paper_active, ...},
        "bot2_db":  {state, stats_7d, stats_30d, has_paper_active, ...},
        "eco_status": {blocked, reason, blocked_until_iso, resume_in_sec}
      }

    FIX 30/04 (Jackson "ON AURAIS DU A VOIR UN TIMER") : ajout cle
    `eco_status` partagee par les 2 bots (les blocs eco/session s'appliquent
    aux 2 bots simultanement). Le frontend utilise resume_in_sec pour
    afficher "Bot reprend dans HH:MM".

    FIX 30/04 v2 : cleanup NaN/Inf avant return (prevent JSON 500 error).
    """
    # 04/05 SOIR FIX : `STATE_FILE_DB` = V1 DEPRECATED (databento_paper_state.json,
    # last 02/05) → bouton Bot 2 ROUGE alors que Bot 2 V2 (Sim2 SetupEngine) tourne
    # bien sur `STATE_FILE_DB_V2` (databento_paper_v2_state.json). Fix : pointer
    # vers V2 qui est le bot reellement actif depuis 02/05/2026.
    payload = {
        "bot1_dmp": _build_bot_payload(STATE_FILE, "*_trades.jsonl", "dmp"),
        # FIX 11/05 (audit bug attribution) : pattern *_databento_trades.jsonl = Bot 2 V1 ARCHIVE
        # (deprecated 11/05). Bot 2 V6 utilise state_v6.json + *_v6_trades.jsonl.
        "bot2_db":  _build_bot_payload(STATE_FILE_DB_V2, "*_v6_trades.jsonl", "db"),
        "eco_status": get_eco_status_payload(),
    }
    return _clean_nan_inf(payload)


def get_bot2_v2_payload() -> dict:
    """BOT 2 V2 (SetupEngine 11 setups, Sim2, deploye 02/05/2026 dimanche soir).

    Structure :
      {
        "state_file": "databento_paper_v2_state.json",
        "state": <contenu state.json brut>,
        "positions_with_countdown": {NQ: {...,seconds_until_timeout, session_label_entry}, ES: ...},
        "setup_stats": {SETUP_NAME: {n_trades, wr_pct, pf, pnl_total_usd, mfe_avg_ticks, ...}},
        "trades_today": [...],  # depuis JSONL
        "trading_window_utc": "2h-21h",
        "phase_1_free_run": True/False,
      }

    Endpoint pour frontend dashboard V2 : afficher countdown timeout + session
    + setup tracking en temps reel.
    """
    state = _safe_read_state(STATE_FILE_DB_V2)
    if not state:
        return {
            "state_file": "databento_paper_v2_state.json",
            "state": None,
            "available": False,
            "msg": "Bot V2 non actif ou state.json non disponible",
        }

    return _clean_nan_inf({
        "state_file": "databento_paper_v2_state.json",
        "state": state,
        "positions_with_countdown": state.get("positions", {}),
        "setup_stats": state.get("setup_stats", {}),
        "trading_window_utc": state.get("trading_window_utc", "2h-21h"),
        "phase_1_free_run": state.get("phase_1_free_run", True),
        "mode": state.get("mode", "PAPER_TRADE_V2"),
        "trade_account": state.get("trade_account", "Sim2"),
        "available": True,
        "ts_utc": state.get("ts_utc"),
    })


def get_bot3_payload() -> dict:
    """BOT 3 MP (Market Profile, 13 niveaux Tier 1/2/3, Sim1, deploye 03/05/2026).

    Structure :
      {
        "state_file": "databento_paper_v3_state.json",
        "state": <contenu state.json brut>,
        "positions_with_countdown": {NQ: {..., seconds_until_timeout, level, side, action, confidence}, ES: ...},
        "level_stats": {LEVEL_NAME: {n_contacts, n_go, n_skip, win_rate, pf, pnl_total_usd, avg_confidence, baseline_rej, baseline_pf}, ...},
        "recent_decisions": [{ts, level, decision, reason, sym, ctx_summary}, ...20 dernieres],
        "phase": "OBSERVE_ONLY" | "PAPER_TIER1" | "FULL",
        "trade_rejections": bool, "trade_breakouts": bool,
        "trading_window_utc": "2h-21h",
        "trade_account": "Sim1",
        "available": True,
      }

    Endpoint pour frontend dashboard Bot 3 : afficher contacts niveaux temps reel
    + level_stats par niveau + recent_decisions feed live (Phase 1 critique pour audit).
    """
    state = _safe_read_state(STATE_FILE_BOT3)
    if not state:
        return {
            "state_file": "databento_paper_v3_state.json",
            "state": None,
            "available": False,
            "state_age_sec": None,
            "paper_trader_alive": False,
            "msg": "Bot 3 MP non actif ou state.json non disponible",
        }

    # P1 audit 17/05 (Jackson Q1) : aligner staleness backend Bot 3 avec Bot 1/2
    # `_build_bot_payload` (lignes 402-414). Avant : frontend calculait age cote
    # JS mais ne signalait JAMAIS staleness (paper_trader_alive=d.available
    # statique). Sans cet ajout, freeze 6h Bot 3 invisible sur dashboard.
    age_sec = None
    ts_iso = state.get("ts_utc") or state.get("updated_iso") or state.get("ts")
    if ts_iso:
        try:
            db_ts = datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00"))
            age_sec = max(0, (datetime.now(timezone.utc) - db_ts).total_seconds())
        except (ValueError, AttributeError):
            pass

    # SOLUTION DURABLE 06/05 (Plan agent GO) : closed_today + stats_today lus
    # depuis le journal append-only `*_databento_v3_trades.jsonl` ecrit par
    # Bot 3 (cf `_bot3_log_trade_close`). Source de verite unique :
    # - audit J+30 cross-bot via glob unifie
    # - restart-safe (fichier persiste)
    # - pas de cap memoire, historique illimite
    # - coherent Bot 1 (`*_trades.jsonl`) et Bot 2 V2 (`*_databento_trades.jsonl`)
    bot3_stats = _compute_stats_today_from_trades("*_databento_v3_trades.jsonl")
    # Cap display 50 derniers trades (volume potentiel Bot 3 = 13 niveaux × 2 sym)
    closed_full = bot3_stats.get("closed_today", [])
    closed_display = closed_full[-50:] if len(closed_full) > 50 else closed_full

    # 13/05 FIX section "7/30 derniers jours" vide pour Bot 3 (Jackson) :
    # get_bot3_payload n'exposait que stats_today, contrairement a _build_bot_payload
    # (Bot 1/Bot 2) qui calcule stats_7d/30d. Frontend (_renderPaperStatsPeriod) lit
    # paperData.stats_7d/30d -> undefined -> "Pas de donnees historiques".
    stats_7d = compute_stats_period(7, "*_databento_v3_trades.jsonl")
    stats_30d = compute_stats_period(30, "*_databento_v3_trades.jsonl")

    return _clean_nan_inf({
        "state_file": "databento_paper_v3_state.json",
        "state": state,
        "positions_with_countdown": state.get("positions", {}),
        "level_stats": state.get("level_stats", {}),
        "recent_decisions": state.get("recent_decisions", [])[-20:],  # 20 dernieres
        "n_contacts_today": state.get("n_contacts_today", {"NQ": 0, "ES": 0}),
        "n_go_today": state.get("n_go_today", {"NQ": 0, "ES": 0}),
        "n_skip_today": state.get("n_skip_today", {"NQ": 0, "ES": 0}),
        "n_veto_today": state.get("n_veto_today", {"NQ": 0, "ES": 0}),
        # Source = journal JSONL (cf `_compute_stats_today_from_trades` ligne 232+)
        "closed_today": closed_display,
        "trade_count_today": bot3_stats.get("trade_count_today", 0),
        "stats_today": bot3_stats.get("stats_today", {}),
        "stats_by_symbol": bot3_stats.get("stats_by_symbol", {}),
        "stats_7d": stats_7d,
        "stats_30d": stats_30d,
        "phase": state.get("phase", "OBSERVE_ONLY"),
        "trade_rejections": state.get("trade_rejections", True),
        "trade_breakouts": state.get("trade_breakouts", True),
        "tier2_enabled": state.get("tier2_enabled", False),
        "tier3_enabled": state.get("tier3_enabled", False),
        "trading_window_utc": state.get("trading_window_utc", "2h-21h"),
        "trade_account": state.get("trade_account", "Sim1"),
        "mode": state.get("mode", "OBSERVE_ONLY"),
        "available": True,
        "ts_utc": state.get("ts_utc"),
        # P1 audit 17/05 : surveillance staleness backend (aligne Bot 1/2).
        "state_age_sec": age_sec,
        "paper_trader_alive": age_sec is not None and age_sec < 120,
    })
