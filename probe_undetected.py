#!/usr/bin/env python3
"""
Script pour contourner Cloudflare avec undetected-chromium.
Utilise une version modifiée de Chromium que Cloudflare ne détecte pas.
"""
import sys
import time
from bs4 import BeautifulSoup

def test_undetected():
    """Teste undetected-chromium."""

    chapter_url = "https://www.japscan.foo/manga/dandadan/247/"

    print(f"\n{'='*70}")
    print("Test undetected-chromium")
    print('='*70)
    print(f"URL: {chapter_url}\n")

    try:
        import undetected_chrome as uc
        print("✓ undetected_chrome importé")
    except ImportError:
        print("✗ undetected_chrome non installé")
        print("\nPour installer :")
        print("  pip install undetected-chromedriver")
        return False

    try:
        print("\nLancement du navigateur undetected...")
        driver = uc.Chrome(headless=True)

        print(f"Chargement {chapter_url}...")
        driver.get(chapter_url)

        # Attendre le chargement
        time.sleep(3)

        html = driver.page_source
        print(f"✓ Chargé: {len(html)} caractères")

        # Analyse
        soup = BeautifulSoup(html, "html.parser")
        title = soup.find("title")
        print(f"✓ Titre: {title.get_text() if title else 'N/A'}")

        if "just a moment" in html.lower():
            print("✗ Still Cloudflare")
            driver.quit()
            return False

        # Cherche les images
        imgs = soup.find_all("img")
        print(f"✓ Images trouvées: {len(imgs)}")

        if imgs:
            print(f"\n  Détails des images:")
            for i, img in enumerate(imgs[:3], 1):
                src = img.get("src", "")
                data_src = img.get("data-src", "")
                classes = img.get("class", [])

                print(f"    [{i}] src={src[:60]}")
                print(f"        data-src={data_src[:60]}")
                print(f"        classes={classes}")

        # Cherche les sélecteurs pour les pages
        print(f"\n  Cherche sélecteurs pour les pages:")

        selectors = [
            "img.page",
            "img[data-src]",
            "img[data-lazy-src]",
            "img[class*='page']",
            "div.page img",
            "img[src*='manga']",
            "img",
        ]

        for selector in selectors:
            matches = soup.select(selector)
            if matches:
                print(f"    ✓ {selector} → {len(matches)} matches")
                if matches:
                    print(f"      Premier: {matches[0].get('src', '')[:60]}")
                    break

        print("\n✓ undetected-chromium FONCTIONNE !")
        driver.quit()
        return True

    except Exception as e:
        print(f"✗ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_undetected()
    sys.exit(0 if success else 1)
