#!/usr/bin/env python3
"""
Script de diagnostic pour charger une page de chapitre Japscan.
Teste différentes stratégies pour contourner le timeout/403.
"""
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import time

def probe_chapter():
    """Teste le chargement d'une page de chapitre."""

    chapter_url = "https://www.japscan.foo/manga/dandadan/247/"

    print(f"\n{'='*70}")
    print("Probe Chapitre Japscan")
    print('='*70)
    print(f"URL: {chapter_url}\n")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # Test 1 : waitUntil="load" (plus rapide que networkidle)
            print("Test 1 : waitUntil='load'")
            try:
                page = browser.new_page()
                page.set_default_timeout(15000)
                response = page.goto(chapter_url, wait_until="load")
                print(f"✓ Status: {response.status if response else 'Unknown'}")
                html = page.content()
                print(f"✓ Chargé: {len(html)} caractères")
                page.close()

                # Analyse rapide
                soup = BeautifulSoup(html, "html.parser")
                title = soup.find("title")
                if title:
                    print(f"✓ Titre: {title.get_text()}")

                # Cherche les images
                imgs = soup.find_all("img")
                print(f"✓ Images trouvées: {len(imgs)}")

                if imgs:
                    print(f"  Première image:")
                    img = imgs[0]
                    print(f"    src: {img.get('src', '')[:80]}")
                    print(f"    data-src: {img.get('data-src', '')[:80]}")
                    print(f"    classes: {img.get('class', [])}")

                return
            except Exception as e:
                print(f"✗ Erreur: {e}\n")

            # Test 2 : waitUntil="domcontentloaded"
            print("Test 2 : waitUntil='domcontentloaded'")
            try:
                page = browser.new_page()
                page.set_default_timeout(15000)
                response = page.goto(chapter_url, wait_until="domcontentloaded")
                print(f"✓ Status: {response.status if response else 'Unknown'}")
                html = page.content()
                print(f"✓ Chargé: {len(html)} caractères")
                page.close()
                return
            except Exception as e:
                print(f"✗ Erreur: {e}\n")

            # Test 3 : timeout plus court avec networkidle
            print("Test 3 : waitUntil='networkidle' + timeout court (5s)")
            try:
                page = browser.new_page()
                page.set_default_timeout(5000)
                response = page.goto(chapter_url, wait_until="networkidle")
                print(f"✓ Status: {response.status if response else 'Unknown'}")
                html = page.content()
                print(f"✓ Chargé: {len(html)} caractères")
                page.close()
                return
            except Exception as e:
                print(f"✗ Erreur (normal si timeout): {e}\n")

            # Test 4 : Sans wait_until
            print("Test 4 : Sans attendre (wait_until=None)")
            try:
                page = browser.new_page()
                page.set_default_timeout(5000)
                response = page.goto(chapter_url)
                print(f"✓ Status: {response.status if response else 'Unknown'}")
                html = page.content()
                print(f"✓ Chargé: {len(html)} caractères")
                page.close()
                return
            except Exception as e:
                print(f"✗ Erreur: {e}\n")

            browser.close()

    except Exception as e:
        print(f"❌ Erreur fatale: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    probe_chapter()
