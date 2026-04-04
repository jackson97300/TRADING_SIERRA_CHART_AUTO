"""FastAPI application du dashboard MIA."""
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from DASHBOARD.api.auth import auth_router, get_user_tier as auth_get_user_tier
from DASHBOARD.api.briefing import router as briefing_router
from DASHBOARD.api.data_reader import (
    build_bot_status_basic,
    build_instrument_status,
    build_intermarket,
    build_market_context_basic,
    build_market_context_full,
    build_options_gamma,
    build_order_flow,
    build_signals_journal,
    read_bot_status,
    read_last_bar,
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")

app = FastAPI(title="MIA Dashboard", version="1.0.0")

# CORS ouvert (phase dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router)
app.include_router(briefing_router)

# Fichiers statiques
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    """Sert index.html depuis le dossier static."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse(
        {"error": "index.html non trouve", "hint": "Placer index.html dans DASHBOARD/static/"},
        status_code=404,
    )


@app.get("/login")
async def login_page():
    """Sert la page de connexion."""
    path = os.path.join(STATIC_DIR, "login.html")
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"error": "login.html non trouve"}, status_code=404)


@app.get("/register")
async def register_page():
    """Sert la page d'inscription."""
    path = os.path.join(STATIC_DIR, "register.html")
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"error": "register.html non trouve"}, status_code=404)


@app.get("/briefing")
async def briefing_page():
    """Sert la page briefing."""
    path = os.path.join(STATIC_DIR, "briefing.html")
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"error": "briefing.html non trouve"}, status_code=404)


@app.get("/pricing")
async def pricing_page():
    """Sert la page tarifs."""
    path = os.path.join(STATIC_DIR, "pricing.html")
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"error": "pricing.html non trouve"}, status_code=404)


@app.get("/api/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "mia-dashboard"}


@app.get("/api/dashboard")
async def dashboard(request: Request):
    """Endpoint principal du dashboard.

    Tier free  : bot_status basique + market_context basique.
    Tier premium : 6 panels complets.
    """
    authorization = request.headers.get("Authorization", "")
    tier = auth_get_user_tier(authorization)
    now = datetime.now(timezone.utc).isoformat()

    bot_data = read_bot_status()
    bot_status = build_bot_status_basic(bot_data)

    response: dict = {
        "timestamp": now,
        "tier": tier,
        "bot_status": bot_status,
    }

    if tier == "free":
        response["market_context"] = build_market_context_basic(bot_data)
        return response

    # --- Tier premium : tout ---
    bar_es = read_last_bar("ES")
    bar_nq = read_last_bar("NQ")

    response["es"] = build_instrument_status(bot_data, "ES")
    response["nq"] = build_instrument_status(bot_data, "NQ")
    response["market_context"] = build_market_context_full(bot_data, bar_es, bar_nq)
    response["order_flow_es"] = build_order_flow(bar_es) or None
    response["order_flow_nq"] = build_order_flow(bar_nq) or None
    response["options_gamma_es"] = build_options_gamma(bar_es) or None
    response["options_gamma_nq"] = build_options_gamma(bar_nq) or None
    response["intermarket"] = build_intermarket(bar_es, bar_nq) or None
    response["signals_journal"] = build_signals_journal(bot_data) or None

    # Warnings
    warnings = bot_data.get("warnings")
    if warnings:
        response["warnings"] = warnings

    return response
