"""Sources de lecture en français autres que Japscan : sites lus sans navigateur, comme un lecteur qui ouvre des pages.

Chaque source sait trois choses : `rechercher(texte)`, `chapitres(adresse_serie)` et `pages(adresse_chapitre)`. Les chapitres ont la même forme
que ceux de Japscan (`title`, `url`, `chapter_id`, `volume` pour un tome complet), donc le reste de l'appli (cases à cocher, rangement dans
les tomes, protections des tomes déjà là) ne change pas.

Règles : en-tête honnête (`MouFlanga/1.0`), jamais de contournement d'une protection anti-robot (une page qui répond 403/503 ou « un instant »
= la source est mise en pause et dite en panne), `robots.txt` respecté, une requête par seconde et par site, et un chapitre dont une page manque
n'est jamais écrit (aucun tome à trous).
"""
import base64
import json
import logging
import re
import threading
import time
from html import unescape
from urllib.parse import quote, quote_plus, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("mouflanga")

UA = "MouFlanga/1.0"
DELAI_PAR_SITE = 1.0          # secondes entre deux requêtes vers le même site
PAUSE_REFUS = 3600.0          # un site qui refuse (403/429/503) n'est pas relancé avant une heure


class SourceErreur(Exception):
    """La source n'a pas répondu comme il faut (refus, protection, panne). Jamais prise pour « rien trouvé »."""


class _Client:
    def __init__(self):
        self._verrou = threading.Lock()
        self._prochain = {}       # hôte -> heure monotone de la prochaine requête permise
        self._pause = {}          # hôte -> heure monotone de fin de pause
        self._robots = {}         # hôte -> (RobotFileParser ou None)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA

    def _attendre(self, hote):
        with self._verrou:
            fin = self._pause.get(hote, 0)
            if fin > time.monotonic():
                raise SourceErreur(f"{hote} refuse nos demandes pour le moment (nouvel essai dans {int((fin - time.monotonic()) // 60) + 1} min)")
            t = max(time.monotonic(), self._prochain.get(hote, 0))
            self._prochain[hote] = t + DELAI_PAR_SITE
        if t > time.monotonic():
            time.sleep(t - time.monotonic())

    def autorise(self, url):
        p = urlparse(url)
        hote = p.netloc
        if hote not in self._robots:
            rp = RobotFileParser()
            try:
                self._attendre(hote)
                r = self.session.get(f"{p.scheme}://{hote}/robots.txt", timeout=15)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                    self._robots[hote] = rp
                else:
                    self._robots[hote] = None             # pas de robots.txt lisible : rien n'est interdit
            except (requests.RequestException, SourceErreur):
                self._robots[hote] = None
        rp = self._robots[hote]
        return True if rp is None else rp.can_fetch(UA, url)

    def get(self, url, *, binaire=False, referer=None, essais=3, timeout=30):
        """Rend le texte (ou les octets) ; lève SourceErreur pour tout ce qui n'est pas une vraie réponse."""
        hote = urlparse(url).netloc
        if not self.autorise(url):
            raise SourceErreur(f"{hote} interdit cette page dans son robots.txt : non lue")
        derniere = ""
        for essai in range(essais):
            self._attendre(hote)
            try:
                r = self.session.get(url, timeout=timeout, headers={"Referer": referer} if referer else None)
            except requests.RequestException as e:
                derniere = e.__class__.__name__
                time.sleep(2 * (essai + 1))
                continue
            if r.status_code in (403, 429, 503):
                with self._verrou:
                    self._pause[hote] = time.monotonic() + PAUSE_REFUS
                raise SourceErreur(f"{hote} a refusé la demande (HTTP {r.status_code}) : protection du site, rien n'est contourné")
            if r.status_code == 404:
                raise SourceErreur(f"page introuvable (404) : {url}")
            if r.status_code >= 500:
                derniere = f"HTTP {r.status_code}"
                time.sleep(2 * (essai + 1))
                continue
            if r.status_code != 200:
                raise SourceErreur(f"réponse inattendue (HTTP {r.status_code}) : {url}")
            if binaire:
                return r.content
            r.encoding = r.encoding or "utf-8"
            return r.text
        raise SourceErreur(f"{hote} ne répond pas ({derniere or 'pas de réponse'})")


CLIENT = _Client()


