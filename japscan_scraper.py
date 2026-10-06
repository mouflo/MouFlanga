#!/usr/bin/env python3
"""
Scraper Japscan v2.0 - MouFlanga
Capture les flux réseau déchiffrés par Chromium sous Xvfb et génère des archives CBZ.
Utilise Patchright (fork de Playwright) pour meilleur contournement Cloudflare.
"""
import asyncio
import hashlib
import logging
import os
import re
import shutil
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin
from datetime import datetime

from bs4 import BeautifulSoup


def async_playwright():
    """Import paresseux : l'appli démarre même si Patchright n'est pas installé."""
    from patchright.async_api import async_playwright as _ap
    return _ap()


def nom_sur(texte: str, defaut: str = "sans-titre") -> str:
    """Rend un texte utilisable comme nom de fichier/dossier (pas de / ni de ..)."""
    texte = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", texte or "")
    texte = re.sub(r"\s+", " ", texte).strip(" .")
    return texte[:120] or defaut


CHALLENGE_TITRES = ("just a moment", "un instant", "attention required")


async def attendre_cloudflare(page, secondes: int = 45) -> str:
    """Attend la fin du défi Cloudflare ; renvoie le titre final de la page."""
    titre = ""
    for _ in range(secondes):
        try:
            titre = (await page.title()) or ""
        except Exception:
            titre = ""  # page en cours de navigation
        if titre and not any(k in titre.lower() for k in CHALLENGE_TITRES):
            return titre
        await asyncio.sleep(1)
    logger.warning(f"Défi Cloudflare non résolu (titre : {titre!r})")
    return titre


