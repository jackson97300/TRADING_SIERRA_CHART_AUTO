"""Configuration dashboard MIA."""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "DATA")
DASHBOARD_JSON = os.path.join(BASE_DIR, "DASHBOARD", "MIA_AutoTrader_Dashboard.json")

API_HOST = "0.0.0.0"
API_PORT = 8000

JWT_SECRET = os.environ.get("MIA_JWT_SECRET", "CHANGE_ME_IN_PRODUCTION")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")

FREE_PANELS = {"bot_status_basic", "market_context_basic", "intermarket_basic"}
PREMIUM_PANELS = {
    "bot_status",
    "market_context",
    "order_flow",
    "options_gamma",
    "intermarket",
    "signals_journal",
}

POLL_INTERVAL_SEC = 5
