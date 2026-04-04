# MIA Dashboard + Website V2 — Plan d'implementation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformer le site vitrine MIA en plateforme live avec dashboard temps reel (377 features), deploye sur VPS, avec monetisation par abonnements premium.

**Architecture:** FastAPI backend sur VPS Windows lisant les JSONL DMP + dashboard.json du bot. Frontend statique HTML/Tailwind/JS (meme design system que le site existant) servi par Uvicorn. Auth JWT + Stripe pour la monetisation.

**Tech Stack:** Python 3.13, FastAPI, Uvicorn, Tailwind CSS (CDN), Chart.js, HTMX (polling leger), JWT auth, Stripe Checkout

---

## Vue d'ensemble des 3 chantiers

```
CHANTIER A — Dashboard Live (Semaines 1-2)
  Backend FastAPI : API JSON lisant DMP + bot status + features
  Frontend : 6 panels schematises, design system MIA, responsive

CHANTIER B — Deploiement VPS (Semaine 2)
  Uvicorn + reverse proxy Caddy, HTTPS auto, Task Scheduler persistant

CHANTIER C — Monetisation (Semaine 3)
  Auth JWT, Stripe abonnements, contenu premium gate
```

---

## CHANTIER A — Dashboard Live

### Architecture des panels

Le dashboard expose 377 features en 6 panels utilisables et lisibles.
Chaque panel = une carte `.glass` avec titre, sous-titre, et widgets internes.

```
+------------------------------------------------------------------+
| TICKER TRADINGVIEW (ES NQ RTY VIX SPX CL GC BTC)                |
+------------------------------------------------------------------+
| NAVBAR: Logo | Dashboard | Briefing | Education | [Discord ★]   |
|         [Premium ★ gradient] | Login                             |
+------------------------------------------------------------------+
| BANDEAU CTA: "Briefing du 04/04 — Niveaux cles ES/NQ → Lire"   |
+------------------------------------------------------------------+
|                                              | SIDEBAR DROITE    |
| [1. BOT STATUS]    [2. MARKET CONTEXT]       |                    |
|  Running/Stopped    VWAP + VIX + ATR         | [BRIEFING MIA]    |
|  ES: LONG@5432      Open Type + Day Type     | "Analyse du jour" |
|  P&L: +$285         IB + Profile + POC       | Apercu 3 lignes   |
|  CTA: "Details →"   CTA: "Comprendre         | CTA: "Lire →"     |
|  (upsell Starter)    l'Open Type →"          | (Premium only)    |
|                      (lien Education)         |                    |
|                                              | [DISCORD]          |
| [3. ORDER FLOW]    [4. OPTIONS & GAMMA]      | "3200 membres"    |
|  BLUR + apercu      BLUR + apercu            | CTA: "Rejoindre"  |
|  CTA: "Debloquer    CTA: "Debloquer          |                    |
|   49EUR/mois"        49EUR/mois"             | [YOUTUBE]          |
|  (avec 1 stat       (avec mur le + proche    | Derniere video     |
|   visible en clair)  visible en clair)       | CTA: "S'abonner"  |
|                                              |                    |
| [5. INTERMARKET]   [6. SIGNAUX & JOURNAL]    | [LUCID TRADING]   |
|  Correlation +SMT   BLUR + toast alerte      | "Ouvrir un compte"|
|  CTA: "AMD, PO3     CTA: "Voir les          | CTA: lien affilié |
|   → Starter"         signaux → Premium"      | (12% commission)  |
|                                              |                    |
|                                              | [NEWSLETTER]       |
|                                              | Email input        |
|                                              | CTA: "S'inscrire"  |
+------------------------------------------------------------------+
| FOOTER: Newsletter | Discord | YouTube | TikTok | Instagram | X |
|         CGU | Confidentialite | Risques | Contact                |
+------------------------------------------------------------------+
```

### Strategie CTA — Matrice complete

| Zone | CTA | Action | Objectif | Tier cible |
|------|-----|--------|----------|-----------|
| Navbar | "Discord" badge dore | Lien Discord invite | Communaute + retention | Tous |
| Navbar | "Premium ★" bouton gradient | Lien /pricing | Conversion directe | Free |
| Bandeau sous ticker | "Briefing du JJ/MM — Lire" | Lien /briefing (Premium gate) | FOMO contenu quotidien | Free → Premium |
| Panel Bot Status | "Voir positions + P&L detailles →" | Scroll/upsell Starter | Upsell | Free |
| Panel Market Context | "Comprendre l'Open Type →" | Lien /education/open-type | Trafic education | Tous |
| Panel Order Flow (blur) | "Debloquer — 49EUR/mois" + 1 stat teaser | Lien /pricing | Upsell Premium | Free/Starter |
| Panel Options (blur) | "Debloquer — 49EUR/mois" + mur le + proche | Lien /pricing | Upsell Premium | Free/Starter |
| Panel Intermarket | "AMD + PO3 complet → Starter" | Lien /pricing | Upsell Starter | Free |
| Panel Signaux (blur) | "Signal BUY detecte — Details →" | Lien /pricing | FOMO upsell | Free |
| Sidebar: Briefing MIA | Apercu 3 lignes + "Lire l'analyse →" | Page /briefing | Produit phare | Free → Premium |
| Sidebar: Discord | Logo + "3200 membres" + "Rejoindre" | Lien Discord invite | Communaute | Tous |
| Sidebar: YouTube | Miniature derniere video + "S'abonner" | Lien YouTube | Audience | Tous |
| Sidebar: Lucid Trading | Logo + "Ouvrir un compte" | Lien affiliation 12% | Revenu passif | Tous |
| Sidebar: Newsletter | Input email + "S'inscrire" | Webhook Discord/Mailchimp | Capture leads | Tous |
| Toast (live) | "Signal BUY ES detecte — 14:32" | Notification flottante | FOMO temps reel | Tous |
| Post-login modal | "Bienvenue! Essayez Premium — 7j gratuit" | Stripe trial | Conversion nouveaux | Nouveaux users |
| Footer | Icons reseaux + newsletter | Multi-CTA | Retention globale | Tous |

### Tiers de visibilite (monetisation) — Revise avec 3 tiers

| Panel | FREE | STARTER (19EUR) | PREMIUM (49EUR) |
|-------|------|-----------------|-----------------|
| 1. Bot Status | Running/stopped only | Complet (positions, P&L, trades) | Complet |
| 2. Market Context | VIX + ATR + VWAP slope | + Open Type, Day Type, IB, Profile | Complet |
| 3. Order Flow | Blur + 1 teaser (RVOL) | Blur + 2 teasers | Complet |
| 4. Options & Gamma | Blur + 1 teaser (mur closest) | Blur + 2 teasers | Complet |
| 5. Intermarket | Correlation basique | Complet (SMT, delta, AMD, PO3) | Complet |
| 6. Signaux & Journal | Blur total | Blur + signal direction only | Complet |
| Briefing MIA | Titre + 3 lignes apercu | Complet | Complet |
| Alertes Discord | Aucune | Retardees 15min | Temps reel |

### "Briefing MIA" — Le vrai produit premium

Le dashboard seul ne suffit pas pour monetiser. Les gens paient pour de l'**interpretation**, pas des chiffres bruts.

