"""
cta_auto_scraper.py — Extraction automatique des donnees CTA MenthorQ
======================================================================

Pipeline complet :
  1. Playwright headless → Login MenthorQ → Page CTA
  2. Telecharge les PNG des tableaux depuis S3
  3. Envoie a Claude Vision API → extraction JSON
  4. Sauvegarde dans DATA/MENTHORQ/YYYYMMDD_cta.json

Usage :
    python cta_auto_scraper.py                    # date du jour
    python cta_auto_scraper.py 2026-04-02         # date specifique

Tache planifiee VPS : MIA_CTA a 14:30 (08:30 ET)

Auteur : MIA Trading System
Date   : 2026-04-02
"""

import anthropic
import base64
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

DATA_DIR = r"C:\TRADING_SIERRA_CHART_AUTO\DATA\MENTHORQ"
SCREENSHOT_DIR = os.path.join(DATA_DIR, "screenshots")
ENV_FILE = os.path.join(os.path.dirname(__file__), ".env.menthorq")
ANTHROPIC_KEY_FILE = os.path.join(os.path.dirname(__file__), ".env.anthropic")


def load_menthorq_creds():
    """Charge les credentials MenthorQ."""
    creds = {}
    for line in open(ENV_FILE):
        if "=" in line:
            k, v = line.strip().split("=", 1)
            creds[k.strip()] = v.strip()
    return creds.get("MENTHORQ_EMAIL", ""), creds.get("MENTHORQ_PASSWORD", "")


def load_anthropic_key():
    """Charge la cle API Anthropic."""
    # 1. Variable d'environnement
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    # 2. Fichier .env.anthropic
    if os.path.exists(ANTHROPIC_KEY_FILE):
        for line in open(ANTHROPIC_KEY_FILE):
            if "ANTHROPIC_API_KEY" in line and "=" in line:
                return line.strip().split("=", 1)[1].strip()
    return ""


def download_cta_images(date_str: str) -> dict:
    """Telecharge les images CTA depuis MenthorQ via Playwright."""
    from playwright.sync_api import sync_playwright
    import requests

    email, password = load_menthorq_creds()
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    date_file = date_str.replace("-", "")

    images = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 2560, "height": 1440})
        page = context.new_page()

        # Login
        print("  [1] Login MenthorQ...")
        page.goto("https://menthorq.com/wp-login.php")
        page.fill("#user_login", email)
        page.fill("#user_pass", password)
        page.click("#wp-submit")
        page.wait_for_load_state("networkidle")

        # Page CTA
        print("  [2] Page CTA...")
        page.goto(f"https://menthorq.com/account/?action=data&type=dashboard"
                  f"&commands=cta&tickers=cta&date={date_str}&ticker=SPX")
        page.wait_for_load_state("networkidle")
        time.sleep(5)

        # Cliquer sur Main Table
        el = page.query_selector("text=CTAs Main Table")
        if el:
            el.click()
            time.sleep(3)

        # Telecharger les PNG S3
        print("  [3] Telechargement images S3...")
        img_elements = page.query_selector_all("img[src*='s3.amazonaws']")

        name_map = {
            "main_cta": "main_table",
            "equity_cta": "index_table",
            "currencies_cta": "currency_table",
            "commodities_cta": "commodity_table",
        }

        for img in img_elements:
            src = img.get_attribute("src") or ""
            for key, name in name_map.items():
                if key in src:
                    path = os.path.join(SCREENSHOT_DIR, f"{date_file}_cta_{name}.png")
                    try:
                        r = requests.get(src, timeout=30)
                        if r.status_code == 200:
                            with open(path, "wb") as f:
                                f.write(r.content)
                            images[name] = path
                            print(f"      {name}: {len(r.content)//1024}KB")
                    except Exception as e:
                        print(f"      {name}: ERREUR {e}")
                    break

        browser.close()

    return images


def parse_image_with_claude(image_path: str, api_key: str) -> dict:
    """Envoie une image a Claude Vision et extrait les donnees CTA en JSON."""
    client = anthropic.Anthropic(api_key=api_key)

    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_data,
                    },
                },
                {
                    "type": "text",
                    "text": """Extrais TOUTES les donnees de ce tableau CTA en JSON strict.

Format attendu :
{
  "rows": [
    {
      "underlying": "E-Mini S&P 500 Index",
      "position_today": -0.78,
      "position_yesterday": -0.79,
      "position_1m_ago": 0.30,
      "percentile_1m": 0.48,
      "percentile_3m": 0.16,
      "percentile_1y": 0.14,
      "zscore_3m": -1.37
    }
  ]
}

Regles :
- Les valeurs sont en pourcentage (ex: -0.78% → -0.78)
- Les percentiles sont des decimaux entre 0 et 1
- Le Z-score peut etre negatif
- Retourne UNIQUEMENT le JSON, rien d'autre
- Inclus TOUTES les lignes du tableau"""
                }
            ]
        }]
    )

    # Parser le JSON de la reponse
    text = response.content[0].text
    # Extraire le JSON du texte
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        return json.loads(json_match.group())
    return {}


