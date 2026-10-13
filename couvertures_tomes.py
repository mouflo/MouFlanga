"""
Couvertures des tomes : une image de remplacement par tome, rangée à part du fichier CBZ (le fichier n'est jamais touché).

- Emplacement : « <série>/.couvertures/NNN.jpg » (dossier caché : l'appli ne le compte pas comme tome, et il suit la série
  quand elle est renommée). L'ancienne image est gardée en « NNN.ancienne.jpg ».
- Sources en ligne : MangaDex (couvertures par volume, en bonne résolution). Les résultats sont gardés 7 jours dans
  « data/couvertures-trouvees/<série>.json ».
"""
import hashlib
import io
import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DOSSIER_CACHE = Path(__file__).resolve().parent / "data" / "couvertures-trouvees"
DUREE_CACHE = 7 * 86400
# À augmenter quand la logique de recherche change : les résultats anciens (possiblement faux) sont alors refaits seuls.
VERSION_CACHE = 2
PREFIXE_MANGADEX = "https://uploads.mangadex.org/covers/"
_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "MouFlanga/2.0 (bibliotheque de mangas personnelle)"


def dossier_couvertures(dossier_serie: Path) -> Path:
    return Path(dossier_serie) / ".couvertures"


def chemin(dossier_serie: Path, tome: int) -> Path:
    return dossier_couvertures(dossier_serie) / f"{int(tome):03d}.jpg"


def remplacement(dossier_serie: Path, tome: int) -> Path | None:
    """L'image de remplacement du tome, si elle existe."""
    f = chemin(dossier_serie, tome)
    return f if f.is_file() else None


try:  # HEIC/HEIF (photos d'iPhone) : lu seulement si le module est installé
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass


def _image_rgb(octets: bytes):
    """L'image décodée en RGB, réduite à 1200 × 1800 ; ValueError si ce n'est pas une image utilisable.
    Tous les formats que Pillow lit (JPEG, PNG, WebP, GIF, BMP, TIFF, AVIF, HEIC…) sont acceptés.
    Une zone transparente (PNG, WebP) devient blanche, pas noire."""
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(octets))
        img.load()
    except Exception:
        raise ValueError("Ce format d'image n'est pas lu. Essayez en JPEG ou PNG.")
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        fond = Image.new("RGB", img.size, (255, 255, 255))
        fond.paste(img.convert("RGBA"), mask=img.convert("RGBA").getchannel("A"))
        img = fond
    img = img.convert("RGB")
    if img.width < 200 or img.height < 200:
        raise ValueError("Image trop petite pour une couverture (il faut au moins 200 × 200 pixels).")
    img.thumbnail((1200, 1800))
    return img


def verifier_image(octets: bytes) -> None:
    _image_rgb(octets)


def enregistrer_image(dossier_serie: Path, tome: int, octets: bytes) -> Path:
    """Enregistre une image (photo, ou téléchargée) en JPEG. L'ancienne image part en « .ancienne.jpg »."""
    img = _image_rgb(octets)
    dossier = dossier_couvertures(dossier_serie)
    dossier.mkdir(parents=True, exist_ok=True)
    cible = chemin(dossier_serie, tome)
    if cible.is_file():
        os.replace(cible, cible.with_name(f"{int(tome):03d}.ancienne.jpg"))
    tmp = cible.with_suffix(".tmp")
    img.save(tmp, "JPEG", quality=92)
    os.replace(tmp, cible)
    return cible


def retirer(dossier_serie: Path, tome: int) -> bool:
    """Revient à la première page du fichier (l'ancienne image est gardée)."""
    f = chemin(dossier_serie, tome)
    if not f.is_file():
        return False
    os.replace(f, f.with_name(f"{int(tome):03d}.ancienne.jpg"))
    return True


# ---------------- Envoi groupé : numéro lu sur chaque image, aperçu avant enregistrement ----------------
ATTENTE_DIR = DOSSIER_CACHE.parent / "couvertures-attente"   # images d'un envoi groupé, le temps de l'aperçu
DUREE_ATTENTE = 86400
_JETON = re.compile(r"^[0-9a-f]{32}$")


def numero_lu(octets: bytes) -> int | None:
    """Numéro de tome lu sur une couverture (OCR tesseract) : « Tome 3 », « No. 3 » ou un chiffre seul.
    None si rien de clair à lire (ou plusieurs numéros différents)."""
    from sommaire import disponible, ocr
    if not disponible():
        return None
    try:
        texte = ocr(octets)
    except Exception as e:
        logger.info("Lecture du numéro de couverture : %s", e.__class__.__name__)
        return None
    trouves = {int(n) for n in re.findall(r"\b(?:tome|t|vol|no|n°)\.?\s*0*(\d{1,3})\b", texte, re.I)}
    if not trouves:
        trouves = {int(n) for n in re.findall(r"^\s*0*(\d{1,3})\s*$", texte, re.M)}
    return trouves.pop() if len(trouves) == 1 else None


