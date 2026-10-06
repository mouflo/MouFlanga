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
import time
import zipfile
from pathlib import Path

import archives
import tomes_cbz

logger = logging.getLogger(__name__)
LOTS = (".rar", ".zip", ".7z")                 # archives « paquet » (les .cbz / .cbr sont des tomes ou chapitres)
IMAGES = archives.IMAGE_EXT
_TOME = re.compile(r"(?:^|[\s_\-.(\[])(?:t|tome|vol(?:ume)?|v)[\s._-]*0*(\d{1,3})(?=$|[\s_\-.)\]])", re.I)
_NUMERO_FINAL = re.compile(r"^(.*?[A-Za-z].*?)[\s._-]+0*(\d{1,3})(?:[\s._-]+final)?$", re.I)   # « MAR.07 », « Bleach 12 »
_CHAP = re.compile(r"chap(?:itre|ter)?|\bch\b", re.I)
_NUM_DOSSIER = re.compile(r"^(?:chap(?:itre|ter)?[\s._-]*|ch[\s._-]*|#)?0*(\d{1,4}(?:[.,]\d{1,2})?)$", re.I)


class ErreurImport(Exception):
    pass


def numero_tome(nom: str):
    """Numéro de tome d'après un nom (« Toriko.Tome.38 », « Gintama T01 (…) », « Vol. 3 ») ; None pour un chapitre."""
    nom = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", nom).strip()   # « tome 01 (ch. 01 - 07) » : la parenthèse ne compte pas
    if _CHAP.search(nom):
        return None
    m = _TOME.search(nom)
    if not m or re.match(r"\s*[-–à]\s*\d", nom[m.end():]):        # « t01-29 » : plusieurs tomes
        return None
    return int(m.group(1))


def est_lot(f: Path) -> bool:
    return f.suffix.lower() in LOTS


