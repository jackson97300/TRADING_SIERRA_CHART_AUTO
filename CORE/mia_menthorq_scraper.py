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

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


# ─────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────

SITE = "https://menthorq.com"
LOGIN_URL = f"{SITE}/wp-login.php"
AJAX_URL = f"{SITE}/wp-admin/admin-ajax.php"

# Tickers futures (URL-encoded pour le GET, raw pour le POST)
FUTURES_TICKERS_URL = {
    "ES": "es1%21",
    "NQ": "nq1%21",
}
FUTURES_TICKERS_POST = {
    "ES": "es1!",
    "NQ": "nq1!",
}

# Tickers EOD pour swing models (proxy)
EOD_TICKERS = {
    "ES": "SPX",
    "NQ": "QQQ",
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
        "User-Agent": "MIA-Trading-Bot/1.0 (Data Collection)"
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
    for slug in slugs:
        print(f"    {slug}...", end=" ", flush=True)
        result = call_ajax(session, nonce, slug, ticker, date)
        results[slug] = result
        status = "OK" if "error" not in result else result.get("error", "?")
        print(status)
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

def scrape_menthorq(date: str, out_dir: str = DEFAULT_OUT):
    """
    Scrape complet MenthorQ pour ES et NQ.

    Args:
        date: Format YYYY-MM-DD
        out_dir: Repertoire de sortie
    """
    print(f"\n{'='*60}")
    print(f"  MIA MENTHORQ SCRAPER — {date}")
    print(f"{'='*60}\n")

    # Credentials
    email, password = load_credentials()

    # Session
    session = create_session(email, password)
    if session is None:
        return False

    result = {
        "date": date,
        "source": "MenthorQ via mia_menthorq_scraper.py",
        "scrape_time": datetime.now(timezone.utc).isoformat(),
    }

    # ── FUTURES : ES et NQ ──
    for sym in ["ES", "NQ"]:
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

    # ── INTRADAY : 0DTE en temps reel (ES et NQ) ──
    for sym in ["ES", "NQ"]:
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
    all_sections = ["ES", "NQ", "ES_swing", "NQ_swing",
                    "ES_intraday", "NQ_intraday", "CTA", "VOL"]
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
        print(f"  ⚠️ AUCUNE DONNEE — MenthorQ n'a peut-etre pas publie pour {date}")
        return False

    # ── Sauvegarde ──
    os.makedirs(out_dir, exist_ok=True)
    date_compact = date.replace("-", "")
    out_path = os.path.join(out_dir, f"{date_compact}_menthorq_complete.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)

    print(f"  Sauvegarde: {out_path}")
    print(f"  Taille: {os.path.getsize(out_path) / 1024:.1f} KB")
    print(f"\n{'='*60}")
    print(f"  SCRAPING TERMINE — {n_success}/{n_total} donnees")
    print(f"{'='*60}\n")

    return True


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Date (argument ou auto-detection)
    if len(sys.argv) > 1 and re.match(r"\d{4}-\d{2}-\d{2}", sys.argv[1]):
        date = sys.argv[1]
    elif "--today" in sys.argv:
        # Forcer la date du jour (pour la tache MidDay)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        print(f"  [TODAY] Date forcee: {date}")
    else:
        # Auto-detection : utiliser la date du dernier jour de trading
        # MenthorQ publie les données EOD après 18:30 ET
        # Avant ~19:00 ET (01:00 UTC+2), les données du jour ne sont pas prêtes
        # → utiliser la veille (ou vendredi si weekend)
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        # Heure ET approximative
        h_et = (now.hour - 4) % 24

        if h_et < 19:
            # Avant 19:00 ET → données de la veille
            target = now - timedelta(days=1)
        else:
            # Après 19:00 ET → données du jour
            target = now

        # Skip weekends (samedi→vendredi, dimanche→vendredi)
        while target.weekday() >= 5:  # 5=samedi, 6=dimanche
            target -= timedelta(days=1)

        date = target.strftime("%Y-%m-%d")
        print(f"  [AUTO] Date detectee: {date} (h_et={h_et})")

    # Output dir
    out_dir = DEFAULT_OUT
    if "--out" in sys.argv:
        idx = sys.argv.index("--out")
        if idx + 1 < len(sys.argv):
            out_dir = sys.argv[idx + 1]

    ok = scrape_menthorq(date, out_dir)

    # Fallback : si aucune donnee, essayer la veille
    if not ok:
        from datetime import timedelta
        prev = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)
        # Skip weekend
        while prev.weekday() >= 5:
            prev -= timedelta(days=1)
        prev_str = prev.strftime("%Y-%m-%d")
        print(f"\n  [FALLBACK] Tentative avec la veille: {prev_str}")
        scrape_menthorq(prev_str, out_dir)
