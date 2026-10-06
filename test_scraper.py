#!/usr/bin/env python3
"""
Test script to verify Japscan scraper is working.
Run this on your server to test manga list, chapters, and page downloads.
"""
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.DEBUG)

# Add script dir to path so we can import japscan_scraper
sys.path.insert(0, str(Path(__file__).parent))

from japscan_scraper import JapscanScraper
from pathlib import Path

def test_scraper():
    """Test the scraper step by step."""
    output_dir = Path("/tmp/manga_test")

    print("\n" + "="*70)
    print("ÉTAPE 1 : Récupérer la liste des mangas")
    print("="*70)

    scraper = JapscanScraper(output_dir)
    mangas = scraper.list_manga()

    if not mangas:
        print("❌ ERREUR: Aucun manga trouvé!")
        print("\nCela signifie que le sélecteur CSS ne correspond pas à la structure du site.")
        print("Exécute d'abord: python3 probe_japscan.py")
        return False

    print(f"✓ Trouvé {len(mangas)} mangas:")
    for manga in mangas[:5]:
        print(f"  - {manga['title']}")
        print(f"    URL: {manga['url'][:70]}")

    if len(mangas) > 5:
        print(f"  ... et {len(mangas) - 5} autres")

    # Test first manga's chapters
    if mangas:
        print("\n" + "="*70)
        print(f"ÉTAPE 2 : Récupérer les chapitres du premier manga")
        print("="*70)

        first_manga = mangas[0]
        chapters = scraper.get_chapters(first_manga["url"])

        if not chapters:
            print(f"❌ ERREUR: Aucun chapitre trouvé pour {first_manga['title']}")
            print("Exécute probe_japscan.py et cherche le pattern des chapitres")
            return False

        print(f"✓ Trouvé {len(chapters)} chapitres:")
        for ch in chapters[:3]:
            print(f"  - {ch['title']}")
            print(f"    URL: {ch['url'][:70]}")

        if len(chapters) > 3:
            print(f"  ... et {len(chapters) - 3} autres")

        # Test first chapter's pages
        print("\n" + "="*70)
        print(f"ÉTAPE 3 : Récupérer les pages du premier chapitre")
        print("="*70)

        first_chapter = chapters[0]
        pages = scraper.download_chapter_pages(first_chapter["url"])

        if not pages:
            print(f"❌ ERREUR: Aucune page trouvée pour {first_chapter['title']}")
            print("Exécute probe_japscan.py et cherche les sélecteurs pour les images")
            return False

        print(f"✓ Téléchargé {len(pages)} pages")
        for i, page in enumerate(pages[:3], 1):
            print(f"  Page {i}: {len(page)} bytes")

        if len(pages) > 3:
            print(f"  ... et {len(pages) - 3} autres")

    print("\n" + "="*70)
    print("✓ TOUS LES TESTS RÉUSSIS!")
    print("="*70)
    print("\nLe scraper fonctionne correctement.")
    print("Tu peux maintenant utiliser l'interface web pour télécharger des mangas.")
    return True

if __name__ == "__main__":
    try:
        success = test_scraper()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ ERREUR FATALE: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
