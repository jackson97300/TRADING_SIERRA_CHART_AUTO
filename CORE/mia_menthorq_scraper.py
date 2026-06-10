"""
mia_menthorq_scraper.py — Collecte automatique des donnees MenthorQ
====================================================================

Se connecte a MenthorQ via l'API WordPress AJAX, recupere toutes les
donnees gamma/options pour ES et NQ, et sauvegarde un JSON structure.

Les credentials sont lus depuis un fichier .env (jamais en dur).

Usage :
    python mia_menthorq_scraper.py                    # date du jour
    python mia_menthorq_scraper.py 2026-03-31         # date specifique
    python mia_menthorq_scraper.py 2026-03-31 --out C:\\DATA\\MENTHORQ

Emplacement VPS : C:\\TRADING_SIERRA_CHART_AUTO\\CORE\\mia_menthorq_scraper.py
Credentials VPS : C:\\TRADING_SIERRA_CHART_AUTO\\CORE\\.env.menthorq

Auteur : MIA Trading System
Date   : 2026-04-01
"""

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

SLUG_SLEEP_RANGE = (0.8, 2.0)
DATE_SLEEP_RANGE = (60.0, 120.0)
RETRY_SLEEP = 120.0
HEALTHY_MIN_KB = 100
PROACTIVE_RELOGIN_EVERY = 5
COOLDOWN_EVERY = 10
COOLDOWN_SLEEP = 300.0


# ─────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────

SITE = "https://menthorq.com"
LOGIN_URL = f"{SITE}/wp-login.php"
AJAX_URL = f"{SITE}/wp-admin/admin-ajax.php"

# Tickers futures (URL-encoded pour le GET, raw pour le POST)
# 🆕 09/05 : ajout GC (Gold) — Jackson abonnement MenthorQ couvre GC.
FUTURES_TICKERS_URL = {
    "ES": "es1%21",
    "NQ": "nq1%21",
    "GC": "gc1%21",
}
FUTURES_TICKERS_POST = {
    "ES": "es1!",
    "NQ": "nq1!",
    "GC": "gc1!",
}

# Tickers EOD pour swing models (proxy)
EOD_TICKERS = {
    "ES": "SPX",
    "NQ": "QQQ",
    "GC": "GLD",   # 🆕 Gold ETF SPDR Gold Shares = proxy GC standard
}

# Slugs a recuperer par categorie
FUTURES_SLUGS = [
    "qscore_option", "qscore_momentum", "qscore_volatility", "qscore_seasonality",
    "netgex", "netgex_multiexpiry", "key_levels", "bl_levels", "matrix_v1",
    "levels_tv", "future_curve",
]

EOD_SLUGS = [
    "swing_5d", "swing_20d", "swing_levels",
    "liq_snapshot", "key_levels", "netgex", "netgex_multiexpiry",
    "levels_tv", "matrix", "bl_levels",
    "voloi", "voloi_0dte", "mainchart",
    "skew", "skew_0dte", "skew_3m", "term",
    "net_dex", "ivoi", "oi",
    "vol_smile", "vol_surface_3d", "vol_surface_2d", "vrp",
]

# Intraday — niveaux 0DTE en temps reel (scrape MidDay)
INTRADAY_SLUGS = [
    "netgex_0dte", "netgex_intraday", "vol_0dte_intraday",
    "liquidity_summary", "levels_tv_intraday",
    "gex_diff_vs_eod", "gex_diff_vs_last",
]

# CTA — positionnement fonds institutionnels
CTA_SLUGS = [
    "cta_table", "cta_index", "cta_spx", "cta_nasdaq",
    "cta_gold", "cta_silver", "cta_wti",
    "cta_treasury2y", "cta_treasury10y",
]

# Vol Models — regime volatilite
VOL_SLUGS = [
    "vol_control", "vol_barometer", "market_breadth",
    "vrp_dashboard", "hv_vs_iv",
]

DEFAULT_OUT = "C:\\TRADING_SIERRA_CHART_AUTO\\DATA\\MENTHORQ"
ENV_FILE = os.path.join(os.path.dirname(__file__), ".env.menthorq")


