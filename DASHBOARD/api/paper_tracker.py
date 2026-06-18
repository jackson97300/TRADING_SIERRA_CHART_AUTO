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
STATE_FILE = PAPER_DIR / "state.json"                              # BOT 1 DMP (mia_paper Sim2 — reactive 07/06/2026 par Jackson, remplace V2 SetupEngine casse)
STATE_FILE_DB = PAPER_DIR / "databento_paper_state.json"           # BOT 2 DB V1 (databento_paper Sim2 — DEPRECATED)
STATE_FILE_DB_V2 = PAPER_DIR / "state_v6.json"                     # BOT 2 V6 (mia2_brain_v6_databento, V4 enriched 456 cols, Sim2, 05/05/2026)
STATE_FILE_BOT3 = PAPER_DIR / "databento_paper_v3_state.json"      # BOT 3 MP (Market Profile 13 niveaux, Sim1, 03/05/2026)

# BN V4 (Bot 2 v3 Bataille Navale, deploye 23/05/2026 Jackson) :
# Pas de state.json (architecture JSONL append-only via BNV4Logger).
# Source de verite = LOGS/bn_v4/bn_v4_v1_YYYYMMDD.jsonl (events lifecycle).
LOGS_BN_V4_DIR = _ROOT / "LOGS" / "bn_v4"
LOGS_BN_V4_PATTERN = "bn_v4_v1_*.jsonl"

# Bot 3 v3 Continuation (Sim1 NQ) + Bot 3 v4 Data-driven (Sim3 NQ) — deploy 24/05/2026
# Source verite : LOGS/bot3_v{3,4}/bot3_v{3,4}_v1_YYYYMMDD.jsonl (events lifecycle).
LOGS_BOT3_V3_DIR = _ROOT / "LOGS" / "bot3_v3"
LOGS_BOT3_V4_DIR = _ROOT / "LOGS" / "bot3_v4"
LOGS_BOT3_V3_PATTERN = "bot3_v3_v1_*.jsonl"
LOGS_BOT3_V4_PATTERN = "bot3_v4_v1_*.jsonl"

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


# 03/06 P2 FIX (Jackson directive : PnL day pollué par RECOVERED_TIMEOUT fictifs) :
# Quand paper_v2 crash mid-trade et redemarre, _bot3_recover_open_positions detecte
# position broker sans tracking + marque level="_RECOVERED_BOOT_" + flush au timeout
# 60min mark-to-market = PnL ALEATOIRE (chance pure, pas un edge).
# Cf incident 03/06 09:01 : ES RECOVERED -$25 + 07:27 NQ RECOVERED -$150 = -$175
# fictifs qui polluent stats today.
# Le filtre exclut ces closes des calculs pnl/wins/losses/PF dans tous les payloads.
# Filtre existant Bot 1 ancien state.json ligne 250 - on l'unifie ici.
_RECOVERED_TIMEOUT_MARKERS = ("RECOVERED_TIMEOUT", "RECOVERED")
_RECOVERED_TIMEOUT_LEVEL = "_RECOVERED_BOOT_"


