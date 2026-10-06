#!/usr/bin/env python3
"""
Scraper Japscan - Télécharge et assemble les mangas de japscan.st en fichiers CBR.
"""
import hashlib
import io
import json
import logging
import os
import re
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path
from threading import Thread
from urllib.parse import urljoin, quote

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    requests = None
    BeautifulSoup = None

logger = logging.getLogger("japscan_scraper")

JAPSCAN_URL = "https://japscan.cc"  # japscan.st a fermé, on utilise japscan.cc
TIMEOUT = 10
MAX_RETRIES = 3

# État global des téléchargements
download_jobs = {}


class JapscanScraper:
    """Scrape les mangas de Japscan."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session() if requests else None
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def _fetch(self, url: str, **kwargs) -> str | None:
        """Récupère une URL avec retry."""
        if not self.session:
            logger.error("requests non installé")
            return None

        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.get(url, timeout=TIMEOUT, **kwargs)
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                logger.warning(f"Tentative {attempt + 1}/{MAX_RETRIES} échouée pour {url}: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
        return None

    def list_manga(self) -> list[dict]:
        """Liste les mangas disponibles."""
        logger.info("Scrape la liste des mangas...")
        html = self._fetch(f"{JAPSCAN_URL}/listing")
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        mangas = []

        # Structure dépend du site - à adapter
        for item in soup.select("div.manga-item, a.manga-link")[:50]:  # Limite à 50
            try:
                name_el = item.select_one("h3, .title, .name")
                if not name_el:
                    continue

                title = name_el.get_text(strip=True)
                link = item.get("href") or item.select_one("a")
                if not link:
                    link_href = ""
                elif isinstance(link, str):
                    link_href = link
                else:
                    link_href = link.get("href", "")

                url = urljoin(JAPSCAN_URL, link_href)

                mangas.append({
                    "title": title,
                    "url": url,
                    "id": hashlib.md5(url.encode()).hexdigest()[:12]
                })
            except Exception as e:
                logger.warning(f"Erreur parsing manga: {e}")
                continue

        logger.info(f"Trouvé {len(mangas)} mangas")
        return mangas

    def get_chapters(self, manga_url: str) -> list[dict]:
        """Récupère les chapitres d'un manga."""
        logger.info(f"Récupère les chapitres: {manga_url}")
        html = self._fetch(manga_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        chapters = []

        # À adapter selon la structure du site
        for item in soup.select("a.chapter-link, .chapter-item a"):
            try:
                title = item.get_text(strip=True)
                url = urljoin(JAPSCAN_URL, item.get("href", ""))

                if url == JAPSCAN_URL:
                    continue

                chapters.append({
                    "title": title,
                    "url": url,
                    "num": len(chapters) + 1
                })
            except Exception as e:
                logger.warning(f"Erreur parsing chapitre: {e}")

        logger.info(f"Trouvé {len(chapters)} chapitres")
        return list(reversed(chapters))  # Ordre chronologique

    def download_chapter_pages(self, chapter_url: str) -> list[bytes]:
        """Télécharge les pages d'un chapitre."""
        logger.info(f"Télécharge les pages: {chapter_url}")
        html = self._fetch(chapter_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        pages = []

        # À adapter selon la structure (cherche img.page, img[data-src], etc.)
        for img in soup.select("img.page, img[data-src], img[data-lazy-src]"):
            try:
                src = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
                if not src or "blank" in src.lower():
                    continue

                page_url = urljoin(JAPSCAN_URL, src)
                logger.debug(f"Télécharge page: {page_url}")

                # Télécharge l'image
                img_data = self._fetch_binary(page_url)
                if img_data:
                    pages.append(img_data)
                    time.sleep(0.5)  # Rate limiting
            except Exception as e:
                logger.warning(f"Erreur téléchargement page: {e}")

        logger.info(f"Téléchargé {len(pages)} pages")
        return pages

    def _fetch_binary(self, url: str) -> bytes | None:
        """Télécharge un fichier binaire."""
        if not self.session:
            return None

        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.get(url, timeout=TIMEOUT)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                logger.warning(f"Tentative {attempt + 1} échouée pour {url}: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
        return None

    def create_cbr(self, pages: list[bytes], output_path: Path) -> bool:
        """Crée un fichier CBR (ZIP avec images)."""
        logger.info(f"Crée CBR: {output_path}")
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for idx, page_data in enumerate(pages, 1):
                    # Détermine l'extension (jpg ou png)
                    if page_data.startswith(b'\xff\xd8\xff'):
                        ext = "jpg"
                    elif page_data.startswith(b'\x89PNG'):
                        ext = "png"
                    else:
                        ext = "jpg"

                    filename = f"{idx:04d}.{ext}"
                    zf.writestr(filename, page_data)

            logger.info(f"CBR créé: {output_path} ({len(pages)} pages)")
            return True
        except Exception as e:
            logger.error(f"Erreur création CBR: {e}")
            return False


def search_metadata(manga_title: str) -> dict:
    """Cherche les métadonnées du manga (nombre de chapitres par tome)."""
    logger.info(f"Cherche métadonnées: {manga_title}")
    # Implémentation simple - tu peux l'étendre avec TMDb, MyAnimeList, etc.
    return {
        "title": manga_title,
        "chapters_per_tome": [],  # À remplir manuellement
        "total_chapters": 0,
        "source": "manual"
    }


def download_manga_background(job_id: str, manga_title: str, chapters: list[dict],
                              output_dir: Path, progress_callback=None):
    """Télécharge un manga en arrière-plan."""
    job = {
        "id": job_id,
        "title": manga_title,
        "status": "running",
        "progress": 0,
        "total": len(chapters),
        "downloaded": [],
        "error": None,
        "started": datetime.now().isoformat()
    }
    download_jobs[job_id] = job

    try:
        scraper = JapscanScraper(output_dir)

        for idx, chapter in enumerate(chapters):
            try:
                # Télécharge les pages
                pages = scraper.download_chapter_pages(chapter["url"])
                if not pages:
                    logger.warning(f"Aucune page pour {chapter['title']}")
                    continue

                # Crée le CBR
                chapter_file = output_dir / f"{chapter['num']:03d} - {chapter['title']}.cbr"
                if scraper.create_cbr(pages, chapter_file):
                    job["downloaded"].append(str(chapter_file))

                # Mise à jour progression
                job["progress"] = idx + 1
                if progress_callback:
                    progress_callback(job)

            except Exception as e:
                logger.error(f"Erreur chapitre {chapter['title']}: {e}")
                job["error"] = str(e)

        job["status"] = "completed"
        logger.info(f"Téléchargement terminé: {job_id}")

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        logger.error(f"Erreur téléchargement: {e}")

    job["ended"] = datetime.now().isoformat()