# ─────────────────────────────────────────────────────────────────────
# CREDENTIALS
# ─────────────────────────────────────────────────────────────────────

def load_credentials(env_path: str = ENV_FILE) -> tuple:
    """Lit email/password depuis le fichier .env.menthorq."""
    if not os.path.exists(env_path):
        print(f"ERREUR: fichier credentials absent: {env_path}")
        print(f"Creez-le avec:")
        print(f"  MENTHORQ_EMAIL=votre@email.com")
        print(f"  MENTHORQ_PASSWORD=votre_mot_de_passe")
        sys.exit(1)

    creds = {}
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                creds[key.strip()] = val.strip()

    email = creds.get("MENTHORQ_EMAIL", "")
    password = creds.get("MENTHORQ_PASSWORD", "")

    if not email or not password:
        print(f"ERREUR: MENTHORQ_EMAIL ou MENTHORQ_PASSWORD manquant dans {env_path}")
        sys.exit(1)

    return email, password


# ─────────────────────────────────────────────────────────────────────
# SESSION & LOGIN
# ─────────────────────────────────────────────────────────────────────

def create_session(email: str, password: str) -> requests.Session:
    """Cree une session authentifiee sur MenthorQ."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": CHROME_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    })

    print(f"  [LOGIN] Connexion a MenthorQ...")

    # Login WordPress
    login_data = {
        "log": email,
        "pwd": password,
        "wp-submit": "Log In",
        "rememberme": "forever",
        "redirect_to": f"{SITE}/account/",
    }

    resp = session.post(LOGIN_URL, data=login_data, allow_redirects=True)

    # Verifier le login
    if "wordpress_logged_in" not in str(session.cookies):
        print(f"  [ERREUR] Login echoue (pas de cookie wordpress_logged_in)")
        print(f"  Status: {resp.status_code}")
        return None

    print(f"  [LOGIN] Connecte OK (cookie obtenu)")
    return session


# ─────────────────────────────────────────────────────────────────────
# NONCE EXTRACTION
# ─────────────────────────────────────────────────────────────────────

def get_nonce(session: requests.Session, date: str, ticker: str) -> str:
    """Extrait le nonce QDataParams depuis le HTML du dashboard."""
    url = (f"{SITE}/account/?action=data&type=dashboard"
           f"&commands=futures&tickers=futures"
           f"&date={date}&ticker={ticker}")

    resp = session.get(url)
    if resp.status_code != 200:
        print(f"  [ERREUR] Dashboard HTTP {resp.status_code}")
        return None

    # Chercher le nonce SPECIFIQUEMENT dans QDataParams (pas les autres nonces)
    # QDataParams = {"ajax_url":"...","nonce":"bcb02f118a","commands":...}
    match = re.search(r'QDataParams\s*=\s*\{[^}]*?"nonce"\s*:\s*"([a-f0-9]+)"', resp.text)
    if match:
        nonce = match.group(1)
        print(f"  [NONCE] QDataParams: {nonce}")
        return nonce

    print(f"  [ERREUR] Nonce QDataParams introuvable dans le HTML ({len(resp.text)} chars)")
    return None


# ─────────────────────────────────────────────────────────────────────
# API AJAX CALLS
# ─────────────────────────────────────────────────────────────────────

def call_ajax(session: requests.Session, nonce: str, slug: str,
              ticker: str, date: str) -> dict:
    """Appelle un endpoint AJAX MenthorQ."""
    data = {
        "action": "get_command",
        "security": nonce,
        "command_slug": slug,
        "ticker": ticker,
        "date": date,
    }

    try:
        resp = session.post(AJAX_URL, data=data, timeout=30)
        if resp.status_code == 200:
            try:
                return resp.json()
            except json.JSONDecodeError:
                # Reponse HTML (pas JSON)
                return {"html": resp.text[:5000], "status": "html"}
        else:
            return {"error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"error": str(e)}


def fetch_all_slugs(session: requests.Session, nonce: str,
                     slugs: list, ticker: str, date: str) -> dict:
    """Recupere tous les slugs pour un ticker."""
    results = {}
    for i, slug in enumerate(slugs):
        print(f"    {slug}...", end=" ", flush=True)
        result = call_ajax(session, nonce, slug, ticker, date)
        results[slug] = result
        status = "OK" if "error" not in result else result.get("error", "?")
        print(status)
        if i < len(slugs) - 1:
            time.sleep(random.uniform(*SLUG_SLEEP_RANGE))
    return results


# ─────────────────────────────────────────────────────────────────────
# PARSING DES REPONSES
# ─────────────────────────────────────────────────────────────────────

def parse_number(text: str) -> float:
    """Parse un nombre depuis un texte (gere M, B, %, virgules)."""
    if text is None:
        return None
    text = str(text).strip().replace(",", "").replace(" ", "")
    text = text.replace("±", "").replace("%", "").replace("$", "")

    multiplier = 1
    if text.endswith("M"):
        multiplier = 1
        text = text[:-1]
    elif text.endswith("B"):
        multiplier = 1000
        text = text[:-1]
    elif text.endswith("K"):
        multiplier = 0.001
        text = text[:-1]

    try:
        return float(text) * multiplier
    except (ValueError, TypeError):
        return None


def extract_from_html(html: str, patterns: dict) -> dict:
    """Extrait des valeurs depuis du HTML en utilisant des patterns texte."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" | ")
    results = {}

    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            results[key] = parse_number(match.group(1))

    return results


