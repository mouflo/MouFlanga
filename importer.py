"""
Import des séries ajoutées à la main dans le dossier des mangas :
- archives qui regroupent plusieurs tomes (.rar, .zip, .7z : « Kenichi.t01-29.rar ») : extraites dans un dossier
  temporaire caché, puis un fichier par tome ; si un tome contient un dossier par chapitre (« Tome 29/232/… »),
  le fichier de tome garde les chapitres (lecture chapitre par chapitre, comme pour un téléchargement) ;
- PDF : chaque page devient une image (les images d'origine sont reprises telles quelles quand c'est possible) ;
- archives d'archives (.cbz dans un .rar) : chaque .cbz devient un tome.
Les originaux vont à la corbeille seulement quand tout s'est bien passé.
"""
import logging
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import archives
import tomes_cbz

logger = logging.getLogger(__name__)
LOTS = (".rar", ".zip", ".7z")                 # archives « paquet » (les .cbz / .cbr sont des tomes ou chapitres)
IMAGES = archives.IMAGE_EXT
_TOME = re.compile(r"(?:^|[\s_\-.(\[])(?:t|tome|vol(?:ume)?|v)[\s._]*0*(\d{1,3})(?=$|[\s_\-.)\]])", re.I)
_CHAP = re.compile(r"chap(?:itre|ter)?|\bch\b", re.I)
_NUM_DOSSIER = re.compile(r"^(?:chap(?:itre|ter)?[\s._-]*|ch[\s._-]*|#)?0*(\d{1,4}(?:[.,]\d{1,2})?)$", re.I)


class ErreurImport(Exception):
    pass


def numero_tome(nom: str):
    """Numéro de tome d'après un nom (« Toriko.Tome.38 », « Gintama T01 (…) », « Vol. 3 ») ; None pour un chapitre."""
    if _CHAP.search(nom):
        return None
    m = _TOME.search(nom)
    if not m or re.match(r"\s*[-–à]\s*\d", nom[m.end():]):        # « t01-29 » : plusieurs tomes
        return None
    return int(m.group(1))


def _numero_chapitre_dossier(nom: str):
    m = _NUM_DOSSIER.match(nom.strip())
    return float(m.group(1).replace(",", ".")) if m else None


def est_lot(f: Path) -> bool:
    return f.suffix.lower() in LOTS