def _nombre(texte):
    m = re.search(r"(\d+(?:[.,]\d+)?)", texte or "")
    return m.group(1).replace(",", ".") if m else None


def _est_image(octets):
    return octets[:3] == b"\xff\xd8\xff" or octets[:4] == b"\x89PNG" or (octets[:4] == b"RIFF" and octets[8:12] == b"WEBP") \
        or octets[:6] in (b"GIF87a", b"GIF89a") or octets[4:12] in (b"ftypavif", b"ftypavis")


class Source:
    id = ""
    nom = ""
    base = ""

    def rechercher(self, texte):
        raise NotImplementedError

    def chapitres(self, adresse):
        raise NotImplementedError

    def adresses_des_pages(self, adresse_chapitre):
        raise NotImplementedError

    def pages(self, adresse_chapitre):
        """Les images du chapitre, dans l'ordre. Rend [] (et le dit au journal) si UNE page manque : jamais de chapitre à trous."""
        try:
            adresses = self.adresses_des_pages(adresse_chapitre)
        except SourceErreur as e:
            logger.warning("%s : %s", self.nom, e)
            return []
        if not adresses:
            logger.warning("%s : aucune page annoncée pour %s", self.nom, adresse_chapitre)
            return []
        logger.info("%s : %d page(s) annoncée(s) pour %s", self.nom, len(adresses), adresse_chapitre)
        images = []
        for i, a in enumerate(adresses, 1):
            try:
                octets = CLIENT.get(a, binaire=True, referer=adresse_chapitre + "/" if not adresse_chapitre.endswith("/") else adresse_chapitre)
            except SourceErreur as e:
                logger.warning("%s : page %d/%d impossible (%s) : chapitre abandonné, aucun fichier partiel", self.nom, i, len(adresses), e)
                return []
            if len(octets) < 2000 or not _est_image(octets):
                logger.warning("%s : page %d/%d n'est pas une image (%d octets) : chapitre abandonné", self.nom, i, len(adresses), len(octets))
                return []
            images.append(octets)
        logger.info("✓ %s : %d pages lues sur %d.", self.nom, len(images), len(adresses))
        return images


class MangaThemesia(Source):
    """Moteur de nombreux sites de scantrad (thème WordPress « MangaThemesia ») : recherche `/?s=`, fiche avec `#chapterlist`,
    pages dans le script `ts_reader.run({...})` de la page du chapitre (ou, à défaut, dans `#readerarea`)."""

    def __init__(self, id, nom, base, dossier_series="/catalogue"):
        self.id, self.nom, self.base = id, nom, base.rstrip("/")
        self.dossier_series = dossier_series

    def _soupe(self, url):
        return BeautifulSoup(CLIENT.get(url), "html.parser")

    def rechercher(self, texte):
        texte = (texte or "").strip()[:80]
        if len(texte) < 2:
            return []
        soupe = self._soupe(f"{self.base}/?s={quote_plus(texte)}")
        out, vus = [], set()
        for bsx in soupe.select(".listupd .bs .bsx, .listo .bs .bsx, .utao .uta .imgu"):
            a = bsx.find("a", href=True)
            if not a:
                continue
            url = urljoin(self.base + "/", a["href"])
            if url in vus or self.dossier_series not in urlparse(url).path:
                continue
            vus.add(url)
            titre = a.get("title") or (bsx.select_one(".tt") or a).get_text(" ", strip=True)
            genre = (bsx.select_one(".typename") or bsx).get_text(" ", strip=True) if bsx.select_one(".typename") else ""
            out.append({"title": unescape(re.sub(r"\s+", " ", titre)).strip(), "url": url, "type": genre.lower() if genre else "",
                        "id": f"{self.id}-" + re.sub(r"[^a-z0-9]+", "-", urlparse(url).path.lower()).strip("-")[-60:]})
        return out

    def chapitres(self, adresse):
        soupe = self._soupe(adresse)
        out, vus = [], set()
        for li in soupe.select("#chapterlist li, div.bxcl li, div.cl li"):
            a = li.find("a", href=True)
            if not a:
                continue
            url = urljoin(self.base + "/", a["href"])
            if url in vus:
                continue
            vus.add(url)
            etiquette = (li.get("data-num") or "").strip()
            nom = (li.select_one(".chapternum") or a).get_text(" ", strip=True) or etiquette
            nom = re.sub(r"\s+", " ", nom).strip()
            n = _nombre(etiquette) or _nombre(nom)
            if n is None:
                continue
            c = {"title": nom[:120], "url": url, "chapter_id": n}
            if re.match(r"(volume|tome|vol\.?)\b", etiquette or nom, re.I):
                try:
                    c["volume"] = int(float(n))
                except ValueError:
                    pass
            out.append(c)
        return out

    def adresses_des_pages(self, adresse_chapitre):
        html = CLIENT.get(adresse_chapitre)
        soupe = BeautifulSoup(html, "html.parser")
        # 1. le lecteur de scripts : ts_reader.run({... "sources":[{"images":[...]}]})
        m = re.search(r"ts_reader\.run\((\{.*?\})\);", html, re.S)
        if not m:
            script = soupe.select_one('script[src^="data:text/javascript;base64,dHNfcmVhZGVyLnJ1bih7"]')
            if script:
                try:
                    m = re.search(r"ts_reader\.run\((\{.*?\})\);", base64.b64decode(script["src"].split("base64,", 1)[1]).decode("utf-8", "replace"), re.S)
                except ValueError:
                    m = None
        if m:
            try:
                d = json.loads(m.group(1))
                sources = d.get("sources") or []
                choisie = next((s for s in sources if s.get("images")), None)
                if choisie:
                    return [urljoin(self.base + "/", u) for u in choisie["images"] if u]
            except ValueError:
                pass
        # 2. à défaut, les images de la zone de lecture
        pages = []
        for img in soupe.select("div#readerarea img"):
            u = img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
            if u and not u.startswith("data:"):
                pages.append(urljoin(self.base + "/", u.strip()))
        return pages