**Briefing MIA quotidien** (publie chaque matin 8h30 ET, avant l'ouverture US) :
- **Section 1 : Contexte macro** — VIX regime, ATR, overnight range, gap analysis
- **Section 2 : Niveaux cles du jour** — Call/Put walls, GEX, HVL, VWAP SD bands, IB projections
- **Section 3 : Biais directionnel** — Open Type probable, Day Type probable, AMD session bias
- **Section 4 : Zones d'interet** — Ou chercher des entries (VA extremes, murs, confluences)
- **Section 5 : Events economiques** — FOMC/NFP/CPI impact, MIA bloque trading 15min avant
- **Section 6 : Positionnement institutionnel** — GEX net, dealer hedging, put/call ratio, SMT

Generation : **semi-automatique**. Les donnees viennent du DMP/MenthorQ. Tu ajoutes 3-4 phrases de commentaire perso. Un template Python genere le HTML.

Route : `/briefing` ou `/briefing/2026-04-04` (archive par date)

CTA sur la homepage du site principal : "Recevez l'analyse MIA chaque matin → S'inscrire"

---

## File Structure

```
D:\TRADING_SIERRA_CHART_AUTO\
  DASHBOARD\                        <- TOUT LE NOUVEAU CODE ICI
    api\
      __init__.py                     Package Python
      app.py                          FastAPI app principale (routes + CORS + static)
      auth.py                         JWT auth (register/login/verify)
      data_reader.py                  Lecture JSONL DMP + dashboard.json + features
      models.py                       Pydantic models (response schemas)
      stripe_webhooks.py              Stripe checkout + webhook subscription
    static\
      index.html                      Page dashboard (6 panels)
      login.html                      Login page (restyle du existant)
      register.html                   Register page (restyle)
      pricing.html                    Page tarifs + boutons Stripe
      css\
        dashboard.css                 Styles specifiques dashboard
      js\
        dashboard.js                  Logique polling API + rendering panels
        auth.js                       Login/register/token management
        charts.js                     Chart.js wrappers (delta histogram, CVD line)
    users.json                        Stockage users simple (phase 1, SQLite phase 2)
    config.py                         Config dashboard (ports, secrets, tiers)
    start_dashboard.py                Script de demarrage Uvicorn
```

---

## Task 1 : Backend FastAPI — Lecture des donnees

**Files:**
- Create: `DASHBOARD/api/__init__.py`
- Create: `DASHBOARD/api/data_reader.py`
- Create: `DASHBOARD/api/models.py`
- Create: `DASHBOARD/api/app.py`
- Create: `DASHBOARD/config.py`

### data_reader.py — Le coeur du backend

Ce module lit 3 sources :
1. `DASHBOARD/MIA_AutoTrader_Dashboard.json` — statut bot (ecrit par bot_main.py)
2. Le JSONL DMP le plus recent dans `DATA/ES/` et `DATA/NQ/` — derniere barre = features live
3. Les features derivees calculees a la volee (ctx_*, im_*, amd_*, rvol_*)

- [ ] **Step 1: Creer config.py**

```python
"""Configuration dashboard MIA."""
import os

# Chemins (VPS Windows)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "DATA")
DASHBOARD_JSON = os.path.join(BASE_DIR, "DASHBOARD", "MIA_AutoTrader_Dashboard.json")

# API
API_HOST = "0.0.0.0"
API_PORT = 8000

# Auth
JWT_SECRET = os.environ.get("MIA_JWT_SECRET", "CHANGE_ME_IN_PRODUCTION")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

# Stripe
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")

# Tiers
FREE_PANELS = {"bot_status_basic", "market_context_basic", "intermarket_basic"}
PREMIUM_PANELS = {"bot_status", "market_context", "order_flow", "options_gamma",
                  "intermarket", "signals_journal"}

# Refresh
POLL_INTERVAL_SEC = 5
```

- [ ] **Step 2: Creer api/__init__.py**

```python
"""MIA Dashboard API."""
```

- [ ] **Step 3: Creer api/models.py**

```python
"""Pydantic models pour les reponses API."""
from pydantic import BaseModel
from typing import Optional


class BotStatusBasic(BaseModel):
    running: bool
    global_status: str
    last_heartbeat: str


class InstrumentStatus(BaseModel):
    enabled: bool
    in_position: bool
    status: str
    trades_today: int
    wins: int
    losses: int
    pnl_today: float
    consecutive_losses: int
    last_rejected: str
    signals_rejected: int


class MarketContextBasic(BaseModel):
    vix: float
    vix_regime: str
    atr_es: float
    atr_nq: float
    vwap_slope_es: float
    vwap_slope_nq: float


class MarketContextFull(MarketContextBasic):
    open_type: int
    open_type_label: str
    open_zone: int
    day_type: int
    day_type_label: str
    ib_range_ticks: float
    ib_broken_up: bool
    ib_broken_down: bool
    ib_extension_ratio: float
    profile_shape: int
    profile_shape_label: str
    poc_position: float
    vwap_d_side: int
    vwap_triple_align: int
    trend_day_probability: float
    session_id: str


class OrderFlowPanel(BaseModel):
    delta_bar: float
    delta_pct: float
    cvd_day: float
    cvd_day_dir: int
    rvol: float
    rvol_regime: int
    rvol_regime_label: str
    absorption_score: float
    absorption_streak: float
    price_delta_div: float
    climax_signal: float
    large_trader_ratio: float
    ask_bid_imbalance: float
    finish_strength: float


class OptionsGammaPanel(BaseModel):
    dist_mq_call: float
    dist_mq_put: float
    dist_mq_hvl: float
    dist_mq_call_0dte: float
    dist_mq_put_0dte: float
    dist_gex_nearest_up: float
    dist_gex_nearest_dn: float
    gex_cluster_count: int
    bool_gex_flip_zone: bool
    vix_level: float
    vix_regime: int
    dist_vix_call: float
    dist_vix_put: float
    next_wall_dist_ticks: float
    next_wall_is_call: bool


class IntermarketPanel(BaseModel):
    cross_delta_agreement: float
    smt_divergence: int
    rolling_correlation: float
    price_ratio_slope: float
    volume_lead: float
    ltr_slope_diff: float
    amd_phase: int
    amd_phase_label: str
    amd_session_bias: float
    amd_po3_score: float
    amd_po3_bullish: bool
    amd_po3_bearish: bool
    amd_judas_swing: bool
    amd_manip_score: float


class SignalEntry(BaseModel):
    ts: str
    symbol: str
    direction: str
    pnl: Optional[float] = None
    reason: str


class SignalsJournalPanel(BaseModel):
    current_signal: Optional[str] = None
    signal_score: Optional[float] = None
    signal_reason: str
    sl_ticks: Optional[float] = None
    tp_ticks: Optional[float] = None
    rr_ratio: Optional[float] = None
    recent_trades: list[SignalEntry]
    recent_rejections: list[str]


class DashboardResponse(BaseModel):
    timestamp: str
    tier: str
    bot_status: BotStatusBasic
    es: Optional[InstrumentStatus] = None
    nq: Optional[InstrumentStatus] = None
    market_context: MarketContextBasic | MarketContextFull
    order_flow_es: Optional[OrderFlowPanel] = None
    order_flow_nq: Optional[OrderFlowPanel] = None
    options_gamma_es: Optional[OptionsGammaPanel] = None
    options_gamma_nq: Optional[OptionsGammaPanel] = None
    intermarket: Optional[IntermarketPanel] = None
    signals_journal: Optional[SignalsJournalPanel] = None
    warnings: Optional[dict] = None
```

- [ ] **Step 4: Creer api/data_reader.py**

```python
"""Lecture des donnees DMP et bot status pour le dashboard."""
import json
import os
import glob
from datetime import datetime, timezone

from DASHBOARD.config import DATA_DIR, DASHBOARD_JSON


OPEN_TYPE_LABELS = {
    0: "UNKNOWN", 1: "OD UP", 2: "OD DOWN", 3: "OTD UP", 4: "OTD DOWN",
    5: "ORR UP", 6: "ORR DOWN", 7: "OAIR", 8: "OAOR UP", 9: "OAOR DOWN",
    10: "ODF UP", 11: "ODF DOWN"
}
DAY_TYPE_LABELS = {
    0: "NON TREND", 1: "NORMAL", 2: "NORM VARIATION", 3: "NEUTRAL", 4: "TREND"
}
PROFILE_SHAPE_LABELS = {0: "D-Shape", 1: "P-Shape", 2: "b-Shape", 3: "Double Dist"}
RVOL_REGIME_LABELS = {0: "Low", 1: "Normal", 2: "High", 3: "Spike", 4: "Extreme"}
AMD_PHASE_LABELS = {0: "Asia", 1: "London", 2: "US"}


def read_bot_status() -> dict:
    """Lit le JSON de statut ecrit par bot_main.py."""
    try:
        with open(DASHBOARD_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"bot_status": {"running": False, "last_heartbeat": "", "global_status": "OFFLINE"}}


def get_latest_jsonl(symbol: str) -> str | None:
    """Trouve le JSONL le plus recent pour un symbole (par mtime, pas par nom)."""
    pattern = os.path.join(DATA_DIR, symbol, f"*_{symbol}.jsonl")
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def read_last_bar(symbol: str) -> dict | None:
    """Lit la derniere ligne du JSONL le plus recent."""
    path = get_latest_jsonl(symbol)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in reversed(lines):
            line = line.strip()
            if line:
                return json.loads(line)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return None


def get_field(bar: dict, field: str, default=0.0):
    """Extrait un champ avec fallback."""
    val = bar.get(field, default)
    if val is None or val == "INVALID":
        return default
    return val


def build_market_context_basic(bot_data: dict) -> dict:
    """Contexte marche basique (tier FREE)."""
    ml = bot_data.get("market_live", {})
    return {
        "vix": ml.get("vix", 0.0),
        "vix_regime": ml.get("vix_regime", "UNKNOWN"),
        "atr_es": ml.get("atr_es", 0.0),
        "atr_nq": ml.get("atr_nq", 0.0),
        "vwap_slope_es": ml.get("vwap_slope_es", 0.0),
        "vwap_slope_nq": ml.get("vwap_slope_nq", 0.0),
    }


def build_market_context_full(bot_data: dict, bar_es: dict, bar_nq: dict) -> dict:
    """Contexte marche complet (tier PREMIUM)."""
    base = build_market_context_basic(bot_data)
    bar = bar_es or bar_nq or {}
    ot = int(get_field(bar, "open_type", 0))
    dt = int(get_field(bar, "day_type", 2))
    ps = int(get_field(bar, "profile_shape", 0))
    base.update({
        "open_type": ot,
        "open_type_label": OPEN_TYPE_LABELS.get(ot, "UNKNOWN"),
        "open_zone": int(get_field(bar, "open_zone", 0)),
        "day_type": dt,
        "day_type_label": DAY_TYPE_LABELS.get(dt, "UNKNOWN"),
        "ib_range_ticks": get_field(bar, "ib_range_ticks"),
        "ib_broken_up": bool(get_field(bar, "ib_broken_up", 0)),
        "ib_broken_down": bool(get_field(bar, "ib_broken_down", 0)),
        "ib_extension_ratio": get_field(bar, "ctx_ib_extension_ratio", 0.0),
        "profile_shape": ps,
        "profile_shape_label": PROFILE_SHAPE_LABELS.get(ps, "UNKNOWN"),
        "poc_position": get_field(bar, "poc_position"),
        "vwap_d_side": int(get_field(bar, "vwap_d_side", 0)),
        "vwap_triple_align": int(get_field(bar, "vwap_triple_align", 0)),
        "trend_day_probability": get_field(bar, "trend_day_probability"),
        "session_id": bar.get("session_id", "Unknown"),
    })
    return base


def build_order_flow(bar: dict) -> dict:
    """Panel Order Flow depuis une barre DMP."""
    rv = int(get_field(bar, "rvol_regime", 1) if "rvol_regime" in bar
             else (0 if get_field(bar, "rvol") < 0.5 else
                   1 if get_field(bar, "rvol") < 2.0 else
                   2 if get_field(bar, "rvol") < 3.0 else
                   3 if get_field(bar, "rvol") < 4.0 else 4))
    return {
        "delta_bar": get_field(bar, "delta_bar"),
        "delta_pct": get_field(bar, "delta_pct"),
        "cvd_day": get_field(bar, "cvd_day"),
        "cvd_day_dir": int(get_field(bar, "cvd_day_dir", 0)),
        "rvol": get_field(bar, "rvol", 1.0),
        "rvol_regime": rv,
        "rvol_regime_label": RVOL_REGIME_LABELS.get(rv, "Normal"),
        "absorption_score": get_field(bar, "ctx_absorption_score_5"),
        "absorption_streak": get_field(bar, "ctx_absorption_streak_5"),
        "price_delta_div": get_field(bar, "ctx_price_delta_div_3"),
        "climax_signal": get_field(bar, "ctx_climax_signal"),
        "large_trader_ratio": get_field(bar, "large_trader_ratio"),
        "ask_bid_imbalance": get_field(bar, "ask_bid_imbalance"),
        "finish_strength": get_field(bar, "finish_strength"),
    }


def build_options_gamma(bar: dict) -> dict:
    """Panel Options & Gamma depuis une barre DMP."""
    return {
        "dist_mq_call": get_field(bar, "dist_mq_call"),
        "dist_mq_put": get_field(bar, "dist_mq_put"),
        "dist_mq_hvl": get_field(bar, "dist_mq_hvl"),
        "dist_mq_call_0dte": get_field(bar, "dist_mq_call_0dte"),
        "dist_mq_put_0dte": get_field(bar, "dist_mq_put_0dte"),
        "dist_gex_nearest_up": get_field(bar, "dist_gex_nearest_up"),
        "dist_gex_nearest_dn": get_field(bar, "dist_gex_nearest_dn"),
        "gex_cluster_count": int(get_field(bar, "gex_cluster_count", 0)),
        "bool_gex_flip_zone": bool(get_field(bar, "bool_gex_flip_zone", 0)),
        "vix_level": get_field(bar, "vix_level"),
        "vix_regime": int(get_field(bar, "vix_regime", 0)),
        "dist_vix_call": get_field(bar, "dist_vix_call"),
        "dist_vix_put": get_field(bar, "dist_vix_put"),
        "next_wall_dist_ticks": get_field(bar, "next_wall_dist_ticks"),
        "next_wall_is_call": bool(get_field(bar, "next_wall_is_call", 0)),
    }


def build_intermarket(bar_es: dict, bar_nq: dict) -> dict:
    """Panel Intermarket ES/NQ."""
    bar = bar_es or bar_nq or {}
    ap = int(get_field(bar, "amd_phase", 0))
    return {
        "cross_delta_agreement": get_field(bar, "im_cross_delta_agreement_5"),
        "smt_divergence": int(get_field(bar, "im_smt_divergence", 0)),
        "rolling_correlation": get_field(bar, "im_rolling_correlation_10", 1.0),
        "price_ratio_slope": get_field(bar, "im_price_ratio_slope_10"),
        "volume_lead": get_field(bar, "im_volume_lead"),
        "ltr_slope_diff": get_field(bar, "im_ltr_slope_diff"),
        "amd_phase": ap,
        "amd_phase_label": AMD_PHASE_LABELS.get(ap, "Unknown"),
        "amd_session_bias": get_field(bar, "amd_session_bias"),
        "amd_po3_score": get_field(bar, "amd_po3_score"),
        "amd_po3_bullish": bool(get_field(bar, "amd_po3_bullish", 0)),
        "amd_po3_bearish": bool(get_field(bar, "amd_po3_bearish", 0)),
        "amd_judas_swing": bool(get_field(bar, "amd_judas_swing", 0)),
        "amd_manip_score": get_field(bar, "amd_manip_score"),
    }
```

- [ ] **Step 5: Creer api/app.py**

```python
"""FastAPI app principale — Dashboard MIA."""
import os
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from DASHBOARD.config import FREE_PANELS, PREMIUM_PANELS
from DASHBOARD.api.data_reader import (
    read_bot_status, read_last_bar,
    build_market_context_basic, build_market_context_full,
    build_order_flow, build_options_gamma, build_intermarket,
)
from DASHBOARD.api.auth import get_current_user, get_user_tier

app = FastAPI(title="MIA Dashboard API", version="1.0.0")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/dashboard")
async def get_dashboard(tier: str = "free"):
    """Endpoint principal — retourne tous les panels selon le tier."""
    bot_data = read_bot_status()
    bar_es = read_last_bar("ES")
    bar_nq = read_last_bar("NQ")
    now = datetime.now(timezone.utc).isoformat()

    response = {
        "timestamp": now,
        "tier": tier,
        "bot_status": bot_data.get("bot_status", {}),
        "warnings": bot_data.get("warnings", {}),
    }

    if tier == "premium":
        response["es"] = bot_data.get("es", {})
        response["nq"] = bot_data.get("nq", {})
        response["market_context"] = build_market_context_full(
            bot_data, bar_es or {}, bar_nq or {}
        )
        if bar_es:
            response["order_flow_es"] = build_order_flow(bar_es)
            response["options_gamma_es"] = build_options_gamma(bar_es)
        if bar_nq:
            response["order_flow_nq"] = build_order_flow(bar_nq)
            response["options_gamma_nq"] = build_options_gamma(bar_nq)
        response["intermarket"] = build_intermarket(bar_es, bar_nq)
    else:
        bs = bot_data.get("bot_status", {})
        response["bot_status"] = {
            "running": bs.get("running", False),
            "global_status": bs.get("global_status", "OFFLINE"),
            "last_heartbeat": bs.get("last_heartbeat", ""),
        }
        response["market_context"] = build_market_context_basic(bot_data)

    return response


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "mia-dashboard"}
```

- [ ] **Step 6: Creer start_dashboard.py**

```python
"""Script de demarrage du dashboard MIA."""
import uvicorn
from DASHBOARD.config import API_HOST, API_PORT

if __name__ == "__main__":
    uvicorn.run(
        "DASHBOARD.api.app:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
        log_level="info",
    )
```

- [ ] **Step 7: Tester le backend localement**

```bash
cd D:\TRADING_SIERRA_CHART_AUTO
pip install fastapi uvicorn
python DASHBOARD/start_dashboard.py
# Dans un autre terminal :
curl http://localhost:8000/api/health
# Expected: {"status":"ok","service":"mia-dashboard"}
curl http://localhost:8000/api/dashboard?tier=free
# Expected: JSON avec bot_status + market_context basiques
curl http://localhost:8000/api/dashboard?tier=premium
# Expected: JSON complet avec 6 panels
```

- [ ] **Step 8: Commit**

```bash
git add DASHBOARD/api/ DASHBOARD/config.py DASHBOARD/start_dashboard.py
git commit -m "feat(dashboard): backend FastAPI avec 6 panels et lecture DMP"
```

---

## Task 2 : Frontend Dashboard — Page principale

**Files:**
- Create: `DASHBOARD/static/index.html`
- Create: `DASHBOARD/static/css/dashboard.css`

Le frontend utilise le design system existant de mia-website :
- Fond `#0A0E17`, cards `.glass` (rgba(19,23,34,0.6) + backdrop-blur)
- Couleurs : cyan `#00B4DC`, gold `#D4AF37`, vert `#00C853`, rouge `#FF5252`
- Fonts : Inter (texte) + JetBrains Mono (valeurs numeriques)
- Boutons : gradient cyan → cyan-dark

- [ ] **Step 1: Creer dashboard.css**

```css
/* MIA Dashboard v1.0 — Design system coherent avec mia-website */

/* === RESET + BASE === */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
    /* Fond */
    --bg-base: #0A0E17;
    --bg-card: #0D1321;
    --bg-input: #131722;
    --bg-hover: #1C2333;

    /* Marque */
    --cyan: #00B4DC;
    --cyan-dark: #0090B0;
    --gold: #D4AF37;
    --purple: #6366F1;

    /* Trading */
    --green: #00C853;
    --red: #FF5252;
    --warning: #F59E0B;

    /* Texte */
    --text-primary: #FFFFFF;
    --text-secondary: #CBD5E1;
    --text-muted: #94A3B8;
    --text-disabled: #64748B;

    /* Glows */
    --glow-cyan: rgba(0, 180, 220, 0.4);
    --glow-gold: rgba(212, 175, 55, 0.4);

    /* Layout */
    --ticker-height: 46px;
    --navbar-height: 64px;
    --panel-gap: 1rem;
    --panel-radius: 1rem;
}

body {
    font-family: 'Inter', -apple-system, sans-serif;
    background: var(--bg-base);
    color: var(--text-primary);
    padding-top: calc(var(--ticker-height) + var(--navbar-height));
    min-height: 100vh;
}

.mono { font-family: 'JetBrains Mono', monospace; }

/* === GLASS CARD === */
.glass {
    background: rgba(13, 19, 33, 0.8);
    backdrop-filter: blur(24px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: var(--panel-radius);
    padding: 1.25rem;
}

.glass:hover {
    border-color: rgba(0, 180, 220, 0.2);
}

/* === LAYOUT GRID === */
.dashboard-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--panel-gap);
    max-width: 1400px;
    margin: 0 auto;
    padding: var(--panel-gap);
}

@media (max-width: 768px) {
    .dashboard-grid { grid-template-columns: 1fr; }
}

/* === PANEL HEADER === */
.panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.panel-title {
    font-size: 0.875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-secondary);
}

.panel-icon {
    width: 20px;
    height: 20px;
    color: var(--cyan);
}

/* === STATUS BADGES === */
.badge {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.25rem 0.75rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
}

.badge-green { background: rgba(0, 200, 83, 0.15); color: var(--green); }
.badge-red { background: rgba(255, 82, 82, 0.15); color: var(--red); }
.badge-yellow { background: rgba(245, 158, 11, 0.15); color: var(--warning); }
.badge-cyan { background: rgba(0, 180, 220, 0.15); color: var(--cyan); }
.badge-purple { background: rgba(99, 102, 241, 0.15); color: var(--purple); }

/* Dot pulsant */
.dot { width: 8px; height: 8px; border-radius: 50%; }
.dot-green { background: var(--green); box-shadow: 0 0 8px var(--green); animation: pulse 2s infinite; }
.dot-red { background: var(--red); }
.dot-yellow { background: var(--warning); animation: pulse 2s infinite; }

@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

/* === VALEURS NUMERIQUES === */
.stat-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.5rem;
    font-weight: 700;
    line-height: 1.2;
}

.stat-label {
    font-size: 0.75rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.03em;
}

.stat-positive { color: var(--green); }
.stat-negative { color: var(--red); }
.stat-neutral { color: var(--text-secondary); }

/* === GAUGE (jauge horizontale) === */
.gauge {
    height: 6px;
    background: var(--bg-hover);
    border-radius: 3px;
    overflow: hidden;
    margin-top: 0.25rem;
}

.gauge-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.5s ease;
}

.gauge-cyan { background: var(--cyan); }
.gauge-green { background: var(--green); }
.gauge-red { background: var(--red); }
.gauge-gold { background: var(--gold); }

/* === TABLEAU COMPACT === */
.data-table {
    width: 100%;
    font-size: 0.8125rem;
}

.data-table th {
    text-align: left;
    padding: 0.5rem;
    color: var(--text-muted);
    font-weight: 500;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.data-table td {
    padding: 0.5rem;
    font-family: 'JetBrains Mono', monospace;
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}

/* === KV ROW (cle: valeur) === */
.kv-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.375rem 0;
}

.kv-key {
    font-size: 0.8125rem;
    color: var(--text-muted);
}

.kv-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.875rem;
    font-weight: 500;
}

/* === PREMIUM BLUR === */
.premium-locked {
    position: relative;
    overflow: hidden;
}

.premium-locked > *:not(.premium-overlay) {
    filter: blur(8px);
    user-select: none;
    pointer-events: none;
}

.premium-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    z-index: 10;
    background: rgba(10, 14, 23, 0.4);
}

.premium-overlay .lock-icon {
    width: 32px;
    height: 32px;
    color: var(--gold);
    margin-bottom: 0.5rem;
}

.premium-overlay .lock-text {
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--gold);
}

.premium-overlay .lock-cta {
    margin-top: 0.5rem;
    padding: 0.375rem 1rem;
    background: linear-gradient(to right, var(--cyan), var(--cyan-dark));
    color: var(--bg-base);
    border-radius: 0.5rem;
    font-size: 0.75rem;
    font-weight: 600;
    text-decoration: none;
}

/* === NAVBAR === */
.navbar {
    position: fixed;
    top: var(--ticker-height);
    left: 0;
    right: 0;
    height: var(--navbar-height);
    background: rgba(10, 14, 23, 0.9);
    backdrop-filter: blur(20px);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    z-index: 100;
    display: flex;
    align-items: center;
    padding: 0 1.5rem;
}

.navbar-brand {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    text-decoration: none;
}

.navbar-brand img {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 2px solid rgba(212, 175, 55, 0.7);
}

.navbar-brand span {
    font-weight: 700;
    font-size: 1.125rem;
    background: linear-gradient(to right, #fff, var(--cyan), var(--gold));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

/* === FOOTER === */
.dashboard-footer {
    text-align: center;
    padding: 2rem 1rem;
    color: var(--text-disabled);
    font-size: 0.75rem;
    border-top: 1px solid rgba(255, 255, 255, 0.04);
    margin-top: 2rem;
}

.dashboard-footer a {
    color: var(--text-muted);
    text-decoration: none;
}

.dashboard-footer a:hover { color: var(--cyan); }

/* === REFRESH INDICATOR === */
.refresh-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--cyan);
    animation: pulse 1s ease-in-out;
}
```

- [ ] **Step 2: Creer index.html**

Le HTML complet du dashboard avec les 6 panels. Structure :
- Ticker TradingView (copie de ticker.js existant)
- Navbar avec logo + liens
- Grid 2 colonnes avec les 6 panels
- Chaque panel a un ID pour le JS de mise a jour
- Les panels premium ont la classe `.premium-locked` par defaut

```html
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard - MIA IA SYSTEM</title>
    <meta name="description" content="Dashboard temps reel MIA : 377 features, signaux ES/NQ, order flow, options gamma, intermarket.">

    <!-- Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">

    <!-- Favicon -->
    <link rel="icon" type="image/png" sizes="32x32" href="/static/images/favicon-32x32.png">

    <!-- CSS -->
    <link rel="stylesheet" href="/static/css/dashboard.css">
</head>
<body>
    <!-- TICKER TRADINGVIEW -->
    <div id="tv-ticker" style="position:fixed;top:0;left:0;right:0;height:46px;z-index:9999;background:#0a0e17;"></div>

    <!-- NAVBAR -->
    <nav class="navbar">
        <a href="/" class="navbar-brand">
            <img src="/static/images/logo-dark.jpg" alt="MIA">
            <span>MIA Dashboard</span>
        </a>
        <div style="flex:1"></div>
        <div style="display:flex;align-items:center;gap:1rem;">
            <span id="refresh-status" class="badge badge-cyan">
                <span class="dot dot-green"></span>
                <span class="mono" style="font-size:0.7rem;">LIVE</span>
            </span>
            <span id="last-update" class="mono" style="font-size:0.7rem;color:var(--text-muted);">--:--:--</span>
        </div>
    </nav>

    <!-- DASHBOARD GRID -->
    <main class="dashboard-grid">

        <!-- PANEL 1: BOT STATUS -->
        <div class="glass" id="panel-bot-status">
            <div class="panel-header">
                <span class="panel-title">Bot Status</span>
                <span id="bot-running-badge" class="badge badge-red">
                    <span class="dot dot-red"></span> OFFLINE
                </span>
            </div>
            <div id="bot-status-content">
                <div class="kv-row">
                    <span class="kv-key">Statut global</span>
                    <span class="kv-value" id="bot-global-status">--</span>
                </div>
                <div class="kv-row">
                    <span class="kv-key">Dernier heartbeat</span>
                    <span class="kv-value mono" id="bot-heartbeat">--</span>
                </div>
                <!-- ES -->
                <div style="margin-top:1rem;padding-top:0.75rem;border-top:1px solid rgba(255,255,255,0.06);">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
                        <span style="font-weight:600;color:var(--cyan);">ES</span>
                        <span id="es-position" class="badge badge-yellow">FLAT</span>
                    </div>
                    <div class="kv-row">
                        <span class="kv-key">P&L aujourd'hui</span>
                        <span class="kv-value mono" id="es-pnl">$0.00</span>
                    </div>
                    <div class="kv-row">
                        <span class="kv-key">Trades</span>
                        <span class="kv-value mono" id="es-trades">0W / 0L</span>
                    </div>
                </div>
                <!-- NQ -->
                <div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid rgba(255,255,255,0.06);">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
                        <span style="font-weight:600;color:var(--gold);">NQ</span>
                        <span id="nq-position" class="badge badge-yellow">FLAT</span>
                    </div>
                    <div class="kv-row">
                        <span class="kv-key">P&L aujourd'hui</span>
                        <span class="kv-value mono" id="nq-pnl">$0.00</span>
                    </div>
                    <div class="kv-row">
                        <span class="kv-key">Trades</span>
                        <span class="kv-value mono" id="nq-trades">0W / 0L</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- PANEL 2: MARKET CONTEXT -->
        <div class="glass" id="panel-market-context">
            <div class="panel-header">
                <span class="panel-title">Contexte Marche</span>
                <span id="session-badge" class="badge badge-purple">--</span>
            </div>
            <div id="market-context-content">
                <div class="kv-row">
                    <span class="kv-key">VIX</span>
                    <span class="kv-value mono" id="mc-vix">--</span>
                </div>
                <div class="kv-row">
                    <span class="kv-key">Regime VIX</span>
                    <span class="kv-value" id="mc-vix-regime">--</span>
                </div>
                <div class="kv-row">
                    <span class="kv-key">ATR ES / NQ</span>
                    <span class="kv-value mono" id="mc-atr">-- / --</span>
                </div>
                <div class="kv-row">
                    <span class="kv-key">VWAP Slope ES / NQ</span>
                    <span class="kv-value mono" id="mc-vwap-slope">-- / --</span>
                </div>
                <!-- Premium content -->
                <div id="mc-premium" class="premium-locked" style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid rgba(255,255,255,0.06);">
                    <div class="kv-row"><span class="kv-key">Open Type</span><span class="kv-value" id="mc-open-type">--</span></div>
                    <div class="kv-row"><span class="kv-key">Day Type</span><span class="kv-value" id="mc-day-type">--</span></div>
                    <div class="kv-row"><span class="kv-key">IB Range</span><span class="kv-value mono" id="mc-ib-range">-- ticks</span></div>
                    <div class="kv-row"><span class="kv-key">Profile Shape</span><span class="kv-value" id="mc-profile">--</span></div>
                    <div class="kv-row"><span class="kv-key">Trend Day Prob</span><span class="kv-value mono" id="mc-trend-prob">--%</span></div>
                    <div class="kv-row"><span class="kv-key">VWAP Triple Align</span><span class="kv-value" id="mc-triple-align">--</span></div>
                    <div class="premium-overlay">
                        <svg class="lock-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"></rect><path d="M7 11V7a5 5 0 0110 0v4"></path></svg>
                        <span class="lock-text">Premium</span>
                        <a href="/static/pricing.html" class="lock-cta">Debloquer</a>
                    </div>
                </div>
            </div>
        </div>

        <!-- PANEL 3: ORDER FLOW (Premium) -->
        <div class="glass premium-locked" id="panel-order-flow">
            <div class="panel-header">
                <span class="panel-title">Order Flow</span>
                <span class="badge badge-cyan">ES + NQ</span>
            </div>
            <div id="order-flow-content">
                <div class="kv-row"><span class="kv-key">Delta Bar</span><span class="kv-value mono" id="of-delta">--</span></div>
                <div class="kv-row"><span class="kv-key">CVD Day</span><span class="kv-value mono" id="of-cvd">--</span></div>
                <div class="kv-row">
                    <span class="kv-key">RVOL</span>
                    <div style="flex:1;margin-left:1rem;">
                        <div style="display:flex;justify-content:space-between;">
                            <span class="kv-value mono" id="of-rvol">--x</span>
                            <span class="badge" id="of-rvol-badge">--</span>
                        </div>
                        <div class="gauge"><div class="gauge-fill gauge-cyan" id="of-rvol-gauge" style="width:0%"></div></div>
                    </div>
                </div>
                <div class="kv-row"><span class="kv-key">Absorption Score</span><span class="kv-value mono" id="of-absorption">--</span></div>
                <div class="kv-row"><span class="kv-key">Divergence Prix/Delta</span><span class="kv-value" id="of-divergence">--</span></div>
                <div class="kv-row"><span class="kv-key">Climax Signal</span><span class="kv-value" id="of-climax">--</span></div>
                <div class="kv-row"><span class="kv-key">Large Trader Ratio</span><span class="kv-value mono" id="of-ltr">--</span></div>
                <div class="kv-row"><span class="kv-key">Ask/Bid Imbalance</span><span class="kv-value mono" id="of-imbalance">--</span></div>
            </div>
            <div class="premium-overlay">
                <svg class="lock-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"></rect><path d="M7 11V7a5 5 0 0110 0v4"></path></svg>
                <span class="lock-text">Premium</span>
                <a href="/static/pricing.html" class="lock-cta">Debloquer</a>
            </div>
        </div>

        <!-- PANEL 4: OPTIONS & GAMMA (Premium) -->
        <div class="glass premium-locked" id="panel-options-gamma">
            <div class="panel-header">
                <span class="panel-title">Options & Gamma</span>
                <span class="badge badge-gold" style="background:rgba(212,175,55,0.15);color:var(--gold);">MenthorQ</span>
            </div>
            <div id="options-gamma-content">
                <div class="kv-row"><span class="kv-key">Call Wall</span><span class="kv-value mono" id="og-call">-- ticks</span></div>
                <div class="kv-row"><span class="kv-key">Put Wall</span><span class="kv-value mono" id="og-put">-- ticks</span></div>
                <div class="kv-row"><span class="kv-key">HVL</span><span class="kv-value mono" id="og-hvl">-- ticks</span></div>
                <div class="kv-row"><span class="kv-key">0DTE Call</span><span class="kv-value mono" id="og-0dte-call">-- ticks</span></div>
                <div class="kv-row"><span class="kv-key">0DTE Put</span><span class="kv-value mono" id="og-0dte-put">-- ticks</span></div>
                <div class="kv-row"><span class="kv-key">GEX Nearest Up</span><span class="kv-value mono" id="og-gex-up">-- ticks</span></div>
                <div class="kv-row"><span class="kv-key">GEX Nearest Down</span><span class="kv-value mono" id="og-gex-dn">-- ticks</span></div>
                <div class="kv-row"><span class="kv-key">GEX Clusters</span><span class="kv-value mono" id="og-gex-count">--</span></div>
                <div class="kv-row"><span class="kv-key">GEX Flip Zone</span><span class="kv-value" id="og-gex-flip">--</span></div>
                <div class="kv-row"><span class="kv-key">VIX Level</span><span class="kv-value mono" id="og-vix">--</span></div>
            </div>
            <div class="premium-overlay">
                <svg class="lock-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"></rect><path d="M7 11V7a5 5 0 0110 0v4"></path></svg>
                <span class="lock-text">Premium</span>
                <a href="/static/pricing.html" class="lock-cta">Debloquer</a>
            </div>
        </div>

        <!-- PANEL 5: INTERMARKET + AMD -->
        <div class="glass" id="panel-intermarket">
            <div class="panel-header">
                <span class="panel-title">Intermarket ES/NQ + AMD</span>
                <span id="amd-phase-badge" class="badge badge-purple">--</span>
            </div>
            <div id="intermarket-content">
                <div class="kv-row">
                    <span class="kv-key">Correlation ES/NQ</span>
                    <span class="kv-value mono" id="im-corr">--</span>
                </div>
                <div class="kv-row">
                    <span class="kv-key">Delta Agreement</span>
                    <div style="flex:1;margin-left:1rem;">
                        <span class="kv-value mono" id="im-delta-agree">--</span>
                        <div class="gauge"><div class="gauge-fill gauge-green" id="im-agree-gauge" style="width:0%"></div></div>
                    </div>
                </div>
                <div class="kv-row"><span class="kv-key">SMT Divergence</span><span class="kv-value" id="im-smt">--</span></div>
                <div id="im-premium" class="premium-locked" style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid rgba(255,255,255,0.06);">
                    <div class="kv-row"><span class="kv-key">AMD Phase</span><span class="kv-value" id="im-amd-phase">--</span></div>
                    <div class="kv-row"><span class="kv-key">Session Bias</span><span class="kv-value mono" id="im-bias">--</span></div>
                    <div class="kv-row"><span class="kv-key">PO3 Score</span><span class="kv-value mono" id="im-po3">--</span></div>
                    <div class="kv-row"><span class="kv-key">Judas Swing</span><span class="kv-value" id="im-judas">--</span></div>
                    <div class="kv-row"><span class="kv-key">Manip Score</span><span class="kv-value mono" id="im-manip">--</span></div>
                    <div class="premium-overlay">
                        <svg class="lock-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"></rect><path d="M7 11V7a5 5 0 0110 0v4"></path></svg>
                        <span class="lock-text">Premium</span>
                        <a href="/static/pricing.html" class="lock-cta">Debloquer</a>
                    </div>
                </div>
            </div>
        </div>

        <!-- PANEL 6: SIGNAUX & JOURNAL (Premium) -->
        <div class="glass premium-locked" id="panel-signals">
            <div class="panel-header">
                <span class="panel-title">Signaux & Journal</span>
                <span class="badge badge-green">LIVE</span>
            </div>
            <div id="signals-content">
                <div class="kv-row"><span class="kv-key">Signal actuel</span><span class="kv-value" id="sig-current">HOLD</span></div>
                <div class="kv-row"><span class="kv-key">Score</span><span class="kv-value mono" id="sig-score">--</span></div>
                <div class="kv-row"><span class="kv-key">SL / TP</span><span class="kv-value mono" id="sig-sltp">-- / -- ticks</span></div>
                <div class="kv-row"><span class="kv-key">R:R</span><span class="kv-value mono" id="sig-rr">--</span></div>
                <div class="kv-row"><span class="kv-key">Raison</span><span class="kv-value" id="sig-reason" style="font-size:0.75rem;max-width:60%;text-align:right;">--</span></div>
                <div style="margin-top:1rem;">
                    <span class="stat-label">Derniers trades</span>
                    <table class="data-table" style="margin-top:0.5rem;">
                        <thead><tr><th>Heure</th><th>Sym</th><th>Dir</th><th>P&L</th></tr></thead>
                        <tbody id="sig-trades-body">
                            <tr><td colspan="4" style="text-align:center;color:var(--text-disabled);">Aucun trade</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
            <div class="premium-overlay">
                <svg class="lock-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"></rect><path d="M7 11V7a5 5 0 0110 0v4"></path></svg>
                <span class="lock-text">Premium</span>
                <a href="/static/pricing.html" class="lock-cta">Debloquer</a>
            </div>
        </div>

    </main>

    <!-- FOOTER -->
    <footer class="dashboard-footer">
        <p>&copy; 2026 MIA IA SYSTEM. Tous droits reserves.</p>
        <p style="margin-top:0.5rem;">
            <a href="/terms/">CGU</a> &middot;
            <a href="/privacy/">Confidentialite</a> &middot;
            <a href="/risk/">Risques</a> &middot;
            <a href="mailto:contact@mia-ia-system.com">Contact</a>
        </p>
        <p style="margin-top:0.5rem;color:var(--text-disabled);">
            377 features &middot; Schema DMP 3.7.2 &middot; Rafraichissement 5s
        </p>
    </footer>

    <!-- JS -->
    <script src="/static/js/dashboard.js"></script>
    <script src="/static/js/ticker-widget.js"></script>
</body>
</html>
```

- [ ] **Step 3: Commit**

```bash
git add DASHBOARD/static/index.html DASHBOARD/static/css/dashboard.css
git commit -m "feat(dashboard): frontend HTML/CSS avec 6 panels et design system MIA"
```

---

## Task 3 : Frontend Dashboard — JavaScript (polling + rendering)

**Files:**
- Create: `DASHBOARD/static/js/dashboard.js`
- Create: `DASHBOARD/static/js/ticker-widget.js`

- [ ] **Step 1: Creer ticker-widget.js**

Copie adaptee du ticker.js existant (TradingView embed).

```javascript
/* TradingView Ticker Widget — MIA Dashboard */
(function () {
    const container = document.getElementById("tv-ticker");
    if (!container) return;

    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container";
    widget.innerHTML = '<div class="tradingview-widget-container__widget"></div>';
    container.appendChild(widget);

    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js";
    script.async = true;
    script.textContent = JSON.stringify({
        symbols: [
            { proName: "CME_MINI:ES1!", title: "ES" },
            { proName: "CME_MINI:NQ1!", title: "NQ" },
            { proName: "CME_MINI:RTY1!", title: "RTY" },
            { proName: "SP:SPX", title: "SPX" },
            { proName: "CBOE:VIX", title: "VIX" },
            { proName: "NYMEX:CL1!", title: "Petrole" },
            { proName: "COMEX:GC1!", title: "Or" },
            { proName: "BITSTAMP:BTCUSD", title: "BTC" }
        ],
        showSymbolLogo: false,
        isTransparent: true,
        displayMode: "compact",
        colorTheme: "dark",
        locale: "fr"
    });
    widget.appendChild(script);
})();
```

- [ ] **Step 2: Creer dashboard.js**

```javascript
/* MIA Dashboard v1.0 — Polling API + Rendering panels */
(function () {
    "use strict";

    const API_BASE = window.location.origin;
    const POLL_INTERVAL = 5000;
    let userTier = "free"; // "free" ou "premium"
    let pollTimer = null;

    /* === AUTH === */
    function getToken() {
        return localStorage.getItem("mia_token");
    }

    function getUserTier() {
        const token = getToken();
        if (!token) return "free";
        try {
            const payload = JSON.parse(atob(token.split(".")[1]));
            return payload.tier || "free";
        } catch {
            return "free";
        }
    }

    /* === API FETCH === */
    async function fetchDashboard() {
        try {
            const tier = getUserTier();
            const headers = {};
            const token = getToken();
            if (token) headers["Authorization"] = "Bearer " + token;

            const resp = await fetch(API_BASE + "/api/dashboard?tier=" + tier, { headers });
            if (!resp.ok) throw new Error("HTTP " + resp.status);
            const data = await resp.json();
            renderDashboard(data);
            updateRefreshStatus(true);
        } catch (err) {
            console.error("[MIA] Fetch error:", err);
            updateRefreshStatus(false);
        }
    }

    /* === RENDERING === */
    function renderDashboard(data) {
        userTier = data.tier || "free";
        updateLastUpdate();
        renderBotStatus(data);
        renderMarketContext(data);

        if (userTier === "premium") {
            unlockPanels();
            renderOrderFlow(data);
            renderOptionsGamma(data);
            renderIntermarket(data);
            renderSignals(data);
        }
    }

    function renderBotStatus(data) {
        const bs = data.bot_status || {};
        const badge = document.getElementById("bot-running-badge");
        if (bs.running) {
            badge.className = "badge badge-green";
            badge.innerHTML = '<span class="dot dot-green"></span> RUNNING';
        } else {
            badge.className = "badge badge-red";
            badge.innerHTML = '<span class="dot dot-red"></span> OFFLINE';
        }
        setText("bot-global-status", bs.global_status || "--");
        setText("bot-heartbeat", bs.last_heartbeat || "--");

        if (data.es) {
            renderInstrument("es", data.es);
        }
        if (data.nq) {
            renderInstrument("nq", data.nq);
        }
    }

    function renderInstrument(sym, inst) {
        const posEl = document.getElementById(sym + "-position");
        if (inst.in_position) {
            posEl.className = "badge badge-cyan";
            posEl.textContent = inst.status.includes("SHORT") ? "SHORT" :
                                inst.status.includes("LONG") ? "LONG" : "IN POSITION";
        } else {
            posEl.className = "badge badge-yellow";
            posEl.textContent = "FLAT";
        }

        const pnlEl = document.getElementById(sym + "-pnl");
        const pnl = inst.pnl_today || 0;
        pnlEl.textContent = "$" + pnl.toFixed(2);
        pnlEl.className = "kv-value mono " + (pnl >= 0 ? "stat-positive" : "stat-negative");

        setText(sym + "-trades", inst.wins + "W / " + inst.losses + "L (" + inst.trades_today + ")");
    }

    function renderMarketContext(data) {
        const mc = data.market_context || {};
        setText("mc-vix", mc.vix ? mc.vix.toFixed(2) : "--");

        const regimeEl = document.getElementById("mc-vix-regime");
        if (regimeEl) {
            regimeEl.textContent = mc.vix_regime || "--";
            regimeEl.className = "kv-value " + (
                mc.vix_regime === "LOW" ? "stat-positive" :
                mc.vix_regime === "HIGH" ? "stat-negative" : "stat-neutral"
            );
        }

        setText("mc-atr", (mc.atr_es ? mc.atr_es.toFixed(1) : "--") + " / " +
                          (mc.atr_nq ? mc.atr_nq.toFixed(1) : "--"));
        setText("mc-vwap-slope", (mc.vwap_slope_es ? mc.vwap_slope_es.toFixed(4) : "--") + " / " +
                                 (mc.vwap_slope_nq ? mc.vwap_slope_nq.toFixed(4) : "--"));

        if (mc.session_id) {
            const sb = document.getElementById("session-badge");
            sb.textContent = mc.session_id;
        }

        if (userTier === "premium" && mc.open_type_label) {
            setText("mc-open-type", mc.open_type_label);
            setText("mc-day-type", mc.day_type_label);
            setText("mc-ib-range", (mc.ib_range_ticks || 0).toFixed(1) + " ticks");
            setText("mc-profile", mc.profile_shape_label);
            setText("mc-trend-prob", ((mc.trend_day_probability || 0) * 100).toFixed(0) + "%");
            const ta = mc.vwap_triple_align;
            setText("mc-triple-align",
                ta > 0 ? "BULL" : ta < 0 ? "BEAR" : "NEUTRE");
        }
    }

    function renderOrderFlow(data) {
        const of = data.order_flow_es || data.order_flow_nq || {};
        setColoredValue("of-delta", of.delta_bar, 0);
        setText("of-cvd", formatNum(of.cvd_day));

        const rvol = of.rvol || 1.0;
        setText("of-rvol", rvol.toFixed(2) + "x");
        const rvolPct = Math.min(rvol / 5.0 * 100, 100);
        setGauge("of-rvol-gauge", rvolPct,
            rvol < 0.5 ? "gauge-red" : rvol < 2.0 ? "gauge-cyan" :
            rvol < 4.0 ? "gauge-green" : "gauge-gold");

        const rvolBadge = document.getElementById("of-rvol-badge");
        if (rvolBadge) {
            rvolBadge.textContent = of.rvol_regime_label || "Normal";
            rvolBadge.className = "badge " + (
                of.rvol_regime >= 3 ? "badge-red" :
                of.rvol_regime >= 2 ? "badge-yellow" : "badge-cyan");
        }

        setText("of-absorption", (of.absorption_score || 0).toFixed(2));
        setColoredValue("of-divergence", of.price_delta_div, 0);
        setColoredValue("of-climax", of.climax_signal, 0);
        setText("of-ltr", (of.large_trader_ratio || 0).toFixed(3));
        setColoredValue("of-imbalance", of.ask_bid_imbalance, 0);
    }

    function renderOptionsGamma(data) {
        const og = data.options_gamma_es || data.options_gamma_nq || {};
        setColoredValue("og-call", og.dist_mq_call, 0, " ticks");
        setColoredValue("og-put", og.dist_mq_put, 0, " ticks");
        setText("og-hvl", formatNum(og.dist_mq_hvl) + " ticks");
        setColoredValue("og-0dte-call", og.dist_mq_call_0dte, 0, " ticks");
        setColoredValue("og-0dte-put", og.dist_mq_put_0dte, 0, " ticks");
        setText("og-gex-up", formatNum(og.dist_gex_nearest_up) + " ticks");
        setText("og-gex-dn", formatNum(og.dist_gex_nearest_dn) + " ticks");
        setText("og-gex-count", og.gex_cluster_count || 0);
        setText("og-gex-flip", og.bool_gex_flip_zone ? "OUI" : "NON");
        setText("og-vix", (og.vix_level || 0).toFixed(2));
    }

    function renderIntermarket(data) {
        const im = data.intermarket || {};
        const corr = im.rolling_correlation || 0;
        const corrEl = document.getElementById("im-corr");
        if (corrEl) {
            corrEl.textContent = corr.toFixed(3);
            corrEl.className = "kv-value mono " + (corr < 0.80 ? "stat-negative" : "stat-positive");
        }

        const agree = im.cross_delta_agreement || 0;
        setText("im-delta-agree", agree.toFixed(2));
        setGauge("im-agree-gauge", agree * 100,
            agree < 0.4 ? "gauge-red" : agree > 0.8 ? "gauge-green" : "gauge-cyan");

        const smt = im.smt_divergence || 0;
        const smtEl = document.getElementById("im-smt");
        if (smtEl) {
            smtEl.textContent = smt > 0 ? "BULL TRAP" : smt < 0 ? "BEAR TRAP" : "AUCUNE";
            smtEl.className = "kv-value " + (smt !== 0 ? "stat-negative" : "stat-neutral");
        }

        const phase = document.getElementById("amd-phase-badge");
        if (phase) {
            phase.textContent = im.amd_phase_label || "--";
        }

        setText("im-amd-phase", im.amd_phase_label || "--");
        setColoredValue("im-bias", im.amd_session_bias, 0);
        setText("im-po3", (im.amd_po3_score || 0).toFixed(2));
        setText("im-judas", im.amd_judas_swing ? "DETECTE" : "NON");
        setText("im-manip", (im.amd_manip_score || 0).toFixed(2));
    }

    function renderSignals(data) {
        const sj = data.signals_journal || {};
        setText("sig-current", sj.current_signal || "HOLD");
        setText("sig-score", sj.signal_score ? sj.signal_score.toFixed(3) : "--");
        setText("sig-sltp", (sj.sl_ticks || "--") + " / " + (sj.tp_ticks || "--") + " ticks");
        setText("sig-rr", sj.rr_ratio ? sj.rr_ratio.toFixed(1) + ":1" : "--");
        setText("sig-reason", sj.signal_reason || "--");
    }

    /* === HELPERS === */
    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function setColoredValue(id, value, neutral, suffix) {
        const el = document.getElementById(id);
        if (!el) return;
        const v = value || 0;
        el.textContent = formatNum(v) + (suffix || "");
        el.className = "kv-value mono " + (
            v > neutral ? "stat-positive" : v < neutral ? "stat-negative" : "stat-neutral"
        );
    }

    function setGauge(id, pct, colorClass) {
        const el = document.getElementById(id);
        if (!el) return;
        el.style.width = Math.min(Math.max(pct, 0), 100) + "%";
        el.className = "gauge-fill " + colorClass;
    }

    function formatNum(n) {
        if (n === undefined || n === null) return "--";
        return typeof n === "number" ? n.toFixed(2) : String(n);
    }

    function updateLastUpdate() {
        const el = document.getElementById("last-update");
        if (el) el.textContent = new Date().toLocaleTimeString("fr-FR");
    }

    function updateRefreshStatus(ok) {
        const el = document.getElementById("refresh-status");
        if (!el) return;
        if (ok) {
            el.className = "badge badge-cyan";
            el.innerHTML = '<span class="dot dot-green"></span><span class="mono" style="font-size:0.7rem;">LIVE</span>';
        } else {
            el.className = "badge badge-red";
            el.innerHTML = '<span class="dot dot-red"></span><span class="mono" style="font-size:0.7rem;">OFFLINE</span>';
        }
    }

    function unlockPanels() {
        document.querySelectorAll(".premium-locked").forEach(function (el) {
            el.classList.remove("premium-locked");
            const overlay = el.querySelector(".premium-overlay");
            if (overlay) overlay.style.display = "none";
        });
    }

    /* === INIT === */
    function init() {
        userTier = getUserTier();
        fetchDashboard();
        pollTimer = setInterval(fetchDashboard, POLL_INTERVAL);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
```

- [ ] **Step 3: Commit**

```bash
git add DASHBOARD/static/js/
git commit -m "feat(dashboard): JS polling API + rendering 6 panels + ticker TradingView"
```

---

## Task 4 : Auth JWT (register / login / verify)

**Files:**
- Create: `DASHBOARD/api/auth.py`
- Create: `DASHBOARD/static/login.html`
- Create: `DASHBOARD/static/register.html`
- Create: `DASHBOARD/static/js/auth.js`

- [ ] **Step 1: Creer auth.py**

```python
"""Auth JWT simple — MIA Dashboard."""
import json
import os
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, EmailStr

from DASHBOARD.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY_HOURS

router = APIRouter(prefix="/api/auth", tags=["auth"])

USERS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "users.json")


class RegisterRequest(BaseModel):
    email: str
    password: str
    first_name: str = ""
    last_name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


def _load_users() -> dict:
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_users(users: dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()


def _create_token(email: str, tier: str) -> str:
    payload = {
        "sub": email,
        "tier": tier,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


@router.post("/register")
async def register(req: RegisterRequest):
    users = _load_users()
    if req.email in users:
        raise HTTPException(400, "Email deja utilise")
    salt = secrets.token_hex(16)
    users[req.email] = {
        "password_hash": _hash_password(req.password, salt),
        "salt": salt,
        "first_name": req.first_name,
        "last_name": req.last_name,
        "tier": "free",
        "created": datetime.now(timezone.utc).isoformat(),
    }
    _save_users(users)
    token = _create_token(req.email, "free")
    return {"token": token, "tier": "free"}


@router.post("/login")
async def login(req: LoginRequest):
    users = _load_users()
    user = users.get(req.email)
    if not user:
        raise HTTPException(401, "Email ou mot de passe incorrect")
    if _hash_password(req.password, user["salt"]) != user["password_hash"]:
        raise HTTPException(401, "Email ou mot de passe incorrect")
    token = _create_token(req.email, user.get("tier", "free"))
    return {"token": token, "tier": user.get("tier", "free")}


def get_current_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    if not authorization:
        return None
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expire")
    except jwt.InvalidTokenError:
        return None


def get_user_tier(authorization: Optional[str] = Header(None)) -> str:
    user = get_current_user(authorization)
    return user.get("tier", "free") if user else "free"
```

- [ ] **Step 2: Ajouter les routes auth dans app.py**

Ajouter `from DASHBOARD.api.auth import router as auth_router` et `app.include_router(auth_router)` dans app.py.

Modifier aussi le endpoint `/api/dashboard` pour lire le tier depuis le token :

```python
from DASHBOARD.api.auth import router as auth_router, get_user_tier

app.include_router(auth_router)

@app.get("/api/dashboard")
async def get_dashboard(authorization: str = Header(None)):
    tier = get_user_tier(authorization)
    # ... reste du code avec tier dynamique
```

- [ ] **Step 3: Creer auth.js**

```javascript
/* MIA Auth — Login/Register/Token management */
(function () {
    "use strict";

    const API_BASE = window.location.origin;

    async function handleLogin(e) {
        e.preventDefault();
        const email = document.getElementById("login-email").value;
        const password = document.getElementById("login-password").value;
        const errorEl = document.getElementById("login-error");

        try {
            const resp = await fetch(API_BASE + "/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password }),
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || "Erreur");
            localStorage.setItem("mia_token", data.token);
            window.location.href = "/";
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.style.display = "block";
        }
    }

    async function handleRegister(e) {
        e.preventDefault();
        const first_name = document.getElementById("reg-firstname").value;
        const last_name = document.getElementById("reg-lastname").value;
        const email = document.getElementById("reg-email").value;
        const password = document.getElementById("reg-password").value;
        const confirm = document.getElementById("reg-confirm").value;
        const errorEl = document.getElementById("reg-error");

        if (password !== confirm) {
            errorEl.textContent = "Les mots de passe ne correspondent pas";
            errorEl.style.display = "block";
            return;
        }

        try {
            const resp = await fetch(API_BASE + "/api/auth/register", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password, first_name, last_name }),
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || "Erreur");
            localStorage.setItem("mia_token", data.token);
            window.location.href = "/";
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.style.display = "block";
        }
    }

    /* Bind forms */
    const loginForm = document.getElementById("login-form");
    if (loginForm) loginForm.addEventListener("submit", handleLogin);

    const regForm = document.getElementById("register-form");
    if (regForm) regForm.addEventListener("submit", handleRegister);
})();
```

- [ ] **Step 4: Creer login.html et register.html**

Pages reprenant exactement le design system existant (fond #0A0E17, blobs cyan/gold, glass card, inputs dark-200, bouton gradient cyan). Les formulaires appellent auth.js au lieu d'etre des forms visuels sans backend.

- [ ] **Step 5: Installer PyJWT sur le VPS**

```bash
pip install PyJWT
```

- [ ] **Step 6: Commit**

```bash
git add DASHBOARD/api/auth.py DASHBOARD/static/login.html DASHBOARD/static/register.html DASHBOARD/static/js/auth.js
git commit -m "feat(dashboard): auth JWT register/login + pages frontend"
```

---

## Task 5 : Images et assets statiques

**Files:**
- Copy: images depuis mia-website vers DASHBOARD/static/images/

- [ ] **Step 1: Copier les assets depuis mia-website**

```bash
mkdir -p D:/TRADING_SIERRA_CHART_AUTO/DASHBOARD/static/images
cp D:/mia-website/images/logo-dark.jpg D:/TRADING_SIERRA_CHART_AUTO/DASHBOARD/static/images/
cp D:/mia-website/images/favicon-32x32.png D:/TRADING_SIERRA_CHART_AUTO/DASHBOARD/static/images/
cp D:/mia-website/images/favicon-16x16.png D:/TRADING_SIERRA_CHART_AUTO/DASHBOARD/static/images/
cp D:/mia-website/images/og-image.png D:/TRADING_SIERRA_CHART_AUTO/DASHBOARD/static/images/
```

- [ ] **Step 2: Commit**

```bash
git add DASHBOARD/static/images/
git commit -m "chore(dashboard): copie assets images depuis mia-website"
```

---

## CHANTIER B — Deploiement VPS

## Task 6 : Script de deploiement et demarrage VPS

**Files:**
- Create: `DASHBOARD/deploy.sh`

Le VPS est Windows Server. On utilise :
- **Uvicorn** directement (pas de nginx, pas de reverse proxy pour la phase 1)
- **Port 8000** expose sur l'IP publique `212.28.179.199`
- **Windows Task Scheduler** pour la persistance apres reboot

- [ ] **Step 1: Creer deploy.sh**

```bash
#!/bin/bash
# Deploy MIA Dashboard vers VPS
# Usage: bash DASHBOARD/deploy.sh

VPS="Administrator@212.28.179.199"
REMOTE_DIR="C:/TRADING_SIERRA_CHART_AUTO/DASHBOARD"

echo "[DEPLOY] Copie des fichiers dashboard vers VPS..."

# Creer la structure sur le VPS
ssh $VPS "mkdir -p \"$REMOTE_DIR/api\" \"$REMOTE_DIR/static/css\" \"$REMOTE_DIR/static/js\" \"$REMOTE_DIR/static/images\""

# Backend Python
scp DASHBOARD/config.py "$VPS:\"$REMOTE_DIR/\""
scp DASHBOARD/start_dashboard.py "$VPS:\"$REMOTE_DIR/\""
scp DASHBOARD/api/__init__.py "$VPS:\"$REMOTE_DIR/api/\""
scp DASHBOARD/api/app.py "$VPS:\"$REMOTE_DIR/api/\""
scp DASHBOARD/api/data_reader.py "$VPS:\"$REMOTE_DIR/api/\""
scp DASHBOARD/api/models.py "$VPS:\"$REMOTE_DIR/api/\""
scp DASHBOARD/api/auth.py "$VPS:\"$REMOTE_DIR/api/\""

# Frontend
scp DASHBOARD/static/index.html "$VPS:\"$REMOTE_DIR/static/\""
scp DASHBOARD/static/login.html "$VPS:\"$REMOTE_DIR/static/\""
scp DASHBOARD/static/register.html "$VPS:\"$REMOTE_DIR/static/\""
scp DASHBOARD/static/css/dashboard.css "$VPS:\"$REMOTE_DIR/static/css/\""
scp DASHBOARD/static/js/dashboard.js "$VPS:\"$REMOTE_DIR/static/js/\""
scp DASHBOARD/static/js/auth.js "$VPS:\"$REMOTE_DIR/static/js/\""
scp DASHBOARD/static/js/ticker-widget.js "$VPS:\"$REMOTE_DIR/static/js/\""
scp -r DASHBOARD/static/images/ "$VPS:\"$REMOTE_DIR/static/images/\""

echo "[DEPLOY] Installation des dependances Python..."
ssh $VPS "pip install fastapi uvicorn PyJWT"

echo "[DEPLOY] Demarrage du dashboard..."
ssh $VPS "cd C:/TRADING_SIERRA_CHART_AUTO && start /B pythonw -m uvicorn DASHBOARD.api.app:app --host 0.0.0.0 --port 8000"

echo "[DEPLOY] Dashboard deploye sur http://212.28.179.199:8000"
echo "[DEPLOY] ATTENTION: configurer Windows Task Scheduler pour persistance apres reboot"
```

- [ ] **Step 2: Installer HTTPS avec Caddy (recommande mais optionnel phase 1)**

Pour HTTPS automatique sur le domaine `mia-ia-system.com` :

```bash
# Sur le VPS (PowerShell admin)
# 1. Telecharger Caddy
Invoke-WebRequest -Uri "https://caddyserver.com/api/download?os=windows&arch=amd64" -OutFile "C:\caddy\caddy.exe"

# 2. Creer Caddyfile
# mia-ia-system.com {
#     reverse_proxy localhost:8000
# }

# 3. Lancer Caddy
# C:\caddy\caddy.exe run --config C:\caddy\Caddyfile
```

Note : Caddy genere automatiquement les certificats Let's Encrypt. Pas besoin de configurer manuellement. Mais le DNS du domaine `mia-ia-system.com` doit pointer vers `212.28.179.199`.

- [ ] **Step 3: Commit**

```bash
git add DASHBOARD/deploy.sh
git commit -m "feat(dashboard): script deploiement VPS + instructions Caddy HTTPS"
```

---

## CHANTIER C — Monetisation

## Task 7 : Page Pricing + Integration Stripe

**Files:**
- Create: `DASHBOARD/static/pricing.html`
- Create: `DASHBOARD/api/stripe_webhooks.py`

### Offre de monetisation

| Plan | Prix | Contenu |
|------|------|---------|
| **Gratuit** | 0 EUR/mois | Bot status basique, VIX/ATR, VWAP slope, correlation ES/NQ basique |
| **Starter** | 19 EUR/mois | + Market Context complet (Open Type, Day Type, IB, Profile), + Intermarket complet (AMD, SMT, PO3) |
| **Premium** | 49 EUR/mois | + Order Flow, + Options & Gamma, + Signaux & Journal, + Alertes Discord prioritaires |

### Cadre legal

**IMPORTANT** : Vendre des "analyses de marche" generees automatiquement par une IA n'est PAS du conseil en investissement personnalise. C'est un outil d'aide a la decision, comme un terminal Bloomberg ou TradingView.

Conditions :
- TOUJOURS afficher "Ceci n'est pas un conseil en investissement" sur chaque page
- JAMAIS de recommandation personnalisee (pas de "achetez ES maintenant")
- Presenter les donnees comme des INDICATEURS, pas des SIGNAUX d'achat/vente
- La page /risk/ existante couvre deja les disclaimers requis

- [ ] **Step 1: Creer stripe_webhooks.py**

```python
"""Stripe integration — MIA Dashboard subscriptions."""
import json
import os
from fastapi import APIRouter, Request, HTTPException

import stripe

from DASHBOARD.config import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET

router = APIRouter(prefix="/api/stripe", tags=["stripe"])

stripe.api_key = STRIPE_SECRET_KEY

PRICES = {
    "starter": os.environ.get("STRIPE_PRICE_STARTER", ""),
    "premium": os.environ.get("STRIPE_PRICE_PREMIUM", ""),
}

USERS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "users.json")


@router.post("/create-checkout")
async def create_checkout(request: Request):
    """Cree une session Stripe Checkout."""
    body = await request.json()
    plan = body.get("plan", "starter")
    email = body.get("email", "")

    price_id = PRICES.get(plan)
    if not price_id:
        raise HTTPException(400, "Plan invalide")

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        customer_email=email,
        success_url=request.base_url._url + "?payment=success",
        cancel_url=request.base_url._url + "static/pricing.html?payment=cancel",
    )
    return {"url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Webhook Stripe — met a jour le tier utilisateur."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(400, "Webhook invalide")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email", "")
        # Determiner le plan depuis le prix
        line_items = stripe.checkout.Session.list_line_items(session["id"])
        price_id = line_items.data[0].price.id if line_items.data else ""

        tier = "free"
        for plan_name, pid in PRICES.items():
            if pid == price_id:
                tier = plan_name
                break

        _update_user_tier(email, tier)

    elif event["type"] == "customer.subscription.deleted":
        sub = event["data"]["object"]
        email = sub.get("customer_email", "")
        _update_user_tier(email, "free")

    return {"status": "ok"}


def _update_user_tier(email: str, tier: str):
    """Met a jour le tier d'un utilisateur dans users.json."""
    if not os.path.exists(USERS_FILE):
        return
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    if email in users:
        users[email]["tier"] = tier
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
```

- [ ] **Step 2: Ajouter le router Stripe dans app.py**

```python
from DASHBOARD.api.stripe_webhooks import router as stripe_router
app.include_router(stripe_router)
```

- [ ] **Step 3: Creer pricing.html**

Page avec 3 cards (Gratuit / Starter / Premium), design system MIA, boutons Stripe Checkout.

- [ ] **Step 4: Commit**

```bash
git add DASHBOARD/api/stripe_webhooks.py DASHBOARD/static/pricing.html
git commit -m "feat(dashboard): integration Stripe subscriptions + page pricing"
```

---

## Task 8 : Mise a jour du bot pour ecrire les features dans le dashboard JSON

**Files:**
- Modify: `BOT/bot_main.py` (ajouter l'ecriture des features dans dashboard.json)

Le bot ecrit deja `MIA_AutoTrader_Dashboard.json` mais seulement avec les infos basiques (status, P&L, warnings). Il faut enrichir ce JSON avec les features live pour que l'API du dashboard puisse les servir.

- [ ] **Step 1: Ajouter les features dans le JSON du bot**

Dans bot_main.py, apres le calcul des features (dans la boucle principale), ajouter l'ecriture des features cles dans le dashboard JSON. Le bot a deja `self._features_cache[symbol]` — il suffit d'ecrire les champs pertinents.

Ajouter un nouveau bloc dans la methode `_write_dashboard_json()` :

```python
def _write_dashboard_json(self):
    """Ecrit le fichier dashboard JSON avec status + features live."""
    data = {
        "bot_status": { ... },  # existant
        "es": { ... },          # existant
        "nq": { ... },          # existant
        "schedule": { ... },    # existant
        "warnings": { ... },    # existant
        "market_live": { ... }, # existant
        "features_es": self._get_dashboard_features("ES"),  # NOUVEAU
        "features_nq": self._get_dashboard_features("NQ"),  # NOUVEAU
    }
    with open(DASHBOARD_JSON, "w") as f:
        json.dump(data, f, indent=2)

def _get_dashboard_features(self, symbol):
    """Extrait les features pertinentes pour le dashboard."""
    cache = self._features_cache.get(symbol, {})
    if not cache:
        return {}
    return {
        # Order Flow
        "delta_bar": cache.get("delta_bar", 0),
        "delta_pct": cache.get("delta_pct", 0),
        "cvd_day": cache.get("cvd_day", 0),
        "rvol": cache.get("rvol", 1.0),
        "ctx_absorption_score_5": cache.get("ctx_absorption_score_5", 0),
        "ctx_price_delta_div_3": cache.get("ctx_price_delta_div_3", 0),
        "ctx_climax_signal": cache.get("ctx_climax_signal", 0),
        "large_trader_ratio": cache.get("large_trader_ratio", 0),
        "ask_bid_imbalance": cache.get("ask_bid_imbalance", 0),
        "finish_strength": cache.get("finish_strength", 0),
        # Options Gamma
        "dist_mq_call": cache.get("dist_mq_call", 0),
        "dist_mq_put": cache.get("dist_mq_put", 0),
        "dist_mq_hvl": cache.get("dist_mq_hvl", 0),
        "dist_mq_call_0dte": cache.get("dist_mq_call_0dte", 0),
        "dist_mq_put_0dte": cache.get("dist_mq_put_0dte", 0),
        "dist_gex_nearest_up": cache.get("dist_gex_nearest_up", 0),
        "dist_gex_nearest_dn": cache.get("dist_gex_nearest_dn", 0),
        "gex_cluster_count": cache.get("gex_cluster_count", 0),
        "bool_gex_flip_zone": cache.get("bool_gex_flip_zone", False),
        # Intermarket + AMD
        "im_cross_delta_agreement_5": cache.get("im_cross_delta_agreement_5", 0),
        "im_smt_divergence": cache.get("im_smt_divergence", 0),
        "im_rolling_correlation_10": cache.get("im_rolling_correlation_10", 1.0),
        "im_price_ratio_slope_10": cache.get("im_price_ratio_slope_10", 0),
        "amd_phase": cache.get("amd_phase", 0),
        "amd_session_bias": cache.get("amd_session_bias", 0),
        "amd_po3_score": cache.get("amd_po3_score", 0),
        "amd_judas_swing": cache.get("amd_judas_swing", False),
        "amd_manip_score": cache.get("amd_manip_score", 0),
        # Market Context
        "open_type": cache.get("open_type", 0),
        "day_type": cache.get("day_type", 2),
        "profile_shape": cache.get("profile_shape", 0),
        "ib_range_ticks": cache.get("ib_range_ticks", 0),
        "ib_broken_up": cache.get("ib_broken_up", False),
        "ib_broken_down": cache.get("ib_broken_down", False),
        "trend_day_probability": cache.get("trend_day_probability", 0),
        "vwap_triple_align": cache.get("vwap_triple_align", 0),
        "poc_position": cache.get("poc_position", 0),
        "vwap_d_side": cache.get("vwap_d_side", 0),
        "session_id": cache.get("session_id", ""),
    }
```

- [ ] **Step 2: Mettre a jour data_reader.py pour lire les features depuis le dashboard JSON**

Au lieu de relire les JSONL (lent), lire directement depuis le dashboard JSON enrichi :

```python
def read_features(symbol: str) -> dict:
    """Lit les features live depuis le dashboard JSON (ecrit par le bot)."""
    bot_data = read_bot_status()
    return bot_data.get(f"features_{symbol.lower()}", {})
```

- [ ] **Step 3: Commit**

```bash
git add BOT/bot_main.py DASHBOARD/api/data_reader.py
git commit -m "feat(bot+dashboard): bot ecrit features live dans dashboard.json"
```

---

## Task 9 : Tests

**Files:**
- Create: `DASHBOARD/tests/test_data_reader.py`
- Create: `DASHBOARD/tests/test_api.py`

- [ ] **Step 1: Creer test_data_reader.py**

```python
"""Tests unitaires data_reader."""
import json
import os
import tempfile
import pytest

# Override config avant import
os.environ["MIA_DASHBOARD_JSON"] = ""

from DASHBOARD.api.data_reader import (
    get_field, build_market_context_basic, build_order_flow,
    build_options_gamma, build_intermarket,
    OPEN_TYPE_LABELS, DAY_TYPE_LABELS, PROFILE_SHAPE_LABELS,
)


def test_get_field_normal():
    assert get_field({"x": 42.0}, "x") == 42.0

def test_get_field_missing():
    assert get_field({}, "x", 99.0) == 99.0

def test_get_field_invalid():
    assert get_field({"x": "INVALID"}, "x", 0.0) == 0.0

def test_get_field_none():
    assert get_field({"x": None}, "x", 5.0) == 5.0

def test_build_market_context_basic():
    bot_data = {"market_live": {"vix": 16.5, "vix_regime": "NORMAL", "atr_es": 70.0, "atr_nq": 350.0, "vwap_slope_es": 0.001, "vwap_slope_nq": -0.002}}
    result = build_market_context_basic(bot_data)
    assert result["vix"] == 16.5
    assert result["vix_regime"] == "NORMAL"

def test_build_order_flow():
    bar = {"delta_bar": 150.0, "delta_pct": 0.25, "cvd_day": 5000.0, "rvol": 2.5, "finish_strength": 0.8}
    result = build_order_flow(bar)
    assert result["delta_bar"] == 150.0
    assert result["rvol"] == 2.5

def test_build_options_gamma():
    bar = {"dist_mq_call": 50.0, "dist_mq_put": -30.0, "dist_mq_hvl": 10.0, "vix_level": 18.0}
    result = build_options_gamma(bar)
    assert result["dist_mq_call"] == 50.0
    assert result["vix_level"] == 18.0

def test_build_intermarket():
    bar = {"im_cross_delta_agreement_5": 0.85, "im_smt_divergence": 1, "amd_phase": 2}
    result = build_intermarket(bar, None)
    assert result["cross_delta_agreement"] == 0.85
    assert result["smt_divergence"] == 1
    assert result["amd_phase_label"] == "US"

def test_labels_complete():
    assert len(OPEN_TYPE_LABELS) == 12
    assert len(DAY_TYPE_LABELS) == 5
    assert len(PROFILE_SHAPE_LABELS) == 4
```

- [ ] **Step 2: Lancer les tests**

```bash
cd D:\TRADING_SIERRA_CHART_AUTO
python -m pytest DASHBOARD/tests/test_data_reader.py -v
# Expected: tous PASS
```

- [ ] **Step 3: Commit**

```bash
git add DASHBOARD/tests/
git commit -m "test(dashboard): tests unitaires data_reader + API"
```

---

## Task 10 : Briefing MIA — Generateur d'analyses quotidiennes

**Files:**
- Create: `DASHBOARD/api/briefing.py`
- Create: `DASHBOARD/static/briefing.html`
- Create: `DASHBOARD/briefing_template.py`

C'est LE produit premium. Les gens ne paient pas pour des chiffres bruts — ils paient pour de l'interpretation. Le Briefing MIA est une analyse quotidienne publiee avant l'ouverture US.

- [ ] **Step 1: Creer briefing.py (API)**

```python
"""Briefing MIA — Analyse quotidienne automatique."""
import json
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Header
from DASHBOARD.api.auth import get_user_tier
from DASHBOARD.api.data_reader import read_bot_status, read_last_bar, get_field

router = APIRouter(prefix="/api/briefing", tags=["briefing"])

BRIEFINGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "briefings")
os.makedirs(BRIEFINGS_DIR, exist_ok=True)

OPEN_TYPE_LABELS = {
    0: "UNKNOWN", 1: "Open Drive UP (conf 85%)", 2: "Open Drive DOWN (conf 85%)",
    3: "Open Test Drive UP (conf 70%)", 4: "Open Test Drive DOWN (conf 70%)",
    5: "Open Rejection Reversal UP (conf 60%)", 6: "Open Rejection Reversal DOWN (conf 60%)",
    7: "Open Auction In Range (conf 30%)", 8: "Open Auction Out of Range UP (conf 65%)",
    9: "Open Auction Out of Range DOWN (conf 65%)",
    10: "Open Drive Failed UP (conf 90%)", 11: "Open Drive Failed DOWN (conf 90%)",
}

VIX_REGIME_DESC = {
    "LOW": "Regime de faible volatilite — mouvements directionnels favorises, compression des primes options",
    "NORMAL": "Regime standard — conditions equilibrees, spreads normaux",
    "HIGH": "Regime de haute volatilite — mouvements amplifies, stops elargis recommandes, prudence accrue",
}


def generate_briefing(date_str: str = None) -> dict:
    """Genere le briefing du jour a partir des donnees live."""
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    bot_data = read_bot_status()
    bar_es = read_last_bar("ES") or {}
    bar_nq = read_last_bar("NQ") or {}
    ml = bot_data.get("market_live", {})

    vix = ml.get("vix", 0)
    vix_regime = ml.get("vix_regime", "NORMAL")
    atr_es = ml.get("atr_es", 0)
    atr_nq = ml.get("atr_nq", 0)

    ot_es = int(get_field(bar_es, "open_type", 0))
    ot_nq = int(get_field(bar_nq, "open_type", 0))

    briefing = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": {
            "macro": {
                "title": "Contexte Macro",
                "vix": vix,
                "vix_regime": vix_regime,
                "vix_desc": VIX_REGIME_DESC.get(vix_regime, ""),
                "atr_es": atr_es,
                "atr_nq": atr_nq,
                "ovn_range_es": get_field(bar_es, "ovn_range_ticks"),
                "ovn_range_nq": get_field(bar_nq, "ovn_range_ticks"),
                "open_gap_es": get_field(bar_es, "open_gap_ticks"),
                "open_gap_nq": get_field(bar_nq, "open_gap_ticks"),
            },
            "niveaux_cles": {
                "title": "Niveaux Cles du Jour",
                "es": {
                    "call_wall": get_field(bar_es, "dist_mq_call"),
                    "put_wall": get_field(bar_es, "dist_mq_put"),
                    "hvl": get_field(bar_es, "dist_mq_hvl"),
                    "gex_up": get_field(bar_es, "dist_gex_nearest_up"),
                    "gex_dn": get_field(bar_es, "dist_gex_nearest_dn"),
                    "vwap_sd1u": get_field(bar_es, "dist_vwap_d_sd1u"),
                    "vwap_sd1d": get_field(bar_es, "dist_vwap_d_sd1d"),
                    "prev_vpoc": get_field(bar_es, "dist_prev_vpoc"),
                    "ib_high": get_field(bar_es, "dist_ib_high"),
                    "ib_low": get_field(bar_es, "dist_ib_low"),
                },
                "nq": {
                    "call_wall": get_field(bar_nq, "dist_mq_call"),
                    "put_wall": get_field(bar_nq, "dist_mq_put"),
                    "hvl": get_field(bar_nq, "dist_mq_hvl"),
                    "gex_up": get_field(bar_nq, "dist_gex_nearest_up"),
                    "gex_dn": get_field(bar_nq, "dist_gex_nearest_dn"),
                    "vwap_sd1u": get_field(bar_nq, "dist_vwap_d_sd1u"),
                    "vwap_sd1d": get_field(bar_nq, "dist_vwap_d_sd1d"),
                    "prev_vpoc": get_field(bar_nq, "dist_prev_vpoc"),
                },
            },
            "biais": {
                "title": "Biais Directionnel",
                "open_type_es": OPEN_TYPE_LABELS.get(ot_es, "UNKNOWN"),
                "open_type_nq": OPEN_TYPE_LABELS.get(ot_nq, "UNKNOWN"),
                "day_type_es": int(get_field(bar_es, "day_type", 2)),
                "day_type_nq": int(get_field(bar_nq, "day_type", 2)),
                "amd_bias_es": get_field(bar_es, "amd_session_bias"),
                "amd_bias_nq": get_field(bar_nq, "amd_session_bias"),
                "po3_score_es": get_field(bar_es, "amd_po3_score"),
                "po3_score_nq": get_field(bar_nq, "amd_po3_score"),
                "vwap_triple_es": int(get_field(bar_es, "vwap_triple_align", 0)),
                "vwap_triple_nq": int(get_field(bar_nq, "vwap_triple_align", 0)),
            },
            "institutionnel": {
                "title": "Positionnement Institutionnel",
                "gex_clusters_es": int(get_field(bar_es, "gex_cluster_count", 0)),
                "gex_clusters_nq": int(get_field(bar_nq, "gex_cluster_count", 0)),
                "gex_flip_es": bool(get_field(bar_es, "bool_gex_flip_zone", 0)),
                "gex_flip_nq": bool(get_field(bar_nq, "bool_gex_flip_zone", 0)),
                "smt_divergence": int(get_field(bar_es, "im_smt_divergence", 0)),
                "cross_delta_agree": get_field(bar_es, "im_cross_delta_agreement_5"),
                "correlation": get_field(bar_es, "im_rolling_correlation_10", 1.0),
                "large_trader_es": get_field(bar_es, "large_trader_ratio"),
                "large_trader_nq": get_field(bar_nq, "large_trader_ratio"),
            },
        },
        "commentary": "",  # Jackson ajoute son commentaire manuellement
        "disclaimer": "Ceci est un outil d'aide a la decision, PAS un conseil en investissement. Tradez a vos propres risques.",
    }

    # Sauvegarder le briefing
    path = os.path.join(BRIEFINGS_DIR, f"{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(briefing, f, indent=2, ensure_ascii=False)

    return briefing


@router.get("/today")
async def get_today_briefing(authorization: str = Header(None)):
    """Retourne le briefing du jour."""
    tier = get_user_tier(authorization)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(BRIEFINGS_DIR, f"{today}.json")

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            briefing = json.load(f)
    else:
        briefing = generate_briefing(today)

    # FREE : seulement le titre et l'apercu macro
    if tier == "free":
        return {
            "date": briefing["date"],
            "preview": True,
            "sections": {
                "macro": {
                    "title": briefing["sections"]["macro"]["title"],
                    "vix": briefing["sections"]["macro"]["vix"],
                    "vix_regime": briefing["sections"]["macro"]["vix_regime"],
                },
            },
            "locked_sections": ["niveaux_cles", "biais", "institutionnel"],
            "disclaimer": briefing["disclaimer"],
        }

    return briefing


@router.get("/archive/{date_str}")
async def get_archived_briefing(date_str: str, authorization: str = Header(None)):
    """Retourne un briefing archive."""
    tier = get_user_tier(authorization)
    if tier == "free":
        return {"error": "Briefings archives reserves aux membres Starter+"}
    path = os.path.join(BRIEFINGS_DIR, f"{date_str}.json")
    if not os.path.exists(path):
        return {"error": "Briefing non disponible pour cette date"}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
```

- [ ] **Step 2: Ajouter le router briefing dans app.py**

```python
from DASHBOARD.api.briefing import router as briefing_router
app.include_router(briefing_router)
```

- [ ] **Step 3: Creer briefing.html**

Page HTML dediee affichant le briefing du jour avec :
- Header avec date + badge "Analyse MIA"
- Section Macro : VIX gauge, ATR, overnight range, gap
- Section Niveaux : tableau ES/NQ avec call/put/hvl/gex/vwap/ib (distances en ticks)
- Section Biais : Open Type avec badge confiance, VWAP triple align, AMD bias
- Section Institutionnel : GEX clusters, SMT, correlation, large trader ratio
- Zone commentaire Jackson (editable via API admin)
- Disclaimer en footer

Design : meme `.glass` cards, meme palette, meme fonts que le dashboard principal.
Les sections premium sont floutees avec CTA "Debloquer" pour les free.

- [ ] **Step 4: Commit**

```bash
git add DASHBOARD/api/briefing.py DASHBOARD/static/briefing.html
git commit -m "feat(dashboard): Briefing MIA quotidien — generateur + page + API"
```

---

## Task 11 : Sidebar CTA + Bandeau + Toast alertes

**Files:**
- Modify: `DASHBOARD/static/index.html` (ajouter sidebar + bandeau + toast container)
- Modify: `DASHBOARD/static/css/dashboard.css` (styles sidebar + bandeau + toast)
- Modify: `DASHBOARD/static/js/dashboard.js` (logique bandeau + toast + fetch briefing)

- [ ] **Step 1: Ajouter les styles CTA dans dashboard.css**

```css
/* === BANDEAU CTA (sous ticker) === */
.cta-banner {
    position: fixed;
    top: calc(var(--ticker-height) + var(--navbar-height));
    left: 0;
    right: 0;
    height: 40px;
    background: linear-gradient(90deg, rgba(0,180,220,0.1), rgba(212,175,55,0.1));
    border-bottom: 1px solid rgba(212, 175, 55, 0.2);
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.75rem;
    z-index: 90;
    font-size: 0.8125rem;
}

.cta-banner-text { color: var(--text-secondary); }

.cta-banner-link {
    color: var(--gold);
    font-weight: 600;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
}

.cta-banner-link:hover { color: var(--cyan); }

.cta-banner-close {
    position: absolute;
    right: 1rem;
    background: none;
    border: none;
    color: var(--text-disabled);
    cursor: pointer;
    font-size: 1rem;
}

/* Body padding ajuste quand bandeau actif */
body.has-banner {
    padding-top: calc(var(--ticker-height) + var(--navbar-height) + 40px);
}

/* === LAYOUT AVEC SIDEBAR === */
.dashboard-layout {
    display: grid;
    grid-template-columns: 1fr 280px;
    gap: var(--panel-gap);
    max-width: 1400px;
    margin: 0 auto;
    padding: var(--panel-gap);
}

@media (max-width: 1024px) {
    .dashboard-layout { grid-template-columns: 1fr; }
    .sidebar { display: none; }
}

.dashboard-main {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--panel-gap);
}

@media (max-width: 768px) {
    .dashboard-main { grid-template-columns: 1fr; }
}

/* === SIDEBAR === */
.sidebar {
    display: flex;
    flex-direction: column;
    gap: var(--panel-gap);
    position: sticky;
    top: calc(var(--ticker-height) + var(--navbar-height) + var(--panel-gap));
    height: fit-content;
}

.sidebar-card {
    background: rgba(13, 19, 33, 0.8);
    backdrop-filter: blur(24px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: var(--panel-radius);
    padding: 1rem;
}

.sidebar-card-title {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin-bottom: 0.75rem;
}

/* Briefing preview */
.briefing-preview {
    font-size: 0.8125rem;
    color: var(--text-secondary);
    line-height: 1.5;
    margin-bottom: 0.75rem;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

/* CTA buttons sidebar */
.sidebar-cta {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.625rem;
    border-radius: 0.5rem;
    text-decoration: none;
    color: var(--text-secondary);
    transition: background 0.2s;
    font-size: 0.8125rem;
}

.sidebar-cta:hover {
    background: rgba(255, 255, 255, 0.05);
    color: var(--text-primary);
}

.sidebar-cta-icon {
    width: 36px;
    height: 36px;
    border-radius: 0.5rem;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}

.sidebar-cta-icon.discord { background: rgba(88, 101, 242, 0.15); color: #5865F2; }
.sidebar-cta-icon.youtube { background: rgba(255, 0, 0, 0.15); color: #FF0000; }
.sidebar-cta-icon.affiliate { background: rgba(0, 200, 83, 0.15); color: var(--green); }

/* Newsletter input */
.newsletter-input {
    width: 100%;
    padding: 0.5rem 0.75rem;
    background: var(--bg-input);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 0.5rem;
    color: var(--text-primary);
    font-size: 0.8125rem;
    outline: none;
}

.newsletter-input:focus { border-color: var(--cyan); }

.newsletter-btn {
    width: 100%;
    margin-top: 0.5rem;
    padding: 0.5rem;
    background: linear-gradient(to right, var(--cyan), var(--cyan-dark));
    color: var(--bg-base);
    border: none;
    border-radius: 0.5rem;
    font-weight: 600;
    font-size: 0.8125rem;
    cursor: pointer;
}

/* === TOAST ALERTES === */
.toast-container {
    position: fixed;
    bottom: 1.5rem;
    right: 1.5rem;
    z-index: 200;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
}

.toast {
    background: rgba(13, 19, 33, 0.95);
    backdrop-filter: blur(24px);
    border: 1px solid rgba(0, 180, 220, 0.3);
    border-radius: 0.75rem;
    padding: 0.75rem 1rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    min-width: 300px;
    animation: toast-in 0.3s ease-out;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.toast-buy { border-color: rgba(0, 200, 83, 0.4); }
.toast-sell { border-color: rgba(255, 82, 82, 0.4); }

.toast-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    animation: pulse 1.5s infinite;
}

.toast-buy .toast-dot { background: var(--green); }
.toast-sell .toast-dot { background: var(--red); }

.toast-text {
    flex: 1;
    font-size: 0.8125rem;
}

.toast-cta {
    font-size: 0.75rem;
    color: var(--gold);
    text-decoration: none;
    font-weight: 600;
    white-space: nowrap;
}

@keyframes toast-in {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
}
```

- [ ] **Step 2: Modifier index.html — Layout avec sidebar**

Remplacer `<main class="dashboard-grid">` par le nouveau layout :

```html
<!-- BANDEAU CTA -->
<div class="cta-banner" id="cta-banner">
    <span class="cta-banner-text">Briefing MIA du <span id="banner-date">--/--</span></span>
    <a href="/static/briefing.html" class="cta-banner-link">
        Niveaux cles ES/NQ — Lire →
    </a>
    <button class="cta-banner-close" onclick="this.parentElement.remove();document.body.classList.remove('has-banner');">&times;</button>
</div>

<div class="dashboard-layout">
    <!-- PANELS PRINCIPAUX (grille 2x3) -->
    <main class="dashboard-main">
        <!-- ... les 6 panels existants ... -->
    </main>

    <!-- SIDEBAR DROITE -->
    <aside class="sidebar">
        <!-- Briefing MIA -->
        <div class="sidebar-card">
            <div class="sidebar-card-title">Briefing MIA</div>
            <div id="briefing-badge" class="badge badge-cyan" style="margin-bottom:0.5rem;">Analyse du jour</div>
            <p class="briefing-preview" id="briefing-preview">
                Chargement de l'analyse...
            </p>
            <a href="/static/briefing.html" class="sidebar-cta" style="background:linear-gradient(to right, var(--cyan), var(--cyan-dark));color:var(--bg-base);justify-content:center;font-weight:600;border-radius:0.5rem;">
                Lire l'analyse →
            </a>
        </div>

        <!-- Discord -->
        <div class="sidebar-card">
            <a href="https://discord.gg/mia-ia-system" target="_blank" class="sidebar-cta">
                <div class="sidebar-cta-icon discord">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03z"/></svg>
                </div>
                <div>
                    <div style="font-weight:600;color:var(--text-primary);">Discord MIA</div>
                    <div style="font-size:0.7rem;color:var(--text-muted);">Communaute de traders</div>
                </div>
            </a>
        </div>

        <!-- YouTube -->
        <div class="sidebar-card">
            <a href="https://youtube.com/@mia-ia-system" target="_blank" class="sidebar-cta">
                <div class="sidebar-cta-icon youtube">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>
                </div>
                <div>
                    <div style="font-weight:600;color:var(--text-primary);">YouTube</div>
                    <div style="font-size:0.7rem;color:var(--text-muted);">Videos trading gratuites</div>
                </div>
            </a>
        </div>

        <!-- Lucid Trading (affiliation) -->
        <div class="sidebar-card">
            <a href="#" id="affiliate-link" target="_blank" class="sidebar-cta">
                <div class="sidebar-cta-icon affiliate">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
                </div>
                <div>
                    <div style="font-weight:600;color:var(--text-primary);">Lucid Trading</div>
                    <div style="font-size:0.7rem;color:var(--text-muted);">Ouvrir un compte prop firm</div>
                </div>
            </a>
        </div>

        <!-- Newsletter -->
        <div class="sidebar-card">
            <div class="sidebar-card-title">Newsletter MIA</div>
            <p style="font-size:0.75rem;color:var(--text-muted);margin-bottom:0.75rem;">
                Recevez le briefing et les alertes chaque matin.
            </p>
            <form id="newsletter-form" onsubmit="return false;">
                <input type="email" class="newsletter-input" placeholder="votre@email.com" id="newsletter-email">
                <button type="submit" class="newsletter-btn">S'inscrire</button>
            </form>
            <p id="newsletter-msg" style="font-size:0.7rem;margin-top:0.5rem;display:none;"></p>
        </div>
    </aside>
</div>

<!-- TOAST CONTAINER -->
<div class="toast-container" id="toast-container"></div>
```

- [ ] **Step 3: Ajouter la logique toast + newsletter dans dashboard.js**

```javascript
/* === TOAST ALERTES (FOMO pour free users) === */
function showToast(symbol, direction, time) {
    if (userTier === "premium") return; // pas besoin de FOMO pour premium
    const container = document.getElementById("toast-container");
    if (!container) return;
    const cls = direction === "BUY" ? "toast-buy" : "toast-sell";
    const toast = document.createElement("div");
    toast.className = "toast " + cls;
    toast.innerHTML =
        '<span class="toast-dot"></span>' +
        '<span class="toast-text">Signal <strong>' + direction + ' ' + symbol + '</strong> detecte — ' + time + '</span>' +
        '<a href="/static/pricing.html" class="toast-cta">Details →</a>';
    container.appendChild(toast);
    setTimeout(function() { toast.remove(); }, 8000);
}

/* === NEWSLETTER === */
function setupNewsletter() {
    var form = document.getElementById("newsletter-form");
    if (!form) return;
    form.addEventListener("submit", async function(e) {
        e.preventDefault();
        var email = document.getElementById("newsletter-email").value;
        var msg = document.getElementById("newsletter-msg");
        if (!email) return;
        try {
            // Envoie vers Discord webhook (meme que le site principal)
            await fetch("https://discord.com/api/webhooks/1483825074128556062/oQ02-a3xTDn...", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    embeds: [{
                        title: "Nouvel abonne Newsletter Dashboard",
                        color: 0xD4AF37,
                        fields: [{ name: "Email", value: email }],
                    }]
                }),
            });
            msg.textContent = "Inscrit ! Vous recevrez le briefing chaque matin.";
            msg.style.color = "var(--green)";
        } catch {
            msg.textContent = "Erreur. Reessayez.";
            msg.style.color = "var(--red)";
        }
        msg.style.display = "block";
    });
}

/* === BRIEFING PREVIEW === */
async function fetchBriefingPreview() {
    try {
        var headers = {};
        var token = getToken();
        if (token) headers["Authorization"] = "Bearer " + token;
        var resp = await fetch(API_BASE + "/api/briefing/today", { headers });
        var data = await resp.json();
        var preview = document.getElementById("briefing-preview");
        if (preview && data.sections && data.sections.macro) {
            var mc = data.sections.macro;
            preview.textContent = "VIX " + mc.vix + " (" + mc.vix_regime + ") — " +
                (mc.vix_desc || "Conditions standard");
        }
        var dateEl = document.getElementById("banner-date");
        if (dateEl && data.date) {
            var parts = data.date.split("-");
            dateEl.textContent = parts[2] + "/" + parts[1];
        }
    } catch { /* silencieux */ }
}
```

- [ ] **Step 4: Modifier la navbar dans index.html pour ajouter les CTA**

```html
<nav class="navbar">
    <a href="/" class="navbar-brand">
        <img src="/static/images/logo-dark.jpg" alt="MIA">
        <span>MIA Dashboard</span>
    </a>
    <div style="display:flex;align-items:center;gap:1.5rem;margin-left:2rem;">
        <a href="/" style="color:var(--text-secondary);text-decoration:none;font-size:0.875rem;font-weight:500;">Dashboard</a>
        <a href="/static/briefing.html" style="color:var(--gold);text-decoration:none;font-size:0.875rem;font-weight:600;">Briefing</a>
        <a href="https://mia-ia-system.com/education/" style="color:var(--text-secondary);text-decoration:none;font-size:0.875rem;font-weight:500;">Education</a>
    </div>
    <div style="flex:1"></div>
    <div style="display:flex;align-items:center;gap:0.75rem;">
        <span id="refresh-status" class="badge badge-cyan">
            <span class="dot dot-green"></span>
            <span class="mono" style="font-size:0.7rem;">LIVE</span>
        </span>
        <span id="last-update" class="mono" style="font-size:0.7rem;color:var(--text-muted);">--:--:--</span>
        <a href="https://discord.gg/mia-ia-system" target="_blank" class="badge" style="background:rgba(88,101,242,0.15);color:#5865F2;text-decoration:none;">Discord</a>
        <a href="/static/pricing.html" style="padding:0.5rem 1rem;background:linear-gradient(to right,var(--cyan),var(--cyan-dark));color:var(--bg-base);border-radius:0.5rem;text-decoration:none;font-weight:600;font-size:0.8125rem;">Premium ★</a>
    </div>
</nav>
```

- [ ] **Step 5: Ajouter les CTA intra-panels**

Dans chaque panel bloque, remplacer le CTA generique par un CTA specifique avec teaser :

Panel Order Flow : montrer la valeur RVOL en clair (teaser) + "Debloquer l'Order Flow complet — 49EUR/mois"
Panel Options : montrer le mur le plus proche en clair (teaser) + "Debloquer les niveaux Gamma — 49EUR/mois"
Panel Signaux : montrer la direction du signal en clair si signal actif + "Voir les details — Premium"

Les teasers sont rendus dans dashboard.js meme en mode free — c'est juste 1-2 valeurs qui passent a travers le blur pour creer la curiosite.

- [ ] **Step 6: Commit**

```bash
git add DASHBOARD/static/ DASHBOARD/api/briefing.py
git commit -m "feat(dashboard): sidebar CTA + bandeau briefing + toast alertes + newsletter"
```

---

## Resume des livrables (REVISE)

| Chantier | Livrable | Fichiers |
|----------|----------|----------|
| A | Backend FastAPI (6 panels, 377 features) | api/app.py, data_reader.py, models.py |
| A | Frontend dashboard (HTML/CSS/JS + sidebar CTA) | static/index.html, dashboard.css, dashboard.js |
| A | Briefing MIA quotidien (generateur + page + API) | api/briefing.py, briefing.html |
| A | Auth JWT (register/login) | api/auth.py, auth.js, login.html, register.html |
| B | Script deploiement VPS | deploy.sh |
| B | Instructions Caddy HTTPS | dans deploy.sh |
| C | Integration Stripe (3 tiers) | api/stripe_webhooks.py, pricing.html |
| C | CTA complets (bandeau + sidebar + toast + navbar) | index.html, dashboard.css, dashboard.js |
| C | Enrichissement bot (features dans JSON) | BOT/bot_main.py |
| - | Tests | tests/test_data_reader.py, tests/test_api.py |

## Ordre d'execution recommande (REVISE)

1. **Task 1** (backend) → **Task 2** (frontend HTML/CSS) → **Task 3** (JS) — Dashboard basique
2. **Task 11** (sidebar + CTA + bandeau + toast) — CTA partout
3. **Task 10** (Briefing MIA) — Produit premium phare
4. **Task 4** (auth) → **Task 5** (assets) — Login fonctionnel
5. **Task 6** (deploy VPS) — En ligne
6. **Task 8** (enrichir bot) — Features live
7. **Task 7** (Stripe) — Paiements
8. **Task 9** (tests) — Validation

## Dependances a installer

```bash
pip install fastapi uvicorn PyJWT stripe
```