def _is_recovered_fictive_close(close_event: dict) -> bool:
    """Detecte si un close_event correspond a un RECOVERED_TIMEOUT fictif.

    Critères (ANY) :
      - level == "_RECOVERED_BOOT_" (event emis par databento_paper_v2 timeout flush)
      - exit_cause / outcome / reason / exit_reason in {"RECOVERED_TIMEOUT", "RECOVERED"}

    Used by stats payloads (Bot 1 v3, Bot 3 v4, Bot 1 MP, BN V4) pour exclure
    les pnl/wins/losses inventes au boot post-crash de paper_v2.

    Compatibilite : retourne False pour close_event=None ou dict vide (safe default).
    """
    if not close_event or not isinstance(close_event, dict):
        return False
    if close_event.get("level") == _RECOVERED_TIMEOUT_LEVEL:
        return True
    # Plusieurs champs possibles selon source logger (bot3_v3_paper, bot3_v4_paper, MP)
    for field in ("exit_cause", "exit_cause_mechanical", "outcome", "reason", "exit_reason"):
        if close_event.get(field) in _RECOVERED_TIMEOUT_MARKERS:
            return True
    # Aussi ctx nested (cas BOT3_FLATTEN_FILL_CAPTURED logger MP + Bot 4 BOT4_RISK qui met tout en ctx)
    # 03/06 P2 fix code-reviewer Q3 : symetrie defensive avec les 6 fields racine
    ctx = close_event.get("ctx") or {}
    if isinstance(ctx, dict):
        if ctx.get("level") == _RECOVERED_TIMEOUT_LEVEL:
            return True
        for field in ("exit_cause", "exit_cause_mechanical", "outcome", "reason", "exit_reason"):
            if ctx.get(field) in _RECOVERED_TIMEOUT_MARKERS:
                return True
    return False


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
      - '*_trades.jsonl'          → BOT 1 DMP (mia_paper_trader.py Sim2 (reactive 07/06/2026))
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
                        # FIX 19/05/2026 (Jackson directive : SUPPRIME ZOMBIES DES DONNER) :
                        # Skip les trades zombies RECOVERED_TIMEOUT. Quand le service
                        # paper_trader_v2 redemarre avec une position ouverte cote
                        # broker sans tracking interne (level/scenario perdus), le
                        # bot detecte la position via `_bot3_recover_open_positions`
                        # et la marque level="_RECOVERED_BOOT_" + action="RECOVERED".
                        # Au timeout 60min, fermeture mark-to-market => PnL aleatoire
                        # (chance pure, pas un edge). Cf incident Phase 4d deploy 18/05 :
                        # NQ SHORT +$1968 par chance, mfe=0/mae=0 = preuve absence
                        # tracking. NE PAS COMPTER dans stats edge analysis.
                        if (trade.get("level") == "_RECOVERED_BOOT_"
                                or trade.get("outcome") == "RECOVERED_TIMEOUT"
                                or trade.get("action") == "RECOVERED"
                                or trade.get("exit_reason") == "RECOVERED_TIMEOUT"):
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
      - '*_trades.jsonl'              (BOT 1 DMP, Sim2 reactive 07/06/2026)
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
    """Retourne payload des DEUX bots (BOT 1 DMP Sim2 reactive + BOT 2 BN V4 ARCHIVE).

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
    # Route 23/05/2026 Jackson : Bot 2 source data depend ENV MIA_BN_V4_ENABLED.
    # - "1" : BN V4 actif -> bot2_db = lecture JSONL `LOGS/bn_v4/`
    # - sinon : legacy Bot 2 V6 (state_v6.json + *_v6_trades.jsonl)
    # Cle `bot2_db` conservee pour eviter regression dashboard.js (25+ refs).
    # Dette nommage acceptee (CHANGELOG 23/05 + IDEAS_BACKLOG).
    # 04/06/2026 Jackson FIX dashboard Bot 2 OFFLINE/FROZEN :
    # BN V4 deprecate 23/05 → BN V5 deploye dans paper_v2 (MIA_BN_V5_ENABLED=1).
    # Route priorite : BN V5 actif > BN V4 (back-compat) > legacy V6 fallback.
    if os.environ.get("MIA_BN_V5_ENABLED", "0") == "1":
        bot2_payload = get_bn_v5_payload()
    elif os.environ.get("MIA_BN_V4_ENABLED", "0") == "1":
        bot2_payload = get_bn_v4_payload()
    else:
        # FIX 11/05 (audit bug attribution) : pattern *_databento_trades.jsonl = Bot 2 V1 ARCHIVE
        # (deprecated 11/05). Bot 2 V6 utilise state_v6.json + *_v6_trades.jsonl.
        bot2_payload = _build_bot_payload(STATE_FILE_DB_V2, "*_v6_trades.jsonl", "db")

    payload = {
        "bot1_dmp": _build_bot_payload(STATE_FILE, "*_trades.jsonl", "dmp"),
        "bot2_db":  bot2_payload,
        "eco_status": get_eco_status_payload(),
    }
    return _clean_nan_inf(payload)


def get_bot2_v2_payload() -> dict:
    """BOT 2 endpoint dedie (alias historique "v2", lit V6 ou BN V4 selon ENV).

    Route 23/05/2026 Jackson :
    - Si MIA_BN_V4_ENABLED=1 -> BN V4 payload (Bataille Navale, deploye 23/05)
    - Sinon -> legacy V6 (state_v6.json, brain V6 mort selon Jackson)

    Structure compatible historique pour conserver wiring frontend `paper_v2_state`.
    """
    # 04/06 FIX dashboard Bot 2 : priorite BN V5 actif > BN V4 (back-compat) > V6 legacy.
    if os.environ.get("MIA_BN_V5_ENABLED", "0") == "1":
        return get_bn_v5_payload()
    if os.environ.get("MIA_BN_V4_ENABLED", "0") == "1":
        return get_bn_v4_payload()

    # Legacy V6 path (back-compat sans ENV)
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


# ════════════════════════════════════════════════════════════════════════════════
# BN V4 (Bot 2 v3 — Bataille Navale, deploye 23/05/2026)
# Source = LOGS/bn_v4/bn_v4_v1_YYYYMMDD.jsonl + LOGS/execution/decisions/events
# Lifecycle JSONL append-only (pas de state.json).
# ════════════════════════════════════════════════════════════════════════════════

def _load_bn_v4_today_state(day_str: Optional[str] = None) -> dict:
    """Reconstruit l'etat BN V4 du CME trading day en parsant le JSONL dedie.

    Args:
        day_str : "YYYYMMDD" UTC (default = today CME trading day).

    Returns:
        dict avec :
          positions_active : dict[sym, dict] positions ouvertes (TRADE_OPEN sans TRADE_CLOSE)
          stats_today : {n_setups, n_trades, n_observations, pnl_session_usd, n_sl_consec}
          setup_stats : {grade: {n, wr_pct, pf, pnl_usd}} pour A++ TRADE + A OBSERVE
          recent_setups : last 20 SETUP_DETECTED (mode + grade + density)
          kill_switch_active : bool
          cooldown_until : iso str ou None
          last_heartbeat_ts : iso str du dernier heartbeat
          paper_trader_alive : bool (heartbeat < 120s)
    """
    if day_str is None:
        # Fix 25/05/2026 00:15 UTC bug Jackson : align convention UTC (cf logger BN V4).
        utc_now = datetime.now(timezone.utc)
        day_str = utc_now.strftime("%Y%m%d")

    # 27/05/2026 fix Jackson "BN V4 rotation pas faite" :
    # Le CME trading day commence 22:00 UTC J-1 et finit 22:00 UTC J.
    # Entre 22:00 et 23:59 UTC les events sont dans le fichier UTC J.
    # Apres 00:00 UTC J+1, events dans le fichier J+1. Le CME day continue.
    # Donc pour lire TOUS les events du CME day courant, il faut potentiellement 2 fichiers UTC.
    # Meme fix que `_load_bot3_vN_today_state` deploye 26/05.
    cme_start_for_files = _cme_trading_day_start_utc()
    utc_now_for_files = datetime.now(timezone.utc)
    files_to_read: list = []
    seen_days = set()
    for day_dt in [cme_start_for_files, utc_now_for_files]:
        d_str = day_dt.strftime("%Y%m%d")
        if d_str in seen_days:
            continue
        seen_days.add(d_str)
        candidate = LOGS_BN_V4_DIR / f"bn_v4_v1_{d_str}.jsonl"
        if candidate.exists():
            files_to_read.append(candidate)

    if not files_to_read:
        return {
            "positions_active": {},
            "stats_today": {"n_setups": 0, "n_trades": 0, "n_observations": 0,
                             "pnl_session_usd": 0.0, "n_sl_consec": {}},
            "setup_stats": {},
            "recent_setups": [],
            "kill_switch_active": False,
            "cooldown_until": None,
            "last_heartbeat_ts": None,
            "paper_trader_alive": False,
            "day_str": day_str,
            "available": False,
        }

    # Parse JSONL (1 ou 2 fichiers cross-rollover UTC midnight)
    events_by_signal_id: dict = {}    # signal_id -> [events ordered]
    setups_log: list = []             # all SETUP_DETECTED
    closes_log: list = []             # all TRADE_CLOSE
    observations_log: list = []       # all OBSERVATION_CLOSE
    kill_switches: list = []
    cooldowns: list = []
    last_heartbeat_ts: Optional[str] = None
    last_event_ts: Optional[datetime] = None

    # Filtre CME day : ne garder que events ts >= cme_start
    cme_start = cme_start_for_files

    for fpath in files_to_read:
      try:
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Filtre CME day (skip events anterieurs au CME start courant)
                ts = d.get("ts")
                try:
                    ts_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if ts_dt < cme_start:
                        continue
                    last_event_ts = ts_dt
                except (ValueError, TypeError):
                    pass

                event = d.get("event", "")
                sid = d.get("signal_id")

                if event == "SETUP_DETECTED":
                    setups_log.append(d)
                    if sid:
                        events_by_signal_id.setdefault(sid, []).append(d)
                elif event == "TRADE_OPEN":
                    if sid:
                        events_by_signal_id.setdefault(sid, []).append(d)
                elif event == "TRADE_CLOSE":
                    closes_log.append(d)
                    if sid:
                        events_by_signal_id.setdefault(sid, []).append(d)
                elif event == "OBSERVATION_CLOSE":
                    observations_log.append(d)
                elif event == "TRAIL_UPDATE":
                    if sid:
                        events_by_signal_id.setdefault(sid, []).append(d)
                elif event == "KILL_SWITCH":
                    kill_switches.append(d)
                elif event == "BAR_PROCESSED":
                    last_heartbeat_ts = ts    # proxy heartbeat (1/min en marche normale)
      except OSError:
        continue  # essayer le fichier suivant

    # Positions actives = TRADE_OPEN sans TRADE_CLOSE matching
    positions_active: dict = {}
    closed_signal_ids = {c.get("signal_id") for c in closes_log if c.get("signal_id")}
    for sid, events in events_by_signal_id.items():
        if sid in closed_signal_ids:
            continue
        # Cherche TRADE_OPEN (= position ouverte sans close)
        open_ev = next((e for e in events if e.get("event") == "TRADE_OPEN"), None)
        if open_ev is None:
            continue
        sym = open_ev.get("symbol")
        if sym is None:
            # Fallback : depuis SETUP_DETECTED
            setup_ev = next((e for e in events if e.get("event") == "SETUP_DETECTED"), None)
            sym = setup_ev.get("symbol") if setup_ev else "?"

        # Trail updates count
        n_trail = sum(1 for e in events if e.get("event") == "TRAIL_UPDATE")

        setup_ev = next((e for e in events if e.get("event") == "SETUP_DETECTED"), None)
        positions_active[sym] = {
            "signal_id": sid,
            "direction": setup_ev.get("direction") if setup_ev else None,
            "grade": setup_ev.get("grade") if setup_ev else None,
            "mode": setup_ev.get("mode") if setup_ev else "TRADE",
            "entry_price": open_ev.get("entry_price"),
            "sl_initial": open_ev.get("sl_initial"),
            "risk_ticks": open_ev.get("risk_ticks"),
            "qty": open_ev.get("qty", 1),
            "n_trail_updates": n_trail,
            "ts_open": open_ev.get("ts"),
        }

    # 27/05/2026 fix Jackson + code-reviewer : Bot 2 BN V4 reutilise le meme
    # signal_id dans plusieurs SETUP_DETECTED (anti-pattern lifecycle BN V4 a fix separe).
    # Sans dedup : un TRADE_CLOSE est compte N fois (1 pour chaque SETUP_DETECTED meme sid).
    # Resultat avant fix : table A++ TRADE affichait $205 au lieu de $102.50 (compte x2).
    # Fix : dedup setups_log par signal_id, garder en priorite mode=TRADE puis le 1er.
    seen_sids = set()
    setups_dedup = []
    for s in setups_log:
        sid_s = s.get("signal_id")
        if not sid_s:
            setups_dedup.append(s)
            continue
        if sid_s in seen_sids:
            continue
        seen_sids.add(sid_s)
        # Priorise le setup avec mode=TRADE pour ce sid (1 setup peut etre re-emit OBSERVE puis TRADE)
        trade_variant = next(
            (x for x in setups_log if x.get("signal_id") == sid_s and x.get("mode") == "TRADE"),
            s
        )
        setups_dedup.append(trade_variant)

    # Stats today (utilise setups_dedup pour counters propres)
    n_setups_today = len(setups_dedup)
    n_trades_today = sum(1 for s in setups_dedup if s.get("mode") == "TRADE")
    n_obs_today = len([s for s in setups_dedup if s.get("mode") == "OBSERVE"])
    # 03/06 P2 FIX : exclure RECOVERED_TIMEOUT fictifs du calcul PnL session
    closes_log = [c for c in closes_log if not _is_recovered_fictive_close(c)]
    pnl_session_usd = sum(c.get("pnl_usd", 0.0) or 0.0 for c in closes_log)

    # Setup_stats par grade (TRADE A++ + OBSERVE A simul)
    # 27/05 fix Option B code-reviewer : iterer sur closes_log + observations_log
    # (chaque close/obs = trade unique par construction logger) au lieu de setups_log.
    # Lookup grade/mode via signal_id -> setup matching (mode TRADE prioritaire).
    setup_stats: dict = {}

    def _lookup_setup_for_sid(sid):
        """Retourne le SETUP_DETECTED le plus pertinent pour ce signal_id.
        Prioritisation : mode=TRADE > mode=OBSERVE > premier trouve.
        """
        if not sid:
            return {"grade": "?", "mode": "TRADE"}
        trade_setup = next(
            (s for s in setups_log if s.get("signal_id") == sid and s.get("mode") == "TRADE"),
            None
        )
        if trade_setup:
            return trade_setup
        return next(
            (s for s in setups_log if s.get("signal_id") == sid),
            {"grade": "?", "mode": "TRADE"}
        )

    # Agreger les TRADE_CLOSE reels (1 close = 1 trade par construction logger)
    for close_ev in closes_log:
        sid_c = close_ev.get("signal_id")
        matched_setup = _lookup_setup_for_sid(sid_c)
        grade = matched_setup.get("grade", "?")
        mode = matched_setup.get("mode", "TRADE")
        key = f"{grade}_{mode}"
        if key not in setup_stats:
            setup_stats[key] = {
                "grade": grade, "mode": mode,
                "n_trades": 0, "n_wins": 0, "n_losses": 0,
                "pnl_R_total": 0.0, "pnl_usd_total": 0.0,
            }
        try:
            pnl_R = float(close_ev.get("pnl_R", 0.0) or 0.0)
            pnl_usd = float(close_ev.get("pnl_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            pnl_R, pnl_usd = 0.0, 0.0
        setup_stats[key]["n_trades"] += 1
        setup_stats[key]["pnl_R_total"] += pnl_R
        setup_stats[key]["pnl_usd_total"] += pnl_usd
        if pnl_R > 0:
            setup_stats[key]["n_wins"] += 1
        elif pnl_R < 0:
            setup_stats[key]["n_losses"] += 1

    # Agreger les OBSERVATION_CLOSE (simules, dedupliques par sid)
    seen_obs_sids = set()
    for obs_ev in observations_log:
        sid_o = obs_ev.get("signal_id")
        if sid_o and sid_o in seen_obs_sids:
            continue
        if sid_o:
            seen_obs_sids.add(sid_o)
        matched_setup = _lookup_setup_for_sid(sid_o)
        grade = matched_setup.get("grade", "?")
        # Force mode=OBSERVE pour les observations (peu importe le mode du setup matche)
        key = f"{grade}_OBSERVE"
        if key not in setup_stats:
            setup_stats[key] = {
                "grade": grade, "mode": "OBSERVE",
                "n_trades": 0, "n_wins": 0, "n_losses": 0,
                "pnl_R_total": 0.0, "pnl_usd_total": 0.0,
            }
        try:
            pnl_R = float(obs_ev.get("pnl_R", obs_ev.get("pnl_simul_R", 0.0)) or 0.0)
            pnl_usd = float(obs_ev.get("pnl_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            pnl_R, pnl_usd = 0.0, 0.0
        setup_stats[key]["n_trades"] += 1
        setup_stats[key]["pnl_R_total"] += pnl_R
        setup_stats[key]["pnl_usd_total"] += pnl_usd
        if pnl_R > 0:
            setup_stats[key]["n_wins"] += 1
        elif pnl_R < 0:
            setup_stats[key]["n_losses"] += 1

    # Calcule wr_pct + pf PAR key (fix #3 : PF specifique au grade_mode, pas global)
    for key, stats in setup_stats.items():
        n = stats["n_trades"]
        stats["wr_pct"] = round(100.0 * stats["n_wins"] / max(n, 1), 1)
        # PF specifique au key : reconstituer les gains/pertes pour CE grade_mode
        pf_gains = max(stats["pnl_R_total"], 0)
        # Note : on ne peut pas reconstituer gains/losses individuels sans tracker
        # les trades du key. Approximation : si n_wins == 0 -> PF inf si pnl_R > 0 sinon None.
        # Pour le vrai PF par key, il faudrait stocker trade-by-trade. Approx OK pour le moment.
        if stats["n_losses"] == 0:
            stats["pf"] = None  # Pas de pertes (PF infini, affiche "—")
        else:
            # PF approx : sum positifs / abs(sum negatifs). Sans trace individuelle = imprecis.
            # Reconstituer par lookup ts dans closes_log filtre par sid de ce key.
            stats["pf"] = None  # Place-holder; vrai PF necessite tracking trade-by-trade

    # Recent setups
    recent_setups = [
        {
            "ts": s.get("ts"),
            "symbol": s.get("symbol"),
            "direction": s.get("direction"),
            "mode": s.get("mode"),
            "grade": s.get("grade"),
            "density": s.get("density"),
            "n_levels": s.get("n_levels"),
            "entry_price": s.get("entry_price"),
            "signal_id": s.get("signal_id"),
        }
        for s in setups_log[-20:]
    ]

    # Kill switch + cooldown (last event prevails)
    kill_switch_active = bool(kill_switches) and (
        not closes_log or
        kill_switches[-1].get("ts", "") > closes_log[-1].get("ts", "")
    )
    cooldown_until = None
    # TODO : parser RISK_COOLDOWN_ACTIVATED depuis LOGS/execution

    # Paper trader alive ? Dernier event < 120s
    now = datetime.now(timezone.utc)
    paper_trader_alive = False
    if last_event_ts is not None:
        if last_event_ts.tzinfo is None:
            last_event_ts = last_event_ts.replace(tzinfo=timezone.utc)
        age_sec = (now - last_event_ts).total_seconds()
        paper_trader_alive = age_sec < 120

    return {
        "positions_active": positions_active,
        "stats_today": {
            "n_setups": n_setups_today,
            "n_trades": n_trades_today,
            "n_observations": n_obs_today,
            "pnl_session_usd": round(pnl_session_usd, 2),
            "n_sl_consec": {},    # alimente par execution events (Phase 2)
        },
        "setup_stats": setup_stats,
        "recent_setups": recent_setups,
        "kill_switch_active": kill_switch_active,
        "cooldown_until": cooldown_until,
        "last_heartbeat_ts": last_heartbeat_ts,
        "paper_trader_alive": paper_trader_alive,
        "day_str": day_str,
        "available": True,
    }


def compute_stats_period_bnv4(days: int) -> dict:
    """Agregation BN V4 sur les N derniers jours (PnL, n_trades, WR, PF).

    Args:
        days : 7 ou 30 typiquement.

    Returns:
        dict {n_trades, n_wins, wr_pct, pf, pnl_usd_total, pnl_R_total}
    """
    n_trades = 0
    n_wins = 0
    gains_R = 0.0
    losses_R = 0.0
    pnl_usd_total = 0.0
    pnl_R_total = 0.0

    cme_now_start = _cme_trading_day_start_utc()
    for offset in range(days):
        day = cme_now_start - timedelta(days=offset)
        day_str = day.strftime("%Y%m%d")
        fpath = LOGS_BN_V4_DIR / f"bn_v4_v1_{day_str}.jsonl"
        if not fpath.exists():
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue
                    if d.get("event") != "TRADE_CLOSE":
                        continue
                    # 03/06 P2 FIX BUG 2 code-reviewer : exclure RECOVERED stats 7d/30d
                    if _is_recovered_fictive_close(d):
                        continue
                    pnl_R = float(d.get("pnl_R", 0.0) or 0.0)
                    pnl_usd = float(d.get("pnl_usd", 0.0) or 0.0)
                    n_trades += 1
                    pnl_R_total += pnl_R
                    pnl_usd_total += pnl_usd
                    if pnl_R > 0:
                        n_wins += 1
                        gains_R += pnl_R
                    elif pnl_R < 0:
                        losses_R += -pnl_R
        except OSError:
            continue

    pf = round(gains_R / max(losses_R, 0.01), 2) if losses_R > 0 else None
    return {
        "n_trades": n_trades,
        "n_wins": n_wins,
        "wr_pct": round(100.0 * n_wins / max(n_trades, 1), 1) if n_trades > 0 else None,
        "pf": pf,
        "pnl_usd_total": round(pnl_usd_total, 2),
        "pnl_R_total": round(pnl_R_total, 3),
        "days_covered": days,
    }


def get_bn_v5_payload() -> dict:
    """Endpoint principal Bot 2 BN V5 pour dashboard (remplace BN V4 deprecate 23/05).

    Structure compatible `get_bot2_v2_payload` pour conserver wiring frontend
    (`paperDataAll.bot2_db`).

    Active uniquement si ENV `MIA_BN_V5_ENABLED=1`. Sinon retourne fallback
    available=False.

    BN V5 ecrit ses heartbeats dans `LOGS/bn_v5/bn_v5_v1_YYYYMMDD.jsonl` (marker
    cree 03/06 R3 reviewer) ET ses events principaux dans `events_*_paper_v2.jsonl`
    (codes prefix BN_V5_*). Cette fonction lit le marker pour determiner alive
    + le dernier heartbeat ts pour compute paper_trader_alive.

    Phase 1 (04/06) : payload minimal pour debloquer dashboard OFFLINE/FROZEN.
    Phase 2 (J+7) : si BN V5 produit des trades, ajouter closed_today, stats_7d,
    stats_30d, positions_active comme BN V4.
    """
    import time as _time
    if os.environ.get("MIA_BN_V5_ENABLED", "0") != "1":
        return {
            "state_file": "bn_v5_marker_jsonl",
            "state": None,
            "available": False,
            "msg": "BN V5 desactive (MIA_BN_V5_ENABLED != 1)",
            "stats_7d": None,
            "stats_30d": None,
            "paper_trader_alive": False,
        }

    # Lire le marker dedie BN V5 (cree par bn_v5_paper.py _write_bn_v5_marker)
    bn_v5_dir = _ROOT / "LOGS" / "bn_v5"
    today_str = datetime.utcnow().strftime("%Y%m%d")
    marker_today = bn_v5_dir / f"bn_v5_v1_{today_str}.jsonl"

    last_heartbeat = None
    last_payload = None
    if marker_today.exists():
        try:
            with open(marker_today, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if lines:
                last_line = lines[-1].strip()
                if last_line:
                    last_payload = json.loads(last_line)
                    ts_str = last_payload.get("ts")
                    if ts_str:
                        # ISO 8601 with timezone
                        try:
                            last_heartbeat = datetime.fromisoformat(
                                ts_str.replace("Z", "+00:00")
                            )
                        except Exception:
                            last_heartbeat = None
        except Exception:
            pass

    # paper_trader_alive : heartbeat < 15 min (HEARTBEAT_INTERVAL_MIN=10 + marge)
    paper_trader_alive = False
    age_sec = None
    if last_heartbeat is not None:
        from datetime import timezone as _tz
        now_utc = datetime.now(_tz.utc)
        age_sec = (now_utc - last_heartbeat).total_seconds()
        paper_trader_alive = age_sec < 900  # 15 min

    # 04/06 FIX Jackson — extraction REELLE des trades depuis LOGS/execution/.
    # AVANT : open_by_symbol={} + closed_today=[] hardcoded → dashboard montrait
    # 0 trade meme quand BN V5 avait position ouverte (trade ES W LONG 09:47).
    # APRES : lit BN_V5_TRADE_OPEN + BN_V5_TRADE_CLOSE_* du jour pour matcher
    # FIFO par symbole. Position non-fermee = ouverte.
    open_by_symbol_bnv5: dict = {}
    closed_today_bnv5: list = []
    stats_today_pnl_usd = 0.0
    stats_today_pnl_ticks = 0.0
    stats_today_wins = 0
    stats_today_losses = 0
    try:
        exec_file = _ROOT / "LOGS" / "execution" / f"execution_{today_str}_paper_v2.jsonl"
        if exec_file.exists():
            opens_by_sym: dict = {}    # sym -> list of TRADE_OPEN dicts
            closes_by_sym: dict = {}   # sym -> list of TRADE_CLOSE dicts
            with open(exec_file, "r", encoding="utf-8") as f:
                for ln in f:
                    if "BN_V5" not in ln:
                        continue
                    try:
                        ev = json.loads(ln)
                    except Exception:
                        continue
                    code = ev.get("code", "")
                    ctx = ev.get("ctx") or {}
                    sym = ctx.get("sym")
                    if not sym:
                        continue
                    if code == "BN_V5_TRADE_OPEN":
                        opens_by_sym.setdefault(sym, []).append(
                            {"ts": ev.get("ts"), **ctx}
                        )
                    elif code.startswith("BN_V5_TRADE_CLOSE"):
                        # BN_V5_TRADE_CLOSE_SL, _TP, _TRAIL, _EOD, _MFE_TP, etc.
                        closes_by_sym.setdefault(sym, []).append(
                            {"ts": ev.get("ts"), "code": code, **ctx}
                        )

            # FIFO matching : si N opens et M closes (M<=N), les M premiers
            # opens sont fermes, les N-M derniers sont encore ouverts.
            for sym, opens in opens_by_sym.items():
                closes = closes_by_sym.get(sym, [])
                n_open = len(opens)
                n_close = len(closes)

                # Trades fermes : opens[0..n_close-1] paired avec closes[0..n_close-1]
                for i in range(n_close):
                    op = opens[i]
                    cl = closes[i]
                    pnl_ticks = cl.get("pnl_ticks") or 0.0
                    pnl_usd = cl.get("pnl_usd") or 0.0
                    try:
                        pnl_ticks = float(pnl_ticks)
                        pnl_usd = float(pnl_usd)
                    except Exception:
                        pass
                    closed_today_bnv5.append({
                        "ts_open": op.get("ts"),
                        "ts_close": cl.get("ts"),
                        "symbol": sym,
                        "side": op.get("side"),
                        "level": op.get("pattern") or "BN_V5",
                        "entry_price": op.get("entry_price"),
                        "exit_price": cl.get("exit_price"),
                        "sl_price": op.get("sl_price"),
                        "qty": op.get("qty", 1),
                        "n_contracts": op.get("qty", 1),
                        "exit_cause": cl.get("code", "").replace("BN_V5_TRADE_CLOSE_", "") or "?",
                        "pnl_ticks": pnl_ticks,
                        "pnl_usd": pnl_usd,
                    })
                    stats_today_pnl_usd += pnl_usd
                    stats_today_pnl_ticks += pnl_ticks
                    if pnl_usd > 0:
                        stats_today_wins += 1
                    elif pnl_usd < 0:
                        stats_today_losses += 1

                # Position ouverte = derniere open sans close matching
                if n_open > n_close:
                    op = opens[-1]
                    open_by_symbol_bnv5[sym] = {
                        "signal_id": op.get("signal_id"),
                        "side": op.get("side"),
                        "direction": op.get("side"),
                        "level": op.get("pattern") or "BN_V5",
                        "entry_price": op.get("entry_price"),
                        "sl_price": op.get("sl_price"),
                        "tp_price": op.get("tp_price"),
                        "sl_ticks": op.get("risk_ticks"),
                        "qty": op.get("qty", 1),
                        "n_contracts": op.get("qty", 1),
                        "n_micros": op.get("qty", 1),
                        "trade_account": os.environ.get("MIA_BN_V5_TRADE_ACCOUNT", "Sim2"),
                        "ts_open": op.get("ts"),
                    }
    except Exception:
        # best-effort : si lecture logs casse, payload minimal mais fonctionnel
        pass

    n_trades_today_bnv5 = len(closed_today_bnv5) + len(open_by_symbol_bnv5)
    pf_today = None
    if stats_today_losses > 0 and stats_today_wins > 0:
        try:
            gross_win = sum(c["pnl_usd"] for c in closed_today_bnv5 if c["pnl_usd"] > 0)
            gross_loss = abs(sum(c["pnl_usd"] for c in closed_today_bnv5 if c["pnl_usd"] < 0))
            if gross_loss > 0:
                pf_today = round(gross_win / gross_loss, 2)
        except Exception:
            pass

    return _clean_nan_inf({
        "state_file": "bn_v5_marker_jsonl",
        "bot_label": "Bot 2 BN V5",
        "mode": "PAPER_BN_V5",
        "state": {
            "ts_utc": last_heartbeat.isoformat() if last_heartbeat else None,
            "last_marker": last_payload,
        },
        "available": True,
        "paper_trader_alive": paper_trader_alive,
        "paper_trader_age_sec": age_sec,
        "msg": (
            f"BN V5 actif (heartbeat il y a {int(age_sec)}s)"
            if age_sec is not None and paper_trader_alive
            else "BN V5 actif mais heartbeat absent ou stale"
        ),
        # 04/06 : extraction REELLE des trades execution
        "closed_today": closed_today_bnv5,
        "open_by_symbol": open_by_symbol_bnv5,
        "positions_with_countdown": open_by_symbol_bnv5,  # alias frontend legacy
        "stats_today": {
            "n_trades": n_trades_today_bnv5,
            "n_setups": (last_payload or {}).get("n_setups", 0),
            "wins": stats_today_wins,
            "losses": stats_today_losses,
            "pnl_usd": round(stats_today_pnl_usd, 2),
            "pnl_ticks": round(stats_today_pnl_ticks, 2),
            "pf": pf_today,
        },
        "stats_7d": None,
        "stats_30d": None,
        "engine_status": (
            "IN_TRADE" if open_by_symbol_bnv5
            else ("ANALYZING" if paper_trader_alive else "OFFLINE")
        ),
        "trade_account": os.environ.get("MIA_BN_V5_TRADE_ACCOUNT", "Sim2"),
    })


def get_bn_v4_payload() -> dict:
    """Endpoint principal Bot 2 BN V4 pour dashboard (remplace Bot 2 V6).

    Structure compatible `get_bot2_v2_payload` pour conserver wiring frontend
    (`paperDataAll.bot2_db`).

    Active uniquement si ENV `MIA_BN_V4_ENABLED=1`. Sinon retourne fallback
    avec available=False.
    """
    if os.environ.get("MIA_BN_V4_ENABLED", "0") != "1":
        return {
            "state_file": "bn_v4_logger_jsonl",
            "state": None,
            "available": False,
            "msg": "BN V4 desactive (MIA_BN_V4_ENABLED != 1)",
            "stats_7d": None,
            "stats_30d": None,
            "paper_trader_alive": False,
        }

    today_state = _load_bn_v4_today_state()
    stats_7d = compute_stats_period_bnv4(7)
    stats_30d = compute_stats_period_bnv4(30)

    # 26/05 Jackson : jauge etat moteur Bot 2 (WARMUP / ANALYZING / IN_TRADE).
    # Lit le dernier BN_V4_DATA_STATS event pour recuperer bars_buffer reel.
    engine_status = _get_bn_v4_engine_status(today_state.get("day_str"))

    # 26/05/2026 fix Jackson "ta pas mis a jour les autres champs du dashboard" :
    # construire closed_today + open_by_symbol + stats_today enrichi pour matcher
    # le format attendu par renderPaperPage (cohérent Bot 1/3 v3/v4).
    closed_today_list = _build_bn_v4_closed_today(today_state.get("day_str"))
    positions_active_bnv4 = today_state.get("positions_active") or {}
    open_by_symbol_norm = {}
    for sym, pos in positions_active_bnv4.items():
        if not pos:
            continue
        side_upper = (pos.get("direction") or "").upper() or None
        qty_val = pos.get("qty", 1)
        open_by_symbol_norm[sym] = {
            "signal_id": pos.get("signal_id"),
            "side": side_upper,
            "direction": side_upper,        # 27/05 alias frontend lit p.direction
            "level": "BN_V4",
            "entry_price": pos.get("entry_price"),
            "sl_price": pos.get("sl_initial"),
            "tp_price": None,
            "sl_ticks": pos.get("risk_ticks"),
            "qty": qty_val,
            "n_contracts": qty_val,         # 27/05 alias frontend fallback
            "n_micros": qty_val,            # 27/05 alias direct frontend
            "trade_account": os.environ.get("MIA_BN_V4_TRADE_ACCOUNT", "Sim2"),
            "ts_open": pos.get("ts_open"),
        }

    # Stats_today enrichi : ajouter trades/wins/losses/pf/pnl_usd/pnl_ticks
    # depuis closed_today_list (compatible rendu Bot 3 v3/v4).
    stats_today_raw = today_state.get("stats_today") or {}
    n_wins = sum(1 for c in closed_today_list if (c.get("pnl_usd") or 0) > 0)
    n_losses = sum(1 for c in closed_today_list if (c.get("pnl_usd") or 0) < 0)
    pnl_ticks_total = sum((c.get("pnl_ticks") or 0) for c in closed_today_list)
    gains_R = sum(max(c.get("pnl_R") or 0, 0) for c in closed_today_list)
    losses_R = -sum(min(c.get("pnl_R") or 0, 0) for c in closed_today_list)
    pf_session = round(gains_R / losses_R, 2) if losses_R > 0.01 else None
    wr_today = round(100.0 * n_wins / max(len(closed_today_list), 1)) if closed_today_list else 0
    stats_today_norm = {
        **stats_today_raw,
        "trades": len(closed_today_list),
        "n_trades_opened": len(closed_today_list),
        "n_trades_closed": len(closed_today_list),
        "wins": n_wins,
        "losses": n_losses,
        "wr": wr_today,
        "pf": pf_session,
        "pnl_usd": stats_today_raw.get("pnl_session_usd", 0.0),
        "pnl_ticks": pnl_ticks_total,
    }

    return _clean_nan_inf({
        "state_file": "bn_v4_logger_jsonl",
        "state": {
            "ts_utc": today_state.get("last_heartbeat_ts"),
            "mode": "PAPER_BN_V4",
            "trade_account": os.environ.get("MIA_BN_V4_TRADE_ACCOUNT", "Sim2"),
            "kill_switch_active": today_state.get("kill_switch_active"),
            "cooldown_until": today_state.get("cooldown_until"),
            "bar_source": {"global": "LIVE_ENRICHED_60s"},
            # 26/05 cles compatibles renderPaperPage (Bot 1/3 v3/v4 format)
            "open_by_symbol": open_by_symbol_norm,
            "closed_today": closed_today_list,
            "stats_today": stats_today_norm,
            # 26/05 Jackson : jauge etat moteur (WARMUP/ANALYZING/IN_TRADE)
            "engine_status": engine_status,
        },
        "engine_status": engine_status,  # alias top-level aussi
        "positions_with_countdown": positions_active_bnv4,
        "closed_today": closed_today_list,  # alias top-level aussi
        "setup_stats": today_state.get("setup_stats", {}),
        "recent_setups": today_state.get("recent_setups", []),
        "stats_today": stats_today_norm,
        "stats_7d": stats_7d,
        "stats_30d": stats_30d,
        "trading_window_utc": "2h-21h",
        "mode": "PAPER_BN_V4",
        "trade_account": os.environ.get("MIA_BN_V4_TRADE_ACCOUNT", "Sim2"),
        "phase_1_free_run": True,
        "available": True,
        "paper_trader_alive": today_state.get("paper_trader_alive", False),
        "ts_utc": today_state.get("last_heartbeat_ts"),
        "day_str": today_state.get("day_str"),
        "has_paper_active": today_state.get("paper_trader_alive", False),
        "bot_label": "Bot 2 BN V4",
        "kill_switch_active": today_state.get("kill_switch_active"),
    })


def _get_bn_v4_engine_status(day_str: Optional[str]) -> dict:
    """Lit le dernier BN_V4_DATA_STATS event pour determiner l'etat moteur Bot 2.

    Returns:
        dict {
            "status": "WARMUP" | "ANALYZING" | "IN_TRADE",
            "label": str (court pour affichage),
            "details": str (detail tooltip),
            "bars_buffer_nq": int,
            "bars_buffer_es": int,
            "pct_warmup_nq": int 0-100,
            "pct_warmup_es": int 0-100,
            "trend_lookback_required": 240,
            "last_close_nq": float | None,
            "last_close_es": float | None,
            "last_bar_age_sec": int | None,
        }
    """
    TREND_LOOKBACK = 240  # = BNV4Params.trend_long_lookback default
    result = {
        "status": "UNKNOWN",
        "label": "Inconnu",
        "details": "",
        "bars_buffer_nq": 0,
        "bars_buffer_es": 0,
        "pct_warmup_nq": 0,
        "pct_warmup_es": 0,
        "trend_lookback_required": TREND_LOOKBACK,
        "last_close_nq": None,
        "last_close_es": None,
        "last_bar_age_sec": None,
    }
    # Lire le dernier BN_V4_DATA_STATS par symbole depuis events
    cme_start = _cme_trading_day_start_utc()
    utc_now = datetime.now(timezone.utc)
    files_to_read = []
    seen = set()
    for day_dt in [cme_start, utc_now]:
        d = day_dt.strftime("%Y%m%d")
        if d in seen:
            continue
        seen.add(d)
        candidate = _ROOT / "LOGS" / "events" / f"events_{d}_paper_v2.jsonl"
        if candidate.exists():
            files_to_read.append(candidate)
    if not files_to_read:
        result["status"] = "OFFLINE"
        result["label"] = "OFFLINE"
        result["details"] = "Aucun event log trouve"
        return result

    last_data_stats = {"NQ": None, "ES": None}
    for fp in reversed(files_to_read):  # le plus recent en dernier
        try:
            with open(fp, "r", encoding="utf-8") as f:
                lines = f.readlines()[-2000:]  # cap pour perf
            for line in reversed(lines):
                if "BN_V4_DATA_STATS" not in line:
                    continue
                try:
                    j = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue
                if j.get("code") != "BN_V4_DATA_STATS":
                    continue
                ctx = j.get("ctx", {})
                sym = ctx.get("sym")
                if sym in ("NQ", "ES") and last_data_stats[sym] is None:
                    last_data_stats[sym] = {
                        "bars_buffer": ctx.get("bars_buffer", 0),
                        "last_close": ctx.get("last_close"),
                        "age_sec": ctx.get("age_sec"),
                        "ts": j.get("ts"),
                    }
                if last_data_stats["NQ"] and last_data_stats["ES"]:
                    break
            if last_data_stats["NQ"] and last_data_stats["ES"]:
                break
        except OSError:
            continue

    nq = last_data_stats["NQ"] or {}
    es = last_data_stats["ES"] or {}
    buf_nq = nq.get("bars_buffer", 0) or 0
    buf_es = es.get("bars_buffer", 0) or 0
    result["bars_buffer_nq"] = buf_nq
    result["bars_buffer_es"] = buf_es
    result["pct_warmup_nq"] = min(100, round(100.0 * buf_nq / TREND_LOOKBACK))
    result["pct_warmup_es"] = min(100, round(100.0 * buf_es / TREND_LOOKBACK))
    result["last_close_nq"] = nq.get("last_close")
    result["last_close_es"] = es.get("last_close")
    age = max(nq.get("age_sec") or 0, es.get("age_sec") or 0)
    result["last_bar_age_sec"] = round(age, 1) if age else None

    min_buf = min(buf_nq, buf_es) if (buf_nq and buf_es) else max(buf_nq, buf_es)
    if min_buf == 0:
        result["status"] = "OFFLINE"
        result["label"] = "OFFLINE"
        result["details"] = "Aucun BN_V4_DATA_STATS recent (pas de bars)"
    elif min_buf < TREND_LOOKBACK:
        result["status"] = "WARMUP"
        pct = round(100.0 * min_buf / TREND_LOOKBACK)
        result["label"] = f"WARMUP {pct}%"
        bars_left = TREND_LOOKBACK - min_buf
        result["details"] = f"NQ={buf_nq}/{TREND_LOOKBACK} ES={buf_es}/{TREND_LOOKBACK} (~{bars_left} bars=~{bars_left}min)"
    else:
        result["status"] = "ANALYZING"
        result["label"] = "ANALYZING"
        result["details"] = f"NQ buffer={buf_nq} ES buffer={buf_es} | dernier close NQ={nq.get('last_close')} ES={es.get('last_close')}"
    return result


def _build_bn_v4_closed_today(day_str: Optional[str]) -> list:
    """Construit closed_today_list pour Bot 2 BN V4 a partir du logger dedie.
    Cross-ref TRADE_OPEN + TRADE_CLOSE par signal_id, applique CME day filter.
    """
    if not day_str:
        return []
    cme_start = _cme_trading_day_start_utc()
    utc_now = datetime.now(timezone.utc)
    files_to_read = []
    seen = set()
    for day_dt in [cme_start, utc_now]:
        d = day_dt.strftime("%Y%m%d")
        if d in seen:
            continue
        seen.add(d)
        candidate = LOGS_BN_V4_DIR / f"bn_v4_v1_{d}.jsonl"
        if candidate.exists():
            files_to_read.append(candidate)
    if not files_to_read:
        return []

    opens_log = []
    closes_log = []
    for fp in files_to_read:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts_str = d.get("ts", "")
                    try:
                        ts_dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        continue
                    if ts_dt < cme_start:
                        continue
                    ev = d.get("event", "")
                    if ev == "TRADE_OPEN":
                        opens_log.append(d)
                    elif ev == "TRADE_CLOSE":
                        # 03/06 P2 FIX BUG 1 code-reviewer : exclure RECOVERED BN V4 closed_today
                        if _is_recovered_fictive_close(d):
                            continue
                        closes_log.append(d)
        except OSError:
            continue

    _TICK_BY_SYM = {"NQ": 0.25, "ES": 0.25, "MGC": 0.10}
    closed_list = []
    for c in closes_log[-50:]:
        sid = c.get("signal_id")
        # Match TRADE_OPEN le plus recent <= ts_close (anti duplicate sid)
        try:
            ts_c = datetime.fromisoformat(str(c.get("ts", "")).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            ts_c = None
        candidates = []
        for o in opens_log:
            if o.get("signal_id") != sid:
                continue
            try:
                ts_o = datetime.fromisoformat(str(o.get("ts", "")).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if ts_c is None or ts_o <= ts_c:
                candidates.append((ts_o, o))
        open_ev = max(candidates, key=lambda x: x[0])[1] if candidates else None

        sym = c.get("symbol") or "NQ"
        tick = _TICK_BY_SYM.get(sym, 0.25)
        entry = (open_ev or {}).get("entry_price")
        exit_p = c.get("exit_price")
        # Derive direction depuis sl_initial vs entry_price
        direction = None
        if open_ev:
            sl_i = open_ev.get("sl_initial")
            ep = open_ev.get("entry_price")
            if sl_i is not None and ep is not None:
                direction = "LONG" if sl_i < ep else "SHORT"
        pnl_ticks_c = None
        if entry and exit_p and direction:
            sign = 1 if direction == "LONG" else -1
            try:
                pnl_ticks_c = int(round(sign * (float(exit_p) - float(entry)) / tick))
            except (TypeError, ValueError):
                pnl_ticks_c = None
        duration_sec_c = None
        ts_o_str = (open_ev or {}).get("ts")
        if ts_o_str and c.get("ts"):
            try:
                t_o = datetime.fromisoformat(str(ts_o_str).replace("Z", "+00:00"))
                t_c = datetime.fromisoformat(str(c.get("ts", "")).replace("Z", "+00:00"))
                duration_sec_c = int((t_c - t_o).total_seconds())
                if duration_sec_c < 0 or duration_sec_c > 6 * 3600:
                    duration_sec_c = None
            except (ValueError, TypeError):
                pass
        closed_list.append({
            "ts_close": c.get("ts"),
            "ts_open": ts_o_str,
            "exit_time": c.get("ts"),       # 26/05 alias code-reviewer Q2 — frontend lit t.exit_time
            "signal_id": sid,
            "symbol": sym,
            "sym": sym,                     # alias (renderPaperPage lit t.sym et t.symbol)
            "side": direction,
            "direction": direction,         # 26/05 alias code-reviewer Q2 — frontend lit t.direction
            "level": "BN_V4",
            "entry_price": entry,
            "exit_price": exit_p,
            "sl_ticks": (open_ev or {}).get("risk_ticks"),
            "tp_mode": None,
            "exit_cause": c.get("exit_cause"),
            "reason": c.get("exit_cause"),
            "exit_reason": c.get("exit_cause"),  # 26/05 alias code-reviewer Q2 — frontend lit t.exit_reason
            "pnl_R": c.get("pnl_R"),
            "pnl_usd": c.get("pnl_usd"),
            "pnl_ticks": pnl_ticks_c,
            "duration_sec": duration_sec_c,
            "duration_bars": c.get("duration_bars"),
            "pnl_known": True,
        })
    return closed_list


def _load_bot3_vN_today_state(version: str, day_str: Optional[str] = None) -> dict:
    """Reconstruit l'etat Bot 3 v3 OU v4 du CME trading day via JSONL dedie.

    Args:
        version : "v3" (Continuation Sim1) ou "v4" (Data-driven Sim3).
        day_str : "YYYYMMDD" UTC (default = today CME trading day).

    Returns:
        dict avec memes cles que _load_bn_v4_today_state() :
          positions_active, stats_today, setup_stats, recent_entries,
          kill_switch_active, cooldown_until, last_heartbeat_ts,
          paper_trader_alive, day_str, available.

    Schema JSONL Bot 3 (cf CORE/bot3_v3v4_logger.py) :
      event : BAR_PROCESSED / STATE_TRANSITION (v3) / TOUCH (v4) /
              ENTRY_SIGNAL / TRADE_OPEN / TRADE_CLOSE
      signal_id : BOT3_V{3|4}_{SYM}_{YYYYMMDD}_{NNNN}
      level / side / entry_price / sl_price / tp_price / sl_ticks /
      tp_mode (v4 only : VPOC / R15) / exit_price / exit_cause / pnl_R /
      pnl_usd / duration_bars / executed / veto_reason
    """
    assert version in ("v3", "v4"), f"version invalid : {version}"
    log_dir = LOGS_BOT3_V3_DIR if version == "v3" else LOGS_BOT3_V4_DIR

    if day_str is None:
        # Fix 25/05/2026 00:15 UTC bug Jackson : convention day MISMATCH.
        # Logger bot3_v3/v4 + bn_v4 utilise UTC date (cf bot3_v3v4_logger.py
        # _build_path : dt.strftime UTC). Mais ici on utilisait CME ET trading
        # day → de 00:00 a 22:00 UTC le dashboard cherchait l'ancien fichier
        # → STATE FROZEN faux positif chaque jour pendant 22h.
        # Solution : aligner sur convention UTC du logger.
        # Fallback : si fichier UTC absent, tente le CME trading day ET (cas
        # legacy logger ou backfill historique).
        utc_now = datetime.now(timezone.utc)
        day_str = utc_now.strftime("%Y%m%d")

    # 26/05/2026 fix Jackson "ALERT plus de donnees" :
    # Le CME trading day commence a 22:00 UTC du jour J-1 et finit 22:00 UTC du jour J.
    # Donc entre 22:00 UTC et 23:59 UTC (du jour J UTC), les events sont dans le fichier
    # UTC du jour J. Apres minuit UTC (00:00 UTC du jour J+1), les events sont dans le fichier
    # UTC du jour J+1. Le CME day CONTINUE jusqu'a 22:00 UTC du jour J+1.
    # Donc pour LIRE TOUS les events du CME day courant, il faut potentiellement 2 fichiers UTC.
    cme_start_for_files = _cme_trading_day_start_utc()
    utc_now_for_files = datetime.now(timezone.utc)
    files_to_read: list = []
    seen_days = set()
    for day_dt in [cme_start_for_files, utc_now_for_files]:
        d_str = day_dt.strftime("%Y%m%d")
        if d_str in seen_days:
            continue
        seen_days.add(d_str)
        candidate = log_dir / f"bot3_{version}_v1_{d_str}.jsonl"
        if candidate.exists():
            files_to_read.append(candidate)

    empty_result = {
        "positions_active": {},
        "stats_today": {"n_entries": 0, "n_trades_opened": 0, "n_trades_closed": 0,
                         "pnl_session_usd": 0.0, "pnl_session_R": 0.0,
                         "n_sl_consec": 0, "n_touches": 0, "n_state_transitions": 0},
        "setup_stats": {},
        "recent_entries": [],
        "kill_switch_active": False,
        "cooldown_until": None,
        "last_heartbeat_ts": None,
        "paper_trader_alive": False,
        "day_str": day_str,
        "available": False,
    }
    if not files_to_read:
        return empty_result

    # Parse JSONL
    events_by_signal_id: dict = {}
    entries_log: list = []      # ENTRY_SIGNAL events (executed True ou veto)
    opens_log: list = []         # TRADE_OPEN events
    closes_log: list = []        # TRADE_CLOSE events
    touches_log: list = []       # TOUCH (v4) events
    transitions_log: list = []   # STATE_TRANSITION (v3) events
    last_heartbeat_ts: Optional[str] = None
    last_event_ts: Optional[datetime] = None

    # Iterate sur 1 ou 2 fichiers (CME day cross UTC midnight)
    for fpath in files_to_read:
      try:
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event = d.get("event", "")
                sid = d.get("signal_id")
                ts = d.get("ts")
                try:
                    last_event_ts = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

                if event == "BAR_PROCESSED":
                    last_heartbeat_ts = ts  # proxy heartbeat (1/min en marche)
                elif event == "STATE_TRANSITION":
                    transitions_log.append(d)
                elif event == "TOUCH":
                    touches_log.append(d)
                    if sid:
                        events_by_signal_id.setdefault(sid, []).append(d)
                elif event == "ENTRY_SIGNAL":
                    entries_log.append(d)
                    if sid:
                        events_by_signal_id.setdefault(sid, []).append(d)
                elif event == "TRADE_OPEN":
                    opens_log.append(d)
                    if sid:
                        events_by_signal_id.setdefault(sid, []).append(d)
                elif event == "TRADE_CLOSE":
                    # Filtre corruption marker 24/05/2026 PM (code-reviewer action #2)
                    # Suite incident ghost trade Bot 3 v4 ($59542 + $59560 sur Sim3
                    # via fill_price=0 mal gere). Tout TRADE_CLOSE avec |pnl_usd|>50k
                    # ou |pnl_R|>100 est presume corrompu (ghost) et skip de l'agrege.
                    # JSONL conserve append-only pour audit, dashboard nettoye.
                    try:
                        pnl_usd_val = float(d.get("pnl_usd") or 0.0)
                        pnl_R_val = float(d.get("pnl_R") or 0.0)
                    except (TypeError, ValueError):
                        pnl_usd_val, pnl_R_val = 0.0, 0.0
                    if abs(pnl_usd_val) > 50000 or abs(pnl_R_val) > 100:
                        # Ghost trade detected : skip + ne pas l'ajouter aux stats
                        # (le signal_id reste en positions_active pour visibilite,
                        # mais sera lui-meme filtre par closed_sids logic ci-dessous)
                        continue
                    closes_log.append(d)
                    if sid:
                        events_by_signal_id.setdefault(sid, []).append(d)
      except OSError:
        continue  # essayer le fichier suivant

    # 25/05/2026 PM fix Jackson "trades d'hier encore visibles" + bug 1 durees aberrantes :
    # Filtrer par CME trading day (au lieu de UTC day) car Asia session demarre 22:00 UTC.
    # Le fichier UTC contient le rollover entre 22:00 UTC et minuit UTC suivant -> avant ce fix,
    # le payload melangait 2 trading days CME dans la meme liste, ET le matching signal_id
    # cross-day faisait que les TRADE_CLOSE du jour J matchaient des TRADE_OPEN du jour J-1
    # (compteur sid reset au boot bot, on a vu 3x le meme sid sur 24h).
    cme_start = _cme_trading_day_start_utc()

    def _ev_dt(ev):
        try:
            return datetime.fromisoformat(str(ev.get("ts", "")).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def _in_cme_day(ev):
        ts = _ev_dt(ev)
        if ts is None:
            return True  # garder si timestamp incomprehensible (fallback safe)
        return ts >= cme_start

    opens_log = [o for o in opens_log if _in_cme_day(o)]
    closes_log = [c for c in closes_log if _in_cme_day(c)]
    # 03/06 P2 FIX : exclure RECOVERED_TIMEOUT fictifs des stats Bot 3 v3/v4
    closes_log = [c for c in closes_log if not _is_recovered_fictive_close(c)]
    entries_log = [e for e in entries_log if _in_cme_day(e)]
    touches_log = [t for t in touches_log if _in_cme_day(t)]
    transitions_log = [t for t in transitions_log if _in_cme_day(t)]
    # Re-build events_by_signal_id filtre CME
    events_by_signal_id = {}
    for ev_list in (opens_log, closes_log, entries_log, touches_log):
        for ev in ev_list:
            sid = ev.get("signal_id")
            if sid:
                events_by_signal_id.setdefault(sid, []).append(ev)

    def _match_open(sid_c: Optional[str], ts_close_str: Optional[str]) -> Optional[dict]:
        """Bug 1 fix : prendre le DERNIER TRADE_OPEN avec ts_open <= ts_close.
        Le compteur signal_id reset au boot du bot -> meme sid attribue plusieurs
        fois par jour. L'ancien next() prenait le 1er, faussant ts_open/entry_price.
        """
        if not sid_c:
            return None
        ts_c = None
        if ts_close_str:
            try:
                ts_c = datetime.fromisoformat(str(ts_close_str).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                ts_c = None
        candidates = []
        for o in opens_log:
            if o.get("signal_id") != sid_c:
                continue
            if ts_c is None:
                candidates.append((None, o))
                continue
            ts_o = _ev_dt(o)
            if ts_o is None or ts_o <= ts_c:
                candidates.append((ts_o, o))
        if not candidates:
            return None
        # Tri descendant ts_open -> le plus recent en premier (= le bon match)
        candidates.sort(key=lambda x: (x[0] is not None, x[0]), reverse=True)
        return candidates[0][1]

    # Positions actives = DERNIER TRADE_OPEN par symbol sans TRADE_CLOSE posterieur.
    #
    # Fix 03/06/2026 Jackson "J'AI UN TRADE ET PAS DANS LE DASHBOARD" :
    # Le compteur `_signal_counter` Bot3V4Logger reset au boot du process bot
    # (re-instanciation par nssm restart, etc.) -> meme `signal_id` reutilise
    # plusieurs fois par jour. L'ancien set `closed_sids` rejetait TOUS les
    # opens partageant un sid deja close, y compris le dernier (= la vraie
    # position active). Symptome : positions_active={} alors que JSONL
    # contient N opens et N-1 closes (7 vs 6 le 03/06).
    #
    # Solution : raisonner par symbol et par timestamp (consistent avec le fix
    # existant `_match_open` lignes 1551-1578 pour closed_today). Un open est
    # actif s'il n'existe aucun close du MEME signal_id posterieur a ts_open.
    positions_active: dict = {}
    # Index closes par sid pour lookup rapide
    closes_by_sid: dict = {}
    for c in closes_log:
        sid_c = c.get("signal_id")
        if sid_c:
            closes_by_sid.setdefault(sid_c, []).append(c)

    # Grouper TRADE_OPEN par symbol, ordonner par ts decroissant, prendre le
    # dernier dont aucun close posterieur n'existe.
    opens_by_sym: dict = {}
    for o in opens_log:
        sym_o = o.get("symbol", "?")
        opens_by_sym.setdefault(sym_o, []).append(o)

    for sym, opens_sym in opens_by_sym.items():
        # Tri descendant par ts -> on traite le plus recent en premier
        opens_sorted = sorted(
            opens_sym,
            key=lambda e: _ev_dt(e) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        open_ev = None
        for cand in opens_sorted:
            ts_o = _ev_dt(cand)
            sid_o = cand.get("signal_id")
            # Cherche un close ULTERIEUR pour ce sid
            has_later_close = False
            for c in closes_by_sid.get(sid_o, []):
                ts_c = _ev_dt(c)
                if ts_o is None or ts_c is None or ts_c >= ts_o:
                    has_later_close = True
                    break
            if not has_later_close:
                open_ev = cand
                break
        if open_ev is None:
            continue
        # Fix 24/05/2026 PM (bug ? affichage) : tp_mode peut etre top-level OU ctx
        tp_mode_active = (
            open_ev.get("tp_mode")
            or (open_ev.get("ctx") or {}).get("tp_mode")
        )
        vpoc_value_active = (
            open_ev.get("vpoc_value")
            or (open_ev.get("ctx") or {}).get("vpoc_value")
        )
        positions_active[sym] = {
            "signal_id": open_ev.get("signal_id"),
            "level": open_ev.get("level"),
            "side": open_ev.get("side"),
            "entry_price": open_ev.get("entry_price"),
            "sl_price": open_ev.get("sl_price"),
            "tp_price": open_ev.get("tp_price"),
            "sl_ticks": open_ev.get("sl_ticks"),
            "tp_mode": tp_mode_active,           # v4 only (VPOC / R15)
            "vpoc_value": vpoc_value_active,     # v4 only
            "qty": open_ev.get("qty", 1),
            "trade_account": open_ev.get("trade_account"),
            "ts_open": open_ev.get("ts"),
        }

    # Stats today
    n_entries_today = len(entries_log)
    n_trades_opened_today = len(opens_log)
    n_trades_closed_today = len(closes_log)
    pnl_session_usd = sum(float(c.get("pnl_usd") or 0.0) for c in closes_log)
    pnl_session_R = sum(float(c.get("pnl_R") or 0.0) for c in closes_log)
    n_touches_today = len(touches_log)
    n_state_transitions_today = len(transitions_log)

    # n_sl_consec : compter SL fills consecutifs depuis dernier TP
    # 28/05 v2 FIX RESERVE R1 code-reviewer : utiliser exit_cause_mechanical
    # (trigger DTC reel) pour rester aligne sur compteur _n_sl_consec interne bot.
    # exit_cause peut etre reclasse sur sign(pnl_usd) v2 logger, ce qui fausserait
    # le compteur cooldown UI vs etat reel bot. Fallback exit_cause pour anciens JSONL.
    n_sl_consec = 0
    for c in reversed(closes_log):
        cause = c.get("exit_cause_mechanical") or c.get("exit_cause")
        if cause == "SL":
            n_sl_consec += 1
        elif cause == "TP":
            break
        # TIMEOUT / EOD / MANUAL n'incrementent ni ne reset (neutre)

    # Setup_stats par level (+ tp_mode pour v4)
    setup_stats: dict = {}
    for close in closes_log:
        level = close.get("level", "?")
        if version == "v4":
            # cherche tp_mode depuis le matching TRADE_OPEN
            # Fix 24/05/2026 PM (bug "?" affichage dashboard) : le logger Bot 3 v4
            # serialize tp_mode dans ctx={tp_mode, vpoc_value}, pas au top-level.
            # Order priorite : top-level (compat) -> ctx.tp_mode -> "?".
            # 25/05 fix Bug 1 : _match_open au lieu de next() (signal_id duplique).
            sid = close.get("signal_id")
            open_ev = _match_open(sid, close.get("ts"))
            if open_ev:
                tp_mode = (
                    open_ev.get("tp_mode")
                    or (open_ev.get("ctx") or {}).get("tp_mode")
                    or "?"
                )
            else:
                tp_mode = "?"
            key = f"{level}_{tp_mode}"
        else:
            key = level
        if key not in setup_stats:
            setup_stats[key] = {
                "level": level,
                "tp_mode": tp_mode if version == "v4" else None,
                "n_trades": 0, "n_wins": 0, "n_losses": 0,
                "pnl_R_total": 0.0, "pnl_usd_total": 0.0,
            }
        pnl_R = float(close.get("pnl_R") or 0.0)
        pnl_usd = float(close.get("pnl_usd") or 0.0)
        setup_stats[key]["n_trades"] += 1
        setup_stats[key]["pnl_R_total"] += pnl_R
        setup_stats[key]["pnl_usd_total"] += pnl_usd
        if pnl_R > 0:
            setup_stats[key]["n_wins"] += 1
        elif pnl_R < 0:
            setup_stats[key]["n_losses"] += 1

    # Calcule wr_pct + pf par level
    for key, st in setup_stats.items():
        n = st["n_trades"]
        st["wr_pct"] = round(100.0 * st["n_wins"] / max(n, 1), 1)
        # PF specifique au level (pas global)
        gains_R = sum(
            float(c.get("pnl_R") or 0.0)
            for c in closes_log
            if c.get("level") == st["level"] and (c.get("pnl_R") or 0.0) > 0
        )
        losses_R = -sum(
            float(c.get("pnl_R") or 0.0)
            for c in closes_log
            if c.get("level") == st["level"] and (c.get("pnl_R") or 0.0) < 0
        )
        st["pf"] = round(gains_R / max(losses_R, 0.01), 2) if losses_R > 0 else None
        st["pnl_R_total"] = round(st["pnl_R_total"], 3)
        st["pnl_usd_total"] = round(st["pnl_usd_total"], 2)

    # Closed today (24/05/2026 PM bug Jackson : "trade pas log dans fermes du jour").
    # Le frontend setPaperBot bot3v3/bot3v4 utilise closed_today mais le backend
    # ne le renvoyait pas → vide. Fix : build depuis closes_log enrichi avec
    # entry_price/sl/tp_mode depuis le matching TRADE_OPEN.
    closed_today_list: list = []
    # Tick size par symbole pour calcul pnl_ticks backend
    _TICK_BY_SYM = {"NQ": 0.25, "ES": 0.25, "MGC": 0.10}
    for close_ev in closes_log[-50:]:  # cap 50 derniers
        sid_c = close_ev.get("signal_id")
        ts_close_c = close_ev.get("ts")
        # 25/05 Bug 1 fix : matcher le TRADE_OPEN le plus recent avec ts_open <= ts_close
        # (au lieu du premier trouve, qui peut etre du matin si compteur sid duplique)
        open_ev = _match_open(sid_c, ts_close_c)
        entry_price_c = open_ev.get("entry_price") if open_ev else None
        sl_ticks_c = open_ev.get("sl_ticks") if open_ev else None
        tp_mode_c = None
        if open_ev:
            tp_mode_c = (
                open_ev.get("tp_mode")
                or (open_ev.get("ctx") or {}).get("tp_mode")
            )
        ts_open_c = open_ev.get("ts") if open_ev else None
        try:
            pnl_usd_c = float(close_ev.get("pnl_usd") or 0.0)
            pnl_R_c = float(close_ev.get("pnl_R") or 0.0)
        except (TypeError, ValueError):
            pnl_usd_c, pnl_R_c = 0.0, 0.0
        # Filtre corruption marker (cohomerent avec filtre haut closes_log)
        if abs(pnl_usd_c) > 50000 or abs(pnl_R_c) > 100:
            continue
        # 25/05 Bug 1 fix : calculer pnl_ticks + duration_sec cote backend
        # (anciennement None -> frontend devait reconstruire, mais ts_open faux
        # propageait l'erreur). Maintenant correct car _match_open trouve le bon open.
        symbol_c = close_ev.get("symbol") or "NQ"
        tick_size = _TICK_BY_SYM.get(symbol_c, 0.25)
        exit_price_c = close_ev.get("exit_price")
        pnl_ticks_c = None
        if entry_price_c and exit_price_c:
            try:
                side_c = close_ev.get("side") or (open_ev.get("side") if open_ev else None)
                direction = 1 if side_c in ("LONG", "BUY") else -1
                pnl_ticks_c = int(round(direction * (float(exit_price_c) - float(entry_price_c)) / tick_size))
            except (TypeError, ValueError):
                pnl_ticks_c = None
        duration_sec_c = None
        if ts_open_c and ts_close_c:
            try:
                t_o = datetime.fromisoformat(str(ts_open_c).replace("Z", "+00:00"))
                t_c = datetime.fromisoformat(str(ts_close_c).replace("Z", "+00:00"))
                duration_sec_c = int((t_c - t_o).total_seconds())
                # Safety: si duration > 6h on rejette (probable mismatch residuel)
                if duration_sec_c < 0 or duration_sec_c > 6 * 3600:
                    duration_sec_c = None
            except (ValueError, TypeError):
                duration_sec_c = None
        closed_today_list.append({
            "ts_close": ts_close_c,
            "ts_open": ts_open_c,
            "signal_id": sid_c,
            "symbol": symbol_c,
            "side": close_ev.get("side"),
            "level": close_ev.get("level"),
            "entry_price": entry_price_c,
            "exit_price": exit_price_c,
            "sl_ticks": sl_ticks_c,
            "tp_mode": tp_mode_c,
            "exit_cause": close_ev.get("exit_cause"),
            "reason": close_ev.get("exit_cause"),  # alias pour rendu UI v3
            "pnl_R": pnl_R_c,
            "pnl_usd": pnl_usd_c,
            "pnl_ticks": pnl_ticks_c,
            "duration_sec": duration_sec_c,
            "duration_bars": close_ev.get("duration_bars"),
            "pnl_known": True,
        })

    # Recent entries (last 20)
    recent_entries = [
        {
            "ts": e.get("ts"),
            "symbol": e.get("symbol"),
            "level": e.get("level"),
            "side": e.get("side"),
            "entry_price": e.get("entry_price"),
            "sl_price": e.get("sl_price"),
            "tp_price": e.get("tp_price"),
            "sl_ticks": e.get("sl_ticks"),
            "tp_mode": e.get("tp_mode"),
            "executed": e.get("executed", False),
            "veto_reason": e.get("veto_reason"),
            "signal_id": e.get("signal_id"),
        }
        for e in entries_log[-20:]
    ]

    # Paper trader alive ? Dernier event < 120s
    now = datetime.now(timezone.utc)
    paper_trader_alive = False
    if last_event_ts is not None:
        if last_event_ts.tzinfo is None:
            last_event_ts = last_event_ts.replace(tzinfo=timezone.utc)
        age_sec = (now - last_event_ts).total_seconds()
        paper_trader_alive = age_sec < 120

    return {
        "positions_active": positions_active,
        "stats_today": {
            "n_entries": n_entries_today,
            "n_trades_opened": n_trades_opened_today,
            "n_trades_closed": n_trades_closed_today,
            "pnl_session_usd": round(pnl_session_usd, 2),
            "pnl_session_R": round(pnl_session_R, 3),
            "n_sl_consec": n_sl_consec,
            "n_touches": n_touches_today,
            "n_state_transitions": n_state_transitions_today,
        },
        "setup_stats": setup_stats,
        "recent_entries": recent_entries,
        "closed_today": closed_today_list,  # 24/05/2026 PM bug Jackson fix
        "kill_switch_active": False,  # TODO parser KILL_MANUAL events si besoin
        "cooldown_until": None,
        "last_heartbeat_ts": last_heartbeat_ts,
        "paper_trader_alive": paper_trader_alive,
        "day_str": day_str,
        "available": True,
    }


def compute_stats_period_bot3(version: str, days: int) -> dict:
    """Agregation Bot 3 v3 OU v4 sur N derniers jours.

    Args:
        version : "v3" ou "v4"
        days : 7 ou 30 typiquement

    Returns:
        {n_trades, n_wins, wr_pct, pf, pnl_usd_total, pnl_R_total, days_covered}
    """
    assert version in ("v3", "v4")
    log_dir = LOGS_BOT3_V3_DIR if version == "v3" else LOGS_BOT3_V4_DIR

    n_trades = 0
    n_wins = 0
    gains_R = 0.0
    losses_R = 0.0
    pnl_usd_total = 0.0
    pnl_R_total = 0.0

    cme_now_start = _cme_trading_day_start_utc()
    for offset in range(days):
        day = cme_now_start - timedelta(days=offset)
        day_str = day.strftime("%Y%m%d")
        fpath = log_dir / f"bot3_{version}_v1_{day_str}.jsonl"
        if not fpath.exists():
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue
                    if d.get("event") != "TRADE_CLOSE":
                        continue
                    pnl_R = float(d.get("pnl_R") or 0.0)
                    pnl_usd = float(d.get("pnl_usd") or 0.0)
                    n_trades += 1
                    pnl_R_total += pnl_R
                    pnl_usd_total += pnl_usd
                    if pnl_R > 0:
                        n_wins += 1
                        gains_R += pnl_R
                    elif pnl_R < 0:
                        losses_R += -pnl_R
        except OSError:
            continue

    pf = round(gains_R / max(losses_R, 0.01), 2) if losses_R > 0 else None
    return {
        "n_trades": n_trades,
        "n_wins": n_wins,
        "wr_pct": round(100.0 * n_wins / max(n_trades, 1), 1) if n_trades > 0 else None,
        "pf": pf,
        "pnl_usd_total": round(pnl_usd_total, 2),
        "pnl_R_total": round(pnl_R_total, 3),
        "days_covered": days,
    }


# ─────────────────────────────────────────────────────────────────────────
# Bot MR (Sim1) — Countdown helpers (cooldown + MAX_HOLD)
# Ajout 18/06/2026 Jackson : dashboard PROTECTIONS ACTIVES affiche les
# temps restants au lieu d'un simple "Pret".
#
# Sources lues :
#   - state_sim1.json (StateBridge dashboard, deja lu par get_bot3_v3_payload)
#   - bot_mr_runtime_positions.json (PositionStore Bot MR, source verite
#     pour positions ouvertes + last_trade_ts_by_symbol persistant)
#
# Convention BotMRConfig :
#   - COOLDOWN_BARS exprime en MINUTES (1 bar = 60 sec, cf signal_engine.py:183)
#   - MAX_HOLD_MINUTES en minutes
#   - entry_ts dans positions = MILLISECONDES epoch (cf position_store.py:13)
#   - last_trade_ts_by_symbol = ISO 8601 UTC string (cf position_store.py:24)
# ─────────────────────────────────────────────────────────────────────────

# Path source positions Bot MR (PositionStore dedie, voir
# CORE/bot_mean_revert/main.py:65). Path absolu pour evite ambiguite cwd.
BOT_MR_RUNTIME_POSITIONS_FILE = PAPER_DIR / "bot_mr_runtime_positions.json"


def _bot_mr_cooldown_remaining_sec(last_trade_ts_iso: Optional[str],
                                   cooldown_minutes: int,
                                   now_utc: Optional[datetime] = None) -> int:
    """Secondes restantes avant fin cooldown Bot MR (0 si expire/absent).

    Le PositionStore.set_last_trade_ts() stocke un ISO 8601 UTC string apres
    chaque OPEN_TRADE. Le cooldown = `cooldown_minutes * 60` secondes apres ce ts.

    Args:
        last_trade_ts_iso: ISO 8601 UTC string ou None.
        cooldown_minutes: BotMRConfig.COOLDOWN_BARS (en minutes, 1 bar = 1 min).
        now_utc: override pour tests (default = utcnow).

    Returns:
        Secondes restantes (int >= 0). 0 si cooldown expire OU last_trade_ts
        absent OU ISO corrompu (fail-safe : ne bloque pas l'affichage).
    """
    if not last_trade_ts_iso or cooldown_minutes <= 0:
        return 0
    try:
        last_dt = datetime.fromisoformat(last_trade_ts_iso.replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return 0
    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    elapsed = (now - last_dt).total_seconds()
    remaining = (cooldown_minutes * 60) - elapsed
    return max(0, int(remaining))


def _bot_mr_max_hold_remaining_sec(entry_ts_ms: Optional[float],
                                   max_hold_minutes: int,
                                   now_ts_sec: Optional[float] = None) -> Optional[int]:
    """Secondes restantes avant MAX_HOLD force close (None si pas de position).

    Bot MR positions.entry_ts est en MILLISECONDES epoch (cf position_store.py).
    MAX_HOLD = hard timeout Lopez Triple Barrier (close marche si elapsed
    >= max_hold_minutes sans toucher TP/SL).

    Args:
        entry_ts_ms: epoch milliseconds OU None/0 si pas de position.
        max_hold_minutes: BotMRConfig.MAX_HOLD_MINUTES.
        now_ts_sec: override pour tests (default = time.time()).

    Returns:
        Secondes restantes (int >= 0) OU None si pas de position.
        Si max_hold expire deja -> 0 (force close imminent).
    """
    if not entry_ts_ms or entry_ts_ms <= 0:
        return None
    if max_hold_minutes <= 0:
        return None
    import time as _time
    now_sec = now_ts_sec if now_ts_sec is not None else _time.time()
    entry_sec = float(entry_ts_ms) / 1000.0
    elapsed = now_sec - entry_sec
    remaining = (max_hold_minutes * 60) - elapsed
    return max(0, int(remaining))


def _bot_mr_read_runtime_config() -> tuple[int, int]:
    """Lit cooldown_minutes + max_hold_minutes depuis env (override BotMRConfig).

    Pattern aligne sur BotMRConfig.from_env() : env vars BOTMR_COOLDOWN_BARS
    et BOTMR_MAX_HOLD_MINUTES, defaults config.py (30 / 30).

    Defensive : si env corrompu (non-int), retourne defaults. Ne crash JAMAIS
    le payload dashboard sur env var malforme.
    """
    try:
        cooldown_min = int(os.environ.get("BOTMR_COOLDOWN_BARS", "30"))
    except (ValueError, TypeError):
        cooldown_min = 30
    try:
        max_hold_min = int(os.environ.get("BOTMR_MAX_HOLD_MINUTES", "30"))
    except (ValueError, TypeError):
        max_hold_min = 30
    return cooldown_min, max_hold_min


def _bot_mr_build_cooldown_status(runtime_path: Path,
                                  cooldown_minutes: int,
                                  max_hold_minutes: int,
                                  now_utc: Optional[datetime] = None,
                                  now_ts_sec: Optional[float] = None) -> dict:
    """Lit bot_mr_runtime_positions.json et construit le payload cooldown_status.

    Structure retournee compatible frontend convention (Bot 1, BN V4, Bot 4) :
        {
          "ES": {
            "cooldown_remaining_sec": int,
            "max_hold_remaining_sec": int | None,
          },
          "NQ": {...},
        }

    Defensive : si fichier absent OU JSON corrompu OU clefs absentes,
    retourne {} (frontend retombe sur "Pret" defensive).
    """
    if not runtime_path.exists():
        return {}
    try:
        with runtime_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    # FIX 18/06 R1 code-reviewer : prefer meta_config persiste par le bot
    # (source unique de verite) plutot que les env vars du process dashboard
    # (process distinct nssm = env vars decorrelees).
    meta = data.get("meta_config") or {}
    if isinstance(meta, dict):
        try:
            cd_meta = int(meta.get("cooldown_minutes", 0))
            if cd_meta > 0:
                cooldown_minutes = cd_meta
        except (ValueError, TypeError):
            pass
        try:
            mh_meta = int(meta.get("max_hold_minutes", 0))
            if mh_meta > 0:
                max_hold_minutes = mh_meta
        except (ValueError, TypeError):
            pass
    positions = data.get("positions") or {}
    last_trade_ts_by_sym = data.get("last_trade_ts_by_symbol") or {}
    # Union des symboles vus en cooldown OU position ouverte (pour ne pas oublier
    # un symbole qui a juste un cooldown actif sans position).
    symbols = set()
    if isinstance(positions, dict):
        symbols.update(positions.keys())
    if isinstance(last_trade_ts_by_sym, dict):
        symbols.update(last_trade_ts_by_sym.keys())
    result = {}
    for sym in symbols:
        sym_up = sym.upper()
        last_iso = last_trade_ts_by_sym.get(sym_up) if isinstance(last_trade_ts_by_sym, dict) else None
        cd_sec = _bot_mr_cooldown_remaining_sec(last_iso, cooldown_minutes, now_utc=now_utc)
        pos = positions.get(sym_up) if isinstance(positions, dict) else None
        entry_ts_ms = pos.get("entry_ts") if isinstance(pos, dict) else None
        mh_sec = _bot_mr_max_hold_remaining_sec(entry_ts_ms, max_hold_minutes, now_ts_sec=now_ts_sec)
        result[sym_up] = {
            "cooldown_remaining_sec": cd_sec,
            "max_hold_remaining_sec": mh_sec,
        }
    return result


def get_bot3_v3_payload() -> dict:
    """Endpoint slot Sim1 pour dashboard.

    REFACTOR 16/06/2026 Jackson souverain :
      Le slot "Bot 1 Continuation Sim1" hebergeait historiquement Bot 3 v3 +
      Bot 3 MP (NQ Wyckoff + ES/MGC dip). Ces 2 bots ont ete KILLED ce matin
      (8 agents convergence NOGO + auteur initial recommandait deja KILL).

      Sim1 est maintenant occupe par **Bot Mean Revert** :
        - Strategie : Mean Reversion VWAP SD2/SD3 + IntermarketGate ES leader
        - Service VPS : MIA-Paper-BotMR-Sim1
        - State : DATA/PAPER_TRADES/state_sim1.json (StateBridge sub-class)
        - 24h ES + NQ (NQ confirme par ES leader)

      Ce endpoint lit donc maintenant `state_sim1.json` (Bot Mean Revert).
      L'endpoint conserve le nom `get_bot3_v3_payload` (et l'URL
      `/api/paper_bot3_v3_state`) pour compat retro frontend, mais le label
      affiche reflete la realite "Bot Mean Revert".

    18/06/2026 ajout countdown :
      Le payload `state` est enrichi avec `cooldown_status[sym]` exposant :
        - cooldown_remaining_sec : temps avant fin cooldown 15 min
        - max_hold_remaining_sec : temps avant MAX_HOLD force close (None si
          pas de position ouverte)
      Source : bot_mr_runtime_positions.json (PositionStore Bot MR).
    """
    state_sim1_file = PAPER_DIR / "state_sim1.json"
    mr_state = _safe_read_state(state_sim1_file)
    if mr_state and mr_state.get("updated_ts"):
        import time as _time
        now_ts = _time.time()
        try:
            last_update = float(mr_state.get("updated_ts", 0))
        except (TypeError, ValueError):
            last_update = 0
        paper_trader_alive = (now_ts - last_update) < 120  # heartbeat < 2 min
        # Compute stats_today depuis closed_today
        closed_today = mr_state.get("closed_today", []) or []
        n_trades = len(closed_today)
        n_wins = sum(1 for t in closed_today if (t.get("pnl_usd") or 0) > 0)
        pnl_usd = sum(float(t.get("pnl_usd") or 0) for t in closed_today)
        # FIX 18/06 Jackson : injecter stats_today DANS state pour que frontend
        # le lise correctement (frontend cherche state.stats_today, line 7252 dashboard.js).
        stats_today_dict = {
            "n_trades": n_trades,
            "n_wins": n_wins,
            "wr_pct": round(100.0 * n_wins / n_trades, 1) if n_trades > 0 else None,
            "pnl_usd": round(pnl_usd, 2),
        }
        mr_state["stats_today"] = stats_today_dict
        # 18/06 ajout countdown : lecture bot_mr_runtime_positions.json pour exposer
        # cooldown 15 min + MAX_HOLD 30 min restants par symbole dans le payload.
        # Defensive : si runtime file absent (Bot MR pas demarre), cooldown_status
        # reste {} et frontend retombe sur "Pret" defensive (pas de regression).
        cooldown_minutes, max_hold_minutes = _bot_mr_read_runtime_config()
        cooldown_status = _bot_mr_build_cooldown_status(
            BOT_MR_RUNTIME_POSITIONS_FILE,
            cooldown_minutes=cooldown_minutes,
            max_hold_minutes=max_hold_minutes,
        )
        mr_state["cooldown_status"] = cooldown_status
        return {
            "state_file": "state_sim1.json (Bot Mean Revert)",
            "state": mr_state,
            "available": True,
            "bot_label": "Bot Mean Revert Sim1",
            "bot_description": "Mean Reversion VWAP SD2/SD3 + IntermarketGate ES leader - 24h ES + NQ",
            "stats_today": stats_today_dict,
            "stats_7d": None,  # Bot MR vient de demarrer 16/06, pas d'historique
            "stats_30d": None,
            "paper_trader_alive": paper_trader_alive,
            "last_update_age_sec": int(now_ts - last_update) if last_update > 0 else None,
            # Exposes config Bot MR (consume par UI labels "Cooldown 15m / MAX_HOLD 30m")
            "cooldown_minutes": cooldown_minutes,
            "max_hold_minutes": max_hold_minutes,
        }
    # Fallback : state_sim1.json absent ou vide -> Bot MR pas demarre
    return {
        "state_file": "state_sim1.json (Bot Mean Revert)",
        "state": None,
        "available": False,
        "msg": "Bot Mean Revert Sim1 non actif (state_sim1.json absent ou stale)",
        "bot_label": "Bot Mean Revert Sim1",
        "stats_today": None,
        "stats_7d": None,
        "stats_30d": None,
        "paper_trader_alive": False,
    }


def get_bot3_v3_payload_legacy() -> dict:
    """Ancien Bot 3 v3 Continuation (Sim1 NQ Wyckoff) - DEPRECATED 16/06.

    Active uniquement si ENV `MIA_BOT3_V3_ENABLED=1` (default 0 = OFF).
    Bot 3 v3 + Bot 3 MP killed 16/06 ce matin (service stopped+disabled).
    Conserve pour reference historique, n'est plus appele en prod.
    """
    if os.environ.get("MIA_BOT3_V3_ENABLED", "0") != "1":
        return {
            "state_file": "bot3_v3_logger_jsonl",
            "state": None,
            "available": False,
            "msg": "Bot 3 v3 desactive (MIA_BOT3_V3_ENABLED != 1)",
            "stats_7d": None,
            "stats_30d": None,
            "paper_trader_alive": False,
        }
    today = _load_bot3_vN_today_state("v3")
    stats_7d = compute_stats_period_bot3("v3", 7)
    stats_30d = compute_stats_period_bot3("v3", 30)

    # Fix 28/05 directive Jackson : "Bot 1 lit les trades des 2 indices".
    # Le toggle UI "Bot 1" = bot3_v3 (NQ only) post-rebrand 24/05. Mais le
    # MEME process MIA-DataBento-Paper-V2 execute aussi databento_paper_trader_v2
    # ._bot3_execute_trade qui trade NQ+ES+MGC sur Sim1 (toggle "Bot 3 MP" cache).
    # On merge ici les closed ES/MGC depuis *_databento_v3_trades.jsonl pour
    # rendre la totalite des trades Sim1 visible sur l'onglet Bot 1.
    # Anti double-counting : on filtre sym != "NQ" (NQ provient deja de bot3_v3).
    closed_v3_nq = today.get("closed_today", []) or []
    closed_es_mgc: list = []
    stats_es_mgc: dict = {"trades": 0, "wins": 0, "losses": 0, "wr": 0,
                          "pf": None, "pnl_usd": 0, "pnl_ticks": 0}
    try:
        mp_stats = _compute_stats_today_from_trades("*_databento_v3_trades.jsonl")
        for tr in (mp_stats.get("closed_today") or []):
            sym = tr.get("symbol") or tr.get("sym")
            if sym in ("ES", "MGC"):
                closed_es_mgc.append(tr)
        # Stats agreg ES+MGC (sans NQ)
        if closed_es_mgc:
            wins = sum(1 for t in closed_es_mgc if (t.get("pnl_usd") or 0) > 0)
            losses = sum(1 for t in closed_es_mgc if (t.get("pnl_usd") or 0) < 0)
            n = len(closed_es_mgc)
            pnl_u = sum((t.get("pnl_usd") or 0) for t in closed_es_mgc)
            pnl_t = sum((t.get("pnl_ticks") or 0) for t in closed_es_mgc)
            gw = sum(t.get("pnl_usd") or 0 for t in closed_es_mgc if (t.get("pnl_usd") or 0) > 0)
            gl = -sum(t.get("pnl_usd") or 0 for t in closed_es_mgc if (t.get("pnl_usd") or 0) < 0)
            pf = (gw / gl) if gl > 0 else None
            stats_es_mgc = {
                "trades": n, "wins": wins, "losses": losses,
                "wr": round(100 * wins / n, 1) if n > 0 else 0,
                "pf": round(pf, 2) if pf is not None else None,
                "pnl_usd": round(pnl_u, 2), "pnl_ticks": round(pnl_t, 1),
            }
    except Exception as _e:
        # Best-effort : si journal MP corrompu, on garde Bot 1 NQ-only sans crash
        pass

    # Fusion closed (trie par ts decroissant pour affichage)
    closed_merged = list(closed_v3_nq) + closed_es_mgc
    try:
        closed_merged.sort(key=lambda t: t.get("ts") or t.get("ts_close") or "", reverse=True)
    except Exception:
        pass

    # === FIX 2026-06-02 (Jackson "trades ES pas affiches Bot 1") ============
    # Merge positions ACTIVES ES/MGC depuis le state Bot 3 MP.
    # Le runner Wyckoff bot3_v3_continuation_paper.py ne logge que NQ -> les
    # positions ES/MGC ouvertes via _bot3_execute_trade (databento_paper_v2)
    # sont persistees dans databento_paper_v3_state.json["positions"] MAIS
    # JAMAIS dans LOGS/bot3_v3/. Sans merge, l'onglet "Bot 1 NQ + ES" affiche
    # "aucune position ouverte" alors qu'un trade ES est actif sur Sim1.
    # Cf agent dispatched 02/06 + memory project_bots_architecture_20260529.
    positions_active_merged = dict(today.get("positions_active", {}) or {})  # NQ depuis bot3_v3
    try:
        mp_state = _safe_read_state(STATE_FILE_BOT3)
        mp_positions = (mp_state or {}).get("positions", {}) or {}
        for sym in ("ES", "MGC"):
            pos = mp_positions.get(sym)
            if not pos or not isinstance(pos, dict):
                continue
            # Defense en profondeur : ne pas ecraser une position NQ qui aurait
            # ete loggee dans bot3_v3 (impossible aujourd'hui — Wyckoff NQ-only —
            # mais previent une future extension Wyckoff multi-symboles).
            if sym in positions_active_merged:
                continue
            # Normaliser format pour matcher schema bot3_v3
            # (renderPaperBot3V3Section dashboard.js:5455+ consomme ces champs).
            positions_active_merged[sym] = {
                "signal_id": pos.get("signal_id"),
                "level": pos.get("level"),
                "side": pos.get("side"),
                "entry_price": pos.get("entry_price"),
                "sl_price": pos.get("sl_price"),
                "tp_price": pos.get("tp_cap_price"),    # Bot 3 MP utilise tp_cap_price
                "sl_ticks": None,
                "tp_mode": None,
                "vpoc_value": None,
                "qty": pos.get("n_contracts", 1),
                "trade_account": "Sim1",
                "ts_open": pos.get("ts_open"),
                # Champs additifs Bot 3 MP (consommables frontend si voulu)
                "level_tier": pos.get("level_tier"),
                "confidence": pos.get("confidence"),
                "mfe_ticks": pos.get("mfe_ticks"),
                "mae_ticks": pos.get("mae_ticks"),
                "_source": "bot3_mp_state",  # traceability merge
            }
    except Exception:
        # Best-effort : si state corrompu, garde NQ-only sans crash
        pass

    # Stats today agrege NQ (bot3_v3 schema n_trades_*) + ES/MGC (MP schema trades/wins/losses)
    # Fix review agent 28/05 : le logger bot3_v3 expose des cles differentes (n_trades_closed,
    # pnl_session_usd, ...) que le MP (trades, wins, pnl_usd). Mon premier patch lisait les
    # mauvaises cles -> compteurs Bot 1 affichaient 0 (regression critique). Cette version
    # PRESERVE le dict st_nq original (n_entries, n_touches, n_state_transitions, n_sl_consec,
    # n_trades_opened, pnl_session_R lus par renderPaperBot3V3Section) ET ajoute les agregees
    # ES+MGC sur les cles utilisees par setPaperBot statsTodayNorm.
    st_nq = today.get("stats_today") or {}
    n_nq = int(st_nq.get("n_trades_closed", 0) or 0)
    pnl_u_nq = float(st_nq.get("pnl_session_usd", 0) or 0)
    pnl_R_nq = float(st_nq.get("pnl_session_R", 0) or 0)
    # wins/losses NQ : agreger depuis setup_stats (comme le frontend)
    w_nq = sum(s.get("n_wins", 0) for s in (today.get("setup_stats") or {}).values())
    l_nq = sum(s.get("n_losses", 0) for s in (today.get("setup_stats") or {}).values())
    # pnl_ticks NQ : recompute depuis closed_v3_nq (closed_today liste backend bot3_v3)
    pnl_t_nq = sum((t.get("pnl_ticks") or 0) for t in closed_v3_nq)

    n_tot = n_nq + stats_es_mgc["trades"]
    w_tot = w_nq + stats_es_mgc["wins"]
    l_tot = l_nq + stats_es_mgc["losses"]
    pnl_u_tot = pnl_u_nq + stats_es_mgc["pnl_usd"]
    pnl_t_tot = pnl_t_nq + stats_es_mgc["pnl_ticks"]
    # PF agrege : recompute depuis closed_merged (gross_win / gross_loss total)
    gw_tot = sum((t.get("pnl_usd") or 0) for t in closed_merged if (t.get("pnl_usd") or 0) > 0)
    gl_tot = -sum((t.get("pnl_usd") or 0) for t in closed_merged if (t.get("pnl_usd") or 0) < 0)
    pf_tot = (gw_tot / gl_tot) if gl_tot > 0 else None

    # IMPORTANT : PRESERVER les cles bot3_v3 originelles + ajouter les agregees normalisees.
    # renderPaperBot3V3Section (dashboard.js:5455+) consomme n_trades_closed, pnl_session_usd,
    # n_entries, n_touches, n_state_transitions, n_sl_consec, n_trades_opened, pnl_session_R.
    # setPaperBot statsTodayNorm (dashboard.js:5198+) consomme trades, wins, losses, wr, pf,
    # pnl_usd, pnl_ticks.
    stats_today_merged = dict(st_nq)  # garde n_entries, n_touches, n_state_transitions, etc.
    stats_today_merged.update({
        # Overwrite avec totaux NQ + ES/MGC (frontend Bot 3 v3 schema)
        "n_trades_closed": n_tot,
        "pnl_session_usd": round(pnl_u_tot, 2),
        "pnl_session_R": round(pnl_R_nq, 3),  # NQ-only (MP n'a pas de R)
        # Cles additives normalisees (setPaperBot statsTodayNorm)
        "trades": n_tot, "wins": w_tot, "losses": l_tot,
        "wr": round(100 * w_tot / n_tot, 1) if n_tot > 0 else 0,
        "pf": round(pf_tot, 2) if pf_tot is not None else None,
        "pnl_usd": round(pnl_u_tot, 2),
        "pnl_ticks": round(pnl_t_tot, 1),
    })

    return _clean_nan_inf({
        "state_file": "bot3_v3_logger_jsonl",
        "state": {
            "ts_utc": today.get("last_heartbeat_ts"),
            "mode": "PAPER_BOT3_V3",
            "trade_account": os.environ.get("MIA_BOT3_V3_TRADE_ACCOUNT", "Sim1"),
            "kill_switch_active": today.get("kill_switch_active"),
            "cooldown_until": today.get("cooldown_until"),
            "bar_source": {"global": "LIVE_ENRICHED_60s"},
        },
        "positions_with_countdown": positions_active_merged,  # FIX 02/06 : NQ + ES/MGC
        "setup_stats": today.get("setup_stats", {}),
        "recent_entries": today.get("recent_entries", []),
        "closed_today": closed_merged,   # Fusion NQ (bot3_v3) + ES/MGC (MP)
        "stats_today": stats_today_merged,  # Agrege NQ + ES/MGC
        # Champs additifs pour traceability (non-breaking pour frontend existant)
        "stats_today_nq": st_nq,
        "stats_today_es_mgc": stats_es_mgc,
        "stats_7d": stats_7d,
        "stats_30d": stats_30d,
        "trading_window_utc": "00h-22h",
        "mode": "PAPER_BOT3_V3",
        "trade_account": os.environ.get("MIA_BOT3_V3_TRADE_ACCOUNT", "Sim1"),
        "phase_paper": True,
        "available": True,
        "paper_trader_alive": today.get("paper_trader_alive", False),
        "ts_utc": today.get("last_heartbeat_ts"),
        "day_str": today.get("day_str"),
        "has_paper_active": today.get("paper_trader_alive", False),
        "bot_label": "Bot 1 Sim1 - NQ + ES/MGC",
        "kill_switch_active": today.get("kill_switch_active"),
    })


def get_bot3_v4_payload() -> dict:
    """Endpoint slot Sim3 pour dashboard.

    REFACTOR 16/06/2026 Jackson souverain :
      Le slot "Bot 3 v4 Data-driven Sim3" hebergeait historiquement le Bot 3 v4
      Data-driven (mort 11/06, killed 16/06 matin). Sim3 est maintenant occupe
      par **Bot 3 BN V4 (Bataille Navale V4)** :
        - Strategie : reversal LONG post-baisse + 5 phases (trend baissier +
          bottom zone + density clusters + edge buy + confirmation volume)
        - Service VPS : MIA-Paper-BotBN-Sim3
        - State : DATA/PAPER_TRADES/state_sim3.json (StateBridge sub-class)
        - Grade A++ TRADE + SHADOW A/B observation
        - NQ uniquement, US RTH only

      Ce endpoint lit donc maintenant `state_sim3.json` (Bot BN V4).
      L'endpoint conserve le nom `get_bot3_v4_payload` (et l'URL
      `/api/paper_bot3_v4_state`) pour compat retro frontend, mais le label
      affiche reflete la realite "Bot 3 BN V4".
    """
    state_sim3_file = PAPER_DIR / "state_sim3.json"
    bn_state = _safe_read_state(state_sim3_file)
    if bn_state and bn_state.get("updated_ts"):
        import time as _time
        now_ts = _time.time()
        try:
            last_update = float(bn_state.get("updated_ts", 0))
        except (TypeError, ValueError):
            last_update = 0
        paper_trader_alive = (now_ts - last_update) < 120  # heartbeat < 2 min
        closed_today = bn_state.get("closed_today", []) or []
        n_trades = len(closed_today)
        n_wins = sum(1 for t in closed_today if (t.get("pnl_usd") or 0) > 0)
        pnl_usd = sum(float(t.get("pnl_usd") or 0) for t in closed_today)
        return {
            "state_file": "state_sim3.json (Bot 3 BN V4)",
            "state": bn_state,
            "available": True,
            "bot_label": "Bot 3 BN V4 Sim3",
            "bot_description": "Bataille Navale V4 - reversal LONG post-baisse (5 phases) - A++ TRADE + SHADOW A/B - NQ US RTH",
            "stats_today": {
                "n_trades": n_trades,
                "n_wins": n_wins,
                "wr_pct": round(100.0 * n_wins / n_trades, 1) if n_trades > 0 else None,
                "pnl_usd": round(pnl_usd, 2),
            },
            "stats_7d": None,  # Bot BN V4 vient de demarrer 16/06
            "stats_30d": None,
            "paper_trader_alive": paper_trader_alive,
            "last_update_age_sec": int(now_ts - last_update) if last_update > 0 else None,
        }
    # Fallback : state_sim3.json absent ou stale -> Bot BN V4 pas demarre
    return {
        "state_file": "state_sim3.json (Bot 3 BN V4)",
        "state": None,
        "available": False,
        "msg": "Bot 3 BN V4 Sim3 non actif (state_sim3.json absent ou stale)",
        "bot_label": "Bot 3 BN V4 Sim3",
        "stats_today": None,
        "stats_7d": None,
        "stats_30d": None,
        "paper_trader_alive": False,
    }


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


# ============================================================================
# BOT 4 — NEW_BOT_2_MIA_TRADER (J12.2 Dashboard V2, deploy 2026-05-27)
# ============================================================================
#
# Sources data Bot 4 (2 systemes paralleles - cf PLAN_J12_DASHBOARD_V2) :
#
# 1) Telemetry M6 Pydantic snapshots — EXCLUSIF Bot 4 (Bot 1/2/3 n'utilisent pas) :
#    LOGS/{reader|decision|risk|sltp|execution}/{YYYYMMDD}_{cat}.jsonl (singulier)
#    Pas de filtre process necessaire (autres bots = pas dans ces fichiers).
#
# 2) Logger V2 codes — lifecycle/exceptions :
#    LOGS/{events|decisions|execution|risk|errors}/{cat}_{YYYYMMDD}_bot4.jsonl
#    (pluriel + suffixe _bot4 = filtre process AUTOMATIQUE via filename, P0.1 Option C).
#    AUCUN filtre host_process side loader.
#
# Constantes top-level (LOGS_ROOT override via MIA_LOG_DIR pour tests).
LOGS_ROOT = Path(os.environ.get("MIA_LOG_DIR", str(_ROOT / "LOGS")))

# Constantes Bot 4 (I1 fix review code J12 : magic numbers extraits)
# Corruption ghost trade filter (pattern Bot 3 v4 reuse) :
#   abs(pnl_usd) > 50000 OU abs(pnl_R) > 100 -> trade ignore (ghost detect)
BOT4_PNL_CORRUPTION_USD = 50000.0
BOT4_PNL_R_CORRUPTION = 100.0
# Paper trader alive threshold (heartbeat freshness) :
#   state_age_sec < 180 -> alive (3x heartbeat 60s, pattern Bot 3 v3/v4 dashboard.js:4731)
#   Fix review J12 PM Jackson : 120s strict = 50% temps DOWN car heartbeat 1/min.
BOT4_ALIVE_THRESHOLD_SEC = 180
# Recent entries / vetos limit anti-chrono (Card 5 + Card 6 frontend)
BOT4_RECENT_LIMIT = 20
# Daily Loss Limit hardcode P7.1 (Topstep $50k account standard)
# TRIGGER : a remplacer par lecture config Topstep API en P7.2
BOT4_P71_DLL_HARDCODE_USD = 1000.0

# Logger V2 dirs (pluriel) — fichiers suffixe `_bot4.jsonl`
LOGS_BOT4_EVENTS_DIR = LOGS_ROOT / "events"
LOGS_BOT4_DECISIONS_DIR = LOGS_ROOT / "decisions"
LOGS_BOT4_EXECUTION_LOGGER_DIR = LOGS_ROOT / "execution"
LOGS_BOT4_RISK_LOGGER_DIR = LOGS_ROOT / "risk"
LOGS_BOT4_ERRORS_DIR = LOGS_ROOT / "errors"

# Telemetry M6 Pydantic dirs (singulier) — fichiers `{day}_{cat}.jsonl`
LOGS_BOT4_READER_DIR = LOGS_ROOT / "reader"
LOGS_BOT4_DECISION_DIR = LOGS_ROOT / "decision"
LOGS_BOT4_RISK_DIR = LOGS_ROOT / "risk"
LOGS_BOT4_SLTP_DIR = LOGS_ROOT / "sltp"
LOGS_BOT4_EXECUTION_DIR = LOGS_ROOT / "execution"


def _read_logger_v2_jsonl_bot4(category: str, day_str: str) -> list[dict]:
    """Lit LOGS/{category}/{category}_{day_str}_bot4.jsonl (Logger V2, pluriel).

    Process suffix `_bot4` dans le filename = filtre process AUTOMATIQUE (P0.1
    Option C). Aucun filtre `host_process` n'est applique cote loader.

    Args:
        category : "events" | "decisions" | "execution" | "risk" | "errors".
        day_str : "YYYYMMDD" UTC.

    Returns:
        Liste d'events (dict). Vide si fichier absent. Lines JSONL invalides
        ignorees silencieusement (R13 race condition tolerance, pattern existant
        cf `_load_bot3_vN_today_state`).
    """
    path = LOGS_ROOT / category / f"{category}_{day_str}_bot4.jsonl"
    if not path.exists():
        return []
    events: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return events


def _read_telemetry_pydantic_jsonl(category: str, day_str: str) -> list[dict]:
    """Lit LOGS/{category}/{day_str}_{category}.jsonl (Pydantic Telemetry M6, singulier).

    Format singulier `{day}_{cat}.jsonl` = EXCLUSIF Bot 4 (Bot 1/2/3 n'utilisent
    pas Telemetry M6). Donc aucun filtre process necessaire.

    Args:
        category : "reader" | "decision" | "risk" | "sltp" | "execution".
        day_str : "YYYYMMDD" UTC.

    Returns:
        Liste d'events (dict). Vide si fichier absent.
    """
    path = LOGS_ROOT / category / f"{day_str}_{category}.jsonl"
    if not path.exists():
        return []
    events: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return events


def _load_bot4_today_state(day_str: Optional[str] = None) -> dict:
    """Reconstruit l'etat Bot 4 du CME trading day.

    Calque architectural sur `_load_bot3_vN_today_state` avec ajouts P7.1
    SAFE COLLECT :
      - `n_signals_seen` (total DecisionEvent ACHAT+VENTE+ATTENDRE)
      - `n_passed` (DecisionEvent action IN (ACHAT, VENTE))
      - `n_veto` (DecisionEvent action=ATTENDRE AND binding_gate IS NOT NULL)
      - `recent_signals_veto[]` (last 20 DecisionEvent vetoed anti-chrono)
      - `setup_stats={}` placeholder P7.1 (TBD P7.2)

    Args:
        day_str : "YYYYMMDD" UTC (default = today CME trading day UTC).

    Returns:
        dict (cf docstring J12.2 plan, schema return identique bot3_vN + extras).

    Comportements attendus (documentes pour tests J12.7) :
      - Fichiers absents → `available=False`, `paper_trader_alive=False`, stats=0.
      - `recent_signals_veto[]` : toujours array, jamais `null` (P2.1 test #10).
      - CME boundary 22:00 UTC : trades J-1 visibles avant rollover, disparaissent
        apres (idem pattern bot3_vN avec `_in_cme_day`).
      - Filtre corruption `|pnl_usd|>50000 or |pnl_R|>100` (pattern Bot 3 v4).
      - Multi-PID restart : plusieurs BOOT_START dans meme fichier → on prend
        toujours le DERNIER event lifecycle (R16 plan V2).
    """
    if day_str is None:
        utc_now = datetime.now(timezone.utc)
        day_str = utc_now.strftime("%Y%m%d")

    # CME trading day cross 22:00 UTC : potentiellement 2 fichiers a lire
    cme_start = _cme_trading_day_start_utc()
    utc_now = datetime.now(timezone.utc)
    days_to_read: list[str] = []
    seen_days: set = set()
    for day_dt in [cme_start, utc_now]:
        d_str = day_dt.strftime("%Y%m%d")
        if d_str not in seen_days:
            seen_days.add(d_str)
            days_to_read.append(d_str)

    # Empty result (used si rien trouve)
    empty_result = {
        "positions_active": {},
        "stats_today": {
            "n_signals_seen": 0,
            "n_passed": 0,
            "n_veto": 0,
            "n_trades_opened": 0,
            "n_trades_closed": 0,
            "pnl_session_usd": 0.0,
            "pnl_session_R": 0.0,
            "n_sl_consec": 0,
        },
        "setup_stats": {},
        "setup_stats_info": "TBD P7.2 (setups structurels)",
        "recent_entries": [],
        "recent_signals_veto": [],
        "kill_switch_active": False,
        "cooldown_until": None,
        "last_heartbeat_ts": None,
        "bar_source": None,
        "phase": None,
        "dry_run": None,
        "paper_trader_alive": False,
        "day_str": day_str,
        "available": False,
        "errors": [],
    }

    # Aggregation cross-files (Logger V2 + Pydantic)
    events_logger: list[dict] = []
    decisions_logger: list[dict] = []
    execution_logger: list[dict] = []
    risk_logger: list[dict] = []
    errors_logger: list[dict] = []

    decision_pyd: list[dict] = []
    risk_pyd: list[dict] = []
    sltp_pyd: list[dict] = []
    execution_pyd: list[dict] = []
    reader_pyd: list[dict] = []

    any_file_found = False
    for d_str in days_to_read:
        # Logger V2 (5 fichiers `_bot4.jsonl`)
        ev = _read_logger_v2_jsonl_bot4("events", d_str)
        dec = _read_logger_v2_jsonl_bot4("decisions", d_str)
        ex_l = _read_logger_v2_jsonl_bot4("execution", d_str)
        rk_l = _read_logger_v2_jsonl_bot4("risk", d_str)
        err = _read_logger_v2_jsonl_bot4("errors", d_str)

        # Pydantic Telemetry M6 (5 fichiers singulier)
        dec_p = _read_telemetry_pydantic_jsonl("decision", d_str)
        rk_p = _read_telemetry_pydantic_jsonl("risk", d_str)
        sl_p = _read_telemetry_pydantic_jsonl("sltp", d_str)
        ex_p = _read_telemetry_pydantic_jsonl("execution", d_str)
        rd_p = _read_telemetry_pydantic_jsonl("reader", d_str)

        if (ev or dec or ex_l or rk_l or err or dec_p or rk_p or sl_p or ex_p or rd_p):
            any_file_found = True

        events_logger.extend(ev)
        decisions_logger.extend(dec)
        execution_logger.extend(ex_l)
        risk_logger.extend(rk_l)
        errors_logger.extend(err)

        decision_pyd.extend(dec_p)
        risk_pyd.extend(rk_p)
        sltp_pyd.extend(sl_p)
        execution_pyd.extend(ex_p)
        reader_pyd.extend(rd_p)

    if not any_file_found:
        return empty_result

    # Helpers timestamp + filtre CME day
    def _ev_dt(ev: dict) -> Optional[datetime]:
        ts = ev.get("ts")
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    def _in_cme_day(ev: dict) -> bool:
        ts = _ev_dt(ev)
        if ts is None:
            return True  # fallback safe (garder si ts illisible)
        return ts >= cme_start

    # Filtre CME day sur toutes les sources (sauf events lifecycle = on garde
    # full file pour avoir BOOT_READY/BOOT_START meme tres anciens du jour).
    decisions_logger = [e for e in decisions_logger if _in_cme_day(e)]
    execution_logger = [e for e in execution_logger if _in_cme_day(e)]
    risk_logger_cme = [e for e in risk_logger if _in_cme_day(e)]

    decision_pyd_cme = [e for e in decision_pyd if _in_cme_day(e)]
    risk_pyd_cme = [e for e in risk_pyd if _in_cme_day(e)]
    sltp_pyd_cme = [e for e in sltp_pyd if _in_cme_day(e)]
    execution_pyd_cme = [e for e in execution_pyd if _in_cme_day(e)]

    # --- Lifecycle (events_logger) : DERNIER event de chaque type ---
    # R16 plan V2 : multi-PID restart possible → prendre le plus recent.
    last_kill_switch_ev: Optional[dict] = None
    last_heartbeat_ev: Optional[dict] = None
    last_config_loaded_ev: Optional[dict] = None
    last_boot_ready_ev: Optional[dict] = None
    last_boot_start_ev: Optional[dict] = None

    # Tri par timestamp ascendant pour recuperer le DERNIER (tail safe)
    def _ts_key(ev: dict) -> datetime:
        dt = _ev_dt(ev)
        return dt if dt is not None else datetime.min.replace(tzinfo=timezone.utc)

    events_sorted = sorted(events_logger, key=_ts_key)
    for ev in events_sorted:
        code = ev.get("code", "")
        if code == "BOT4_KILL_SWITCH_DETECTED":
            last_kill_switch_ev = ev
        elif code == "BOT4_HEARTBEAT":
            last_heartbeat_ev = ev
        elif code == "BOT4_CONFIG_LOADED":
            last_config_loaded_ev = ev
        elif code == "BOT4_BOOT_READY":
            last_boot_ready_ev = ev
        elif code == "BOT4_BOOT_START":
            last_boot_start_ev = ev

    kill_switch_active = False
    if last_kill_switch_ev is not None:
        # Presence d'un BOT4_KILL_SWITCH_DETECTED recent = actif (binaire P7.1).
        # Pattern aligne Bot 3 : on ne suit pas un "deactivation" event ici.
        kill_switch_active = True

    last_heartbeat_ts: Optional[str] = (
        last_heartbeat_ev.get("ts") if last_heartbeat_ev else None
    )
    bar_source: Optional[str] = None
    if last_config_loaded_ev is not None:
        ctx = last_config_loaded_ev.get("ctx") or {}
        if isinstance(ctx, dict):
            bar_source = ctx.get("bar_source")

    phase: Optional[str] = None
    if last_boot_ready_ev is not None:
        ctx = last_boot_ready_ev.get("ctx") or {}
        if isinstance(ctx, dict):
            phase = ctx.get("phase")

    dry_run: Optional[bool] = None
    if last_boot_start_ev is not None:
        ctx = last_boot_start_ev.get("ctx") or {}
        if isinstance(ctx, dict):
            raw_dr = ctx.get("dry_run")
            if isinstance(raw_dr, bool):
                dry_run = raw_dr
            elif isinstance(raw_dr, str):
                dry_run = raw_dr.lower() in ("1", "true", "yes")
            elif isinstance(raw_dr, (int, float)):
                dry_run = bool(raw_dr)

    # cooldown_until : derniere RiskEvent.cooldown_until non-null (Pydantic prioritaire)
    cooldown_until: Optional[str] = None
    for ev in reversed(risk_pyd_cme):
        cu = ev.get("cooldown_until")
        if cu:
            cooldown_until = cu
            break
    if cooldown_until is None:
        # Fallback Logger V2 risk_*_bot4.jsonl (ctx.cooldown_until)
        for ev in reversed(risk_logger_cme):
            ctx = ev.get("ctx") or {}
            if isinstance(ctx, dict):
                cu = ctx.get("cooldown_until")
                if cu:
                    cooldown_until = cu
                    break

    # --- Positions actives : match TRADE_OPEN/TRADE_CLOSE par signal_id ---
    # Source PRIMAIRE : Logger V2 risk codes (BOT4_RISK_TRADE_OPEN / _CLOSE).
    opens_log: list[dict] = []
    closes_log: list[dict] = []
    for ev in risk_logger_cme:
        code = ev.get("code", "")
        if code == "BOT4_RISK_TRADE_OPEN":
            opens_log.append(ev)
        elif code == "BOT4_RISK_TRADE_CLOSE":
            # Filtre corruption ghost trade (pattern Bot 3 v4)
            ctx = ev.get("ctx") or {}
            try:
                pnl_usd = float(ctx.get("pnl_usd") or 0.0)
                pnl_R = float(ctx.get("pnl_R") or 0.0)
            except (TypeError, ValueError):
                pnl_usd, pnl_R = 0.0, 0.0
            if abs(pnl_usd) > BOT4_PNL_CORRUPTION_USD or abs(pnl_R) > BOT4_PNL_R_CORRUPTION:
                continue
            closes_log.append(ev)

    # Helper _match_open (calque bot3 ligne 1473)
    def _match_open(sid_c: Optional[str], ts_close_str: Optional[str]) -> Optional[dict]:
        """Prend le DERNIER TRADE_OPEN avec ts_open <= ts_close (sid duplique reboot)."""
        if not sid_c:
            return None
        ts_c: Optional[datetime] = None
        if ts_close_str:
            try:
                ts_c = datetime.fromisoformat(str(ts_close_str).replace("Z", "+00:00"))
                if ts_c.tzinfo is None:
                    ts_c = ts_c.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                ts_c = None
        candidates: list = []
        for o in opens_log:
            if o.get("signal_id") != sid_c:
                continue
            if ts_c is None:
                candidates.append((None, o))
                continue
            ts_o = _ev_dt(o)
            if ts_o is None or ts_o <= ts_c:
                candidates.append((ts_o, o))
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0] is not None, x[0]), reverse=True)
        return candidates[0][1]

    closed_sids = {c.get("signal_id") for c in closes_log if c.get("signal_id")}
    # 04/06 Jackson : cross-ref bot4_open_positions.json (state file = source de
    # verite Bot 4). Si state file existe ET ne contient PAS le signal_id, c'est
    # un OPEN orphelin (ex: flatten manuel via Sierra Chart non synchronise avec
    # log risk_*_bot4.jsonl). Ignore le OPEN orphelin pour eviter affichage
    # position fantome dashboard. Si state file absent ou unreadable -> fail-open
    # (comportement legacy, pas de regression).
    bot4_state_real_sids: Optional[set] = None
    try:
        bot4_state_path = LOGS_ROOT / "bot4_open_positions.json"
        if bot4_state_path.exists():
            # utf-8-sig : tolere BOM eventuel (PowerShell Set-Content UTF8 en met).
            with open(bot4_state_path, "r", encoding="utf-8-sig") as fh:
                _real_state = json.load(fh) or {}
            bot4_state_real_sids = set(_real_state.keys())
    except (OSError, json.JSONDecodeError, ValueError):
        bot4_state_real_sids = None  # fail-open

    positions_active: dict = {}
    # Fix 28/05 BUG#1 audit : un OPEN ancien sans CLOSE matchant + ctx incomplet
    # (entry_price=None) provient du pre-patch _on_filled (prefix MIA4_ vs MIA_).
    # Filtre : si OPEN > 2h sans CLOSE ET ctx sans entry_price -> orphelin, ignore.
    BOT4_OPEN_ORPHAN_MAX_AGE_SEC = 7200  # 2h
    # NB : datetime/timezone deja importes au top du module (ne pas re-importer
    # localement -> shadow UnboundLocalError).
    _now_utc = datetime.now(timezone.utc)
    for o in opens_log:
        sid = o.get("signal_id")
        if not sid or sid in closed_sids:
            continue
        # 04/06 cross-ref state file Bot 4 : ignore si le bot lui-meme dit
        # qu'il n'a pas ce signal_id en position ouverte.
        if bot4_state_real_sids is not None and sid not in bot4_state_real_sids:
            continue
        ctx_o = o.get("ctx") or {}
        # Anti-orphelin (BUG#1 28/05) : OPEN ancien sans entry_price = trace
        # pre-patch _on_filled bloque (prefix MIA4_ vs MIA_). Ignore pour ne pas
        # afficher position fantome eternellement.
        if ctx_o.get("entry_price") is None:
            ts_o_str = o.get("ts", "")
            try:
                ts_o = datetime.fromisoformat(ts_o_str.replace("Z", "+00:00"))
                age_sec = (_now_utc - ts_o).total_seconds()
                if age_sec > BOT4_OPEN_ORPHAN_MAX_AGE_SEC:
                    continue
            except (ValueError, AttributeError):
                pass
        # Fix 28/05 cle ctx : le log Bot 4 ecrit "sym", le tracker lisait "symbol"
        # uniquement -> sym vide "?" sur dashboard. Maintenant accept les 2 cles.
        sym = ctx_o.get("symbol") or ctx_o.get("sym") or o.get("symbol") or "?"
        positions_active[sym] = {
            "signal_id": sid,
            "side": ctx_o.get("side") or o.get("side"),
            "entry_price": ctx_o.get("entry_price"),
            "sl_price": ctx_o.get("sl_price"),
            "tp_price": ctx_o.get("tp_price"),
            "sl_ticks": ctx_o.get("sl_ticks"),
            "tp_ticks": ctx_o.get("tp_ticks"),
            "qty": ctx_o.get("qty", 1),
            "trade_account": ctx_o.get("trade_account"),
            "ts_open": o.get("ts"),
        }

    # --- Stats today ---
    # n_signals_seen : total DecisionEvent (Pydantic decision)
    n_signals_seen = len(decision_pyd_cme)
    n_passed = sum(1 for e in decision_pyd_cme if e.get("action") in ("ACHAT", "VENTE"))
    n_veto = sum(
        1 for e in decision_pyd_cme
        if e.get("action") == "ATTENDRE" and e.get("binding_gate")
    )
    n_trades_opened = len(opens_log)
    # 03/06 P2 FIX : exclure RECOVERED_TIMEOUT fictifs des stats Bot 4 (BOT4_RISK_TRADE_CLOSE)
    # Le check ctx field couvre level/reason/outcome via _is_recovered_fictive_close
    closes_log = [c for c in closes_log if not _is_recovered_fictive_close(c)]
    n_trades_closed = len(closes_log)

    pnl_session_usd = 0.0
    pnl_session_R = 0.0
    for c in closes_log:
        ctx = c.get("ctx") or {}
        try:
            pnl_session_usd += float(ctx.get("pnl_usd") or 0.0)
            pnl_session_R += float(ctx.get("pnl_R") or 0.0)
        except (TypeError, ValueError):
            continue

    # n_sl_consec : SL consecutifs depuis dernier TP (pattern Bot 3)
    # 28/05 v2 FIX RESERVE R1 : lire exit_cause_mechanical pour rester aligne
    # sur trigger DTC reel (exit_cause v2 reclasse sur sign(pnl_usd) fausserait
    # compteur cooldown UI vs _n_sl_consec interne bot). Fallback v1 JSONL.
    n_sl_consec = 0
    for c in reversed(closes_log):
        ctx = c.get("ctx") or {}
        cause = (
            ctx.get("exit_cause_mechanical")
            or c.get("exit_cause_mechanical")
            or ctx.get("exit_cause")
            or c.get("exit_cause")
        )
        if cause == "SL":
            n_sl_consec += 1
        elif cause == "TP":
            break

    # --- recent_entries (action IN ACHAT/VENTE, anti-chrono last 20) ---
    decision_sorted = sorted(
        decision_pyd_cme, key=lambda e: _ev_dt(e) or datetime.min.replace(tzinfo=timezone.utc)
    )
    entries_pyd = [e for e in decision_sorted if e.get("action") in ("ACHAT", "VENTE")]
    recent_entries = [
        {
            "ts": e.get("ts"),
            "symbol": e.get("symbol"),
            "action": e.get("action"),
            "side": e.get("side"),
            "entry_price": e.get("entry_price"),
            "sl_price": e.get("sl_price"),
            "tp_price": e.get("tp_price"),
            "sl_ticks": e.get("sl_ticks"),
            "tp_ticks": e.get("tp_ticks"),
            "score": e.get("score"),
            "tier": e.get("tier"),
            "signal_id": e.get("signal_id"),
        }
        for e in entries_pyd[-BOT4_RECENT_LIMIT:]
    ]
    # Reverse anti-chrono (plus recent en premier)
    recent_entries.reverse()

    # --- recent_signals_veto (action=ATTENDRE AND binding_gate, last 20 anti-chrono) ---
    veto_pyd = [
        e for e in decision_sorted
        if e.get("action") == "ATTENDRE" and e.get("binding_gate")
    ]
    recent_signals_veto = [
        {
            "ts": e.get("ts"),
            "symbol": e.get("symbol"),
            "binding_gate": e.get("binding_gate"),
            "veto_reason": e.get("veto_reason") or e.get("reason"),
            "score": e.get("score"),
            "tier": e.get("tier"),
            "signal_id": e.get("signal_id"),
        }
        for e in veto_pyd[-BOT4_RECENT_LIMIT:]
    ]
    recent_signals_veto.reverse()

    # --- paper_trader_alive : derniere event < 120s ---
    paper_trader_alive = False
    if last_heartbeat_ts:
        try:
            hb_dt = datetime.fromisoformat(str(last_heartbeat_ts).replace("Z", "+00:00"))
            if hb_dt.tzinfo is None:
                hb_dt = hb_dt.replace(tzinfo=timezone.utc)
            age_sec = (datetime.now(timezone.utc) - hb_dt).total_seconds()
            paper_trader_alive = age_sec < 120
        except (ValueError, TypeError):
            paper_trader_alive = False

    # --- Errors (last 10 from errors_*_bot4.jsonl) ---
    errors_recent = errors_logger[-10:] if errors_logger else []

    # --- closed_today[] (J12.7 fix : Card 5 frontend trades fermes) ---
    # Transform closes_log -> displayable format anti-chrono. Match open via
    # _match_open pour entry_price + side + level snapshot complet.
    closed_today_list: list[dict] = []
    for c in closes_log:
        sid = c.get("signal_id")
        ctx_c = c.get("ctx") or {}
        open_ev = _match_open(sid, c.get("ts"))
        ctx_o = (open_ev.get("ctx") or {}) if open_ev else {}
        closed_today_list.append({
            "ts_close": c.get("ts"),
            "ts_open": open_ev.get("ts") if open_ev else None,
            "signal_id": sid,
            "symbol": ctx_c.get("sym") or ctx_o.get("sym") or "?",
            "side": ctx_o.get("side") or ctx_c.get("side"),
            "level": ctx_o.get("level"),
            "entry_price": ctx_o.get("entry_price"),
            "exit_price": ctx_c.get("exit_price"),
            "sl_ticks": ctx_o.get("sl_ticks"),
            "exit_cause": ctx_c.get("exit_reason"),
            "pnl_R": ctx_c.get("pnl_R"),
            "pnl_usd": ctx_c.get("pnl_usd"),
            "pnl_ticks": ctx_c.get("pnl_ticks"),
            "duration_sec": ctx_c.get("duration_sec"),
            "duration_bars": ctx_c.get("duration_bars"),
        })
    # Tri anti-chrono (most recent first)
    closed_today_list.sort(
        key=lambda x: x.get("ts_close") or "", reverse=True,
    )

    return {
        "positions_active": positions_active,
        "stats_today": {
            "n_signals_seen": n_signals_seen,
            "n_passed": n_passed,
            "n_veto": n_veto,
            "n_trades_opened": n_trades_opened,
            "n_trades_closed": n_trades_closed,
            "pnl_session_usd": round(pnl_session_usd, 2),
            "pnl_session_R": round(pnl_session_R, 3),
            "n_sl_consec": n_sl_consec,
        },
        "setup_stats": {},                            # P0.3 Option A : OFF P7.1
        "setup_stats_info": "TBD P7.2 (setups structurels)",
        "recent_entries": recent_entries,
        "recent_signals_veto": recent_signals_veto,   # toujours array (P2.1 test #10)
        "closed_today": closed_today_list,            # J12.7 fix : Card 5 frontend
        "kill_switch_active": kill_switch_active,
        "cooldown_until": cooldown_until,
        "last_heartbeat_ts": last_heartbeat_ts,
        "bar_source": bar_source,
        "phase": phase,
        "dry_run": dry_run,
        "paper_trader_alive": paper_trader_alive,
        "day_str": day_str,
        "available": True,
        "errors": errors_recent,
    }


def compute_stats_period_bot4(days: int) -> dict:
    """Agregation Bot 4 sur N derniers jours via Logger V2 risk_*_bot4.jsonl.

    Args:
        days : 7 ou 30 typiquement.

    Returns:
        {n_trades, n_wins, wr_pct, pf, pnl_usd_total, pnl_R_total, days_covered}.
    """
    n_trades = 0
    n_wins = 0
    gains_R = 0.0
    losses_R = 0.0
    pnl_usd_total = 0.0
    pnl_R_total = 0.0

    cme_now_start = _cme_trading_day_start_utc()
    for offset in range(days):
        day = cme_now_start - timedelta(days=offset)
        day_str = day.strftime("%Y%m%d")
        risk_events = _read_logger_v2_jsonl_bot4("risk", day_str)
        for ev in risk_events:
            if ev.get("code") != "BOT4_RISK_TRADE_CLOSE":
                continue
            ctx = ev.get("ctx") or {}
            try:
                pnl_R = float(ctx.get("pnl_R") or 0.0)
                pnl_usd = float(ctx.get("pnl_usd") or 0.0)
            except (TypeError, ValueError):
                continue
            # Filtre corruption ghost trade (I1 fix : constantes top-level)
            if abs(pnl_usd) > BOT4_PNL_CORRUPTION_USD or abs(pnl_R) > BOT4_PNL_R_CORRUPTION:
                continue
            n_trades += 1
            pnl_R_total += pnl_R
            pnl_usd_total += pnl_usd
            if pnl_R > 0:
                n_wins += 1
                gains_R += pnl_R
            elif pnl_R < 0:
                losses_R += -pnl_R

    pf = round(gains_R / max(losses_R, 0.01), 2) if losses_R > 0 else None
    return {
        "n_trades": n_trades,
        "n_wins": n_wins,
        "wr_pct": round(100.0 * n_wins / max(n_trades, 1), 1) if n_trades > 0 else None,
        "pf": pf,
        "pnl_usd_total": round(pnl_usd_total, 2),
        "pnl_R_total": round(pnl_R_total, 3),
        "days_covered": days,
    }


def get_bot4_payload() -> dict:
    """Endpoint Bot 4 (NEW_BOT_2_MIA_TRADER) pour dashboard.

    Fix bug Jackson 27/05 PM "Bot 4 desactive" malgre Bot 4 LIVE :
    Le check `MIA_BOT4_ENABLED` etait pose cote service DASHBOARD, mais l'ENV
    n'est defini que sur le service MIA-Bot-4-Paper (nssm). Donc dashboard
    retournait toujours available=False. FIX : detecter "Bot 4 actif" via
    presence fichiers JSONL Bot 4 + heartbeat recent (pas ENV).

    Schema return : cf Section 3 PLAN_J12_DASHBOARD_V2_20260527.md.
    """
    # Detection presence Bot 4 via fichier events JSONL du jour (Logger V2 suffixe _bot4).
    # Si aucun fichier existe -> service jamais demarre -> available=False.
    # Sinon -> on procede au load complet et available depend du content.
    _today_utc = datetime.now(timezone.utc).strftime("%Y%m%d")
    _events_path = LOGS_ROOT / "events" / f"events_{_today_utc}_bot4.jsonl"
    if not _events_path.exists():
        return {
            "state_file": "bot4_logger_v2_telemetry",
            "state": None,
            "available": False,
            "msg": "Bot 4 service jamais demarre aujourd'hui (aucun events_*_bot4.jsonl)",
            "reason": "no_events_jsonl_today",
            "stats_7d": None,
            "stats_30d": None,
            "paper_trader_alive": False,
            "phase": None,
            "phase_source": None,
            "dry_run": None,
            "bar_source": None,
            "kill_switch_active": False,
            "cooldown_until": None,
            "positions_with_countdown": {},
            "setup_stats": {},
            "setup_stats_info": "TBD P7.2 (setups structurels)",
            "recent_entries": [],
            "recent_signals_veto": [],
            "stats_today": {},
            "errors": [],
            "prop_firm_metrics": {
                "distance_to_dll_usd": None,
                "trailing_dd_highwater_usd": None,
                "consistency_pct": None,
            },
            "state_age_sec": None,
        }

    today = _load_bot4_today_state()
    stats_7d = compute_stats_period_bot4(7)
    stats_30d = compute_stats_period_bot4(30)

    # state_age_sec : derive de last_heartbeat_ts (gestion timezone aware/naive)
    last_hb = today.get("last_heartbeat_ts")
    state_age_sec: Optional[int] = None
    if last_hb:
        try:
            dt = datetime.fromisoformat(str(last_hb).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            state_age_sec = int((datetime.now(timezone.utc) - dt).total_seconds())
        except (ValueError, TypeError):
            state_age_sec = None
    paper_trader_alive = state_age_sec is not None and state_age_sec < BOT4_ALIVE_THRESHOLD_SEC

    # Prop firm metrics (P7.1 placeholder - vrais calculs P7.2)
    # R1 fix review J12 Plan agent : aligner contract sur frontend (Card 4
    # `renderPaperBot4Section` dashboard.js:5853-5879). Le frontend calcule
    # dllRemaining = daily_loss_limit_usd - abs(min(pnl_today_usd, 0)) lui-meme.
    # I2 fix review J12 code-reviewer : `trailing_dd_highwater_usd` lazy compute
    # etait FAUX (cumul 7j net masque highwater intra-period). P7.2 = vrai
    # highwater jour-par-jour style Topstep "locked at starting balance".
    pnl_today_value = (today.get("stats_today") or {}).get("pnl_session_usd", 0.0)
    try:
        pnl_today_float = float(pnl_today_value or 0.0)
    except (TypeError, ValueError):
        pnl_today_float = 0.0
    prop_firm_metrics = {
        "daily_loss_limit_usd": BOT4_P71_DLL_HARDCODE_USD,  # P7.1 hardcode Topstep $50k
        "pnl_today_usd": pnl_today_float,                   # frontend calcule dllRemaining
        "trailing_dd_highwater_usd": None,                  # P7.2 : vrai highwater
        "trailing_dd_cushion_usd": None,                    # P7.2 : highwater - current_loss
        "consistency_rule": None,                           # P7.2 : besoin 7+ jours data
    }

    payload = {
        "state_file": "bot4_logger_v2_telemetry",
        "state": {
            "ts_utc": today.get("last_heartbeat_ts"),
            "mode": "PAPER_BOT4",
            "trade_account": os.environ.get("MIA_BOT4_TRADE_ACCOUNT", "Sim4"),
            "kill_switch_active": today.get("kill_switch_active"),
            "cooldown_until": today.get("cooldown_until"),
            "bar_source": {"global": today.get("bar_source") or "UNKNOWN"},
            "phase": today.get("phase"),
            "dry_run": today.get("dry_run"),
        },
        "positions_with_countdown": today.get("positions_active", {}),
        "setup_stats": today.get("setup_stats", {}),
        "setup_stats_info": today.get(
            "setup_stats_info", "TBD P7.2 (setups structurels)"
        ),
        "recent_entries": today.get("recent_entries", []),
        "recent_signals_veto": today.get("recent_signals_veto", []),
        "closed_today": today.get("closed_today", []),  # J12.7 fix : Card 5 frontend
        "stats_today": today.get("stats_today", {}),
        "stats_7d": stats_7d,
        "stats_30d": stats_30d,
        "errors": today.get("errors", []),
        "prop_firm_metrics": prop_firm_metrics,
        # P1.1 fix : phase publie par Bot 4 lui-meme (BOT4_BOOT_READY.ctx.phase)
        "phase": today.get("phase"),
        "phase_source": "bot4_self",
        "dry_run": today.get("dry_run"),
        "bar_source": today.get("bar_source"),
        "kill_switch_active": today.get("kill_switch_active"),
        "cooldown_until": today.get("cooldown_until"),
        "trading_window_utc": "00h-22h",
        "mode": "PAPER_BOT4",
        "trade_account": os.environ.get("MIA_BOT4_TRADE_ACCOUNT", "Sim4"),
        "phase_paper": True,
        "available": today.get("available", False),
        "paper_trader_alive": paper_trader_alive,
        "ts_utc": today.get("last_heartbeat_ts"),
        "day_str": today.get("day_str"),
        "has_paper_active": paper_trader_alive,
        "bot_label": "Bot 4 NEW_BOT_2_MIA_TRADER",
        "state_age_sec": state_age_sec,
    }

    # Pattern G : _clean_nan_inf defensif final
    return _clean_nan_inf(payload)

