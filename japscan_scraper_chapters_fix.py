"""
Méthode get_chapters() améliorée et plus robuste.

À tester une fois qu'on a la structure HTML réelle.
"""
import re
from urllib.parse import urljoin

JAPSCAN_URL = "https://www.japscan.foo"

async def get_chapters_robust(self, manga_url: str) -> list[dict]:
    """
    Récupère les chapitres avec plusieurs stratégies de fallback.
    Utilise l'interception réseau pour capturer les URLs de chapitres.
    """
    manga_url = self.extract_manga_root_url(manga_url)
    logger.info(f"Chargement de la fiche série : {manga_url}")

    captured_chapters = {}

    async with async_playwright() as p:
        browser, context = await self._init_browser(p)
        page = await context.new_page()

        # Listener pour capturer les requêtes de chapitres
        async def on_response(response):
            try:
                # Cherche les URLs contenant les patterns de chapitres
                url = response.url
                if any(k in url.lower() for k in ["/chapitre/", "/chapter/", "/lecture/", "/read/", "/manga/", "/ch"]):
                    # Vérifie que ce n'est pas une ressource (image, CSS, JS)
                    content_type = response.headers.get("content-type", "")
                    if "text/html" in content_type or content_type == "":
                        if url not in captured_chapters:
                            captured_chapters[url] = True
            except Exception:
                pass

        page.on("response", on_response)

        try:
            await page.goto(manga_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            chapters = []
            seen_urls = set()

            # Stratégie 1 : Sélecteurs spécifiques (testés)
            selectors_to_try = [
                "div#chapters_list a",           # ID spécifique
                "div.chapters a",                # Class spécifique
                "div.chapter-list a",
                "div.episode-list a",
                "table.chapter-table a",         # Tableau
                "ul.chapter-list li a",          # Liste
                "a[href*='/chapitre/']",         # Pattern URL chapitre
                "a[href*='/chapter/']",          # Anglais
                "a[href*='/lecture/']",          # Lecture
                "a[href*='/manga/'][href*='/']", # Contient /manga/ ET un numéro
            ]

            all_links = []
            for selector in selectors_to_try:
                try:
                    links = soup.select(selector)
                    if links:
                        logger.info(f"  Sélecteur '{selector}' : {len(links)} matches")
                        all_links.extend(links)
                except Exception as e:
                    logger.debug(f"Erreur sélecteur '{selector}': {e}")

            # Déduplique
            seen = set()
            for link in all_links:
                href = link.get("href", "")
                if href not in seen:
                    seen.add(href)

            # Stratégie 2 : Cherche TOUS les <a> et filtre par URL pattern
            for a in soup.find_all("a"):
                href = a.get("href", "")
                title = a.get_text(strip=True)

                if not href or not title:
                    continue

                # Filtre : URL qui contient /manga/ et un numéro OU contient chapitre/chapter
                is_chapter_url = (
                    ("/manga/" in href.lower() and re.search(r"/\d+/?$", href)) or
                    any(k in href.lower() for k in ["chapitre", "chapter", "lecture", "/ch"])
                )

                if is_chapter_url:
                    full_url = urljoin(JAPSCAN_URL, href)
                    if full_url not in seen_urls:
                        seen_urls.add(full_url)
                        chapters.append({
                            "title": title,
                            "url": full_url,
                            "num": len(chapters) + 1
                        })

            # Stratégie 3 : URLs capturées par l'interception réseau
            for url in captured_chapters.keys():
                if any(k in url.lower() for k in ["/chapitre/", "/chapter/", "/lecture/"]):
                    if url not in seen_urls:
                        seen_urls.add(url)
                        # Extrait le numéro de l'URL
                        match = re.search(r"/(\d+)/?$", url)
                        chapter_num = match.group(1) if match else str(len(chapters) + 1)
                        chapters.append({
                            "title": f"Chapitre {chapter_num}",
                            "url": url,
                            "num": len(chapters) + 1
                        })

            await browser.close()

            # Trie par numéro (ordre chronologique)
            chapters = sorted(chapters, key=lambda x: x["num"])
            logger.info(f"✓ {len(chapters)} chapitres trouvés (stratégies combinées)")
            return chapters

        except Exception as e:
            logger.error(f"Erreur récupération chapitres : {e}")
            await browser.close()
            return []