class Madara(Source):
    """Moteur WordPress « Madara », très répandu chez les scantrads : recherche `/?s=…&post_type=wp-manga`, fiche `/manga/<série>/`,
    liste des chapitres demandée à `…/ajax/chapters/` (à défaut lue dans la fiche), images dans `div.reading-content`."""

    def __init__(self, id, nom, base):
        self.id, self.nom, self.base = id, nom, base.rstrip("/")

    def rechercher(self, texte):
        texte = (texte or "").strip()[:80]
        if len(texte) < 2:
            return []
        soupe = BeautifulSoup(CLIENT.get(f"{self.base}/?s={quote_plus(texte)}&post_type=wp-manga"), "html.parser")
        out, vus = [], set()
        for bloc in soupe.select(".c-tabs-item__content"):
            a = bloc.select_one(".post-title a")
            if not a or not a.get("href"):
                continue
            url = urljoin(self.base + "/", a["href"])
            if url in vus:
                continue
            vus.add(url)
            out.append({"title": unescape(re.sub(r"\s+", " ", a.get_text(" ", strip=True))), "url": url, "type": "",
                        "id": f"{self.id}-" + re.sub(r"[^a-z0-9]+", "-", urlparse(url).path.lower()).strip("-")[-60:]})
        return out

    def _liste(self, adresse):
        """La liste des chapitres : la requête `ajax/chapters/` (comme le fait le site), sinon la fiche elle-même."""
        base = adresse if adresse.endswith("/") else adresse + "/"
        try:
            CLIENT._attendre(urlparse(adresse).netloc)
            r = CLIENT.session.post(base + "ajax/chapters/", timeout=30)
            if r.status_code == 200 and "wp-manga-chapter" in r.text:
                return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException:
            pass
        return BeautifulSoup(CLIENT.get(adresse), "html.parser")

    def chapitres(self, adresse):
        if not CLIENT.autorise(adresse):
            raise SourceErreur("page interdite par le robots.txt du site : non lue")
        out, vus = [], set()
        for li in self._liste(adresse).select("li.wp-manga-chapter"):
            a = li.find("a", href=True)
            if not a or a["href"].strip() in ("#", ""):
                continue
            url = urljoin(self.base + "/", a["href"].strip())
            if url in vus:
                continue
            vus.add(url)
            nom = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
            n = _nombre(nom) or _nombre(re.sub(r"(?<=\d)-(?=\d)", ".", urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]))
            if n is None:
                continue
            c = {"title": nom[:120] or f"Chapitre {n}", "url": url, "chapter_id": n}
            if re.match(r"(volume|tome|vol\.?)\b", nom, re.I):
                try:
                    c["volume"] = int(float(n))
                except ValueError:
                    pass
            out.append(c)
        return out

    def adresses_des_pages(self, adresse_chapitre):
        soupe = BeautifulSoup(CLIENT.get(adresse_chapitre), "html.parser")
        pages = []
        for img in soupe.select("div.reading-content img"):
            u = (img.get("data-src") or img.get("data-lazy-src") or img.get("src") or "").strip()
            if u and not u.startswith("data:"):
                pages.append(urljoin(self.base + "/", u))
        return pages


