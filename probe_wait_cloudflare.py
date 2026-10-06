#!/usr/bin/env python3
"""
Test attendre que Cloudflare se résolve tout seul.
Cloudflare renvoie un challenge, puis après ~5 secondes + interaction,
laisse passer le traffic.
"""
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import time
import sys

def test_wait_cloudflare():
    """Teste l'attente pour que Cloudflare se résolve."""

    chapter_url = "https://www.japscan.foo/manga/dandadan/247/"

    print(f"\n{'='*70}")
    print("Test Attendre Cloudflare")
    print('='*70)
    print(f"URL: {chapter_url}\n")

    try:
        print("Lancement Playwright avec headless=False...")
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ]
            )

            page = browser.new_page()

            # Masquer webdriver
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false,
                });
            """)

            print(f"Chargement {chapter_url}...")
            response = page.goto(chapter_url, wait_until="load")
            status = response.status if response else "Unknown"
            print(f"Status initial: {status}")

            html = page.content()
            if "just a moment" in html.lower():
                print("✗ Cloudflare challenge détecté")
                print("\nAttente 10 secondes pour résolution...")

                # Attendre
                for i in range(10, 0, -1):
                    print(f"  {i}s...", end="\r")
                    time.sleep(1)

                print("\n✓ Rechargement de la page...")
                response = page.reload(wait_until="load")
                status = response.status if response else "Unknown"
                print(f"Status après attente: {status}")

                html = page.content()

            print(f"✓ Chargé: {len(html)} caractères")

            # Analyse
            soup = BeautifulSoup(html, "html.parser")
            title = soup.find("title")
            print(f"✓ Titre: {title.get_text() if title else 'N/A'}")

            if "just a moment" in html.lower():
                print("✗ Cloudflare toujours présent")
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

                    if src:
                        print(f"    [{i}] src={src[:80]}")
                    if data_src:
                        print(f"    [{i}] data-src={data_src[:80]}")

            print("\n✓ SUCCÈS ! Page chargée sans Cloudflare !")

            browser.close()
            return True

    except Exception as e:
        print(f"✗ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Lance avec : xvfb-run -a python3 probe_wait_cloudflare.py")
    print("")

    success = test_wait_cloudflare()
    sys.exit(0 if success else 1)