def build_structured_json(raw_data: dict, ticker_label: str) -> dict:
    """Construit le JSON structure depuis les reponses AJAX brutes."""
    out = {}

    # Les reponses AJAX peuvent etre JSON ou HTML selon le slug
    # On extrait ce qu'on peut de chaque reponse
    for slug, response in raw_data.items():
        if isinstance(response, dict):
            if "data" in response:
                out[slug] = response["data"]
            elif "html" in response:
                out[slug] = response["html"]
            elif "error" not in response:
                out[slug] = response

    return out


# ─────────────────────────────────────────────────────────────────────
# MAIN SCRAPER
# ─────────────────────────────────────────────────────────────────────

def _is_scrape_healthy(out_path: str) -> bool:
    """🆕 09/05 fix code-reviewer #3 : check sémantique en plus de la taille.

    Un scrape est sain SI :
      1. Fichier existe + taille >= HEALTHY_MIN_KB
      2. ES + NQ + GC ont chacun raw_ajax non-vide ET pas de section error

    Sans ce check, un fichier rempli de {"error": "nonce_failed"} pouvait
    dépasser 100 KB et être considéré sain → corruption silencieuse data.
    """
    if not os.path.exists(out_path):
        return False
    if os.path.getsize(out_path) < HEALTHY_MIN_KB * 1024:
        return False
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    # Verification sémantique : ES + NQ + GC chacun avec raw_ajax peuplé
    for sym in ("ES", "NQ", "GC"):
        section = data.get(sym, {})
        if not isinstance(section, dict):
            return False
        if "error" in section:
            return False
        raw = section.get("raw_ajax", {})
        if not raw or not isinstance(raw, dict):
            return False
    return True