def lister(path: Path) -> list[str]:
    """Contenu d'une archive, sans l'extraire."""
    r = subprocess.run(["bsdtar", "-tf", str(path)], capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise ErreurImport(f"{path.name} illisible : {r.stderr.strip()[:200]}")
    return [l for l in r.stdout.splitlines() if l and not l.endswith("/")]


def extraire(path: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["bsdtar", "-xf", str(path), "-C", str(dest)], capture_output=True, text=True, timeout=7200)
    if r.returncode != 0:
        raise ErreurImport(f"Extraction de {path.name} impossible : {r.stderr.strip()[:200]}")


def _est_image(p: Path) -> bool:
    return p.suffix.lower() in IMAGES and not p.name.startswith(".") and "__MACOSX" not in p.parts


def repartir(racine: Path, tome_par_defaut=None) -> tuple[dict, list]:
    """Répartit les images extraites par tome : {tome: {"chapitres": {n°: [images]}, "pages": [images]}}
    et renvoie aussi les archives trouvées dedans (.cbz dans un .rar…)."""
    tomes, autres = {}, []
    for f in sorted(racine.rglob("*"), key=lambda p: archives.natural_key(str(p))):
        if not f.is_file():
            continue
        rel = f.relative_to(racine).parts
        if f.suffix.lower() in archives.ARCHIVE_EXT + (".pdf",):
            autres.append(f)
            continue
        if not _est_image(f):
            continue
        tome, idx = None, None
        for i, partie in enumerate(rel[:-1]):
            t = numero_tome(partie)
            if t is not None:
                tome, idx = t, i
        if tome is None:
            tome, idx = tome_par_defaut, -1
            if tome is None:
                continue
        bloc = tomes.setdefault(tome, {"chapitres": {}, "pages": []})
        reste = rel[idx + 1:-1]                         # dossiers sous le dossier du tome
        num = _numero_chapitre_dossier(reste[0]) if reste else None
        if num is not None:
            bloc["chapitres"].setdefault(num, []).append(f)
        else:
            bloc["pages"].append(f)
    return tomes, autres


def ecrire_tome(dossier_serie: Path, serie: str, tome: int, bloc: dict) -> Path | None:
    """Écrit le fichier d'un tome. Avec des dossiers de chapitres : fichier de tome « à chapitres » (comme les
    téléchargements) ; sinon un .cbz ordinaire. Ne remplace jamais un fichier existant (renvoie None)."""
    cible = tomes_cbz.fichier_tome(dossier_serie, serie, tome)
    if cible.exists():
        logger.info("Import : %s existe déjà, tome %s laissé de côté", cible.name, tome)
        return None
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_name(cible.name + ".tmp")
    chapitres = bloc["chapitres"]
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        if chapitres:
            nums = sorted(chapitres)
            # Pages hors chapitre (couverture « 00.png »…) : en tête du premier chapitre
            total = 0
            for n in nums:
                pages = (bloc["pages"] if n == nums[0] else []) + sorted(chapitres[n], key=lambda p: archives.natural_key(p.name))
                for k, f in enumerate(pages, 1):
                    z.write(f, tomes_cbz.nom_page(n, k, ext=f.suffix.lower().lstrip(".")))
                    total += 1
            z.writestr(tomes_cbz.INFO, tomes_cbz.json.dumps({"serie": serie, "tome": tome,
                                                             "titres": {f"{n:g}": "" for n in nums}}, indent=1))
            z.writestr(tomes_cbz.COMICINFO, tomes_cbz._comicinfo(serie, tome, {n: "" for n in nums}, total))
        else:
            for k, f in enumerate(bloc["pages"], 1):
                z.write(f, f"{k:04d}{f.suffix.lower()}")
            z.writestr(tomes_cbz.COMICINFO, tomes_cbz._comicinfo(serie, tome, {}, len(bloc["pages"])))
    os.replace(tmp, cible)
    return cible


def pdf_vers_cbz(pdf: Path, cible: Path):
    """Chaque page du PDF devient une image ; l'image d'origine est reprise telle quelle si la page n'en contient qu'une."""
    import pymupdf
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_name(cible.name + ".tmp")
    with pymupdf.open(pdf) as doc, zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        for i, page in enumerate(doc, 1):
            imgs = page.get_images(full=True)
            donnees, ext = None, "jpg"
            if len(imgs) == 1:
                try:
                    brut = doc.extract_image(imgs[0][0])
                    if brut.get("ext") in ("jpeg", "jpg", "png") and brut["width"] >= page.rect.width * 0.8:
                        donnees, ext = brut["image"], ("jpg" if brut["ext"] in ("jpeg", "jpg") else "png")
                except Exception:
                    donnees = None
            if donnees is None:
                donnees = page.get_pixmap(dpi=200).tobytes("jpeg", jpg_quality=88)
            z.writestr(f"{i:04d}.{ext}", donnees)
    os.replace(tmp, cible)


def importer_lot(lot: Path, dossier_serie: Path, serie: str, etat: dict) -> list[Path]:
    """Extrait une archive de plusieurs tomes et écrit un fichier par tome. Renvoie les fichiers créés."""
    temp = dossier_serie / ".import" / lot.stem
    shutil.rmtree(temp, ignore_errors=True)
    crees = []
    try:
        etat["message"] = f"Extraction de {lot.name}…"
        extraire(lot, temp)
        tomes, autres = repartir(temp, numero_tome(lot.stem))
        for t in sorted(tomes):
            etat["message"] = f"{lot.name} : tome {t}…"
            f = ecrire_tome(dossier_serie, serie, t, tomes[t])
            if f:
                crees.append(f)
        for a in autres:                                    # .cbz / .pdf rangés dans le paquet
            t = numero_tome(a.stem)
            if t is None:
                continue
            cible = tomes_cbz.fichier_tome(dossier_serie, serie, t)
            if cible.exists():
                continue
            if a.suffix.lower() == ".pdf":
                pdf_vers_cbz(a, cible)
            else:
                cible.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(a), str(cible.with_suffix(a.suffix.lower())))
                cible = cible.with_suffix(a.suffix.lower())
            crees.append(cible)
        if not crees and not tomes:
            raise ErreurImport(f"{lot.name} : aucun tome reconnu dedans (dossiers « Tome NN » attendus)")
        return crees
    finally:
        shutil.rmtree(temp, ignore_errors=True)
        try:
            (dossier_serie / ".import").rmdir()
        except OSError:
            pass