def lister(path: Path) -> list[str]:
    """Contenu d'une archive, sans l'extraire."""
    r = subprocess.run(["bsdtar", "-tf", str(path)], capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise ErreurImport(f"{path.name} illisible : {r.stderr.strip()[:200]}")
    return [l for l in r.stdout.splitlines() if l and not l.endswith("/")]


def _extraire_unar(path: Path, dest: Path) -> bool:
    """Outil de secours (« unar ») : lit les RAR que bsdtar ne sait pas décompresser (filtres) et les noms mal encodés."""
    if not shutil.which("unar"):
        return False
    r = subprocess.run(["unar", "-q", "-f", "-D", "-o", str(dest), str(path)], capture_output=True, text=True, timeout=7200)
    if r.returncode != 0:
        logger.info("unar sur %s : %s", path.name, (r.stderr or r.stdout).strip()[:200])
    return any(f.suffix.lower() in IMAGES or f.suffix.lower() in (".zip", ".rar", ".cbz", ".cbr", ".7z", ".pdf")
               for f in dest.rglob("*") if f.is_file())


def extraire(path: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    # Sur un partage réseau (NAS), on ne peut pas redonner aux fichiers leur propriétaire d'origine :
    # --no-same-owner / --no-same-permissions évitent ces avertissements, qui ne sont pas des erreurs
    r = subprocess.run(["bsdtar", "-x", "--no-same-owner", "--no-same-permissions", "-f", str(path), "-C", str(dest)],
                       capture_output=True, text=True, timeout=7200)
    vraies = [l for l in r.stderr.splitlines()
              if l.strip() and not re.search(r"Can't set (user|group|permissions|time)|Operation not permitted", l)]
    # Fichiers parasites illisibles (« iPod Photo Cache/….ithmb », Thumbs.db…) : sans importance ; images illisibles : signalées
    images_ko = [l.split(":", 1)[0] for l in vraies if Path(l.split(":", 1)[0]).suffix.lower() in IMAGES]
    if r.returncode != 0 and (vraies or images_ko):
        # bsdtar s'est arrêté ou a raté des fichiers : on recommence avec l'outil de secours
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)
        if _extraire_unar(path, dest):
            logger.info("Extraction de %s : faite avec l'outil de secours (unar)", path.name)
            return
        if not any(dest.rglob("*")):
            subprocess.run(["bsdtar", "-x", "--no-same-owner", "--no-same-permissions", "-f", str(path), "-C", str(dest)],
                           capture_output=True, text=True, timeout=7200)
    a_des_images = any(f.suffix.lower() in IMAGES for f in dest.rglob("*") if f.is_file())
    if r.returncode != 0 and not a_des_images:
        raise ErreurImport(f"Extraction de {path.name} impossible : {' '.join(vraies or r.stderr.splitlines())[:200]}")
    if images_ko:
        logger.warning("Extraction de %s : %d image(s) illisible(s), ex. %s", path.name, len(images_ko), images_ko[0])
    elif vraies:
        logger.info("Extraction de %s : fichiers non-images ignorés (%d)", path.name, len(vraies))


def _est_image(p: Path) -> bool:
    return p.suffix.lower() in IMAGES and not p.name.startswith(".") and "__MACOSX" not in p.parts


_PLAGE = re.compile(r"\d+\s*(?:à|a|-|–)\s*\d+", re.I)
_NUMERO_COLLE = re.compile(r"^(.*?[A-Za-z])[\s._-]*0*(\d{1,3})(?:[\s._-]+final)?$", re.I)   # « MAR.07 », « jojo13 »


def _tome_souple(nom: str):
    """Numéro de tome sans le mot « tome » : « MAR.07 » → 7, « jojo13 » → 13 (seulement en dernier recours).
    Jamais pour une plage (« the breaker 01 à 10 ») ni pour un chapitre."""
    nom = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", nom).strip()
    if _CHAP.search(nom) or _PLAGE.search(nom):
        return None
    m = _NUMERO_COLLE.match(nom)
    return int(m.group(2)) if m else None


def _numero_chapitre_dossier(nom: str):
    m = _NUM_DOSSIER.match(nom.strip())
    return float(m.group(1).replace(",", ".")) if m else None


def deplier(racine: Path, profondeur: int = 3):
    """Ouvre les archives et PDF rangés dans l'archive (un .cbr par tome, un .rar par chapitre, un PDF par tome…) :
    chacun devient un dossier d'images du même nom, à la même place."""
    for _ in range(profondeur):
        trouves = [f for f in racine.rglob("*") if f.is_file()
                   and f.suffix.lower() in (".zip", ".rar", ".cbz", ".cbr", ".7z", ".pdf")]
        if not trouves:
            return
        for f in trouves:
            dest = f.with_name(f.stem)
            k = 2
            while dest.exists():
                dest = f.with_name(f"{f.stem} ({k})")
                k += 1
            try:
                if f.suffix.lower() == ".pdf":
                    pdf_vers_dossier(f, dest)
                else:
                    extraire(f, dest)
            except Exception as e:
                logger.warning("Archive intérieure %s illisible : %s", f.name, e)
            try:
                f.unlink()
            except OSError:
                pass


def _classer(rel):
    """(tome, position du dossier du tome, n° de chapitre) d'une image d'après son chemin dans l'archive."""
    dossiers = rel[:-1]
    tome, idx = None, None
    for i, partie in enumerate(dossiers):                  # 1. le mot « tome » / « T01 » / « vol » dans un dossier
        t = numero_tome(partie)                            #    (le plus haut : « tome 02/…Vol 2…/ » reste le tome 2)
        if t is not None:
            tome, idx = t, i
            break
    if tome is None:                                       # 2. numéro au bout du nom du dossier (« MAR.07 », « jojo13 »)
        for i, partie in enumerate(dossiers):
            t = _tome_souple(partie)
            if t is not None:
                tome, idx = t, i
                break
    if tome is None:                                       # 3. le tome écrit dans le nom de l'image (« ….Tome 01.P001.jpg »)
        t = numero_tome(Path(rel[-1]).stem)
        if t is not None:
            tome, idx = t, len(dossiers) - 1
    debut = (idx + 1) if idx is not None else 0
    chapitre = None
    for partie in dossiers[debut:]:                        # premier dossier sous le tome qui est un numéro de chapitre
        chapitre = _numero_chapitre_dossier(partie)
        if chapitre is not None:
            break
    return tome, idx, chapitre


def repartir(racine: Path, tome_par_defaut=None) -> tuple[dict, list]:
    """Répartit les images extraites (après « deplier ») : {nom: {tome: {"chapitres": {n°: [images]}, "pages": [images]}}}.
    nom « » = la série de l'archive ; un autre nom = une autre série trouvée dedans (suite, spin-off, artbook).
    Règles : dossiers de tomes de préfixes différents dont les numéros se chevauchent (20th / 21st Century Boys)
    = séries différentes, sinon une seule (les parties de JoJo) ; chapitres sans tome = « Hors tome » (tome None) ;
    archive sans aucun repère = un seul volume (tome 1) ; groupe d'images à part (≥ 20) = série à part.
    Le deuxième élément renvoyé liste les groupes d'images laissés de côté (trop petits pour être une série)."""
    par_prefixe, sans = {}, {}
    for f in sorted(racine.rglob("*"), key=lambda p: archives.natural_key(str(p))):
        if not f.is_file() or not _est_image(f):
            continue
        rel = f.relative_to(racine).parts
        tome, idx, chapitre = _classer(rel)
        if tome is None and chapitre is None:
            sans.setdefault("/".join(rel[:-1]), []).append(f)
            continue
        prefixe = "/".join(rel[:idx]) if tome is not None and idx and idx > 0 else ""
        bloc = par_prefixe.setdefault(prefixe, {}).setdefault(tome, {"chapitres": {}, "pages": []})
        if chapitre is not None:
            bloc["chapitres"].setdefault(chapitre, []).append(f)
        else:
            bloc["pages"].append(f)
    taille = lambda tomes: sum(len(b["pages"]) + sum(len(c) for c in b["chapitres"].values()) for b in tomes.values())
    series = {}
    if par_prefixe:
        principal = max(par_prefixe, key=lambda p: taille(par_prefixe[p]))
        series[""] = par_prefixe.pop(principal)
        for pre, tomes in sorted(par_prefixe.items()):
            chevauche = {t for t in tomes if t is not None} & {t for t in series[""] if t is not None}
            if chevauche:
                series.setdefault(nom_depuis_prefixe(pre), {}).update(tomes)
            else:                                          # numéros à la suite : même série (parties de JoJo)
                for t, b in tomes.items():
                    dest = series[""].setdefault(t, {"chapitres": {}, "pages": []})
                    dest["pages"] += b["pages"]
                    for n, imgs in b["chapitres"].items():
                        dest["chapitres"].setdefault(n, []).extend(imgs)
    ecartes = []
    groupes = sorted(sans.items(), key=lambda kv: archives.natural_key(kv[0]))
    if not series:
        # Aucun repère nulle part : un seul volume (one-shot), ou un tome par paquet, dans l'ordre (« 01 à 10 », « 11 à 20 »…)
        for k, (groupe, imgs) in enumerate(groupes, 1):
            series.setdefault("", {})[(tome_par_defaut or 1) if len(groupes) == 1 else k] = {"chapitres": {}, "pages": imgs}
    else:
        for groupe, imgs in groupes:                     # à côté de la série : suite, spin-off, artbook…
            if len(imgs) >= 20:
                series.setdefault(nom_depuis_prefixe(groupe) or "Bonus", {})[1] = {"chapitres": {}, "pages": imgs}
            else:
                ecartes.append(f"{groupe or '(racine)'} : {len(imgs)} image(s)")
    return series, ecartes


def nom_depuis_prefixe(prefixe: str) -> str:
    """« 21st-century-boys » → « 21st Century Boys » ; « [MFT]Beelzebub_Side_Story_c1 » → « Beelzebub Side Story »."""
    dernier = prefixe.rstrip("/").split("/")[-1]
    dernier = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", dernier)
    dernier = re.sub(r"[._-]+", " ", dernier)
    dernier = re.sub(r"\b(c|ch|chap|chapitre)\s*\d+\b", " ", dernier, flags=re.I)
    mots = dernier.split()
    return " ".join(m[:1].upper() + m[1:] for m in mots)


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


def pdf_vers_dossier(pdf: Path, dest: Path):
    """Pages d'un PDF en images dans un dossier (pour un PDF rangé dans une archive)."""
    import pymupdf
    dest.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf) as doc:
        for i, page in enumerate(doc, 1):
            donnees, ext = _image_de_page(doc, page)
            (dest / f"{i:04d}.{ext}").write_bytes(donnees)


