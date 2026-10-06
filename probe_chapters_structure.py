#!/usr/bin/env python3
"""
Diagnostic : structure HTML des chapitres
Lance : xvfb-run -a python3 probe_chapters_structure.py
"""
import asyncio
import logging
from patchright.async_api import async_playwright
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def diagnose():
    """Analyse la structure HTML d'une page série."""

    manga_url = "https://www.japscan.foo/manga/dandadan/"
    logger.info(f"Diagnostic de {manga_url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--window-size=1920,1080",
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        try:
            await page.goto(manga_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            print("\n" + "="*70)
            print("DIAGNOSTIC STRUCTURE HTML")
            print("="*70)

            # Cherche les sections communes
            print("\n1. Recherche des DIVs avec 'chapter' dans l'ID/class:")
            for div in soup.find_all("div", class_=lambda x: x and "chapter" in x.lower()):
                print(f"   - {div.name} class='{div.get('class')}' id='{div.get('id')}'")
                # Affiche les enfants <a>
                for a in div.find_all("a", limit=3):
                    href = a.get("href", "")
                    text = a.get_text(strip=True)[:50]
                    print(f"     └─ <a href='{href}'> {text}")

            print("\n2. Recherche des tags <a> avec href contenant chapitre/chapter:")
            links = soup.find_all("a", href=lambda x: x and any(k in x.lower() for k in ["chapitre", "chapter", "lecture", "/ch"]))
            print(f"   Total : {len(links)} liens")
            for link in links[:5]:
                href = link.get("href", "")
                text = link.get_text(strip=True)[:50]
                print(f"   - <a href='{href}'> {text}")

            print("\n3. Recherche des <img> avec 'cover' ou 'poster':")
            imgs = soup.find_all("img", class_=lambda x: x and any(k in x.lower() for k in ["cover", "poster", "thumb"]))
            print(f"   Total : {len(imgs)} images")
            for img in imgs[:3]:
                src = img.get("src", "")
                alt = img.get("alt", "")
                print(f"   - <img src='{src[:60]}...' alt='{alt}'")

            print("\n4. Recherche de listes (<ul>, <ol>):")
            for ul in soup.find_all(["ul", "ol"], limit=5):
                children = len(ul.find_all("li"))
                classes = ul.get("class", [])
                print(f"   - <{ul.name} class='{' '.join(classes)}'> ({children} items)")

            print("\n5. Recherche de divs avec id contenant 'chapter' ou 'episode':")
            for div in soup.find_all("div", id=lambda x: x and any(k in x.lower() for k in ["chapter", "episode", "lecture"])):
                div_id = div.get("id", "")
                children = len(div.find_all(["a", "li"], limit=10))
                print(f"   - <div id='{div_id}'> ({children} enfants)")

            print("\n6. Contenu brut (premiers 500 caractères):")
            text_content = soup.get_text()[:500]
            print(f"   {text_content}")

            print("\n" + "="*70)
            print("FIN DIAGNOSTIC")
            print("="*70)

            await browser.close()

        except Exception as e:
            logger.error(f"Erreur : {e}", exc_info=True)
            await browser.close()


if __name__ == "__main__":
    asyncio.run(diagnose())
