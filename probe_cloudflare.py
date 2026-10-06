#!/usr/bin/env python3
"""
Script pour contourner la protection Cloudflare sur Japscan.
Teste différentes techniques anti-détection Playwright.
"""
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import time

def test_cloudflare():
    """Teste les techniques pour contourner Cloudflare."""

    chapter_url = "https://www.japscan.foo/manga/dandadan/247/"

    print(f"\n{'='*70}")
    print("Contournement Cloudflare Japscan")
    print('='*70)
    print(f"URL: {chapter_url}\n")

    try:
        # Test 1 : Headless normal
        print("Test 1 : Headless normal (baseline)")
        try:
            p = sync_playwright().start()
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(10000)

            response = page.goto(chapter_url, wait_until="load")
            status = response.status if response else "Unknown"
            html = page.content()

            print(f"✓ Status: {status}")
            print(f"✓ Size: {len(html)} chars")

            title = BeautifulSoup(html, "html.parser").find("title")
            print(f"✓ Title: {title.get_text() if title else 'N/A'}")

            if "just a moment" not in html.lower():
                print("✓ Cloudflare CONTOURNÉ !")
                return True
            else:
                print("✗ Still Cloudflare")

            page.close()
            browser.close()
            p.stop()
        except Exception as e:
            print(f"✗ Erreur: {e}\n")

        # Test 2 : Headless désactivé (vrai navigateur visible)
        print("\nTest 2 : Headless=False (navigateur visible)")
        try:
            p = sync_playwright().start()
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.set_default_timeout(10000)

            print("  (Navigateur ouvert, attend 3 secondes...)")
            response = page.goto(chapter_url, wait_until="load")
            status = response.status if response else "Unknown"
            html = page.content()

            print(f"✓ Status: {status}")
            print(f"✓ Size: {len(html)} chars")

            title = BeautifulSoup(html, "html.parser").find("title")
            print(f"✓ Title: {title.get_text() if title else 'N/A'}")

            if "just a moment" not in html.lower():
                print("✓ Cloudflare CONTOURNÉ !")
                return True
            else:
                print("✗ Still Cloudflare")

            page.close()
            browser.close()
            p.stop()
            time.sleep(2)
        except Exception as e:
            print(f"✗ Erreur: {e}\n")

        # Test 3 : Avec --disable-blink-features
        print("\nTest 3 : Avec --disable-blink-features=AutomationControlled")
        try:
            p = sync_playwright().start()
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = browser.new_page()
            page.set_default_timeout(10000)

            # Masquer Playwright
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false,
                });
            """)

            response = page.goto(chapter_url, wait_until="load")
            status = response.status if response else "Unknown"
            html = page.content()

            print(f"✓ Status: {status}")
            print(f"✓ Size: {len(html)} chars")

            title = BeautifulSoup(html, "html.parser").find("title")
            print(f"✓ Title: {title.get_text() if title else 'N/A'}")

            if "just a moment" not in html.lower():
                print("✓ Cloudflare CONTOURNÉ !")
                return True
            else:
                print("✗ Still Cloudflare")

            page.close()
            browser.close()
            p.stop()
        except Exception as e:
            print(f"✗ Erreur: {e}\n")

        # Test 4 : Attendre et scroller
        print("\nTest 4 : Attendre 5 secondes + scroller")
        try:
            p = sync_playwright().start()
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(15000)

            print("  Chargement...")
            response = page.goto(chapter_url, wait_until="load")

            print("  Attente 5 secondes...")
            page.wait_for_timeout(5000)

            print("  Scroll...")
            page.evaluate("window.scrollBy(0, window.innerHeight)")

            html = page.content()
            status = response.status if response else "Unknown"

            print(f"✓ Status: {status}")
            print(f"✓ Size: {len(html)} chars")

            title = BeautifulSoup(html, "html.parser").find("title")
            print(f"✓ Title: {title.get_text() if title else 'N/A'}")

            if "just a moment" not in html.lower():
                print("✓ Cloudflare CONTOURNÉ !")
                return True
            else:
                print("✗ Still Cloudflare")

            page.close()
            browser.close()
            p.stop()
        except Exception as e:
            print(f"✗ Erreur: {e}\n")

        print("\n" + "="*70)
        print("Aucune technique n'a fonctionné.")
        print("Cloudflare est trop restrictif pour ce site.")
        print("="*70)
        return False

    except Exception as e:
        print(f"❌ Erreur fatale: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_cloudflare()
