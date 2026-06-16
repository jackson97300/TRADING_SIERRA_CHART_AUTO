"""FastAPI application du dashboard MIA V2."""
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from DASHBOARD.api.admin_routes import admin_router
from DASHBOARD.api.auth import auth_router, get_user_tier as auth_get_user_tier, get_tier_level
from DASHBOARD.api.briefing import router as briefing_router
from DASHBOARD.api.eco_calendar_routes import eco_calendar_router
from DASHBOARD.api.data_reader import (
    build_advisory,
    build_battle_navale,
    build_big_orders,
    build_bot_status,
    build_conseil_global,
    build_initial_balance,
    build_instrument_status,
    build_intermarket,
    build_levels_distances,
    build_manual_indicators,         # 04/05 — Phase 1 widgets trading manuel
    build_order_flow_advanced,       # 04/05 — Bonus widgets V4 (cluster/big/SMT/npoc)
    build_market_profile,
    build_options_levels,
    build_order_flow,
    build_price_banner,
    build_regime_context,
    build_session_open,
    build_signals_journal,
    build_trade_suggestion,
    build_vix_gamma,
    detect_active_setups,             # 04/05 — Phase 2 setups composites

    detect_double_pattern,
    detect_intraday_double,
    generate_market_narrative,
    get_latest_jsonl,
    read_bars,
    read_bot_status,
    read_cta_data,
    read_ib_bars,
    read_last_bar,
    read_menthorq_detail,
    read_mtf_bias,
    read_volume_profile,
)
from DASHBOARD.api.v4_reader import (    # 04/05 — branchement parquet V4 enriched
    read_last_v4_row,
    merge_dmp_v4,
)
from DASHBOARD.api.stabilizers import (
    _cached_call,
    _enrich_regime_with_mtf,
    _log_session_snapshot,
    _stabilize_favor,
    _stabilize_qui,
    detect_level_breaks,
)
from DASHBOARD.api.stripe_webhooks import stripe_router
from DASHBOARD.api.tier_filter import _filter_response_by_tier, _require_tier
from DASHBOARD.api.v1_engines import check_health

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")

# ── Health check auto-runner (Jackson directive 08/05) ──
# Run check global toutes les 10 min + Discord alert + history JSONL.
# Self-watchdog via DATA/HEARTBEAT/health_runner.json (cf admin_routes.py).
HEALTH_CHECK_INTERVAL_S = int(os.environ.get("MIA_HEALTH_CHECK_INTERVAL_S", "600"))
_health_runner_task = None


async def _health_check_loop():
    """Background task : run health check toutes HEALTH_CHECK_INTERVAL_S secondes."""
    import asyncio as _asyncio
    import time as _t
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    try:
        from BOT.health_checker import HealthChecker, append_history, maybe_alert_discord
    except ImportError as e:
        print(f"[HEALTH_LOOP] import fail: {e}", file=sys.stderr)
        return

    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    runner_hb = os.path.join(base, "DATA", "HEARTBEAT", "health_runner.json")
    os.makedirs(os.path.dirname(runner_hb), exist_ok=True)

    # Try logging_v2 emit
    try:
        from CORE.logging_v2 import get_logger
        _v2log_health = get_logger("dashboard_health_runner", process="dashboard")
    except ImportError:
        _v2log_health = None

    def _emit(code, **ctx):
        if _v2log_health is not None:
            try:
                _v2log_health.emit(code, **ctx)
            except Exception:
                pass

    n_iter = 0
    print(f"[HEALTH_LOOP] Started (interval {HEALTH_CHECK_INTERVAL_S}s)", flush=True)
    while True:
        try:
            n_iter += 1
            loop = _asyncio.get_running_loop()
            report = await loop.run_in_executor(None, HealthChecker().run_all)
            append_history(report, trigger="auto")
            alert_summary = maybe_alert_discord(report)

            # Log structured
            _emit("HEALTH_CHECK_RUN",
                  trigger="auto", score=report.get("score", "?"),
                  worst=report.get("worst_status", "?"))
            for c in report.get("checks", []):
                if c["status"] in ("WARN", "DOWN"):
                    _emit("HEALTH_CHECK_FAIL",
                          check_name=c["name"], status=c["status"],
                          details=c.get("details", "")[:200])
                elif c["status"] == "CRIT":
                    _emit("HEALTH_CHECK_CRIT",
                          check_name=c["name"],
                          details=c.get("details", "")[:200],
                          fix=c.get("fix_suggestion", "")[:200])

            # Self-watchdog heartbeat
            try:
                with open(runner_hb, "w", encoding="utf-8") as f:
                    json.dump({
                        "ts_utc": report.get("ts"),
                        "interval_s": HEALTH_CHECK_INTERVAL_S,
                        "n_iter": n_iter,
                        "score": report.get("score"),
                        "worst_status": report.get("worst_status"),
                        "alert_summary": alert_summary,
                    }, f)
            except OSError as e:
                print(f"[HEALTH_LOOP] heartbeat write fail: {e}", file=sys.stderr)

        except _asyncio.CancelledError:
            print("[HEALTH_LOOP] Cancelled")
            break
        except Exception as e:
            print(f"[HEALTH_LOOP] iter {n_iter} fail: {type(e).__name__}: {e}", file=sys.stderr)

        try:
            await _asyncio.sleep(HEALTH_CHECK_INTERVAL_S)
        except _asyncio.CancelledError:
            break


# Lifespan moderne FastAPI 0.110+ (remplace @app.on_event deprecated)
from contextlib import asynccontextmanager


@asynccontextmanager
async def _app_lifespan(app):
    """Lifespan handler : startup + shutdown background tasks."""
    global _health_runner_task
    import asyncio as _asyncio
    # Startup
    if os.environ.get("MIA_HEALTH_CHECK_DISABLED", "0") != "1":
        _health_runner_task = _asyncio.create_task(_health_check_loop())
        print("[HEALTH_LOOP] Background task scheduled at startup", flush=True)
    else:
        print("[HEALTH_LOOP] Disabled via MIA_HEALTH_CHECK_DISABLED=1", flush=True)
    yield
    # Shutdown
    if _health_runner_task is not None:
        _health_runner_task.cancel()
        try:
            await _health_runner_task
        except _asyncio.CancelledError:
            pass


app = FastAPI(
    title="MIA Dashboard V2", version="2.0.0",
    lifespan=_app_lifespan,
)

# ── Gzip compression (-70% bande passante) ──
app.add_middleware(GZipMiddleware, minimum_size=500)

ALLOWED_ORIGINS = os.environ.get("MIA_CORS_ORIGINS", "https://dashboard.mia-ia-system.com,https://mia-ia-system.com").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── Rate limiter simple (par IP, en memoire) ──
_rate_limits: dict = defaultdict(list)  # {ip: [timestamps]}
RATE_LIMIT_WINDOW = 60  # 1 minute
RATE_LIMIT_MAX = 10  # 10 requetes par minute sur les endpoints auth


_rate_limit_sweep_counter = 0


