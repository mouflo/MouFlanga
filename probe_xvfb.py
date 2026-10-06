#!/usr/bin/env python3
"""
Test Xvfb + Playwright-stealth pour contourner Cloudflare.
À lancer avec : xvfb-run -a python3 probe_xvfb.py
"""
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import sys

def test_xvfb_stealth():
    """Teste Playwright avec stealth mode via Xvfb."""

    chapter_url = "https://www.japscan.foo/manga/dandadan/247/"

    print(f"\n{'='*70}")
    print("Test Xvfb + Playwright-stealth")
    print('='*70)
    print(f"URL: {chapter_url}\n")

    try:
        import playwright_stealth
        print("✓ playwright-stealth importé")
    except ImportError:
        print("✗ playwright-stealth non installé")
        print("\nInstalle avec :")
        print("  pip install playwright-stealth")
        return False

    try:
        print("\nLancement Playwright avec stealth...")
        with sync_playwright() as p:
            # Headless=False + Xvfb simule un vrai navigateur
            browser = p.chromium.launch(
                headless=False,  # Important : headless=False avec Xvfb
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ]
            )

            page = browser.new_page()

            # Masquer la présence de Playwright
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false,
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });
            """)

            page.set_default_timeout(15000)

            print(f"Chargement {chapter_url}...")
            response = page.goto(chapter_url, wait_until="load")
            status = response.status if response else "Unknown"
            print(f"✓ Status: {status}")

            html = page.content()
            print(f"✓ Chargé: {len(html)} caractères")

            # Analyse
            soup = BeautifulSoup(html, "html.parser")
            title = soup.find("title")
            print(f"✓ Titre: {title.get_text() if title else 'N/A'}")

            if "just a moment" in html.lower():
                print("✗ Still Cloudflare - technique échouée")
                browser.close()
                return False

            # Cherche les images
            imgs = soup.find_all("img")
            print(f"✓ Images trouvées: {len(imgs)}")

            if imgs:
                print(f"\n  Premières images :")
                for i, img in enumerate(imgs[:5], 1):
                    src = img.get("src", "")
                    data_src = img.get("data-src", "")

                    if src and "manga" in src.lower():
                        print(f"    [{i}] Manga page: {src[:80]}")
                    elif data_src and "manga" in data_src.lower():
                        print(f"    [{i}] Data-src: {data_src[:80]}")

            print("\n✓ SUCCÈS ! Xvfb + stealth fonctionne !")
            print("\nLe scraper peut maintenant :")
            print("  1. Charger les pages de chapitres")
            print("  2. Extraire les images")
            print("  3. Créer les fichiers CBR")

            browser.close()
            return True

    except Exception as e:
        print(f"✗ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("IMPORTANT : Lance ce script avec :")
    print("  xvfb-run -a python3 probe_xvfb.py")
    print("")

    success = test_xvfb_stealth()
    sys.exit(0 if success else 1)