class PizzaReader(Source):
    """Moteur « PizzaReader » (API JSON ouverte du site) : recherche `/api/search/<texte>`, fiche `/api/comics/<série>`,
    pages `/api/read/<série>/<langue>/vol/<v>/ch/<c>[/sub/<s>]`. Les séries pour adultes ne sont jamais proposées."""

    def __init__(self, id, nom, base, langue="fr"):
        self.id, self.nom, self.base, self.langue = id, nom, base.rstrip("/"), langue

    def _json(self, chemin):
        try:
            return json.loads(CLIENT.get(self.base + chemin))
        except ValueError:
            raise SourceErreur(f"{self.nom} a répondu autre chose que des données lisibles : {chemin}")

    def rechercher(self, texte):
        texte = (texte or "").strip()[:80]
        if len(texte) < 2:
            return []
        out = []
        for c in self._json("/api/search/" + quote(texte, safe="")).get("comics") or []:
            if c.get("adult") or c.get("hidden") or not c.get("slug"):
                continue
            out.append({"title": (c.get("title") or c["slug"]).strip(), "url": f"{self.base}/comics/{c['slug']}", "type": "",
                        "id": f"{self.id}-{c['slug']}"[:80]})
        return out

    def chapitres(self, adresse):
        slug = urlparse(adresse).path.rstrip("/").rsplit("/", 1)[-1]
        fiche = self._json(f"/api/comics/{quote(slug, safe='')}").get("comic") or {}
        if fiche.get("adult"):
            return []
        out, vus = [], set()
        for ch in fiche.get("chapters") or []:
            if ch.get("hidden") or ch.get("licensed") or (ch.get("language") or self.langue) != self.langue or not ch.get("url"):
                continue
            url = self.base + ch["url"]
            if url in vus:
                continue
            vus.add(url)
            n = str(ch.get("chapter") if ch.get("chapter") is not None else "")
            if ch.get("subchapter") not in (None, "", 0, "0"):
                n += "." + str(ch["subchapter"])
            if not _nombre(n):
                continue
            titre = (ch.get("full_title") or f"Chapitre {n}").strip()
            out.append({"title": titre[:120], "url": url, "chapter_id": _nombre(n)})
        return out

    def adresses_des_pages(self, adresse_chapitre):
        chemin = urlparse(adresse_chapitre).path
        if not chemin.startswith("/read/"):
            raise SourceErreur(f"adresse de chapitre inattendue : {adresse_chapitre}")
        pages = (self._json("/api" + chemin).get("chapter") or {}).get("pages") or []
        return [urljoin(self.base + "/", u) for u in pages if u]


SOURCES = {s.id: s for s in (
    MangaThemesia("sushiscan", "Sushi-Scan", "https://sushiscan.net"),
    MangaThemesia("lelmanga", "LelManga", "https://www.lelmanga.com", dossier_series="/manga"),
    Madara("harmonyscan", "Harmony-Scan", "https://harmony-scan.fr"),
    Madara("pantheon", "Pantheon-Scan", "https://pantheon-scan.com"),
    PizzaReader("bluesolo", "Bluesolo", "https://bluesolo.org"),
    PizzaReader("fmteam", "FMTeam", "https://fmteam.fr"),
)}


def source(identifiant):
    """La source demandée (« japscan » n'en fait pas partie : Japscan a son propre lecteur). Lève KeyError si elle n'existe pas."""
    return SOURCES[identifiant]


def liste():
    """Pour l'interface : [{id, nom}], Japscan en premier."""
    return [{"id": "japscan", "nom": "Japscan"}] + [{"id": s.id, "nom": s.nom} for s in SOURCES.values()]
