"""
cta_screenshot.py — Capture screenshot des donnees CTA MenthorQ
================================================================

Se connecte a MenthorQ via Playwright headless, navigue vers la page CTA,
attend le chargement des donnees, et sauvegarde un screenshot.

Le screenshot sera ensuite envoye a Claude Vision API pour extraction des donnees.

Usage :
    python cta_screenshot.py                    # date du jour
    python cta_screenshot.py 2026-04-02         # date specifique

Auteur : MIA Trading System
Date   : 2026-04-02
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

DATA_DIR = r"C:\TRADING_SIERRA_CHART_AUTO\DATA\MENTHORQ"
ENV_FILE = os.path.join(os.path.dirname(__file__), ".env.menthorq")


def load_credentials():
    """Charge les credentials MenthorQ."""
    if not os.path.exists(ENV_FILE):
        print(f"ERREUR: {ENV_FILE} absent")
        sys.exit(1)
    creds = {}
    for line in open(ENV_FILE):
        if "=" in line:
            k, v = line.strip().split("=", 1)
            creds[k.strip()] = v.strip()
    return creds.get("MENTHORQ_EMAIL", ""), creds.get("MENTHORQ_PASSWORD", "")


def capture_cta(date_str: str = None):
    """Capture les screenshots CTA pour une date donnee."""
    from playwright.sync_api import sync_playwright

    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    email, password = load_credentials()
    os.makedirs(DATA_DIR, exist_ok=True)

    date_file = date_str.replace("-", "")
    screenshot_dir = os.path.join(DATA_DIR, "screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)

    print(f"CTA Screenshot — {date_str}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        # 1. Login
        print("  [1] Login MenthorQ...")
        page.goto("https://menthorq.com/wp-login.php")
        page.fill("#user_login", email)
        page.fill("#user_pass", password)
        page.click("#wp-submit")
        page.wait_for_load_state("networkidle")
        print("  [1] Login OK")

        # 2. Page CTA Index
        print("  [2] Navigation CTA Index...")
        cta_url = (f"https://menthorq.com/account/?action=data&type=dashboard"
                   f"&commands=cta&tickers=cta&date={date_str}&ticker=SPX")
        page.goto(cta_url)
        page.wait_for_load_state("networkidle")
        time.sleep(3)  # Attendre le rendu des images

        # Cliquer sur cta_index pour afficher le tableau complet
        try:
            # Chercher le bouton/onglet CTA Index
            for selector in [
                "text=CTA Index", "text=cta_index", "text=Index",
                "[data-slug='cta_index']", ".command-item:has-text('Index')"
            ]:
                el = page.query_selector(selector)
                if el:
                    el.click()
                    time.sleep(3)
                    print(f"  [2] Clique sur {selector}")
                    break
        except Exception as e:
            print(f"  [2] Pas de bouton index: {e}")

        # Screenshot page complete
        path_full = os.path.join(screenshot_dir, f"{date_file}_cta_full.png")
        page.screenshot(path=path_full, full_page=True)
        print(f"  [2] Screenshot: {path_full}")

        # 3. Page CTA SPX specifique
        print("  [3] Navigation CTA SPX...")
        for slug in ["cta_spx", "cta_nasdaq"]:
            try:
                for selector in [
                    f"text={slug}", f"[data-slug='{slug}']",
                    f".command-item:has-text('{slug}')"
                ]:
                    el = page.query_selector(selector)
                    if el:
                        el.click()
                        time.sleep(3)
                        path_slug = os.path.join(screenshot_dir, f"{date_file}_{slug}.png")
                        page.screenshot(path=path_slug, full_page=True)
                        print(f"  [3] Screenshot {slug}: {path_slug}")
                        break
            except Exception as e:
                print(f"  [3] Skip {slug}: {e}")

        # 4. Essayer de capturer les tableaux individuellement
        print("  [4] Capture tableaux...")
        tables = page.query_selector_all("table")
        for i, table in enumerate(tables):
            try:
                path_table = os.path.join(screenshot_dir, f"{date_file}_cta_table_{i}.png")
                table.screenshot(path=path_table)
                print(f"  [4] Table {i}: {path_table}")
            except:
                pass

        # 5. Capturer les images CTA (PNG pre-rendus par MenthorQ)
        print("  [5] Capture images CTA...")
        images = page.query_selector_all("img[src*='s3.amazonaws']")
        for i, img in enumerate(images[:5]):
            src = img.get_attribute("src")
            if src and "cta" in src.lower():
                print(f"  [5] Image CTA trouvee: {src[:100]}...")

        # 6. Extraire le contenu visible de la page (texte brut)
        print("  [6] Extraction texte...")
        text_content = page.inner_text("body")
        path_text = os.path.join(screenshot_dir, f"{date_file}_cta_text.txt")
        with open(path_text, "w", encoding="utf-8") as f:
            f.write(text_content)
        print(f"  [6] Texte sauve: {path_text} ({len(text_content)} chars)")

        browser.close()

    print(f"\nScreenshots sauves dans {screenshot_dir}")
    return screenshot_dir


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else None
    capture_cta(date)