def build_features(parsed_data: dict) -> dict:
    """Construit les features ML depuis les donnees CTA parsees."""
    features = {}

    ticker_map = {
        "E-Mini S&P 500": "es",
        "S&P 500": "es",
        "SPX": "es",
        "CME Nasdaq": "nq",
        "Nasdaq": "nq",
        "Gold": "gold",
        "10-Year": "treasury_10y",
        "10Y": "treasury_10y",
        "2-Year": "treasury_2y",
        "2Y": "treasury_2y",
        "Brent": "brent",
        "EUR/USD": "eur_usd",
        "Micro EUR": "eur_usd",
    }

    for row in parsed_data.get("rows", []):
        underlying = row.get("underlying", "")
        # Trouver le ticker
        ticker = None
        for key, val in ticker_map.items():
            if key.lower() in underlying.lower():
                ticker = val
                break
        if not ticker:
            continue

        # Features
        features[f"cta_{ticker}_position"] = row.get("position_today", 0)
        features[f"cta_{ticker}_yesterday"] = row.get("position_yesterday", 0)
        features[f"cta_{ticker}_1m_ago"] = row.get("position_1m_ago", 0)
        features[f"cta_{ticker}_pct_3m"] = row.get("percentile_3m", 0.5)
        features[f"cta_{ticker}_pct_1y"] = row.get("percentile_1y", 0.5)
        features[f"cta_{ticker}_zscore"] = row.get("zscore_3m", 0)

        # Bias derive
        pos = row.get("position_today", 0)
        if pos > 0.5:
            features[f"cta_{ticker}_bias"] = 1  # LONG fort
        elif pos > 0:
            features[f"cta_{ticker}_bias"] = 0.5  # LONG faible
        elif pos > -0.5:
            features[f"cta_{ticker}_bias"] = -0.5  # SHORT faible
        else:
            features[f"cta_{ticker}_bias"] = -1  # SHORT fort

    # Cross-asset : ES vs Gold divergence
    es_pos = features.get("cta_es_position", 0)
    gold_pos = features.get("cta_gold_position", 0)
    features["cta_es_gold_divergence"] = es_pos - gold_pos

    return features


def scrape_cta(date_str: str = None):
    """Pipeline complet : Playwright → S3 images → Claude Vision → JSON."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    date_file = date_str.replace("-", "")

    print(f"\n{'=' * 60}")
    print(f"  CTA AUTO SCRAPER — {date_str}")
    print(f"{'=' * 60}\n")

    # 1. Telecharger les images
    images = download_cta_images(date_str)
    if "main_table" not in images:
        print("  ERREUR: main_table non telechargee")
        return False

    # 2. Parser avec Claude Vision
    api_key = load_anthropic_key()
    if not api_key:
        print("  ERREUR: cle API Anthropic manquante")
        print("  Creez .env.anthropic avec ANTHROPIC_API_KEY=sk-...")
        return False

    print("\n  [4] Parsing Claude Vision...")
    result = {"date": date_str, "source": "MenthorQ CTA via Playwright + Claude Vision"}

    for table_name, path in images.items():
        if "table" in table_name:
            print(f"      Parsing {table_name}...")
            try:
                parsed = parse_image_with_claude(path, api_key)
                result[table_name] = parsed
                n_rows = len(parsed.get("rows", []))
                print(f"      {table_name}: {n_rows} lignes extraites")
            except Exception as e:
                print(f"      {table_name}: ERREUR {e}")

    # 3. Construire les features ML
    print("\n  [5] Construction features ML...")
    all_features = {}
    for table_name, parsed in result.items():
        if isinstance(parsed, dict) and "rows" in parsed:
            features = build_features(parsed)
            all_features.update(features)

    result["features"] = all_features
    print(f"      {len(all_features)} features CTA extraites")

    for k, v in sorted(all_features.items()):
        print(f"        {k:35s} = {v}")

    # 4. Sauvegarder
    out_path = os.path.join(DATA_DIR, f"{date_file}_cta.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n  Sauvegarde: {out_path} ({os.path.getsize(out_path)//1024}KB)")

    print(f"\n{'=' * 60}")
    print(f"  CTA SCRAPING TERMINE — {len(all_features)} features")
    print(f"{'=' * 60}\n")

    return True


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else None
    scrape_cta(date)
