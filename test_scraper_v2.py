#!/usr/bin/env python3
"""
Test du scraper Japscan v2.0
Lance : xvfb-run -a python3 test_scraper_v2.py
"""
import asyncio
import logging
from pathlib import Path
from japscan_scraper import JapscanScraper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Test complet : liste → chapitres → pages → CBZ"""
    output_dir = Path("/tmp/test_japscan_v2")
    scraper = JapscanScraper(output_dir)

    try:
        # Test 1 : Liste des mangas
        print("\n" + "="*70)
        print("TEST 1 : Récupération de la liste des mangas")
        print("="*70)
        mangas = await scraper.list_manga()
        print(f"✓ {len(mangas)} mangas trouvés")
        if not mangas:
            print("✗ Aucun manga trouvé - abandon")
            return

        # Prendre le premier manga trouvé
        first_manga = mangas[0]
        print(f"Premier manga : {first_manga['title']}")
        print(f"URL : {first_manga['url']}")

        # Test 2 : Récupération des chapitres
        print("\n" + "="*70)
        print("TEST 2 : Récupération des chapitres")
        print("="*70)
        chapters = await scraper.get_chapters(first_manga['url'])
        print(f"✓ {len(chapters)} chapitres trouvés")
        if not chapters:
            print("✗ Aucun chapitre trouvé - abandon")
            return

        # Prendre le dernier chapitre (plus petit)
        last_chapter = chapters[-1]
        print(f"Chapitre testé : {last_chapter['title']}")
        print(f"URL : {last_chapter['url']}")

        # Test 3 : Téléchargement des pages
        print("\n" + "="*70)
        print("TEST 3 : Téléchargement des pages du chapitre")
        print("="*70)
        pages = await scraper.download_chapter_pages(last_chapter['url'])
        print(f"✓ {len(pages)} pages capturées")
        if not pages:
            print("✗ Aucune page capturée - abandon")
            return

        # Test 4 : Création CBZ
        print("\n" + "="*70)
        print("TEST 4 : Création archive CBZ")
        print("="*70)
        cbz_path = output_dir / f"test_chapter_{last_chapter['num']:03d}.cbz"
        success = scraper.create_cbz(pages, cbz_path)
        if success:
            file_size = cbz_path.stat().st_size / (1024 * 1024)  # En Mo
            print(f"✓ CBZ créé : {cbz_path.name} ({file_size:.2f} Mo)")
        else:
            print(f"✗ Erreur création CBZ")
            return

        print("\n" + "="*70)
        print("✓ TOUS LES TESTS RÉUSSIS !")
        print("="*70)
        print(f"\nArchive créée : {cbz_path}")
        print(f"Pages : {len(pages)}")
        print(f"Taille : {file_size:.2f} Mo")

    except Exception as e:
        logger.error(f"Erreur : {e}", exc_info=True)
        print(f"\n✗ ERREUR : {e}")


if __name__ == "__main__":
    asyncio.run(main())