def _check_rate_limit(ip: str) -> bool:
    """Retourne True si la requete est autorisee, False si rate-limited."""
    global _rate_limit_sweep_counter
    now = time.time()
    _rate_limits[ip] = [t for t in _rate_limits[ip] if now - t < RATE_LIMIT_WINDOW]
    _rate_limit_sweep_counter += 1
    if _rate_limit_sweep_counter >= 100:
        _rate_limit_sweep_counter = 0
        dead_ips = [k for k, v in _rate_limits.items() if not v]
        for k in dead_ips:
            del _rate_limits[k]
    if len(_rate_limits[ip]) >= RATE_LIMIT_MAX:
        return False
    _rate_limits[ip].append(now)
    return True


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Rate limiting sur les endpoints auth
    path = request.url.path
    if path.startswith("/api/auth/") and request.method == "POST":
        ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "0.0.0.0")
        if not _check_rate_limit(ip):
            return JSONResponse({"error": "Trop de requetes. Reessayez dans 1 minute."}, status_code=429)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

    # CSP — Content Security Policy
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://accounts.google.com https://cdn.jsdelivr.net https://unpkg.com https://challenges.cloudflare.com https://static.cloudflareinsights.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://accounts.google.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "frame-src https://accounts.google.com https://challenges.cloudflare.com; "
        "connect-src 'self' https://challenges.cloudflare.com https://accounts.google.com"
    )

    # Cache-Control pour les assets statiques
    if path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=86400"

    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    if proto == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

app.include_router(auth_router)
app.include_router(briefing_router)
app.include_router(stripe_router)
app.include_router(admin_router)
app.include_router(eco_calendar_router)

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ═══════════════════════════════════════════════════════════════
# Pages statiques
# ═══════════════════════════════════════════════════════════════


def _serve_page(name: str):
    """Sert une page HTML statique avec no-cache pour eviter Cloudflare cache."""
    path = os.path.join(STATIC_DIR, name)
    if os.path.exists(path):
        return FileResponse(
            path,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
    return JSONResponse({"error": f"{name} non trouve"}, status_code=404)


@app.get("/")
async def root():
    return _serve_page("index.html")


@app.get("/login")
async def login_page():
    return _serve_page("login.html")


@app.get("/register")
async def register_page():
    return _serve_page("register.html")


@app.get("/briefing")
async def briefing_page():
    return _serve_page("briefing.html")


@app.get("/calendar")
async def calendar_page():
    return _serve_page("calendar.html")


@app.get("/lexique")
async def lexique_page():
    return _serve_page("lexique.html")


@app.get("/pricing")
async def pricing_page():
    return _serve_page("pricing.html")


@app.get("/cgu")
async def cgu_page():
    return _serve_page("cgu.html")


@app.get("/privacy")
async def privacy_page():
    return _serve_page("privacy.html")


@app.get("/welcome")
async def welcome_page():
    return _serve_page("welcome.html")


@app.get("/verify")
async def verify_page():
    return _serve_page("verify.html")


@app.get("/billing")
async def billing_page():
    return _serve_page("billing.html")


@app.get("/api/stripe/links")
async def stripe_links():
    """Retourne les Payment Links Stripe (public)."""
    from DASHBOARD.config import STRIPE_LINKS
    return STRIPE_LINKS


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "mia-dashboard-v2"}


def _is_cme_futures_open(now_utc=None) -> bool:
    """Retourne True si le marche CME futures (ES, NQ, MGC) est ouvert.

    Horaires CME futures :
    - Ouvert : dimanche 18:00 ET → vendredi 17:00 ET
    - Pause maintenance lun-jeu : 17:00-18:00 ET
    - Weekend ferme : vendredi 17:00 ET → dimanche 18:00 ET

    Utilise par /api/data_freshness pour distinguer staleness vs marche ferme.
    Fix 18/05 Jackson "DOWN 51h weekend = faux positif".
    """
    from datetime import datetime as _dt, timezone as _tz
    try:
        from zoneinfo import ZoneInfo
        et_tz = ZoneInfo("America/New_York")
    except ImportError:
        try:
            from pytz import timezone as _pytz_tz
            et_tz = _pytz_tz("America/New_York")
        except ImportError:
            return True
    if now_utc is None:
        now_utc = _dt.now(_tz.utc)
    now_et = now_utc.astimezone(et_tz)
    weekday = now_et.weekday()
    hour = now_et.hour
    if weekday == 4 and hour >= 17:
        return False
    if weekday == 5:
        return False
    if weekday == 6 and hour < 18:
        return False
    if weekday in (0, 1, 2, 3) and hour == 17:
        return False
    return True


