"""FastAPI application du dashboard MIA V2."""
import os
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
    build_market_profile,
    build_options_levels,
    build_order_flow,
    build_price_banner,
    build_regime_context,
    build_session_open,
    build_signals_journal,
    build_trade_suggestion,
    build_vix_gamma,
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

app = FastAPI(title="MIA Dashboard V2", version="2.0.0")

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

    # Timestamp derniere barre
    last_bar_ts = _format_ts(bar_es.get("ts") or bar_nq.get("ts"))

    # Panels communs
    banner = build_price_banner(bar_es, bar_nq)
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

    def _build_instrument(bar, symbol):
        """Construit tous les panels pour un instrument."""
        if not bar:
            return None
        regime = build_regime_context(bar)
        mtf = mtf_es if symbol == "ES" else mtf_nq
        _enrich_regime_with_mtf(regime, mtf)
        options = build_options_levels(bar)
        return {
            "regime": regime,
            "session": build_session_open(bar),
            "options": options,
            "vix_gamma": build_vix_gamma(bar),
            "order_flow": build_order_flow(bar),
            "battle_navale": build_battle_navale(bar),
            "market_profile": build_market_profile(bar),
            "initial_balance": build_initial_balance(bar),
            "levels": build_levels_distances(bar),
            "big_orders": build_big_orders(bar),
            "suggestion": build_trade_suggestion(bar, symbol, regime, options),
        }

    response["es"] = _build_instrument(bar_es, "ES")
    response["nq"] = _build_instrument(bar_nq, "NQ")
    response["mtf_es"] = mtf_es
    response["mtf_nq"] = mtf_nq

    # Conseil Global par instrument (pour le paper trader)
    # Options recuperes depuis _build_instrument (deja calcules, pas de double calcul)
    es_reg = response["es"]["regime"] if response.get("es") else {}
    nq_reg = response["nq"]["regime"] if response.get("nq") else {}
    es_opt = response["es"]["options"] if response.get("es") else None
    nq_opt = response["nq"]["options"] if response.get("nq") else None
    response["conseil_global"] = {
        "es": build_conseil_global(bar_es, es_reg, es_opt),
        "nq": build_conseil_global(bar_nq, nq_reg, nq_opt),
    }
    response["intermarket"] = build_intermarket(bar_es, bar_nq)
    response["instrument_status"] = {
        "es": build_instrument_status(bot_data, "ES"),
        "nq": build_instrument_status(bot_data, "NQ"),
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
    _stabilize_favor("ES", regime_es, advisory, response.get("level_breaks", {}).get("es", []))
    _stabilize_favor("NQ", response.get("nq", {}).get("regime", {}), None, response.get("level_breaks", {}).get("nq", []))

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