def scrape_gc_only(date: str, out_dir: str = DEFAULT_OUT,
                    session: requests.Session = None) -> bool:
    """🆕 09/05 — Mode --gc-only : scrape uniquement section GC.

    Charge le JSON existant, ajoute/remplace section GC, GC_swing, GC_intraday.
    ~3-5x plus rapide que mode complet --force (~10-15 min/date au lieu de 40+).

    Idéal pour backfill GC sur ~130 dates où ES+NQ déjà scrapés.
    """
    date_compact = date.replace("-", "")
    out_path = os.path.join(out_dir, f"{date_compact}_menthorq_complete.json")

    # Skip si déjà fait (GC présent + valide)
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if "GC" in existing and isinstance(existing["GC"], dict) \
                    and "error" not in existing["GC"] \
                    and existing["GC"].get("raw_ajax"):
                print(f"  [SKIP GC] {date_compact} déjà scraped GC")
                return True
        except (json.JSONDecodeError, OSError):
            existing = {}
    else:
        print(f"  [WARN] Fichier {out_path} absent, --gc-only nécessite ES/NQ existant")
        return False

    print(f"\n{'='*60}")
    print(f"  MIA MENTHORQ GC-ONLY — {date}")
    print(f"{'='*60}\n")

    if session is None:
        email, password = load_credentials()
        session = create_session(email, password)
        if session is None:
            return False

    # ─── GC Futures (gc1!) ───
    ticker_url = FUTURES_TICKERS_URL["GC"]
    ticker_post = FUTURES_TICKERS_POST["GC"]
    print(f"  [GC] Futures ({ticker_post})")
    nonce = get_nonce(session, date, ticker_url)
    if nonce is None:
        existing["GC"] = {"error": "nonce_failed"}
    else:
        raw = fetch_all_slugs(session, nonce, FUTURES_SLUGS, ticker_post, date)
        existing["GC"] = {"raw_ajax": raw, "structured": build_structured_json(raw, "GC")}

    # ─── GC EOD Swing via GLD ───
    eod_ticker = EOD_TICKERS["GC"]
    print(f"\n  [GC] Swing Models via {eod_ticker}")
    eod_url = (f"{SITE}/account/?action=data&type=dashboard"
               f"&commands=eod&tickers=eod"
               f"&date={date}&ticker={eod_ticker}")
    resp = session.get(eod_url)
    match = re.search(r'QDataParams\s*=\s*\{[^}]*?"nonce"\s*:\s*"([a-f0-9]+)"', resp.text)
    if match:
        eod_nonce = match.group(1)
        print(f"  [NONCE EOD] {eod_nonce}")
        swing_raw = fetch_all_slugs(session, eod_nonce, EOD_SLUGS, eod_ticker, date)
        existing["GC_swing"] = {"proxy_ticker": eod_ticker, "raw_ajax": swing_raw}
    else:
        existing["GC_swing"] = {"error": "nonce_failed"}

    # ─── GC Intraday 0DTE ───
    print(f"\n  [GC] Intraday 0DTE ({ticker_post})")
    intraday_url = (f"{SITE}/account/?action=data&type=dashboard"
                    f"&commands=intraday&tickers=futures"
                    f"&date={date}&ticker={ticker_url}")
    resp = session.get(intraday_url)
    match = re.search(r'QDataParams\s*=\s*\{[^}]*?"nonce"\s*:\s*"([a-f0-9]+)"', resp.text)
    if match:
        intra_nonce = match.group(1)
        intra_raw = fetch_all_slugs(session, intra_nonce, INTRADAY_SLUGS, ticker_post, date)
        existing["GC_intraday"] = {"raw_ajax": intra_raw}
    else:
        existing["GC_intraday"] = {"error": "nonce_failed"}

    # Update metadata
    existing["gc_scrape_time"] = datetime.now(timezone.utc).isoformat()

    # Sauvegarde atomique (fix code-reviewer #1)
    os.makedirs(out_dir, exist_ok=True)
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp_path, out_path)

    print(f"\n  Sauvegarde GC-only: {out_path}")
    print(f"  Taille: {os.path.getsize(out_path) / 1024:.1f} KB")
    return True