def attente_creer(images: list[bytes]) -> str:
    """Garde les images d'un envoi groupé (JPEG) pour l'aperçu. Les envois de plus d'un jour sont effacés."""
    ATTENTE_DIR.mkdir(parents=True, exist_ok=True)
    maintenant = time.time()
    for ancien in ATTENTE_DIR.iterdir():
        if maintenant - ancien.stat().st_mtime > DUREE_ATTENTE:
            shutil.rmtree(ancien, ignore_errors=True)
    jeton = uuid.uuid4().hex
    dossier = ATTENTE_DIR / jeton
    dossier.mkdir()
    for i, octets in enumerate(images):
        _image_rgb(octets).save(dossier / f"{i}.jpg", "JPEG", quality=92)
    return jeton


def attente_image(jeton: str, index: int) -> bytes | None:
    if not _JETON.match(jeton or ""):
        return None
    f = ATTENTE_DIR / jeton / f"{int(index)}.jpg"
    return f.read_bytes() if f.is_file() else None


def attente_supprimer(jeton: str) -> None:
    if _JETON.match(jeton or ""):
        shutil.rmtree(ATTENTE_DIR / jeton, ignore_errors=True)


def _cle(texte: str) -> str:
    """Lettres de toutes les langues, minuscules, sans espaces ni tirets : « WORST » ≠ « WORST外伝 ».
    Les ! ? et autres signes restent : « Again » ≠ « Again!! » (deux séries différentes)."""
    return re.sub(r"[\s\-'’:.,_]+", "", (texte or "").lower())


def _variantes(titre: str) -> list[str]:
    """« + Again » s'écrit aussi « Plus Again » : l'API de recherche ignore le « + », on essaie donc les deux."""
    return [titre, re.sub(r"^\+\s*", "Plus ", titre)] if titre.startswith("+") else [titre]


def _mangadex_manga(titres: list[str]) -> str | None:
    """Identifiant MangaDex de la série : seulement un titre identique (jamais une série au nom voisin)."""
    for titre in dict.fromkeys(v for t in titres if t for v in _variantes(t)):
        try:
            r = _SESSION.get("https://api.mangadex.org/manga", params={"title": titre, "limit": 100}, timeout=15).json()
        except Exception:
            continue
        for m in r.get("data") or []:
            a = m.get("attributes") or {}
            noms = [*(a.get("title") or {}).values(), *(v for x in a.get("altTitles") or [] for v in x.values())]
            if any(_cle(n) == _cle(titre) for n in noms):
                return m["id"]
    return None


def couvertures_en_ligne(serie: str, titres: list[str], forcer: bool = False) -> dict:
    """{numéro de tome: [{"url", "vignette", "langue"}]} : couvertures trouvées sur MangaDex (gardées 7 jours)."""
    DOSSIER_CACHE.mkdir(parents=True, exist_ok=True)
    # Le nom du fichier garde un empreinte : « + Again » et « Again » ne doivent pas partager le même cache.
    empreinte = hashlib.sha1(serie.encode("utf-8")).hexdigest()[:8]
    f = DOSSIER_CACHE / (re.sub(r"[^A-Za-z0-9]+", "_", serie).strip("_") + "_" + empreinte + ".json")
    if f.is_file() and not forcer:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("version") == VERSION_CACHE and time.time() - d.get("date", 0) < DUREE_CACHE:
                return {int(k): v for k, v in d.get("tomes", {}).items()}
        except (OSError, ValueError):
            pass
    tomes = {}
    manga = _mangadex_manga(titres)
    if manga:
        offset = 0
        while True:
            try:
                r = _SESSION.get("https://api.mangadex.org/cover", params={"manga[]": manga, "limit": 100, "offset": offset,
                                                                         "order[volume]": "asc"}, timeout=20).json()
            except Exception as e:
                logger.info("Couvertures MangaDex de %s : %s", serie, e.__class__.__name__)
                break
            for c in r.get("data") or []:
                a = c.get("attributes") or {}
                try:
                    num = int(float(a.get("volume")))
                except (TypeError, ValueError):
                    continue
                url = f"{PREFIXE_MANGADEX}{manga}/{a.get('fileName')}"
                tomes.setdefault(num, []).append({"url": url, "vignette": url + ".256.jpg", "langue": a.get("locale") or ""})
            offset += 100
            if offset >= (r.get("total") or 0) or not r.get("data"):
                break
    f.write_text(json.dumps({"version": VERSION_CACHE, "date": time.time(), "manga": manga,
                             "tomes": {str(k): v for k, v in tomes.items()}},
                            ensure_ascii=False, indent=1), encoding="utf-8")
    return tomes


def telecharger(url: str) -> bytes:
    """Télécharge une couverture trouvée en ligne. Seules les adresses MangaDex connues sont acceptées."""
    if not url.startswith(PREFIXE_MANGADEX):
        raise ValueError("Adresse de couverture non reconnue.")
    r = _SESSION.get(url, timeout=30)
    r.raise_for_status()
    return r.content
