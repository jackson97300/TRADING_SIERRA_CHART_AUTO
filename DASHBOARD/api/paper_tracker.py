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
STATE_FILE_DB = PAPER_DIR / "databento_paper_state.json"           # BOT 2 DB (databento_paper Sim2)

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
    """Lit state.json (atomic read, fallback dict vide si absent)."""
    if not state_file.exists():
        return _empty_state()
    try:
        with state_file.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
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

    pattern : '*_trades.jsonl' (BOT 1 DMP) ou '*_databento_trades.jsonl' (BOT 2 DB)

    FIX 29/04 soir (verdict code-reviewer NOGO) : le glob '*_trades.jsonl'
    matche AUSSI '*_databento_trades.jsonl' → Bot 1 stats incluaient les
    trades Bot 2 = double-comptage dashboard. Exclusion explicite des fichiers
    contenant 'databento' quand le pattern est Bot 1.
    """
    if not PAPER_DIR.exists():
        return
    is_bot1_pattern = "databento" not in pattern
    for path in sorted(glob(str(PAPER_DIR / pattern))):
        # Filter by filename date
        fname = os.path.basename(path)
        # FIX 29/04 soir : exclure les fichiers Bot 2 du glob Bot 1
        if is_bot1_pattern and "databento" in fname:
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

    pattern : '*_trades.jsonl' (BOT 1 DMP) ou '*_databento_trades.jsonl' (BOT 2 DB)
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    trades = list(_iter_trades_from_files(since, pattern))
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
    trades = list(_iter_trades_from_files(today_start, pattern))
    if not trades:
        return {
            "stats_today": {"trades": 0, "wins": 0, "losses": 0, "wr": 0,
                             "pf": None, "pnl_usd": 0, "pnl_ticks": 0},
            "closed_today": [],
            "trade_count_today": 0,
            "stats_by_symbol": {"ES": {"trades": 0}, "NQ": {"trades": 0}},
        }

    wins = [t for t in trades if t.get("pnl_ticks", 0) > 0]
    losses = [t for t in trades if t.get("pnl_ticks", 0) <= 0]
    win_ticks = sum(t.get("pnl_ticks", 0) for t in wins)
    loss_ticks = sum(abs(t.get("pnl_ticks", 0)) for t in losses)
    pnl_usd = sum(t.get("pnl_usd", 0) for t in trades)
    pnl_ticks = sum(t.get("pnl_ticks", 0) for t in trades)

    by_sym = {}
    for sym in ("ES", "NQ"):
        sub = [t for t in trades if t.get("symbol") == sym]
        if not sub:
            by_sym[sym] = {"trades": 0, "wins": 0, "losses": 0, "wr": 0,
                            "pnl_usd": 0, "pnl_ticks": 0}
            continue
        sw = [t for t in sub if t.get("pnl_ticks", 0) > 0]
        sl = [t for t in sub if t.get("pnl_ticks", 0) <= 0]
        by_sym[sym] = {
            "trades": len(sub),
            "wins": len(sw),
            "losses": len(sl),
            "wr": round(len(sw) / len(sub) * 100, 1),
            "pnl_usd": round(sum(t.get("pnl_usd", 0) for t in sub), 2),
            "pnl_ticks": round(sum(t.get("pnl_ticks", 0) for t in sub), 1),
        }

    return {
        "stats_today": {
            "trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "wr": round(len(wins) / len(trades) * 100, 1),
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

    # Age du state (DMP utilise updated_ts, DB utilise ts ISO)
    age_sec = None
    updated_ts = state.get("updated_ts")
    if updated_ts:
        age_sec = max(0, datetime.now(timezone.utc).timestamp() - updated_ts)
    elif state.get("ts"):
        try:
            db_ts = datetime.fromisoformat(state["ts"].replace("Z", "+00:00"))
            age_sec = max(0, (datetime.now(timezone.utc) - db_ts).total_seconds())
        except (ValueError, AttributeError):
            pass

    return {
        "bot": bot_label,
        "state": state,
        "stats_7d": stats_7d,
        "stats_30d": stats_30d,
        "has_paper_active": has_open or has_cooldown,
        "state_age_sec": age_sec,
        "paper_trader_alive": age_sec is not None and age_sec < 120,
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
    payload = {
        "bot1_dmp": _build_bot_payload(STATE_FILE, "*_trades.jsonl", "dmp"),
        "bot2_db":  _build_bot_payload(STATE_FILE_DB, "*_databento_trades.jsonl", "db"),
        "eco_status": get_eco_status_payload(),
    }
    return _clean_nan_inf(payload)