def scrape_menthorq(date: str, out_dir: str = DEFAULT_OUT,
                    force: bool = False, session: requests.Session = None):
    """
    Scrape complet MenthorQ pour ES et NQ.

    Args:
        date: Format YYYY-MM-DD
        out_dir: Repertoire de sortie
        force: Si False, skip si le fichier existe deja
        session: Session reutilisable (sinon en cree une nouvelle)
    """
    date_compact = date.replace("-", "")
    out_path = os.path.join(out_dir, f"{date_compact}_menthorq_complete.json")

    if not force and _is_scrape_healthy(out_path):
        size_kb = os.path.getsize(out_path) / 1024
        print(f"  [SKIP] {out_path} existe deja ({size_kb:.1f} KB)")
        return True

    print(f"\n{'='*60}")
    print(f"  MIA MENTHORQ SCRAPER — {date}")
    print(f"{'='*60}\n")

    if session is None:
        email, password = load_credentials()
        session = create_session(email, password)
        if session is None:
            return False

    result = {
        "date": date,
        "source": "MenthorQ via mia_menthorq_scraper.py",
        "scrape_time": datetime.now(timezone.utc).isoformat(),
    }

    # ── FUTURES : ES, NQ, GC (🆕 09/05) ──
    for sym in ["ES", "NQ", "GC"]:
        ticker_url = FUTURES_TICKERS_URL[sym]
        ticker_post = FUTURES_TICKERS_POST[sym]
        print(f"\n  [{sym}] Futures ({ticker_post})")

        nonce = get_nonce(session, date, ticker_url)
        if nonce is None:
            result[sym] = {"error": "nonce_failed"}
            continue

        raw = fetch_all_slugs(session, nonce, FUTURES_SLUGS, ticker_post, date)
        result[sym] = {
            "raw_ajax": raw,
            "structured": build_structured_json(raw, sym),
        }

    # ── EOD : Swing Models (SPX proxy ES, QQQ proxy NQ) ──
    for sym, eod_ticker in EOD_TICKERS.items():
        print(f"\n  [{sym}] Swing Models via {eod_ticker}")

        # Dashboard EOD
        eod_url = (f"{SITE}/account/?action=data&type=dashboard"
                   f"&commands=eod&tickers=eod"
                   f"&date={date}&ticker={eod_ticker}")

        resp = session.get(eod_url)
        match = re.search(r'QDataParams\s*=\s*\{[^}]*?"nonce"\s*:\s*"([a-f0-9]+)"', resp.text)
        if match:
            eod_nonce = match.group(1)
            print(f"  [NONCE EOD] {eod_nonce}")

            swing_raw = fetch_all_slugs(session, eod_nonce, EOD_SLUGS, eod_ticker, date)
            result[f"{sym}_swing"] = {
                "proxy_ticker": eod_ticker,
                "raw_ajax": swing_raw,
            }
        else:
            print(f"  [ERREUR] Nonce EOD introuvable pour {eod_ticker}")
            result[f"{sym}_swing"] = {"error": "nonce_failed"}

    # ── INTRADAY : 0DTE en temps reel (ES, NQ, GC 🆕 09/05) ──
    for sym in ["ES", "NQ", "GC"]:
        ticker_url = FUTURES_TICKERS_URL[sym]
        ticker_post = FUTURES_TICKERS_POST[sym]
        print(f"\n  [{sym}] Intraday 0DTE ({ticker_post})")

        intraday_url = (f"{SITE}/account/?action=data&type=dashboard"
                        f"&commands=intraday&tickers=futures"
                        f"&date={date}&ticker={ticker_url}")
        resp = session.get(intraday_url)
        match = re.search(r'QDataParams\s*=\s*\{[^}]*?"nonce"\s*:\s*"([a-f0-9]+)"', resp.text)
        if match:
            intra_nonce = match.group(1)
            print(f"  [NONCE INTRA] {intra_nonce}")
            intra_raw = fetch_all_slugs(session, intra_nonce, INTRADAY_SLUGS, ticker_post, date)
            result[f"{sym}_intraday"] = {"raw_ajax": intra_raw}
        else:
            print(f"  [ERREUR] Nonce intraday introuvable pour {sym}")
            result[f"{sym}_intraday"] = {"error": "nonce_failed"}

    # ── CTA : Positionnement fonds institutionnels ──
    print(f"\n  [CTA] Positionnement institutionnel")
    cta_url = (f"{SITE}/account/?action=data&type=dashboard"
               f"&commands=cta&tickers=cta&date={date}&ticker=SPX")
    resp = session.get(cta_url)
    match = re.search(r'QDataParams\s*=\s*\{[^}]*?"nonce"\s*:\s*"([a-f0-9]+)"', resp.text)
    if match:
        cta_nonce = match.group(1)
        print(f"  [NONCE CTA] {cta_nonce}")
        cta_raw = fetch_all_slugs(session, cta_nonce, CTA_SLUGS, "SPX", date)
        result["CTA"] = {"raw_ajax": cta_raw}
    else:
        print(f"  [ERREUR] Nonce CTA introuvable")
        result["CTA"] = {"error": "nonce_failed"}

    # ── VOL MODELS : Regime volatilite ──
    print(f"\n  [VOL] Modeles de volatilite")
    vol_url = (f"{SITE}/account/?action=data&type=dashboard"
               f"&commands=vol&tickers=vol&date={date}&ticker=SPX")
    resp = session.get(vol_url)
    match = re.search(r'QDataParams\s*=\s*\{[^}]*?"nonce"\s*:\s*"([a-f0-9]+)"', resp.text)
    if match:
        vol_nonce = match.group(1)
        print(f"  [NONCE VOL] {vol_nonce}")
        vol_raw = fetch_all_slugs(session, vol_nonce, VOL_SLUGS, "SPX", date)
        result["VOL"] = {"raw_ajax": vol_raw}
    else:
        print(f"  [ERREUR] Nonce VOL introuvable")
        result["VOL"] = {"error": "nonce_failed"}

    # ── Validation ──
    n_success = 0
    n_total = 0
    all_sections = ["ES", "NQ", "GC",
                    "ES_swing", "NQ_swing", "GC_swing",
                    "ES_intraday", "NQ_intraday", "GC_intraday",
                    "CTA", "VOL"]
    for section in all_sections:
        raw_ajax = result.get(section, {}).get("raw_ajax", {})
        for slug, resp in raw_ajax.items():
            n_total += 1
            if isinstance(resp, dict) and resp.get("success"):
                rdata = resp.get("data", {}).get("resource", {}).get("data", {})
                if rdata:
                    n_success += 1

    print(f"\n  Validation: {n_success}/{n_total} slugs avec donnees JSON")

    if n_success == 0 and n_total > 0:
        print(f"  [WARN] Aucune donnee JSON structuree — sauvegarde des donnees brutes quand meme")

    # ── Sauvegarde ATOMIQUE 🆕 09/05 fix code-reviewer #1 ──
    # Anti race-condition : si MIA-LivePipeline lit le fichier pendant le json.dump,
    # il peut tronquer les fichiers consommateurs. Ecriture .tmp puis os.replace()
    # garantit que le fichier final est soit l'ancien (intact) soit le nouveau (complet),
    # jamais entre les deux.
    os.makedirs(out_dir, exist_ok=True)
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp_path, out_path)  # atomic sur Windows + Unix

    print(f"  Sauvegarde: {out_path}")
    print(f"  Taille: {os.path.getsize(out_path) / 1024:.1f} KB")
    print(f"\n{'='*60}")
    print(f"  SCRAPING TERMINE — {n_success}/{n_total} donnees")
    print(f"{'='*60}\n")

    return True