@app.get("/api/data_freshness")
async def data_freshness():
    """Voyant fraicheur donnees temps reel (Jackson 01/05 "voyant DI DIT").

    Retourne pour chaque source critique l'age en secondes + status OK/WARN/CRIT.
    Utilise par le widget dashboard pour afficher un indicateur visuel.

    18/05 fix Jackson : si marche CME ferme (weekend/maintenance), worst_status
    devient MARKET_CLOSED (gris) au lieu de DOWN/CRIT (rouge alarmant faux positif).
    """
    import time as _t
    import glob as _g
    import json as _json
    from datetime import datetime as _dt, timezone as _tz

    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sources = []
    now_ts = _t.time()

    def _file_age_sec(path: str) -> tuple:
        """Returns (age_sec, exists)."""
        try:
            return (now_ts - os.stat(path).st_mtime, True)
        except (FileNotFoundError, OSError):
            return (None, False)

    def _glob_latest_age(pattern: str) -> tuple:
        """Returns (age_sec, latest_path or None)."""
        matches = _g.glob(pattern)
        if not matches:
            return (None, None)
        try:
            latest = max(matches, key=lambda p: os.stat(p).st_mtime)
            return (now_ts - os.stat(latest).st_mtime, latest)
        except OSError:
            return (None, None)

    def _classify(age: float, warn_s: float, crit_s: float) -> str:
        if age is None:
            return "ABSENT"
        if age > crit_s:
            return "CRIT"
        if age > warn_s:
            return "WARN"
        return "OK"

    # 1. JSONL live_enriched (source unique 3 bots multi-bot depuis 24/05/2026).
    # FIX 25/05/2026 Jackson "DOWN 51.5h banner" : ancien check lisait
    # LIVE_CACHE/{ES,NQ}_c_0_last.json (Bot 2 V6 LIVE cache mort post-transition
    # multi-bot 24/05) → mtime 51.5h → faux positif permanent. Aligner sur
    # check_pipeline_v4 (health_checker.py 25/05) qui lit le JSONL live frais.
    def _glob_age_only(pattern):
        a, _ = _glob_latest_age(pattern)
        return a
    age_es_live = _glob_age_only(os.path.join(base, "DATA", "live_enriched", "ES", "*_ES.jsonl"))
    age_nq_live = _glob_age_only(os.path.join(base, "DATA", "live_enriched", "NQ", "*_NQ.jsonl"))
    age_live = max(age_es_live or 0, age_nq_live or 0) if (age_es_live or age_nq_live) else None
    sources.append({
        "name": "JSONL live_enriched (3 bots source)",
        "age_sec": round(age_live, 1) if age_live else None,
        # 180s WARN, 600s CRIT (= 3min/10min vs plancher ~60s normal Databento+enricher)
        "status": _classify(age_live, 180, 600),
        "details": f"ES {round(age_es_live, 1) if age_es_live else 'n/a'}s · NQ {round(age_nq_live, 1) if age_nq_live else 'n/a'}s · plancher 60s normal",
    })

    # 2. DMP JSONL (Bot 1 Sierra source)
    # FIX 04/05 22:45 UTC : Sierra Chart utilise CME trading day (bascule 18:00 ET
    # = 22:00 UTC ete / 23:00 UTC hiver). UTC date naive lit le mauvais fichier
    # apres 22:00 UTC -> faux positif "DOWN 1.7h". Utilise meme logique que Bot 1.
    try:
        from CORE.constants import get_cme_trading_day as _get_cme_day
        today = _get_cme_day()
    except ImportError:
        today = _dt.now(_tz.utc).strftime("%Y%m%d")
    age_es_dmp, _ = _file_age_sec(os.path.join(base, "DATA", "ES", f"{today}_ES.jsonl"))
    age_nq_dmp, _ = _file_age_sec(os.path.join(base, "DATA", "NQ", f"{today}_NQ.jsonl"))
    age_dmp = max(age_es_dmp or 0, age_nq_dmp or 0) if (age_es_dmp or age_nq_dmp) else None
    sources.append({
        "name": "DMP JSONL (Sierra Chart)",
        "age_sec": round(age_dmp, 1) if age_dmp else None,
        "status": _classify(age_dmp, 90, 300),
        "details": f"ES {round(age_es_dmp, 1) if age_es_dmp else 'n/a'}s · NQ {round(age_nq_dmp, 1) if age_nq_dmp else 'n/a'}s",
    })

    # 3. Pipeline parquet v4_enriched (Bot 3 source structurelle)
    # 11/05 FIX CRITIQUE Jackson : mesure mtime fichier = TROMPEUR (pipeline reecrit
    # le parquet toutes les 5min meme quand last bar interne stuck a 13:25 UTC).
    # Bot 3 muet 1h40 sans aucune alerte dashboard. Switch a lecture last ts_event
    # interne du parquet = age REEL des bars utilisees par Bot 3.
    # Seuils alignes avec Bot 3 (DATA_CRIT_THR_SEC=2700s).
    # Retirer is_historical=True flag : Bot 3 prod utilise cette source.
    def _parquet_last_ts_age(path: str) -> tuple:
        """Age de la derniere bar (ts_event max) dans le parquet vs now.
        Returns (age_sec, last_ts_iso) ou (None, None).
        """
        try:
            import pyarrow.parquet as _pq
            pf = _pq.ParquetFile(path)
            tbl = pf.read(columns=['ts_event'])
            if tbl.num_rows == 0:
                return (None, None)
            df_ts = tbl.to_pandas()
            last_ts = df_ts['ts_event'].max()
            # tz-aware handling
            if hasattr(last_ts, 'tz_localize') and last_ts.tzinfo is None:
                last_ts = last_ts.tz_localize('UTC')
            if hasattr(last_ts, 'to_pydatetime'):
                last_ts = last_ts.to_pydatetime()
            age = (_dt.now(_tz.utc) - last_ts).total_seconds()
            return (age, last_ts.isoformat())
        except (OSError, ImportError, KeyError, ValueError):
            return (None, None)

    # Glob pour trouver le parquet du mois courant
    es_pattern = os.path.join(base, "DATA", "datasets", "v4_enriched", "symbol=ES.c.0", "year=*", "month=*", "data.parquet")
    _, es_path = _glob_latest_age(es_pattern)
    nq_pattern = os.path.join(base, "DATA", "datasets", "v4_enriched", "symbol=NQ.c.0", "year=*", "month=*", "data.parquet")
    _, nq_path = _glob_latest_age(nq_pattern)
    pipe_age_es, last_ts_es = (_parquet_last_ts_age(es_path) if es_path else (None, None))
    pipe_age_nq, last_ts_nq = (_parquet_last_ts_age(nq_path) if nq_path else (None, None))
    # Age MAX (le pire des 2 symboles) pour worst_status
    pipe_age = max(pipe_age_es or 0, pipe_age_nq or 0) if (pipe_age_es or pipe_age_nq) else None
    sources.append({
        "name": "Pipeline parquet v4 (backtest historique)",
        "age_sec": round(pipe_age, 1) if pipe_age else None,
        # 26/05/2026 fix Jackson "voyant STALE braque sur mauvais fichier" :
        # is_historical=True car apres transition multi-bot 24/05 (Bot 1 v3 +
        # Bot 2 BN V4 + Bot 3 v4), AUCUN bot en prod ne consomme ce parquet.
        # Tous lisent JSONL live_enriched (cf bot3_v3/v4/bn_v4_paper.py).
        # Le parquet v4 est utilise UNIQUEMENT pour backtests/recherche.
        # Le seuil reste pour info dans le tooltip mais ne pollue plus le
        # voyant LIVE principal (qui doit refleter la source consommee).
        "status": _classify(pipe_age, 1500, 2700),
        "details": (
            f"ES last bar {last_ts_es[11:16] if last_ts_es else 'n/a'} ({round((pipe_age_es or 0)/60,1)} min) · "
            f"NQ last bar {last_ts_nq[11:16] if last_ts_nq else 'n/a'} ({round((pipe_age_nq or 0)/60,1)} min) · "
            f"plancher normal ~18 min · non-consomme par bots live"
        ),
        # 26/05 fix : is_historical=True (les bots prod multi-bot lisent JSONL live_enriched).
        # 11/05 commentaire obsolete : "Bot 3 prod utilise cette source live" valait pour Bot 3 MP V6
        # (deactivated 24/05). Bot 3 v4 Data-driven actuel lit JSONL live_enriched, pas parquet.
        "is_historical": True,
    })

    # 4. V2CLEAN brain heartbeat — SUPPRIME 25/05/2026 (post-transition multi-bot).
    # V2CLEAN tournait en dry-run depuis 24/05 et ne logge plus de heartbeat.
    # Le service Windows est gardée (Phase 1 logger) mais le fichier
    # V2CLEAN/logs/heartbeat.txt n'est plus update → faux positif "DOWN 51.5h".
    # Si reactivation V2CLEAN futur, re-ajouter ce bloc.

    # Worst status pour le voyant principal — exclut sources historiques
    # (cycle 5min + delay 30min normal pollue indicateur live)
    priority = {"OK": 0, "WARN": 1, "CRIT": 2, "ABSENT": 3}
    live_sources = [s for s in sources if not s.get("is_historical", False)]
    worst = max(live_sources, key=lambda s: priority.get(s["status"], 0)) if live_sources else {"status": "OK"}

    # 18/05 fix Jackson "DOWN 51h weekend" : si marche CME ferme,
    # remplacer worst_status par MARKET_CLOSED. Les sources Databento Live
    # + Pipeline parquet v4 sont staleness NORMALE pendant weekend/maintenance.
    # On garde le status original par source pour le tooltip (audit detail),
    # mais worst_status pousse MARKET_CLOSED pour eviter le faux positif visuel.
    market_open = _is_cme_futures_open()
    worst_status_final = worst["status"]
    if not market_open and worst["status"] in ("CRIT", "WARN"):
        worst_status_final = "MARKET_CLOSED"

    return {
        "sources": sources,
        "worst_status": worst_status_final,
        "worst_status_raw": worst["status"],  # status sans override market_closed
        "market_open": market_open,
        "ts": _dt.now(_tz.utc).isoformat(),
    }