logger = logging.getLogger("japscan_scraper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

JAPSCAN_URL = "https://www.japscan.foo"

# État global des téléchargements (pour Flask)
download_jobs = {}


class JapscanScraper:
    """Scraper Japscan v2.0 avec interception réseau pour contourner Cloudflare."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def _init_browser(self, p):
        """Lance Chromium sous Xvfb avec les arguments anti-détection."""
        browser = await p.chromium.launch(
            headless=False,  # Lancé via xvfb-run sur serveur
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--window-size=1920,1080",
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
            timezone_id="Europe/Paris"
        )
        return browser, context

    def extract_manga_root_url(self, url: str) -> str:
        """Nettoie une URL de chapitre pour obtenir l'URL racine de la série."""
        match = re.match(r"^(https?://[^/]+/(?:manga|manhua|manhwa)/[^/]+/).*", url)
        if match:
            return match.group(1)
        return url

    async def list_manga(self) -> list[dict]:
        """Liste les mangas disponibles."""
        logger.info("Récupération de la liste des mangas...")
        mangas = []

        async with async_playwright() as p:
            browser, context = await self._init_browser(p)
            page = await context.new_page()

            try:
                # Essaie plusieurs endpoints - / fonctionne le mieux
                endpoints = ["/", "/mangas/", "/listing", "/series"]
                html = None

                for endpoint in endpoints:
                    url = f"{JAPSCAN_URL}{endpoint}"
                    logger.info(f"Essai endpoint : {url}")
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        await attendre_cloudflare(page)
                        await asyncio.sleep(2)
                        html = await page.content()
                        if html and len(html) > 1000:
                            logger.info(f"✓ Endpoint {endpoint} chargé ({len(html)} caractères)")
                            break
                    except Exception as e:
                        logger.warning(f"Erreur endpoint {endpoint}: {e}")
                        continue

                if not html:
                    logger.error("Impossible de charger la liste des mangas")
                    await browser.close()
                    return []

                soup = BeautifulSoup(html, "html.parser")
                seen_urls = set()

                # Sélecteurs pour trouver les mangas
                selectors = [
                    "a[href*='/manga/']",
                    "a[href*='/manhua/']",
                    "a[href*='/manhwa/']",
                    "a.image-box",
                ]

                for selector in selectors:
                    try:
                        matches = soup.select(selector)
                        logger.info(f"Sélecteur '{selector}' : {len(matches)} matches")

                        for item in matches:
                            try:
                                title = item.get_text(strip=True)
                                href = item.get("href", "")

                                if not title or not href:
                                    continue

                                if not any(x in href.lower() for x in ["manga", "manhua", "manhwa"]):
                                    continue

                                url = urljoin(JAPSCAN_URL, href)
                                if url in seen_urls or url == JAPSCAN_URL:
                                    continue

                                seen_urls.add(url)
                                mangas.append({
                                    "title": title,
                                    "url": url,
                                    "id": hashlib.md5(url.encode()).hexdigest()[:12]
                                })
                            except Exception as e:
                                logger.debug(f"Erreur parsing item: {e}")
                                continue
                    except Exception as e:
                        logger.debug(f"Erreur sélecteur '{selector}': {e}")
                        continue

                await browser.close()
                logger.info(f"✓ {len(mangas)} mangas trouvés au total")
                return mangas

            except Exception as e:
                logger.error(f"Erreur liste mangas: {e}")
                await browser.close()
                return []

    async def get_chapters(self, manga_url: str) -> list[dict]:
        """Récupère la liste des chapitres d'un manga."""
        manga_url = self.extract_manga_root_url(manga_url)
        logger.info(f"Chargement de la fiche série : {manga_url}")

        async with async_playwright() as p:
            browser, context = await self._init_browser(p)
            page = await context.new_page()

            try:
                # domcontentloaded au lieu de networkidle pour éviter les timeouts
                await page.goto(manga_url, wait_until="domcontentloaded", timeout=30000)

                title = await attendre_cloudflare(page)

                await asyncio.sleep(2)  # Laisse le JS injecter la liste
                html = await page.content()
                logger.info(f"Fiche série chargée : titre={title!r}, {len(html)} caractères")

                # Dump de debug pour analyse hors-ligne
                try:
                    Path("/tmp/japscan_series_debug.html").write_text(html, encoding="utf-8")
                except Exception:
                    pass

                soup = BeautifulSoup(html, "html.parser")
                slug_match = re.search(r"/(?:manga|manhua|manhwa)/([^/]+)/?", manga_url)
                slug = slug_match.group(1) if slug_match else None
                chapters = []
                seen_urls = set()

                # Tous les liens pointant vers /<type>/<slug>/<numéro>/ de CETTE série
                pattern = re.compile(
                    r"/(?:manga|manhua|manhwa)/" + (re.escape(slug) if slug else r"[^/]+") + r"/([\w.\-]+)/?$"
                )
                for item in soup.find_all("a", href=True):
                    href = item["href"]
                    m = pattern.search(href)
                    if not m or not re.search(r"\d", m.group(1)):
                        continue
                    full_url = urljoin(JAPSCAN_URL, href)
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)
                    chapters.append({
                        "title": item.get_text(strip=True) or f"Chapitre {m.group(1)}",
                        "url": full_url,
                        "chapter_id": m.group(1),
                    })

                # Ordre chronologique (le site liste du plus récent au plus ancien)
                def _key(c):
                    try:
                        return float(c["chapter_id"])
                    except ValueError:
                        return float("inf")
                chapters.sort(key=_key)
                for i, c in enumerate(chapters, 1):
                    c["num"] = i

                await browser.close()
                logger.info(f"✓ {len(chapters)} chapitres trouvés.")
                return chapters

            except Exception as e:
                logger.error(f"Erreur lors de la récupération des chapitres : {e}")
                await browser.close()
                return []

    async def download_chapter_pages(self, chapter_url: str) -> list[bytes]:
        """Télécharge les pages en interceptant le flux réseau déchiffré."""
        logger.info(f"Début de l'aspiration du chapitre : {chapter_url}")
        captured_images = {}

        async with async_playwright() as p:
            browser, context = await self._init_browser(p)
            page = await context.new_page()

            # Listener d'interception des requêtes d'images
            async def on_response(response):
                try:
                    content_type = response.headers.get("content-type", "")
                    if "image" in content_type and response.status == 200:
                        url = response.url
                        # Exclure les éléments d'interface (logos, pubs, avatars, favicons)
                        chemin = url.split("?")[0].lower()
                        if not any(k in chemin for k in ["logo", "avatar", "banner", "/ads/", "/ad/", "favicon", "/icons/"]):
                            body = await response.body()
                            if len(body) > 15000:  # Exclure les petites images/icônes (< 15 Ko)
                                captured_images[url] = body
                except Exception:
                    pass

            page.on("response", on_response)

            try:
                await page.goto(chapter_url, wait_until="domcontentloaded", timeout=30000)
                await attendre_cloudflare(page)
                await asyncio.sleep(4)  # Laisser charger le lecteur JS

                # Simuler un défilement progressif vers le bas pour forcer le chargement de toutes les pages
                logger.info("Défilement de la page pour forcer le lazy-loading...")
                for _ in range(15):
                    await page.mouse.wheel(0, 1200)
                    await asyncio.sleep(0.6)

                await asyncio.sleep(2)
                await browser.close()

            except Exception as e:
                logger.error(f"Erreur lors du chargement du chapitre {chapter_url} : {e}")
                await browser.close()

        # Tri des images par URL/ordre de capture
        def _naturel(u):
            return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", u.split("?")[0])]
        sorted_urls = sorted(captured_images.keys(), key=_naturel)
        images_bytes = [captured_images[u] for u in sorted_urls]
        logger.info(f"✓ {len(images_bytes)} pages capturées sur le réseau.")
        return images_bytes

    def create_cbz(self, pages: list[bytes], output_path: Path) -> bool:
        """Combine les pages capturées dans un fichier .cbz (Archive Zip)."""
        if not pages:
            return False

        logger.info(f"Création de l'archive CBZ : {output_path}")
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for idx, page_data in enumerate(pages, 1):
                    # Déduction de l'extension selon le magic byte
                    ext = "jpg"
                    if page_data.startswith(b"\x89PNG"):
                        ext = "png"
                    elif page_data.startswith(b"RIFF") and page_data[8:12] == b"WEBP":
                        ext = "webp"

                    filename = f"page_{idx:03d}.{ext}"
                    zf.writestr(filename, page_data)

            logger.info(f"✓ CBZ créé avec succès ({len(pages)} pages) -> {output_path}")
            return True
        except Exception as e:
            logger.error(f"Erreur création CBZ : {e}")
            return False

    # ------------------------------------------------------------------
    # Versions synchrones (Flask n'est pas asynchrone)
    # ------------------------------------------------------------------
    def list_manga_sync(self) -> list[dict]:
        return asyncio.run(self.list_manga())

    def get_chapters_sync(self, manga_url: str) -> list[dict]:
        return asyncio.run(self.get_chapters(manga_url))

    def download_manga_sync(self, job_id: str, manga_title: str, chapters: list[dict],
                            progress_callback=None):
        """Télécharge les chapitres un par un et crée un .cbz par chapitre."""
        job = {
            "id": job_id,
            "title": manga_title,
            "status": "running",
            "progress": 0,
            "total": len(chapters),
            "downloaded": [],
            "failed": [],
            "error": None,
            "started": datetime.now().isoformat(),
        }
        download_jobs[job_id] = job

        try:
            for idx, chapter in enumerate(chapters):
                titre = chapter.get("title") or f"Chapitre {idx + 1}"
                try:
                    pages = asyncio.run(self.download_chapter_pages(chapter["url"]))
                    if not pages:
                        logger.warning(f"Aucune page pour {titre}")
                        job["failed"].append(titre)
                    else:
                        num = int(chapter.get("num") or idx + 1)
                        fichier = self.output_dir / f"{num:03d} - {nom_sur(titre)}.cbz"
                        if self.create_cbz(pages, fichier):
                            job["downloaded"].append(str(fichier))
                        else:
                            job["failed"].append(titre)
                except Exception as e:
                    logger.error(f"Erreur chapitre {titre} : {e}")
                    job["failed"].append(titre)
                    job["error"] = str(e)

                job["progress"] = idx + 1
                if progress_callback:
                    progress_callback(job)

            job["status"] = "completed"
            logger.info(f"Téléchargement terminé : {job_id}")
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            logger.error(f"Erreur téléchargement : {e}")

        job["ended"] = datetime.now().isoformat()


def download_manga_background(job_id: str, manga_title: str, chapters: list[dict], output_dir: Path):
    """Point d'entrée utilisé par l'appli (dans un thread)."""
    JapscanScraper(output_dir).download_manga_sync(job_id, manga_title, chapters)