# ─────────────────────────────────────────────────────────────────────
# BATCH BACKFILL
# ─────────────────────────────────────────────────────────────────────

def iter_business_days(start: datetime, end: datetime):
    """Yield les jours ouvres (lun-ven) entre start et end inclus."""
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def _fresh_session() -> requests.Session:
    """Cree une nouvelle session authentifiee."""
    email, password = load_credentials()
    return create_session(email, password)


def scrape_with_retry(date: str, out_dir: str, force: bool,
                      session: requests.Session) -> tuple:
    """
    Scrape une date avec validation healthy + retry + re-login auto.

    Un scrape reussit seulement si le fichier final fait >= HEALTHY_MIN_KB.
    Sinon le fichier corrompu est supprime, session recreee, retry 1 fois.

    Returns:
        (success: bool, session: Session)
    """
    date_compact = date.replace("-", "")
    out_path = os.path.join(out_dir, f"{date_compact}_menthorq_complete.json")

    try:
        scrape_menthorq(date, out_dir, force=force, session=session)
    except Exception as e:
        print(f"  [ERREUR] {date}: {e}")

    if _is_scrape_healthy(out_path):
        return True, session

    size_kb = os.path.getsize(out_path) / 1024 if os.path.exists(out_path) else 0
    print(f"  [UNHEALTHY] {date} fichier {size_kb:.1f} KB (min {HEALTHY_MIN_KB} KB)")

    if os.path.exists(out_path):
        os.remove(out_path)
        print(f"  [CLEANUP] Fichier corrompu supprime")

    print(f"  [RETRY] Re-login + sleep {RETRY_SLEEP:.0f}s...")
    time.sleep(RETRY_SLEEP)
    new_session = _fresh_session()
    if new_session is None:
        print(f"  [FATAL] Re-login echoue pour {date}")
        return False, session

    try:
        scrape_menthorq(date, out_dir, force=True, session=new_session)
    except Exception as e:
        print(f"  [ERREUR] {date} (retry): {e}")

    if _is_scrape_healthy(out_path):
        print(f"  [RECOVERED] {date} OK apres retry")
        return True, new_session

    if os.path.exists(out_path):
        os.remove(out_path)
    print(f"  [GIVEUP] {date} echec definitif")
    return False, new_session