@app.get("/api/bots/health")
async def bots_health():
    """Voyant sante des 3 bots — refactor 25/05/2026 Jackson "BOTS 2/3 bug".

    AVANT (BOT_HEARTBEAT generique) : drift desynchronise post-transition multi-bot
    (24/05). Le BOTS hardcode du endpoint divergeait de BOT_DEFINITIONS canonique
    dans BOT/health_checker.py (codes BOT3_V3_HEARTBEAT / BN_V4_HEARTBEAT /
    BOT3_V4_HEARTBEAT). Resultat : Bot 1+3 jamais OK -> widget "BOTS 2/3".

    APRES : consomme HealthChecker.run_all() (single source of truth) + agrege
    par bot_key (worst check du bot definit son status). SKIP normalise en OK
    (= pas une alerte user).
    """
    import asyncio as _asyncio
    from datetime import datetime as _dt, timezone as _tz
    try:
        # Import HealthChecker (single source de verite)
        _hc_path = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        if _hc_path not in sys.path:
            sys.path.insert(0, _hc_path)
        from BOT.health_checker import HealthChecker, BOT_DEFINITIONS
    except ImportError as e:
        return {
            "bots": [], "worst_status": "OK", "error": f"import HealthChecker: {e}",
            "ts": _dt.now(_tz.utc).isoformat(),
        }

    loop = _asyncio.get_event_loop()
    report = await loop.run_in_executor(None, HealthChecker().run_all)

    # Agrege par bot_key (worst check par bot = son status)
    priority = {"OK": 0, "SKIP": 0, "WARN": 1, "CRIT": 2, "DOWN": 3}
    by_key = {}
    for c in report.get("checks", []):
        bk = c.get("bot_key")
        if not bk:
            continue  # checks system-wide (Pipeline data live, Disk, etc.)
        prev = by_key.get(bk)
        if prev is None or priority.get(c["status"], 0) > priority.get(prev["status"], 0):
            by_key[bk] = c

    bots_status = []
    for bot_def in BOT_DEFINITIONS:
        bk = bot_def["key"]
        worst_check = by_key.get(bk)
        if not worst_check:
            bots_status.append({
                "name": bot_def["name"], "key": bk,
                "status": "OK", "reason": "Aucun check non-OK",
                "last_bar_age_sec": None, "hb_age_sec": None,
            })
            continue
        # SKIP traite comme OK (= non-bloquant, ex: cross-check fraicheur sans
        # last_bar_age field dans le HEARTBEAT modeles bot3_v3/v4/bnv4).
        st = worst_check["status"] if worst_check["status"] != "SKIP" else "OK"
        bots_status.append({
            "name": bot_def["name"], "key": bk,
            "status": st,
            "reason": worst_check.get("details", ""),
            "last_bar_age_sec": None,  # non-critique widget (cf check pipeline_v4 live)
            "hb_age_sec": None,
        })

    if bots_status:
        worst = max(bots_status, key=lambda s: priority.get(s["status"], 0))
    else:
        worst = {"status": "OK"}
    return {
        "bots": bots_status,
        "worst_status": worst["status"],
        "ts": _dt.now(_tz.utc).isoformat(),
    }