def _image_de_page(doc, page):
    imgs = page.get_images(full=True)
    if len(imgs) == 1:
        try:
            brut = doc.extract_image(imgs[0][0])
            if brut.get("ext") in ("jpeg", "jpg", "png") and brut["width"] >= page.rect.width * 0.8:
                return brut["image"], ("jpg" if brut["ext"] in ("jpeg", "jpg") else "png")
        except Exception:
            pass
    return page.get_pixmap(dpi=200).tobytes("jpeg", jpg_quality=88), "jpg"


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
    """Extrait une archive (de plusieurs tomes, d'archives, de PDF…) et écrit un fichier par tome.
    Une autre série trouvée dedans (suite, spin-off) va dans son propre dossier, à côté. Renvoie les fichiers créés."""
    temp = dossier_serie / ".import" / lot.stem
    shutil.rmtree(temp, ignore_errors=True)
    crees = []
    try:
        taille = lot.stat().st_size / 1e9
        etat.update(message=f"Extraction de {lot.name} ({taille:.1f} Go)…", etape_depuis=time.time(), sous_fait=0, sous_total=0)
        extraire(lot, temp)
        etat.update(message=f"{lot.name} : ouverture des archives et PDF intérieurs…", etape_depuis=time.time())
        deplier(temp)
        series, ecartes = repartir(temp, numero_tome(lot.stem))
        etat.update(sous_fait=0, sous_total=sum(len(v) for v in series.values()), etape_depuis=time.time())
        for nom in sorted(series, key=lambda n: (n != "", n)):
            if nom == "":
                cible_dossier, cible_nom = dossier_serie, serie
            else:
                cible_nom = nom
                cible_dossier = dossier_serie.parent / cible_nom
                logger.info("Import : « %s » trouvée dans %s, rangée comme série à part", cible_nom, lot.name)
            for t in sorted(series[nom], key=lambda x: (x is None, x or 0)):
                etat["message"] = f"{lot.name} : écriture de {cible_nom} " + (f"tome {t}" if t is not None else "chapitres hors tome") + "…"
                f = ecrire_tome(cible_dossier, cible_nom, t, series[nom][t])
                etat["sous_fait"] = etat.get("sous_fait", 0) + 1
                if f:
                    crees.append(f)
        if ecartes:
            logger.info("Import de %s : laissé de côté %s", lot.name, " · ".join(ecartes))
        if not series:
            raise ErreurImport(f"{lot.name} : aucune image reconnue dedans")
        return crees
    finally:
        shutil.rmtree(temp, ignore_errors=True)
        try:
            (dossier_serie / ".import").rmdir()
        except OSError:
            pass