def run_batch(start_date: str, end_date: str, out_dir: str, force: bool,
              gc_only: bool = False):
    """Backfill batch sur une plage de dates.

    Args:
        gc_only: Si True, scrape uniquement section GC (skip ES/NQ existants).
                 Beaucoup plus rapide pour backfill GC sur ~130 dates.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    if start > end:
        print(f"ERREUR: --from {start_date} > --to {end_date}")
        sys.exit(1)

    days = list(iter_business_days(start, end))
    mode_str = "GC-ONLY (rapide)" if gc_only else "COMPLET (ES+NQ+GC)"
    print(f"\n{'#'*60}")
    print(f"  BATCH BACKFILL — {start_date} -> {end_date}")
    print(f"  Mode : {mode_str}")
    print(f"  {len(days)} jours ouvres a scraper")
    print(f"  Cadence : {DATE_SLEEP_RANGE[0]:.0f}-{DATE_SLEEP_RANGE[1]:.0f}s entre dates")
    print(f"  Re-login proactif : toutes les {PROACTIVE_RELOGIN_EVERY} dates scrapees")
    print(f"  Cooldown : {COOLDOWN_SLEEP:.0f}s toutes les {COOLDOWN_EVERY} dates scrapees")
    print(f"{'#'*60}\n")

    session = _fresh_session()
    if session is None:
        print("FATAL: login initial echoue")
        sys.exit(1)

    n_ok = 0
    n_fail = 0
    n_skip = 0
    n_scraped = 0

    for i, day in enumerate(days):
        date_str = day.strftime("%Y-%m-%d")
        date_compact = date_str.replace("-", "")
        out_path = os.path.join(out_dir, f"{date_compact}_menthorq_complete.json")

        # Mode GC-ONLY : skip si GC déjà présent dans le fichier existant
        if gc_only:
            try:
                with open(out_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                gc_section = existing.get("GC", {})
                if isinstance(gc_section, dict) and "error" not in gc_section \
                        and gc_section.get("raw_ajax"):
                    n_skip += 1
                    print(f"[{i+1}/{len(days)}] SKIP {date_str} (GC déjà présent)")
                    continue
            except (json.JSONDecodeError, OSError, FileNotFoundError):
                # Fichier absent ou corrompu : on skip car --gc-only nécessite ES/NQ existant
                n_skip += 1
                print(f"[{i+1}/{len(days)}] SKIP {date_str} (fichier ES/NQ absent — --gc-only impossible)")
                continue
        elif not force and _is_scrape_healthy(out_path):
            n_skip += 1
            print(f"[{i+1}/{len(days)}] SKIP {date_str} (healthy file exists)")
            continue

        if n_scraped > 0 and n_scraped % PROACTIVE_RELOGIN_EVERY == 0:
            print(f"  [RELOGIN] Re-login proactif apres {n_scraped} scrapes")
            session = _fresh_session() or session

        if n_scraped > 0 and n_scraped % COOLDOWN_EVERY == 0:
            print(f"  [COOLDOWN] Sleep {COOLDOWN_SLEEP:.0f}s (rate limit reset)")
            time.sleep(COOLDOWN_SLEEP)

        print(f"\n[{i+1}/{len(days)}] {date_str}")
        if gc_only:
            try:
                ok = scrape_gc_only(date_str, out_dir, session=session)
            except Exception as e:
                print(f"  [ERREUR GC-ONLY] {date_str}: {e}")
                ok = False
        else:
            ok, session = scrape_with_retry(date_str, out_dir, force, session)
        n_scraped += 1
        if ok:
            n_ok += 1
        else:
            n_fail += 1

        if i < len(days) - 1:
            sleep_s = random.uniform(*DATE_SLEEP_RANGE)
            print(f"  [SLEEP] {sleep_s:.1f}s avant prochaine date...")
            time.sleep(sleep_s)

    print(f"\n{'#'*60}")
    print(f"  BATCH TERMINE")
    print(f"  OK: {n_ok}  FAIL: {n_fail}  SKIP: {n_skip}  TOTAL: {len(days)}")
    print(f"{'#'*60}\n")


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def auto_detect_date() -> str:
    """Detecte la date EOD courante (veille si avant 19:00 ET, skip weekend)."""
    now = datetime.now(timezone.utc)
    h_et = (now.hour - 4) % 24
    if h_et < 19:
        target = now - timedelta(days=1)
    else:
        target = now
    while target.weekday() >= 5:
        target -= timedelta(days=1)
    return target.strftime("%Y-%m-%d")


def parse_cli():
    parser = argparse.ArgumentParser(
        description="MIA MenthorQ scraper — single date ou batch backfill"
    )
    parser.add_argument("date", nargs="?",
                        help="Date YYYY-MM-DD (mode single)")
    parser.add_argument("--from", dest="date_from",
                        help="Date debut YYYY-MM-DD (mode batch)")
    parser.add_argument("--to", dest="date_to",
                        help="Date fin YYYY-MM-DD (mode batch)")
    parser.add_argument("--today", action="store_true",
                        help="Force la date du jour")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help=f"Repertoire de sortie (defaut: {DEFAULT_OUT})")
    parser.add_argument("--force", action="store_true",
                        help="Re-scrape meme si le fichier existe")
    parser.add_argument("--gc-only", action="store_true",
                        help="🆕 Scrape UNIQUEMENT section GC (skip ES/NQ/CTA/VOL existants). "
                             "Merge dans le JSON existant. ~3-5x plus rapide pour backfill GC.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_cli()

    if args.date_from and args.date_to:
        run_batch(args.date_from, args.date_to, args.out, args.force,
                  gc_only=args.gc_only)
        sys.exit(0)

    # Mode --gc-only single date
    if args.gc_only and args.date:
        ok = scrape_gc_only(args.date, args.out)
        sys.exit(0 if ok else 1)

    if args.date_from or args.date_to:
        print("ERREUR: --from et --to doivent etre fournis ensemble")
        sys.exit(1)

    if args.date:
        if not re.match(r"\d{4}-\d{2}-\d{2}", args.date):
            print(f"ERREUR: format date invalide: {args.date} (attendu YYYY-MM-DD)")
            sys.exit(1)
        date = args.date
    elif args.today:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        print(f"  [TODAY] Date forcee: {date}")
    else:
        date = auto_detect_date()
        print(f"  [AUTO] Date detectee: {date}")

    ok = scrape_menthorq(date, args.out, force=args.force)

    if not ok:
        prev = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)
        while prev.weekday() >= 5:
            prev -= timedelta(days=1)
        prev_str = prev.strftime("%Y-%m-%d")
        print(f"\n  [FALLBACK] Tentative avec la veille: {prev_str}")
        scrape_menthorq(prev_str, args.out, force=args.force)