@app.get("/_disabled_bots_health_legacy")
async def bots_health_legacy():
    """LEGACY endpoint preserve mais desactive (cf bots_health refactor 25/05)."""
    import time as _t
    import glob as _g
    import json as _json
    from datetime import datetime as _dt, timezone as _tz

    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    logs_dir = os.path.join(base, "LOGS", "events")
    now_ts = _t.time()

    # Bot definitions : path glob events + seuils
    BOTS = [
        {
            "name": "Bot 1 (DMP Sierra Sim2)",
            "key": "bot1",
            "glob": os.path.join(logs_dir, "events_*_paper.jsonl"),
            # FIX 08/05 (faux positif WARN) : 90s trop strict pour bars 1m DMP cycle naturel
            "warn_age_s": 180, "crit_age_s": 480,
        },
        # FIX 23/05/2026 Jackson : Bot 2 health check route conditionnelle.
        # Si MIA_BN_V4_ENABLED=1 -> heartbeat BN V4 dans events_*_paper_v2.jsonl
        # avec filtre prefix code BN_V4_HEARTBEAT (BN V4 wire dans paper_v2 process).
        # Sinon -> legacy events_*_paper_v6.jsonl (Brain V6).
        (
            {
                "name": "Bot 2 BN V4 (Databento Sim2)",
                "key": "bot2_bnv4",
                "glob": os.path.join(logs_dir, "events_*_paper_v2.jsonl"),
                "code_prefix": "BN_V4_HEARTBEAT",    # filtre exclusif vs BOT3
                "warn_age_s": 900, "crit_age_s": 1800,
            }
            if os.environ.get("MIA_BN_V4_ENABLED", "0") == "1"
            else {
                "name": "Bot 2 V6 (Databento Sim2)",
                "key": "bot2_v6",
                "glob": os.path.join(logs_dir, "events_*_paper_v6.jsonl"),
                "warn_age_s": 600, "crit_age_s": 1800,
            }
        ),
        {
            "name": "Bot 3 MP (Databento Sim1)",
            "key": "bot3",
            "glob": os.path.join(logs_dir, "events_*_paper_v2.jsonl"),
            "warn_age_s": 1500, "crit_age_s": 2700,
        },
    ]

    def _last_heartbeat(path_glob: str) -> dict:
        """Cherche le dernier BOT_HEARTBEAT dans le file le plus recent.

        Returns {ts_utc, last_bar_age, hb_age_sec} ou {} si rien.
        """
        files = sorted(_g.glob(path_glob), reverse=True)
        if not files:
            return {}
        latest_file = files[0]
        try:
            # tail 200 lines pour eviter OOM sur gros files (events accum sur 24h)
            with open(latest_file, "r", encoding="utf-8") as f:
                lines = f.readlines()[-200:]
            for line in reversed(lines):
                line = line.strip()
                if "BOT_HEARTBEAT" not in line:
                    continue
                try:
                    j = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                if j.get("code") != "BOT_HEARTBEAT":
                    continue
                ts_str = j.get("ts", "")
                ctx = j.get("ctx", {})
                last_bar_age = ctx.get("last_bar_age", None)
                try:
                    hb_ts = _dt.fromisoformat(ts_str.replace("Z", "+00:00"))
                    hb_age = (_dt.now(_tz.utc) - hb_ts).total_seconds()
                except (ValueError, TypeError):
                    hb_age = None
                return {
                    "ts_utc": ts_str,
                    "last_bar_age": last_bar_age,
                    "hb_age_sec": hb_age,
                }
        except OSError:
            pass
        return {}

    bots_status = []
    priority = {"OK": 0, "WARN": 1, "CRIT": 2, "DOWN": 3}
    for bot in BOTS:
        hb = _last_heartbeat(bot["glob"])
        if not hb:
            bots_status.append({
                "name": bot["name"], "key": bot["key"],
                "status": "DOWN", "reason": "Aucun heartbeat trouve",
                "last_bar_age_sec": None, "hb_age_sec": None,
            })
            continue
        hb_age = hb.get("hb_age_sec")
        last_bar_age = hb.get("last_bar_age")
        # Heartbeat lui-meme pas frais (process mort / freeze)
        if hb_age is not None and hb_age > 300:
            status = "DOWN"
            reason = f"Heartbeat dernier il y a {int(hb_age)}s (>5min)"
        elif last_bar_age is None:
            status = "WARN"
            reason = "Heartbeat present mais pas de last_bar_age"
        elif last_bar_age >= 99000:
            # Sentinel data manquante (cf bug 08/05 Bot 2 V6 banner schema)
            status = "CRIT"
            reason = f"Sentinel data manquante (last_bar_age={int(last_bar_age)})"
        elif last_bar_age > bot["crit_age_s"]:
            status = "CRIT"
            reason = f"Last bar age {int(last_bar_age)}s > seuil {bot['crit_age_s']}s"
        elif last_bar_age > bot["warn_age_s"]:
            status = "WARN"
            reason = f"Last bar age {int(last_bar_age)}s > seuil {bot['warn_age_s']}s"
        else:
            status = "OK"
            reason = f"Bar fresh ({int(last_bar_age)}s)"
        bots_status.append({
            "name": bot["name"], "key": bot["key"],
            "status": status, "reason": reason,
            "last_bar_age_sec": last_bar_age,
            "hb_age_sec": round(hb_age, 1) if hb_age else None,
            "hb_ts_utc": hb.get("ts_utc"),
        })

    worst = max(bots_status, key=lambda s: priority.get(s["status"], 0))
    return {
        "bots": bots_status,
        "worst_status": worst["status"],
        "ts": _dt.now(_tz.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# Data endpoints
# ═══════════════════════════════════════════════════════════════


@app.get("/api/bars/{symbol}")
async def bars(request: Request, symbol: str, n: int = 200, tf: int = 1):
    """Renvoie les N dernieres barres OHLC + niveaux.

    Filtrage tier :
    - FREE : bars OHLC seuls (zero niveaux)
    - STARTER : bars + niveaux essentiels (VWAP, VPOC, VAH, VAL)
    - PRO/OWNER : tout (bars + 30+ niveaux)

    tf: timeframe en minutes (1, 5, 15, 60). Defaut 1min.
    """
    sym = symbol.upper()
    if sym not in ("ES", "NQ"):
        return JSONResponse({"error": "Symbol invalide"}, status_code=400)
    result = read_bars(sym, min(n * max(tf, 1), 5000))
    if tf > 1 and result.get("bars"):
        result["bars"] = _aggregate_bars(result["bars"], tf)

    # Filtrage tier-based des niveaux
    auth = request.headers.get("Authorization", "")
    tier = auth_get_user_tier(auth)
    level = get_tier_level(tier)

    if level == 0:
        result["levels"] = []
        result["level_groups"] = {}
        result["tier_locked_levels"] = True
    elif level == 1:
        essential_labels = {
            "VWAP", "VWAP D", "VPOC", "VAH", "VAL",
            "Swing H", "Swing L", "SwingH", "SwingL",
        }
        levels = result.get("levels") or []
        result["levels"] = [lv for lv in levels if (lv.get("label") or "") in essential_labels]
        result["tier_limited_levels"] = True

    return result


def _aggregate_bars(bars: list, tf_minutes: int) -> list:
    """Agrege les barres 1min en barres de tf_minutes."""
    if not bars or tf_minutes <= 1:
        return bars
    interval = tf_minutes * 60
    aggregated = []
    current = None
    for b in bars:
        bucket = (b["time"] // interval) * interval
        if current is None or current["time"] != bucket:
            if current:
                aggregated.append(current)
            current = {
                "time": bucket,
                "open": b["open"],
                "high": b["high"],
                "low": b["low"],
                "close": b["close"],
                "volume": b.get("volume", 0),
                "delta": b.get("delta", 0),
                "buy_vol": b.get("buy_vol", 0),
                "sell_vol": b.get("sell_vol", 0),
            }
        else:
            current["high"] = max(current["high"], b["high"])
            current["low"] = min(current["low"], b["low"])
            current["close"] = b["close"]
            current["volume"] = current.get("volume", 0) + b.get("volume", 0)
            current["delta"] = current.get("delta", 0) + b.get("delta", 0)
            current["buy_vol"] = current.get("buy_vol", 0) + b.get("buy_vol", 0)
            current["sell_vol"] = current.get("sell_vol", 0) + b.get("sell_vol", 0)
    if current:
        aggregated.append(current)
    return aggregated


@app.get("/api/ib-bars/{symbol}")
async def ib_bars(request: Request, symbol: str):
    """Renvoie les barres 1min de l'IB — STARTER+ (level >= 1)."""
    _require_tier(request, 1)
    sym = symbol.upper()
    if sym not in ("ES", "NQ"):
        return JSONResponse({"error": "Symbol invalide"}, status_code=400)
    return read_ib_bars(sym)


@app.get("/api/cta")
async def cta(request: Request):
    """Renvoie les donnees CTA — PRO+ (level >= 2)."""
    _require_tier(request, 2)
    return read_cta_data()


@app.get("/api/menthorq")
async def menthorq(request: Request):
    """Renvoie les donnees MenthorQ — PRO+ (level >= 2)."""
    _require_tier(request, 2)
    return read_menthorq_detail()


@app.get("/api/mtf/{symbol}")
async def mtf_bias(request: Request, symbol: str):
    """Renvoie le bias multi-timeframe — STARTER+ (level >= 1)."""
    _require_tier(request, 1)
    sym = symbol.upper()
    if sym not in ("ES", "NQ"):
        return JSONResponse({"error": "Symbol invalide"}, status_code=400)
    return read_mtf_bias(sym)


@app.get("/api/profile/{symbol}")
async def profile(request: Request, symbol: str):
    """Renvoie le volume profile — STARTER+ (level >= 1)."""
    _require_tier(request, 1)
    sym = symbol.upper()
    if sym not in ("ES", "NQ"):
        return JSONResponse({"error": "Symbol invalide"}, status_code=400)
    return read_volume_profile(sym)


@app.get("/api/paper_trades")
async def paper_trades_endpoint(request: Request):
    """Paper trades state + stats (v2 22/04).

    Lit `DATA/PAPER_TRADES/state.json` ecrit par `CORE/mia_paper_trader.py`.
    Retourne : state live (open/closed/stats today) + stats_7d + stats_30d.
    """
    from DASHBOARD.api.paper_tracker import get_paper_trades_payload
    _require_tier(request, 1)  # STARTER+
    return get_paper_trades_payload()


@app.get("/api/paper_trades_dual")
async def paper_trades_dual_endpoint(request: Request):
    """Paper trades DUAL bots (BOT 1 DMP Sim2 reactive 07/06 + BOT 2 BN V4 ARCHIVE) — A/B testing 28/04.

    BOT 1 DMP : `state.json` (mia_paper_trader, source DMP JSONL, dashboard rules)
    BOT 2 DB  : `databento_paper_state.json` (databento_paper_trader, Databento + 420 features)

    Retourne :
      {
        "bot1_dmp": {state, stats_7d, stats_30d, has_paper_active, paper_trader_alive, ...},
        "bot2_db":  {state, stats_7d, stats_30d, has_paper_active, paper_trader_alive, ...}
      }
    """
    from DASHBOARD.api.paper_tracker import get_dual_bots_payload
    _require_tier(request, 1)
    return get_dual_bots_payload()


@app.get("/api/paper_v2_state")
async def paper_v2_state_endpoint(request: Request):
    """BOT 2 V2 (SetupEngine 11 setups, Sim2, deploye 02/05/2026).

    Lit `DATA/PAPER_TRADES/databento_paper_v2_state.json` ecrit par
    `CORE/databento_paper_trader_v2.py`.

    Retourne :
      {
        "available": True/False,
        "state": <state.json brut>,
        "positions_with_countdown": {NQ: {seconds_until_timeout, session_label_entry, ...}, ES: ...},
        "setup_stats": {SETUP_NAME: {n_trades, wr_pct, pf, pnl_total_usd, ...}},
        "trading_window_utc": "2h-21h",
        "phase_1_free_run": True,
        "mode": "PAPER_TRADE_V2_FREE_RUN",
      }

    Frontend doit afficher :
      - Countdown timeout par position en cours (positions_with_countdown[sym].seconds_until_timeout)
      - Session entry par trade (positions_with_countdown[sym].session_label_entry)
      - Stats par setup (setup_stats : tri par pnl_total_usd desc)
      - Mode FREE_RUN indicator
    """
    from DASHBOARD.api.paper_tracker import get_bot2_v2_payload
    _require_tier(request, 1)
    return get_bot2_v2_payload()


@app.get("/api/paper_v3_state")
async def paper_v3_state_endpoint(request: Request):
    """BOT 3 MP (Market Profile, 13 niveaux Tier 1/2/3, Sim1, deploye 03/05/2026).

    Lit `DATA/PAPER_TRADES/databento_paper_v3_state.json` ecrit par le
    Bot 3 MP integre in-process dans `CORE/databento_paper_trader_v2.py`.

    Retourne :
      {
        "available": True/False,
        "state": <state.json brut>,
        "positions_with_countdown": {NQ: {level, side, action, confidence, sl_ticks, ...}, ES: ...},
        "level_stats": {LEVEL_NAME: {n_contacts, n_go, win_rate, pf, baseline_rej, baseline_pf, ...}},
        "recent_decisions": [{ts, sym, level, decision, reason}, ...20 dernieres],
        "n_contacts_today": {NQ: int, ES: int},
        "n_go_today": ..., "n_skip_today": ..., "n_veto_today": ...,
        "phase": "OBSERVE_ONLY" | "PAPER_TIER1" | "FULL",
        "trade_rejections": bool, "trade_breakouts": bool,
        "tier2_enabled": bool, "tier3_enabled": bool,
        "trading_window_utc": "2h-21h",
        "trade_account": "Sim1",
        "mode": "OBSERVE_ONLY" | "PAPER_TRADE",
      }

    Frontend doit afficher :
      - Phase badge (OBSERVE_ONLY orange / PAPER vert)
      - Positions NQ + ES avec niveau contacte + confidence
      - Level stats par niveau (rejection live vs baseline doc)
      - Recent decisions feed live (Phase 1 critique pour audit GO/SKIP)
    """
    from DASHBOARD.api.paper_tracker import get_bot3_payload
    _require_tier(request, 1)
    return get_bot3_payload()


@app.get("/api/paper_bot3_v3_state")
async def paper_bot3_v3_state_endpoint(request: Request):
    """BOT 3 v3 Continuation NQ Sim1 (paper deploy 24/05/2026).

    Backtest baseline 130j MenthorQ : n=1611 WR 43% PF 1.045 DSR 0.21.
    Paradigme : state machine 4 etats (Wyckoff phase E + retest + confirmation).

    Lit `LOGS/bot3_v3/bot3_v3_v1_YYYYMMDD.jsonl` (Bot3V3Logger).

    Active si ENV `MIA_BOT3_V3_ENABLED=1`. Sinon `available=False` (no crash).

    Retourne :
      {
        "available": True/False,
        "state": {ts_utc, mode, trade_account, kill_switch_active, bar_source},
        "positions_with_countdown": {NQ: {level, side, entry, sl, tp, sl_ticks, ...}},
        "setup_stats": {LEVEL_NAME: {n_trades, n_wins, wr_pct, pf, pnl_R_total, pnl_usd_total}},
        "recent_entries": [{ts, level, side, entry, sl, tp, executed, veto_reason}, ...20 dernieres],
        "stats_today": {n_entries, n_trades_opened, n_trades_closed, pnl_session_usd,
                        pnl_session_R, n_sl_consec, n_touches, n_state_transitions},
        "stats_7d": {n_trades, wr_pct, pf, pnl_usd_total, pnl_R_total, days_covered: 7},
        "stats_30d": idem 30 jours,
        "trading_window_utc": "00h-22h",
        "mode": "PAPER_BOT3_V3",
        "trade_account": "Sim1",
        "paper_trader_alive": True/False (heartbeat < 120s),
        "bot_label": "Bot 3 v3 Continuation",
      }

    Frontend doit afficher :
      - Position NQ avec level + side + entry/sl/tp + sl_ticks + countdown timeout (360 bars)
      - Setup stats par level (priorite tri par n_trades desc)
      - Recent entries (incluant veto_reason si executed=False : news / position / kill_switch / dry_run / cross_bot_same_side)
      - Stats today : n_state_transitions (criticite : si 0 alors que touches > 0 = bug long_up_bar)
    """
    from DASHBOARD.api.paper_tracker import get_bot3_v3_payload
    _require_tier(request, 1)
    return get_bot3_v3_payload()


@app.get("/api/paper_bot3_v4_state")
async def paper_bot3_v4_state_endpoint(request: Request):
    """BOT 3 v4 Data-driven NQ Sim3 (paper deploy 24/05/2026).

    Backtest baseline 130j MenthorQ : n=1110 WR 30% PF 1.033 DSR 0.13.
    Paradigme : 6 triggers asymetriques empiriques + TP cur_VPOC magnet.

    Lit `LOGS/bot3_v4/bot3_v4_v1_YYYYMMDD.jsonl` (Bot3V4Logger).

    Active si ENV `MIA_BOT3_V4_ENABLED=1`. Sinon `available=False`.

    Differences vs v3 :
      - setup_stats clef = LEVEL_TPMODE (ex: SWING_LOW_VPOC, CUR_VAH_R15)
      - tp_mode_distribution : {vpoc_magnet, r15_fallback} (edge backtest)
      - Pas de state_transitions (engine = touch direct, pas state machine)

    Retourne meme structure que v3 + tp_mode_distribution.

    Frontend doit afficher :
      - Position NQ avec level + tp_mode (VPOC / R15) + vpoc_value
      - TP mode distribution (% VPOC magnet vs R15 fallback) : alerte si >80% R15 (= bug cur_vpoc)
      - Setup stats par level_tpmode
    """
    from DASHBOARD.api.paper_tracker import get_bot3_v4_payload
    _require_tier(request, 1)
    return get_bot3_v4_payload()


@app.get("/api/paper_bot4_state")
async def paper_bot4_state_endpoint(request: Request):
    """BOT 4 MIA Trader Sim4 (paper deploy 27/05/2026, Phase 7.1 SAFE COLLECT).

    Architecture J10 : M1 Reader -> M2 Decide -> M4 Risk -> M3 SLTP -> M5 Execution -> M3.5 Monitor.
    100% rules-based (pas de ML). 1 micro safe debug runtime puis 3 micros aggressive.

    Lit 2 systemes paralleles (J11) :
      1. Telemetry M6 Pydantic : LOGS/{reader|decision|risk|sltp|execution}/{YYYYMMDD}_{cat}.jsonl
         (snapshots, EXCLUSIF Bot 4 car Bot 1/2/3 n'utilisent pas M6)
      2. Logger V2 codes : LOGS/{events|decisions|execution|risk|errors}/{cat}_{YYYYMMDD}_bot4.jsonl
         (50 codes BOT4_*, filtre process via filename suffixe)

    Active si ENV `MIA_BOT4_ENABLED=1`. Sinon `available=False`.

    Innovation vs bot3_v4 :
      - `recent_signals_veto[]` : last 20 DecisionEvent action=ATTENDRE + binding_gate
        (CRITIQUE P7.1 SAFE pour comprendre pourquoi Bot 4 ne trade PAS)
      - `stats_today.n_signals_seen / n_passed / n_veto` (funnel decision)
      - `phase` lu depuis BOT4_BOOT_READY.ctx.phase (PAS depuis ENV dashboard)
      - `prop_firm_metrics` : distance_to_dll, trailing_dd_highwater, consistency_pct

    Frontend doit afficher :
      - 8 cards (header / stats today / positions / prop firm risk / closes /
        VETO recents / setup stats placeholder P7.1 / breakdowns multidim)
      - Phase badge (P7.1_SAFE_COLLECT vert / P7.2_AGGRESSIVE orange)
      - Dry_run badge jaune si dry_run=True (T3 fix review)
      - Bar source ROUGE si != LIVE_ENRICHED_60s (R8 anti incident Bot 2 V6 17/05)
    """
    from DASHBOARD.api.paper_tracker import get_bot4_payload
    _require_tier(request, 1)
    return get_bot4_payload()


# ═══════════════════════════════════════════════════════════════
# Endpoint principal — /api/dashboard
# ═══════════════════════════════════════════════════════════════


@app.get("/api/dashboard")
async def dashboard(request: Request):
    """Endpoint principal V2 — structure par instrument.

    Tier free  : banner + regime + advisory + health
    Tier premium : TOUT (15 panels x 2 instruments)
    """
    authorization = request.headers.get("Authorization", "")
    tier = auth_get_user_tier(authorization)
    now = datetime.now(timezone.utc).isoformat()

    bot_data = read_bot_status()
    bar_es = read_last_bar("ES")
    bar_nq = read_last_bar("NQ")
    # 11/05 J2b — MGC integration foundation (foundation read, panels MGC J5).
    # OBSERVE_ONLY : bar lue + slot expose mais aucun trade declenche dessus.
    bar_mgc = read_last_bar("MGC")

    # Timestamp derniere barre
    last_bar_ts = _format_ts(bar_es.get("ts") or bar_nq.get("ts") or bar_mgc.get("ts"))

    # Panels communs
    # 11/05 J2b MGC : passer bar_mgc pour ajout slot banner mgc (retro-compat None).
    banner = build_price_banner(bar_es, bar_nq, bar_mgc=bar_mgc)
    regime_es = build_regime_context(bar_es)
    regime_nq = build_regime_context(bar_nq)
    session_es = build_session_open(bar_es)

    # MTF — cache 10s (lit tout le JSONL)
    mtf_es = _cached_call("mtf_es", read_mtf_bias, "ES", ttl=10, file_path=get_latest_jsonl("ES"))
    mtf_nq = _cached_call("mtf_nq", read_mtf_bias, "NQ", ttl=10, file_path=get_latest_jsonl("NQ"))
    _enrich_regime_with_mtf(regime_es, mtf_es)
    _enrich_regime_with_mtf(regime_nq, mtf_nq)

    advisory = build_advisory(regime_es, session_es)

    response = {
        "timestamp": now,
        "tier": tier,
        "last_bar_time": last_bar_ts,
        "bot_status": build_bot_status(bot_data),
        "banner": banner,
        "health": check_health(bot_data, bar_es),
        "advisory": advisory,
    }

    # ─── Merge DMP + V4 enriched UNE fois (04/05) ────────────────
    # V4 prioritaire pour features qu'il calcule (456 cols vs 268 DMP).
    # Fallback DMP transparent si V4 absent. Cache 5s gere par v4_reader.
    # R8 fix : skip V4 read pour tier=free (CPU/IO gaspille, panels filtres
    # apres par _filter_response_by_tier de toute facon).
    # 11/05 J2b MGC : meme pattern merge DMP+V4 que ES/NQ (Jackson directive
    # "on doit recevoir comme pour ES et NQ les donnees live et les enrichir").
    # 11/05 J2c FIX B3 (code-reviewer) : skip merge V4 pour MGC si source =
    # LIVE_CACHE (pas un vrai DMP JSONL). Sinon le merge_dmp_v4 staleness check
    # plante (bar_mgc.ts = int ms vs bar_v4.ts_event = ISO -> TypeError swallowed
    # par except -> merge se fait quand même avec V4 stale = pollution avril).
    # Tant que MGC n'a pas DMP JSONL (DMP C++ hardcoded ES/NQ), bar_mgc reste
    # LIVE_CACHE minimal (OHLC seul, features riches absentes mais pas crash).
    if get_tier_level(tier) >= 1 and (bar_es or bar_nq or bar_mgc):
        v4_es = read_last_v4_row("ES") if bar_es else {}
        v4_nq = read_last_v4_row("NQ") if bar_nq else {}
        # MGC : skip V4 read si LIVE_CACHE source (pas merge possible avec safety)
        # 11/05 J2c FIX I6 (code-reviewer round 2) : garde-fou source inattendu.
        # Transitions futures J3-J5 quand DMP JSONL MGC sera dispo : _source pourra
        # etre "DMP_JSONL" (vide ou None pour bar DMP natif). Log warning si source
        # inattendu pour eviter merge silencieux d'un format non testé.
        _bar_mgc_source = bar_mgc.get("_source") if bar_mgc else None
        _MGC_KNOWN_SOURCES = (None, "LIVE_CACHE_DATABENTO", "DMP_JSONL")
        if _bar_mgc_source not in _MGC_KNOWN_SOURCES:
            import logging as _logging
            _logging.getLogger("DASHBOARD.api.app").warning(
                "MGC bar source inattendu: %r (attendu: %s). Skip merge V4 par defense.",
                _bar_mgc_source, _MGC_KNOWN_SOURCES,
            )
            _bar_mgc_is_live_cache = True  # force skip merge V4 si source inconnue
        else:
            _bar_mgc_is_live_cache = _bar_mgc_source == "LIVE_CACHE_DATABENTO"
        v4_mgc = read_last_v4_row("MGC") if (bar_mgc and not _bar_mgc_is_live_cache) else {}
        bar_es_enr = merge_dmp_v4(bar_es, v4_es) if (bar_es and v4_es) else bar_es
        bar_nq_enr = merge_dmp_v4(bar_nq, v4_nq) if (bar_nq and v4_nq) else bar_nq
        bar_mgc_enr = merge_dmp_v4(bar_mgc, v4_mgc) if (bar_mgc and v4_mgc) else bar_mgc
    else:
        bar_es_enr = bar_es
        bar_nq_enr = bar_nq
        bar_mgc_enr = bar_mgc

    def _build_instrument(bar_enriched, symbol):
        """Construit tous les panels pour un instrument depuis le bar deja enrichi V4."""
        if not bar_enriched:
            return None
        regime = build_regime_context(bar_enriched)
        # 11/05 J2b MGC : mtf MGC reservé J5 (page dashboard dediee).
        # Pour ES/NQ, garde le pattern existant.
        if symbol == "ES":
            mtf = mtf_es
        elif symbol == "NQ":
            mtf = mtf_nq
        else:
            mtf = {}  # MGC : pas de MTF pour l'instant (J5 dashboard MGC)
        _enrich_regime_with_mtf(regime, mtf)
        # 11/05 J2b MGC : passer symbol pour tick correct (MGC=0.10 vs ES/NQ=0.25)
        options = build_options_levels(bar_enriched, symbol=symbol)
        return {
            "regime": regime,
            "session": build_session_open(bar_enriched),
            "options": options,
            "vix_gamma": build_vix_gamma(bar_enriched),
            "order_flow": build_order_flow(bar_enriched),
            "battle_navale": build_battle_navale(bar_enriched),
            "market_profile": build_market_profile(bar_enriched),
            "initial_balance": build_initial_balance(bar_enriched),
            "levels": build_levels_distances(bar_enriched),
            "big_orders": build_big_orders(bar_enriched),
            "suggestion": build_trade_suggestion(bar_enriched, symbol, regime, options),
            # 04/05 — Indicateurs trading manuel Jackson (Phase 1+3)
            "manual_indicators": build_manual_indicators(bar_enriched),
            # 04/05 — Setups composites actifs (Phase 2 banner alerts)
            "active_setups": detect_active_setups(bar_enriched),
            # 04/05 — Order flow avance V4 (cluster/big/SMT/naked_poc)
            # 16/06 MIGRATION : signature (bar, symbol) pour proximity symbol-aware
            # (R1 Plan agent) + detection auto sierra_enriched.
            "order_flow_advanced": build_order_flow_advanced(bar_enriched, symbol),
        }

    response["es"] = _build_instrument(bar_es_enr, "ES")
    response["nq"] = _build_instrument(bar_nq_enr, "NQ")
    # 11/05 J2b — slot MGC enrichi (Jackson "comme pour ES et NQ").
    # bar_mgc_enr = DMP JSONL Sierra Chart + merge V4 enriched (Databento Historical).
    # OBSERVE-ONLY : panels expose mais aucun trade Bot 3 declenche dessus.
    response["mgc"] = _build_instrument(bar_mgc_enr, "MGC") if bar_mgc_enr else None
    response["mtf_es"] = mtf_es
    response["mtf_nq"] = mtf_nq

    # Conseil Global par instrument (pour le paper trader)
    # Options recuperes depuis _build_instrument (deja calcules, pas de double calcul)
    es_reg = response["es"]["regime"] if response.get("es") else {}
    nq_reg = response["nq"]["regime"] if response.get("nq") else {}
    es_opt = response["es"]["options"] if response.get("es") else None
    nq_opt = response["nq"]["options"] if response.get("nq") else None
    response["conseil_global"] = {
        "es": build_conseil_global(bar_es_enr, es_reg, es_opt),
        "nq": build_conseil_global(bar_nq_enr, nq_reg, nq_opt),
    }
    # 11/05 J2b — build_intermarket = SMT ES vs NQ uniquement.
    # MGC SMT non applicable (Gold non corrélé indices US, paires differentes :
    # MGC vs DXY/UST/CL plutot que MGC vs ES). Skip par design.
    response["intermarket"] = build_intermarket(bar_es_enr, bar_nq_enr)
    response["instrument_status"] = {
        "es": build_instrument_status(bot_data, "ES"),
        "nq": build_instrument_status(bot_data, "NQ"),
        # 11/05 J2b — slot MGC instrument_status pour symetrie frontend.
        "mgc": build_instrument_status(bot_data, "MGC") if bar_mgc else None,
    }
    response["signals_journal"] = build_signals_journal(bot_data)
    response["warnings"] = bot_data.get("warnings", {})

    # Detecter cassures de niveaux cles
    response["level_breaks"] = {
        "es": detect_level_breaks("ES", bar_es),
        "nq": detect_level_breaks("NQ", bar_nq),
    }

    # Double Bottom / Double Top detection — cache lourd
    es_price = banner.get("es", {}).get("price", 0) if banner else 0
    nq_price = banner.get("nq", {}).get("price", 0) if banner else 0
    response["patterns"] = {
        "es": _cached_call("pat_daily_es", detect_double_pattern, "ES", es_price, ttl=60),
        "nq": _cached_call("pat_daily_nq", detect_double_pattern, "NQ", nq_price, ttl=60),
    }
    response["patterns_intraday"] = {
        "es": _cached_call("pat_intra_es", detect_intraday_double, "ES", es_price, ttl=15),
        "nq": _cached_call("pat_intra_nq", detect_intraday_double, "NQ", nq_price, ttl=15),
    }

    # Stabiliser le FAVORISER — ne change que sur evenement significatif
    # Fix 15/06 (HTTP 500 sur /api/dashboard) : response["nq"]/"level_breaks"
    # peuvent etre None explicite (assignes ailleurs), `dict.get(k, default)`
    # ne fallback PAS sur None. Utiliser `or {}` apres get pour gerer ce cas.
    _level_breaks = response.get("level_breaks") or {}
    _resp_nq = response.get("nq") or {}
    _stabilize_favor("ES", regime_es, advisory, _level_breaks.get("es", []))
    _stabilize_favor("NQ", _resp_nq.get("regime", {}) or {}, None, _level_breaks.get("nq", []))

    # Stabiliser QUI_A_LA_MAIN
    _stabilize_qui(advisory)

    # Narration du marche
    try:
        cta_data = read_cta_data()
    except Exception:
        cta_data = None
    response["narrative"] = generate_market_narrative(bar_es, bar_nq, cta_data)

    # Session logging — 1 snapshot par minute pour revue post-session
    _log_session_snapshot(bar_es, bar_nq, regime_es, regime_nq, advisory, response.get("intermarket"))

    # Filtrage tier-based (securite F12)
    response = _filter_response_by_tier(response, tier)

    return response


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def _format_ts(ts_ms) -> str:
    """Formate un timestamp ms en string UTC."""
    if not ts_ms:
        return ""
    try:
        dt = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError, OSError):
        return ""
