"""Sommaire d'un tome lu dans ses premières pages (OCR avec tesseract, en français).

Un tome complet (torrent, achat) n'a pas de liste de chapitres : on cherche la page « Sommaire » parmi les premières
images, on en lit les lignes « Chapitre 12 : Titre ...... 45 » et on retrouve où commence chaque chapitre dans le
fichier (décalage entre le numéro imprimé et la position de l'image, trouvé d'après le titre du 1er chapitre).
Le résultat est gardé dans <série>/.mouflanga-infos.json (« sommaires ») : rien n'est relu ensuite.
"""
import difflib
from collections import Counter
import io
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from pathlib import Path

logger = logging.getLogger("mouflanga")

PAGES_MAX = 14                  # images lues au début du tome
VERSION = 6                     # version du lecteur : un tome « sans sommaire » lu par une version plus ancienne est relu
_MOTS = r"(?:chapitre|kapitel|chap|ch|sc[eè]ne|[ée]pisode|ep|acte|round|le[cç]on|lesson|partie|nuit|jour|histoire|file|stage|level|#)"
_CHIFFRES_OCR = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "A": "4", "B": "8", "Z": "2"})
# « SCÈNE 1 La tueuse aux yeux d'argent .......5 », « Chapitre 12 : Le retour 45 », « 12. Le retour ...... 45 »
_LIGNE_MOT = re.compile(r"^\W*" + _MOTS + r"\.?\s*([0-9OoIlSABZ|]{1,4})\b\s*[:.\-–—]?\s*(.*?)[\s.·…_,]+(\d{1,3})\s*$", re.I)
_LIGNE_NUM = re.compile(r"^\W*(\d{1,4})\s*[.):\-–—]\s*(.+?)\s*[.·…_,]{3,}\s*(\d{1,3})\s*$")

_DEBUT_CHAPITRE = re.compile(r"^\W*" + _MOTS + r"\.?\s*([0-9OoIlSABZ|]{1,4})\b\s*[:.\-–—]?\s*(.*)$", re.I)
_LIGNE_SPECIALE = re.compile(r"^\W*((?:[ée]\s?pilogue|prologue|bonus|extra|postface|pr[ée]face|interlude|chapitre\s+final|hors[- ]s[ée]rie)s?)\b"
                             r"[\s:.\-–—@©®°•·€{}()\[\]]*(.*?)[\s.·…_,\-–—]+(\d{1,3})\s*$", re.I)
_SUITE_TITRE = re.compile(r"^\W*(.*?)[\s.·…_,\-–—]+(\d{1,3})\s*$")

_ETAT = {}                      # (série, tome) → {"en_cours", "message"}
_VERROU = threading.Lock()
_FILE = threading.Semaphore(1)  # un seul tome lu à la fois (le processeur reste disponible pour le reste)


def disponible() -> bool:
    return shutil.which("tesseract") is not None


def _simple(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def ocr(image_octets: bytes, clair: bool = False) -> str:
    """Texte d'une image (tesseract, français, une ligne par ligne de texte).
    clair=True : texte blanc sur fond coloré (sommaire d'un tome sur orange, sur rose) : on ne garde que ce qui est clair
    dans les trois canaux (le plus sombre des trois > 180) : le blanc ressort, un fond coloré non."""
    from PIL import Image, ImageChops, ImageOps
    im = Image.open(io.BytesIO(image_octets))
    if clair and im.mode in ("RGB", "RGBA"):
        r, g, b = im.convert("RGB").split()
        im = ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 255 if v > 180 else 0)
    else:
        im = ImageOps.grayscale(im)
    if im.width < 1400:                                   # petites images : agrandies, l'OCR lit mieux
        im = im.resize((im.width * 2, im.height * 2))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    env = dict(os.environ, OMP_THREAD_LIMIT="1")          # un seul cœur : l'appli reste fluide
    r = subprocess.run(["nice", "-n", "10", "tesseract", "stdin", "stdout", "-l", "fra", "--psm", "6"],
                       input=buf.getvalue(), capture_output=True, timeout=120, env=env)
    return r.stdout.decode("utf-8", "replace")


def _numero(brut):
    try:
        return float(brut.translate(_CHIFFRES_OCR))
    except ValueError:
        return None

_UNITES = {"zéro": 0, "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8,
           "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16}
_DIZAINES = {"vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60, "cent": 100}
_ORDINAUX = {"premier": 1, "première": 1, "premiere": 1, "second": 2, "seconde": 2, "unième": 1, "deuxième": 2, "troisième": 3,
             "quatrième": 4, "cinquième": 5, "sixième": 6, "septième": 7, "huitième": 8, "neuvième": 9, "dixième": 10,
             "onzième": 11, "douzième": 12, "treizième": 13, "quatorzième": 14, "quinzième": 15, "seizième": 16,
             "vingtième": 20, "trentième": 30, "quarantième": 40, "cinquantième": 50, "soixantième": 60, "centième": 100}


def isbn_du_texte(texte: str):
    """ISBN-13 imprimé (« ISBN : 978-2-82030-279-3 »), chiffres seuls, ou None. Seule la somme de contrôle valide le garde."""
    for m in re.finditer(r"ISBN[\s:\-]*((?:97[89])[\d\s\-]{10,17})", texte or "", re.I):
        c = re.sub(r"\D", "", m.group(1))[:13]
        if isbn_valide(c):
            return c
    return None


def isbn_valide(c: str) -> bool:
    if not re.fullmatch(r"97[89]\d{10}", c or ""):
        return False
    somme = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(c[:12]))
    return (10 - somme % 10) % 10 == int(c[12])

def lire_isbn(lire_page, nb_pages: int, fin: int = 6, debut: int = 5):
    """ISBN d'un tome lu par OCR, sans toucher au sommaire : d'abord les dernières pages (achevé d'imprimer, 4e de couverture),
    puis les premières (page de titre, copyright). Seul un ISBN à somme de contrôle valide est rendu ; None sinon."""
    fin_pages = list(range(nb_pages - 1, max(nb_pages - 1 - fin, -1), -1))
    debut_pages = [i for i in range(min(debut, nb_pages)) if i not in fin_pages]
    for i in fin_pages + debut_pages:
        try:
            v = isbn_du_texte(ocr(lire_page(i)))
        except Exception as e:
            logger.info("ISBN, page %d : %s", i, e.__class__.__name__)
            continue
        if v:
            return v
    return None



def nombre_fr(texte: str):
    """« Trente-troisième », « Trentième et unième », « Vingt et unième », « Quatre-vingt-dixième » → 33, 31, 21, 90 ;
    None si ce n'est pas un nombre en lettres."""
    mots = [m for m in re.split(r"[\s\-]+", (texte or "").lower().strip()) if m and m != "et"]
    if not mots:
        return None
    total, courant = 0, 0
    for k, m in enumerate(mots):
        if m in _ORDINAUX:
            v = _ORDINAUX[m]
        elif m in _UNITES:
            v = _UNITES[m]
        elif m in _DIZAINES:
            v = _DIZAINES[m]
        elif m in ("quatre", "vingts", "cents"):
            v = 0
        else:
            return None
        if m in ("vingt", "vingts", "vingtième") and mots[k - 1:k] == ["quatre"]:
            courant = courant - 4 + 80 if courant >= 4 else 80
        elif m in ("cent", "cents") and courant in range(2, 10):
            courant *= 100
        else:
            courant += v
    return courant or None


_LIGNE_EPISODE = re.compile(r"^\W*(?P<ord>[A-Za-zéèêîïôûùàçÉ'’\- ]+?)\s+(?:[ée]pisode|chapitre)\s*:?\s*(?P<titre>.*?)[\s.·…_]*"
                            r"(?:page\s*)?(?P<page>\d{1,3})\s*$", re.I)
_LIGNE_EPISODE_SPECIAL = re.compile(r"^\W*[ée]pisodes?\s+sp[ée]cial(?:e)?\s*(?P<n>\d{1,2})?\s*:?\s*(?P<titre>.*?)[\s.·…_]*"
                                    r"(?:page\s*)?(?P<page>\d{1,3})\s*$", re.I)


def analyser(texte: str) -> list[dict]:
    """Lignes de sommaire d'une page : [{"num", "titre", "page"}] (numéro illisible → suite du précédent)."""
    out, attente = [], None
    for ligne in (texte or "").splitlines():
        ligne = ligne.strip()
        if not ligne:                                         # ligne vide entre les deux morceaux d'un titre
            continue
        m = _LIGNE_MOT.match(ligne)
        num = titre = page = None
        speciale = _LIGNE_EPISODE_SPECIAL.match(ligne)
        ordinal = None if speciale else _LIGNE_EPISODE.match(ligne)
        if speciale:                                          # « Épisode spécial 3 : 6♦ - Première partie page 99 »
            reste = speciale.group("titre").strip(" .:-–—,'\"")
            nom = "Épisode spécial" + (" " + speciale.group("n") if speciale.group("n") else "")
            out.append({"num": None, "titre": nom + (" : " + reste if reste else ""), "page": int(speciale.group("page")),
                        "special": True})
            attente = None
            continue
        if ordinal and nombre_fr(ordinal.group("ord")) is not None:   # « Trente-troisième épisode : K♣ - Première partie page 3 »
            out.append({"num": float(nombre_fr(ordinal.group("ord"))), "titre": ordinal.group("titre").strip(" .:-–—,'\""),
                        "page": int(ordinal.group("page"))})
            attente = None
            continue
        if m:
            num, titre, page = _numero(m.group(1)), m.group(2), int(m.group(3))
            attente = None
        else:
            m = _LIGNE_NUM.match(ligne)
            if m:
                num, titre, page = float(m.group(1)), m.group(2), int(m.group(3))
                attente = None
            else:
                m = _LIGNE_SPECIALE.match(ligne)
                if m and out:                                 # « Épilogue ··· L'autre fin du voyage ··· 329 » : suite du précédent
                    mot = m.group(1)[:1].upper() + m.group(1)[1:].lower()
                    reste = re.sub(r"^[^\w«\"“‘'(\[]+", "", m.group(2)).strip(" .:-–—,'\"‘’")
                    num, titre, page = None, (mot + " : " + reste) if reste else mot, int(m.group(3))
                    attente = None
        if page is None and attente is not None:             # titre sur deux lignes : la page est au bout de la seconde
            suite = _SUITE_TITRE.match(ligne)
            if suite and not _DEBUT_CHAPITRE.match(ligne):
                num, titre, page = attente[0], (attente[1] + " " + suite.group(1)).strip(), int(suite.group(2))
            attente = None
        if page is None:
            debut = _DEBUT_CHAPITRE.match(ligne)
            attente = (_numero(debut.group(1)), debut.group(2)) if debut and _numero(debut.group(1)) is not None else None
            continue
        titre = re.sub(r"[.·…_]{2,}.*$", "", titre or "").strip(" .:-–—,'\"‘’")
        titre = re.sub(r"^[^\w«\"“‘'(\[]+", "", titre)                  # le sceau « @ », « € », « €} » devant chaque chapitre
        if num is None and out:
            num = out[-1]["num"] + 1
        if num is None:
            continue
        out.append({"num": num, "titre": titre, "page": page})
    return _numeroter_speciaux(out)


def _reparer_lignes(texte: str) -> list[dict]:
    """Sommaire « Chapitre 1 - Titre ..... 7 » dont quelques lignes sont mal lues (« ChapitreMSllaccostage PP 7 43 »,
    « Chapitre T0 EUKURE RE 177 ») : une ligne « Chapitre » = un chapitre, numérotés à la suite du premier lu ; la page est
    le nombre au bout de la ligne si elle suit la précédente, sinon estimée d'après l'écart habituel entre chapitres.
    [] si ce n'est pas une liste de lignes « Chapitre » (au moins 4, la plupart avec une page)."""
    brutes = [l.strip() for l in (texte or "").splitlines() if re.match(r"^\W*ch\w{0,3}p\w{0,4}tre", l.strip(), re.I)]
    if len(brutes) < 4:
        return []
    lus = []
    for l in brutes:
        m = re.match(r"^\W*ch\w{0,3}p\w{0,4}tre\s*([0-9OoIlT|]{1,4})?\W*(.*?)[\s.·…_,]*(\d{1,3})?\s*$", l, re.I)
        if not m:
            return []
        titre = re.sub(r"[.·…_]{2,}.*$", "", m.group(2) or "").strip(" .:-–—=,'\"‘’|")
        lus.append((_numero(m.group(1)) if m.group(1) else None, titre, int(m.group(3)) if m.group(3) else None))
    if sum(1 for x in lus if x[2] is not None) < 0.6 * len(lus):
        return []
    premier = next((n for n, _, _ in lus if n is not None), None)
    if premier is None:
        return []
    premier = premier - next(i for i, (n, _, _) in enumerate(lus) if n is not None)
    if premier < 0 or premier > 1:
        premier = 1
    pages = [x[2] for x in lus]
    ecarts = sorted(b - a for a, b in zip(pages, pages[1:]) if a is not None and b is not None and 5 <= b - a <= 60)
    if not ecarts:
        return []
    pas = ecarts[len(ecarts) // 2]
    sortie, prec = [], None
    for k, (_, titre, page) in enumerate(lus):
        estimee = page is None or (prec is not None and not (prec < page <= prec + 2.5 * pas))
        if estimee:
            page = (prec + pas) if prec is not None else None
        if page is None:
            return []
        c = {"num": float(premier + k), "titre": titre, "page": page}
        if estimee:
            c["estimee"] = True
        sortie.append(c)
        prec = page
    return sortie



def _numeroter_speciaux(lignes):
    """Chapitres spéciaux (« Épisode spécial 3 ») : numérotés 33,1 ; 33,2… après le chapitre qui les précède (ou avant le
    premier chapitre ordinaire s'ils ouvrent le tome), sans perturber la suite des chapitres."""
    if not any(x.get("special") for x in lignes):
        return lignes
    reguliers = [x["num"] for x in lignes if not x.get("special") and x["num"] is not None]
    if not reguliers:
        return [x for x in lignes if not x.get("special")]
    sortie, dernier, k = [], None, 0
    premier = reguliers[0]
    for x in lignes:
        if x.get("special"):
            base = dernier if dernier is not None else premier - 1
            k += 1
            sortie.append(dict(x, num=round(base + 0.1 * k, 1)))
        else:
            sortie.append(x)
            dernier, k = x["num"], 0
    return sortie


def _numeros_suivis(lignes):
    """« 24 » lu « 21 » après « 23 » : un numéro qui ne suit pas le précédent devient précédent + 1
    (les pages imprimées, elles, doivent déjà croître : sinon la ligne n'est pas un chapitre)."""
    sortie = []
    for x in lignes:
        if sortie and x["num"] <= sortie[-1]["num"]:
            x = dict(x, num=sortie[-1]["num"] + 1)
        sortie.append(x)
    return sortie


def _vraisemblable(lignes) -> bool:
    """Au moins 2 chapitres, numéros et pages qui augmentent : c'est bien un sommaire."""
    if len(lignes) < 2:
        return False
    nums = [x["num"] for x in lignes]
    pages = [x["page"] for x in lignes]
    return all(b > a for a, b in zip(nums, nums[1:])) and all(b > a for a, b in zip(pages, pages[1:]))


# ---------------------------------------------------------------- « CHAPITRE 8 : » puis « TITRE ........ P. 7 »
_ENTETE_CHAPITRE = re.compile(r"^\W*[xX]?\W*ch\w{0,2}p\w{0,3}tre", re.I)


def _lectures_chiffres(im, boite) -> Counter:
    """Un numéro de page lu de plusieurs façons (échelles, modes tesseract, noir sur blanc ou l'inverse) : votes."""
    from PIL import ImageOps
    x0, y0, x1, y1 = boite
    base = ImageOps.grayscale(im.crop((max(0, x0), max(0, y0), min(im.width, x1), min(im.height, y1))))
    votes = Counter()
    if base.width < 6 or base.height < 6:
        return votes
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    for inverse in (False, True):
        c = ImageOps.autocontrast(ImageOps.invert(base)) if inverse else base
        for echelle in (2, 4):
            g = ImageOps.expand(c.resize((c.width * echelle, c.height * echelle)), border=30, fill=255)
            buf = io.BytesIO()
            g.save(buf, "PNG")
            for psm in ("7", "8", "13"):
                r = subprocess.run(["nice", "-n", "10", "tesseract", "stdin", "stdout", "-l", "fra", "--psm", psm, "-c",
                                    "tessedit_char_whitelist=0123456789"], input=buf.getvalue(), capture_output=True,
                                   timeout=60, env=env)
                t = r.stdout.decode("utf-8", "replace").strip()
                if re.fullmatch(r"\d{1,3}", t):
                    votes[int(t)] += 1
    return votes


def analyser_pages_p(image_octets: bytes, numeros=None) -> list[dict]:
    """Sommaire où chaque chapitre a un en-tête « CHAPITRE N : » (police décorative, numéro souvent mal lu) puis son titre
    et « P. 31 » au bout. Les pages sont relues une à une (chiffres seuls, agrandis) ; les numéros viennent de la liste
    des chapitres du tome (`numeros`, d'après Wikipédia) rangés dans l'ordre, jamais de l'en-tête illisible.
    [] si le nombre de lignes « P. » ne correspond pas à la liste connue."""
    from PIL import Image
    mots = mots_ocr(image_octets)
    im = Image.open(io.BytesIO(image_octets)).convert("RGB")
    reperes = sorted((m for m in mots if re.fullmatch(r"[Pp]\.?", m["t"]) or re.fullmatch(r"[Pp]\.\w{0,3}", m["t"])),
                     key=lambda m: m["y"])
    sommaire_y = [m["y"] + m["h"] for m in mots if re.fullmatch(r"\W*sommaire\W*", m["t"], re.I)]
    gros = max((m["h"] for m in mots if len(re.sub(r"\W", "", m["t"])) >= 4 and m["t"].lower() != "sommaire"
                and m.get("c", 0) >= 60 and not re.search(r"(?i)ch\w{0,2}p", m["t"])), default=0)
    sortie, haut = [], (sommaire_y[0] if sommaire_y else 0)
    for r in reperes:
        h = r["h"]
        if sortie and abs(r["y"] - sortie[-1]["_y"]) < h:
            continue
        debut = r["x"] + r["w"] + 2 if len(r["t"]) <= 2 else r["x"] + int(h * 0.55)   # « P.31 » lu d'un seul mot
        boite = (debut, r["y"] - h // 3, r["x"] + r["w"] + h * 5, r["y"] + h + h // 3)
        votes = _lectures_chiffres(im, boite)
        for m in mots:                                       # le mot lu par l'OCR de la page compte aussi
            if abs(m["y"] - r["y"]) < h and m["x"] >= r["x"] and re.search(r"\d", m["t"]):
                t = re.sub(r"^[Pp]\.?", "", m["t"]).translate(_LETTRES_CHIFFRES)
                if re.fullmatch(r"\d{1,3}", t):
                    votes[int(t)] += 1
        page = votes.most_common(1)[0][0] if votes else None
        mots_titre = [m for m in mots if haut <= m["y"] + m["h"] // 2 <= r["y"] + h // 2 and m["x"] + m["w"] <= r["x"] + 4
                      and m["h"] >= gros * 0.7]
        lignes = []
        for m in sorted(mots_titre, key=lambda m: m["y"]):    # lignes regroupées par hauteur, titre sur deux lignes compris
            if lignes and abs(m["y"] - lignes[-1][0]["y"]) < m["h"] * 0.6:
                lignes[-1].append(m)
            else:
                lignes.append([m])
        titre = [" ".join(m["t"] for m in sorted(l, key=lambda m: m["x"])) for l in lignes]
        titre = re.sub(r"(?i)\bch\w{0,2}p\w{0,3}tre\s*[\w|\[\]]{0,3}\s*:?\s*", "", " ".join(titre))
        titre = re.sub(r"^[^\w«\"“‘'(\[]+", "", titre).strip(" .:-–—,'\"‘’")
        sortie.append({"_y": r["y"], "titre": titre, "page": page, "_cands": dict(votes)})
        haut = r["y"] + h
    n = len(numeros or [])
    if n < 2 or len(sortie) != n:
        return []
    sortie = _pages_sures(sortie)                            # suite croissante la plus soutenue ; les trous sont estimés
    if not sortie:
        return []
    return [{"num": float(num), "titre": x["titre"], "page": x["page"]} for num, x in zip(sorted(numeros), sortie)]



# ---------------------------------------------------------------- Sommaire en colonnes (titres décoratifs)
# « Kapitel·1 / La fuite / 5 » côte à côte : l'OCR par lignes mélange les colonnes et lit mal les chiffres d'une police
# carrée. Ici : mots avec leurs positions (tesseract TSV), regroupés sous chaque « Kapitel N », et numéros de page lus
# par segments (7 segments, « 1 » reconnu à sa finesse), voté sur plusieurs seuils.

_SEGMENTS = {"abcdef": "0", "bc": "1", "abdeg": "2", "abcdg": "3", "bcfg": "4", "acdfg": "5", "acdefg": "6", "abc": "7",
             "abcdefg": "8", "abcdfg": "9"}
_ENTETE = re.compile(r"^\W*" + _MOTS + r"\W*([0-9OoIl|]{1,3})?\W*$", re.I)


def mots_ocr(image_octets: bytes, clair: bool = False, psm: int = 11) -> list[dict]:
    """Mots d'une page avec leur boîte : [{"t", "x", "y", "w", "h"}] (tesseract, texte épars)."""
    from PIL import Image, ImageChops, ImageOps
    im = Image.open(io.BytesIO(image_octets))
    if clair and im.mode in ("RGB", "RGBA"):
        r, g, b = im.convert("RGB").split()
        im = ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 255 if v > 180 else 0)
    else:
        im = ImageOps.grayscale(im)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    r = subprocess.run(["nice", "-n", "10", "tesseract", "stdin", "stdout", "-l", "fra", "--psm", str(psm), "tsv"],
                       input=buf.getvalue(), capture_output=True, timeout=120, env=env)
    mots = []
    for ligne in r.stdout.decode("utf-8", "replace").splitlines()[1:]:
        c = ligne.split("\t")
        if len(c) >= 12 and c[11].strip():
            try:
                mots.append({"t": c[11].strip(), "x": int(c[6]), "y": int(c[7]), "w": int(c[8]), "h": int(c[9]),
                             "c": float(c[10])})
            except ValueError:
                continue
    return mots


def _glyphes(masque):
    import numpy as np
    colonnes = masque.any(axis=0)
    out, debut = [], None
    for i, v in enumerate(list(colonnes) + [False]):
        if v and debut is None:
            debut = i
        elif not v and debut is not None:
            if i - debut >= 3:
                out.append((debut, i))
            debut = None
    return out


def _segments(g) -> str:
    """Segments allumés (a=haut, b=haut droite, c=bas droite, d=bas, e=bas gauche, f=haut gauche, g=milieu).
    "?" si un segment est à moitié rempli : ce n'est pas une police à segments (chiffres arrondis, penchés)."""
    h, w = g.shape
    douteux = []

    def mesure(r, axe, seuil):
        v = r.mean(axis=axe).max()
        if .4 < v < seuil - .15:                             # à moitié rempli : pas une police à segments
            douteux.append(v)
        return v >= seuil

    def barre(y0, y1):
        return mesure(g[int(y0 * h):max(int(y0 * h) + 1, int(y1 * h)), int(.2 * w):max(int(.2 * w) + 1, int(.8 * w))], 1, .7)

    def montant(y0, y1, x0, x1):
        return mesure(g[int(y0 * h):max(int(y0 * h) + 1, int(y1 * h)), int(x0 * w):max(int(x0 * w) + 1, int(x1 * w))], 0, .75)
    etat = (barre(0, .22), montant(.22, .42, .65, 1), montant(.58, .8, .65, 1), barre(.78, 1),
            montant(.58, .8, 0, .35), montant(.22, .42, 0, .35), barre(.38, .62))
    if douteux:
        return "?"
    return "".join(k for k, v in zip("abcdefg", etat) if v)


def _sept_penche(g) -> bool:
    """« 7 » dont la tige descend en biais : barre en haut sur presque toute la largeur, puis un seul trait étroit
    (aucune barre en bas ni boucle fermée, ce qui le distingue du 9 ou du 2)."""
    h, w = g.shape
    if h < 8 or w < 8 or g[:max(2, h // 6)].any(axis=0).mean() < .7:
        return False
    for ligne in g[h // 4:]:
        if not ligne.any():
            return False
        pleins = ligne.nonzero()[0]
        if ligne.sum() > .45 * w or np_ptp(pleins) > .5 * w:
            return False
    return True


def np_ptp(v):
    return int(v.max() - v.min())


def lire_numero(image_octets: bytes, boite, marge: int = 10, marge_x: int = 45) -> int | None:
    """Numéro de page écrit dans la boîte (x, y, w, h) de l'image, en police « à segments » : le plus voté sur plusieurs
    seuils, parmi les lectures complètes. None si rien de sûr."""
    import numpy as np
    from PIL import Image
    im = Image.open(io.BytesIO(image_octets)).convert("RGB")
    x, y, w, h = boite
    c = np.asarray(im.crop((max(0, x - marge_x), max(0, y - marge), x + w + marge_x, y + h + marge))).astype(float)
    if c.size == 0:
        return None
    fond = np.median(c.reshape(-1, 3), axis=0)
    d = np.abs(c - fond).sum(axis=2)
    rouge = np.clip(c[:, :, 0] - c[:, :, 1], 0, None)        # chiffres rouges sur halo clair devant un dessin sombre
    lu = None
    if rouge.max() > 60 and (rouge > rouge.max() * .5).sum() > 40:
        lu = _lire_masques(rouge, x, marge_x, w)
    if lu is None and d.max() >= 90:
        lu = _lire_masques(d, x, marge_x, w)
    return lu


def _lire_masques(d, x, marge_x, w):
    """Chiffres lus dans la carte de contraste d (plus c'est grand, plus c'est du texte), votes sur plusieurs seuils."""
    import numpy as np
    votes = Counter()
    for f in (.3, .4, .5, .6):
        m = d > d.max() * f
        gl = _glyphes(m)
        haut = max((np.ptp(m[:, a:b].any(axis=1).nonzero()[0]) + 1 for a, b in gl), default=0)
        groupes, cx = [], x - max(0, x - marge_x) + w / 2        # chiffres voisins du mot lu (pas le dessin autour)
        for g in gl:
            if groupes and g[0] - groupes[-1][-1][1] <= 0.9 * haut:
                groupes[-1].append(g)
            else:
                groupes.append([g])
        if not groupes:
            continue
        gl = min(groupes, key=lambda gr: abs((gr[0][0] + gr[-1][1]) / 2 - cx))
        if not 1 <= len(gl) <= 3:
            continue
        lu = ""
        hauteurs = [np.ptp(m[:, a:b].any(axis=1).nonzero()[0]) + 1 for a, b in gl]
        if min(hauteurs) < .8 * max(hauteurs):               # morceaux de chiffres, pas des chiffres
            continue
        for a, b in gl:
            sub = m[:, a:b]
            lignes = np.where(sub.any(axis=1))[0]
            g = sub[lignes[0]:lignes[-1] + 1]
            if g.shape[0] < 8 or (b - a) > 1.2 * g.shape[0]:   # trop large pour un chiffre : deux chiffres collés
                lu = ""
                break
            lu += "1" if (b - a) < 0.45 * g.shape[0] else "7" if _sept_penche(g) else _SEGMENTS.get(_segments(g), "?")
        if lu and "?" not in lu:
            votes[lu] += 1
    return int(votes.most_common(1)[0][0]) if votes else None


_LETTRES_CHIFFRES = str.maketrans({"O": "0", "o": "0", "D": "0", "I": "1", "l": "1", "|": "1", "i": "1", "S": "5", "s": "5",
                                   "B": "8", "Z": "2", "z": "2", "b": "6", "G": "6", "g": "9", "q": "9"})


def _page_de_ligne(image_octets, ligne):
    """Numéro de page au bout d'une ligne de mots, ou None : le mot de l'OCR s'il est fait de chiffres sûrs, sinon la
    lecture par segments, sinon le mot avec les confusions courantes (« 1D1 » → 101)."""
    m = ligne[-1]
    if len(ligne) >= 2 and len(m["t"]) <= 3 and len(ligne[-2]["t"]) <= 3:
        a = ligne[-2]                                        # « 9] » puis « || » : un seul numéro coupé en deux mots
        if 0 <= m["x"] - (a["x"] + a["w"]) < max(m["h"], a["h"]):
            x0, y0 = min(a["x"], m["x"]), min(a["y"], m["y"])
            p = lire_numero(image_octets, (x0, y0, max(a["x"] + a["w"], m["x"] + m["w"]) - x0,
                                           max(a["y"] + a["h"], m["y"] + m["h"]) - y0))
            if p is not None:
                return p
    brut = m["t"].strip(".,;:'’ ")
    jeton = int(brut) if re.fullmatch(r"\d{1,3}", brut) and m.get("c", 0) >= 70 else None
    if jeton is None and (len(re.sub(r"\W", "", brut)) > 4 or re.fullmatch(r"[^\W\d_]{3,}", brut)):
        return None
    p = lire_numero(image_octets, (m["x"], m["y"], m["w"], m["h"]))
    if p is not None and (jeton is None or len(str(p)) == len(str(jeton))):
        return p                                             # police à segments : plus sûre que l'OCR (153 pour 163)
    if jeton is not None:
        return jeton
    t = brut.translate(_LETTRES_CHIFFRES)
    return int(t) if re.fullmatch(r"\d{1,3}", t) and m.get("c", 0) >= 50 else None


def mots_fusionnes(image_octets: bytes) -> list[dict]:
    """Mots lus en normal et en « clair » (texte pâle sur dessin) : pour chaque endroit, la lecture la plus sûre."""
    normaux = mots_ocr(image_octets)
    try:
        clairs = mots_ocr(image_octets, clair=True)
    except Exception:
        return normaux

    def recouvre(a, b):
        ax, ay = a["x"] + a["w"] / 2, a["y"] + a["h"] / 2
        return b["x"] - 4 <= ax <= b["x"] + b["w"] + 4 and b["y"] - 4 <= ay <= b["y"] + b["h"] + 4
    def meilleur(a, b):                                      # a plus sûr que b : confiance plus haute, texte pas plus court
        return a["c"] > b["c"] and len(a["t"]) >= 0.7 * len(b["t"])
    sortie = []
    for m in normaux:
        autres = [c for c in clairs if recouvre(m, c) or recouvre(c, m)]
        if not any(meilleur(c, m) for c in autres):
            sortie.append(m)
    for c in clairs:
        autres = [m for m in normaux if recouvre(c, m) or recouvre(m, c)]
        if not autres or all(meilleur(c, m) for m in autres):
            sortie.append(c)
    return sortie


def _lire_chiffres(im, boite, clair=False, inverser=False):
    """Numéro lu seul : bande agrandie, chiffres uniquement (tesseract --psm 7), ou None."""
    from PIL import ImageChops, ImageOps
    x0, y0, x1, y1 = boite
    c = im.crop((max(0, x0), max(0, y0), min(im.width, x1), min(im.height, y1)))
    if c.width < 6 or c.height < 6:
        return None
    if clair and c.mode == "RGB":
        r, g, b = c.split()
        c = ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 255 if v > 180 else 0)
    else:
        c = ImageOps.grayscale(c)
        if inverser:                                         # chiffres clairs sur fond sombre : noir sur blanc pour tesseract
            c = ImageOps.autocontrast(ImageOps.invert(c))
    c = ImageOps.expand(c.resize((c.width * 3, c.height * 3)), border=30, fill=255)
    buf = io.BytesIO()
    c.save(buf, "PNG")
    r = subprocess.run(["nice", "-n", "10", "tesseract", "stdin", "stdout", "-l", "fra", "--psm", "7", "-c",
                        "tessedit_char_whitelist=0123456789"], input=buf.getvalue(), capture_output=True, timeout=60,
                       env=dict(os.environ, OMP_THREAD_LIMIT="1"))
    t = r.stdout.decode("utf-8", "replace").strip()
    return int(t) if re.fullmatch(r"\d{1,3}", t) else None


def _lire_bande(im, boite, clair=False):
    """(texte, confiance moyenne) d'une ligne de titre relue seule : bande agrandie, une ligne (tesseract --psm 7)."""
    from PIL import ImageChops, ImageOps
    x0, y0, x1, y1 = boite
    c = im.crop((x0, y0, x1, y1))
    if clair and c.mode == "RGB":
        r, g, b = c.split()
        c = ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 255 if v > 180 else 0)
    else:
        c = ImageOps.grayscale(c)
    c = ImageOps.expand(c.resize((c.width * 2, c.height * 2)), border=20, fill=255)
    buf = io.BytesIO()
    c.save(buf, "PNG")
    r = subprocess.run(["nice", "-n", "10", "tesseract", "stdin", "stdout", "-l", "fra", "--psm", "7", "tsv"],
                       input=buf.getvalue(), capture_output=True, timeout=60, env=dict(os.environ, OMP_THREAD_LIMIT="1"))
    mots, confs = [], []
    for ligne in r.stdout.decode("utf-8", "replace").splitlines()[1:]:
        col = ligne.split("\t")
        if len(col) >= 12 and col[11].strip():
            try:
                confs.append(float(col[10]))
            except ValueError:
                continue
            mots.append(col[11].strip())
    return " ".join(mots), (sum(confs) / len(confs) if confs else 0.0)


def _ligne_relue(im, ligne, cx, demi, actuel, conf_actuelle):
    """Titre d'une ligne relu en entier (normal puis texte clair) ; garde la lecture par mots sauf si la relecture est
    nettement plus sûre (mots oubliés par la lecture de la page entière : « creux »)."""
    if im is None:
        return actuel
    x0 = max(0, int(min(min(m["x"] for m in ligne) - 20, cx - demi)))
    x1 = int(max(max(m["x"] + m["w"] for m in ligne) + 20, cx + demi))
    y0 = max(0, min(m["y"] for m in ligne) - 6)
    y1 = max(m["y"] + m["h"] for m in ligne) + 6
    meilleur, conf = actuel, conf_actuelle
    for clair in (False, True):
        try:
            t, c = _lire_bande(im, (x0, y0, min(im.width, x1), min(im.height, y1)), clair)
        except Exception:
            continue
        lettres = re.sub(r"[^A-Za-zÀ-ÿ]", "", t)
        mots_t = [w for w in t.split() if re.search(r"[A-Za-zÀ-ÿ]{2}", w)]
        mots_a = [w for w in meilleur.split() if re.search(r"[A-Za-zÀ-ÿ]{2}", w)]
        if len(lettres) >= 3 and c >= 70 and len(mots_t) > len(mots_a) \
                and {w.lower() for w in mots_a} <= {w.lower() for w in mots_t}:     # elle ne fait qu'AJOUTER des mots oubliés
            meilleur, conf = t, c
    return meilleur


def _lignes_de(mots):
    """Mots d'une colonne regroupés par ligne (même hauteur à peu près), de haut en bas."""
    lignes = []
    for m in sorted(mots, key=lambda m: (m["y"] + m["h"] / 2, m["x"])):
        centre = m["y"] + m["h"] / 2
        if lignes and abs(centre - lignes[-1][0]) <= max(12, m["h"] * 0.7):
            lignes[-1][1].append(m)
        else:
            lignes.append([centre, [m]])
    return [sorted(l[1], key=lambda m: m["x"]) for l in lignes]


_PETITS_MOTS = {"is", "in", "of", "to", "no", "on", "or", "and", "the", "you", "all", "le", "la", "les", "de", "du", "des", "un", "une", "et", "à", "a", "en", "ou", "au", "aux", "sa", "se", "ce",
                "ne", "si", "l'", "d'", "ma", "mon", "ta", "ton", "ça", "où"}


def _mot_de_titre(m) -> bool:
    """Mot gardé dans le titre : lu avec assez de confiance, ou un vrai mot (même mal lu : « maison » à 10 %) ; les
    parcelles de dessin lues comme « PE » ou « il » en sont écartées."""
    t = m["t"].strip(".,:;'\"‘’“”«»")
    if re.fullmatch(r"\d{1,2}\W{0,3}(?:st|nd|rd|th|e|[a-zA-Z0-9]{1,2})?\W{0,3}", m["t"]):
        return True                                          # rang d'une suite (« 3"* », « 1°" ») : lu même à faible confiance
    lettres = re.sub(r"[^A-Za-zÀ-ÿ]", "", t)
    if len(lettres) <= 2:
        return t.lower() in _PETITS_MOTS and m.get("c", 100) >= 30
    if m.get("c", 100) >= 60:
        return True
    return m.get("c", 100) >= 30 or (len(lettres) >= 4 and len(lettres) >= len(t) - 1 and m.get("c", 100) >= 5)


def _combler_trous(image_octets, mots, entetes):
    """Un en-tête que l'OCR de la page entière n'a pas vu (texte clair sur fond sombre : « Kapitel·9 » entre le 8 et le
    10) se devine à l'écart anormal entre deux en-têtes : la zone est relue seule (lecture par bloc) et un en-tête sans
    numéro est ajouté ; ses mots sont ajoutés à `mots`."""
    from PIL import Image
    entetes = sorted(entetes, key=lambda e: e["m"]["y"])
    ecarts = sorted(b["m"]["y"] - a["m"]["y"] for a, b in zip(entetes, entetes[1:]))
    if len(ecarts) < 2:
        return entetes
    pas = ecarts[0]                                          # le plus petit écart = une colonne
    if pas < 60:
        return entetes
    try:
        im = Image.open(io.BytesIO(image_octets)).convert("RGB")
    except Exception:
        return entetes
    ajoutes = []
    for a, b in zip(entetes, entetes[1:]):
        manque = round((b["m"]["y"] - a["m"]["y"]) / pas) - 1
        if manque < 1 or manque > 3 or abs((b["m"]["y"] - a["m"]["y"]) - pas * (manque + 1)) > pas * .25:
            continue
        if a["num"] is not None and b["num"] is not None and int(b["num"]) - int(a["num"]) != manque + 1:
            continue                                         # pas de numéro manquant entre eux : pas de chapitre caché
        cx = int(a["m"]["x"] + a["m"]["w"] / 2)
        for j in range(1, manque + 1):
            y0 = int(a["m"]["y"] + pas * j) - 40
            y1 = min(im.height, int(a["m"]["y"] + pas * (j + 1)) - 40)
            x0 = max(0, cx - 230)
            buf = io.BytesIO()
            im.crop((x0, y0, cx + 230, y1)).save(buf, "PNG")
            try:
                lus = mots_ocr(buf.getvalue(), psm=6)
            except Exception:
                continue
            lus = [dict(m, x=m["x"] + x0, y=m["y"] + y0, c=max(m["c"], 60)) for m in lus if len(re.sub(r"\W", "", m["t"])) >= 1
                   and not (re.match(r"^[^\W\d_]{4,9}\W*[0-9OoIlBSZ|]{0,3}$", m["t"]) and any(
                       difflib.SequenceMatcher(None, re.sub(r"[^a-z]", "", m["t"].lower()), r).ratio() >= .7
                       for r in ("kapitel", "chapitre", "chapter")))
                   or re.match(r"^\d{1,3}$", m["t"])]
            lus = [m for m in lus if m["y"] > y0 + 45 or re.fullmatch(r"\d{1,3}", m["t"])]
            if not any(len(re.sub(r"[^A-Za-zÀ-ÿ]", "", m["t"])) >= 4 and m["c"] >= 50 for m in lus):
                continue                                     # aucun mot de titre dans la zone : pas de chapitre caché
            lus = [m for m in lus if not any(o["t"] == m["t"] and abs(o["x"] - m["x"]) < 20 and abs(o["y"] - m["y"]) < 20
                                             for o in mots)]       # déjà lus par la page entière
            entete = {"t": "", "x": cx - 80, "y": int(a["m"]["y"] + pas * j), "w": 160, "h": 34, "c": 100}
            mots.extend(lus)
            ajoutes.append({"m": entete, "num": None, "suite": None})
    return sorted(entetes + ajoutes, key=lambda e: e["m"]["y"])


def analyser_colonnes(image_octets: bytes, mots=None) -> list[dict]:
    """Sommaire en colonnes : [{"num", "titre", "page"}] ou []. Les en-têtes « Kapitel·N » placés côte à côte
    (même hauteur) ouvrent chacun une colonne ; sous chacun, le titre (une ou plusieurs lignes) puis le numéro de page,
    à n'importe quelle hauteur."""
    mots = mots if mots is not None else mots_ocr(image_octets)
    entetes = []
    for i, m in enumerate(mots):
        suite, brut = None, m["t"]
        mm = re.match(r"^([^\W\d_]{4,9})(.*)$", brut)
        if not mm or m["h"] < 10 or m["c"] < 20 and len(brut) < 6:
            continue
        mot, reste = mm.group(1).lower(), mm.group(2)
        if not (re.fullmatch(r"(?:chapitre|kapitel|chap|sc[eè]ne|[ée]pisode|acte|chapter)", mot, re.I) or any(difflib.SequenceMatcher(None, mot, r).ratio() >= .75
                                                       for r in ("kapitel", "chapitre", "chapter"))):
            continue
        if not re.search(r"[0-9OoIlBSZ|]", reste):                            # « Kapitel » puis « 1 » séparés
            voisins = [n for n in mots if n is not m and abs(n["y"] - m["y"]) < 20 and 0 < n["x"] - (m["x"] + m["w"]) < 120]
            if voisins:
                n = min(voisins, key=lambda n: n["x"])
                reste, suite = n["t"], n
        chiffres = re.findall(r"[0-9OoIlBSZ|]", re.sub(r"^[\W_]*", "", reste))
        num = _numero("".join(chiffres)) if 1 <= len(chiffres) <= 3 else None
        entetes.append({"m": m, "num": num, "suite": suite})
    if len(entetes) < 2:
        return []
    mots = list(mots)
    entetes = _combler_trous(image_octets, mots, entetes)
    utilises = {id(e["m"]) for e in entetes} | {id(e["suite"]) for e in entetes if e["suite"]}
    centre = lambda m: m["x"] + m["w"] / 2
    blocs = {id(e["m"]): [] for e in entetes}
    restes = [m for m in mots if id(m) not in utilises]
    attribue = {}
    for m in restes:                                         # chaque mot va sous l'en-tête le plus proche au-dessus
        for e in sorted((e for e in entetes if e["m"]["y"] < m["y"] < e["m"]["y"] + 450
                         and abs(centre(m) - centre(e["m"])) <= 270),
                        key=lambda e: (m["y"] - e["m"]["y"]) + abs(centre(m) - centre(e["m"])))[:1]:
            blocs[id(e["m"])].append(m)
            attribue[id(m)] = e
    for _ in range(3):                                       # mot de la même ligne, collé à un mot rangé : même colonne
        for m in restes:
            if id(m) in attribue:
                continue
            cy = m["y"] + m["h"] / 2
            for v in restes:
                if id(v) in attribue and abs(cy - (v["y"] + v["h"] / 2)) <= max(12, m["h"] * 0.7) \
                        and (0 <= m["x"] - (v["x"] + v["w"]) <= 40 or 0 <= v["x"] - (m["x"] + m["w"]) <= 40):
                    if abs(centre(m) - centre(attribue[id(v)]["m"])) > 300:       # pas jusqu'à la colonne voisine
                        continue
                    attribue[id(m)] = attribue[id(v)]
                    blocs[id(attribue[id(v)]["m"])].append(m)
                    break
    try:
        from PIL import Image
        im_rgb = Image.open(io.BytesIO(image_octets)).convert("RGB")
    except Exception:
        im_rgb = None
    demi = {}                                                # demi-largeur d'une colonne : moitié de l'écart au voisin
    for e in entetes:
        voisins = [abs(centre(o["m"]) - centre(e["m"])) for o in entetes
                   if o is not e and abs(o["m"]["y"] - e["m"]["y"]) < 40 and o["m"]["x"] != e["m"]["x"]]
        demi[id(e["m"])] = max(60, min(voisins) / 2 - 4) if voisins else 240
    sortie = []
    for e in entetes:
        titre, page, page_boite = [], None, None
        lignes = _lignes_de(blocs[id(e["m"])])
        for n, ligne in enumerate(lignes):
            if n >= 1:
                utiles = [m for m in ligne if re.search(r"\w", m["t"]) or (m["h"] <= 45 and m["w"] <= 90)]   # « { » du dessin : pas un numéro
                p = _page_de_ligne(image_octets, utiles) if utiles else None
                if p is not None:
                    page_boite = (min(m["x"] for m in utiles) - 8, min(m["y"] for m in utiles) - 6,
                                  max(m["x"] + m["w"] for m in utiles) + 8, max(m["y"] + m["h"] for m in utiles) + 6)
                    page = p
                    ligne = ligne[:-1]
                    while ligne and re.fullmatch(r"[\W_]{1,3}|\W?\d{1,3}\W?", ligne[-1]["t"]):
                        ligne = ligne[:-1]                   # le numéro était coupé en deux mots (« 9] » « || »)
            gardes = [m for m in ligne if _mot_de_titre(m)]
            actuel = " ".join(m["t"] for m in gardes)
            if gardes and page is None:                       # ligne de titre : relue entière, plus fidèle que les mots isolés
                confs = [m.get("c", 100) for m in gardes]
                actuel = _ligne_relue(im_rgb, gardes, centre(e["m"]), demi.get(id(e["m"]), 240), actuel, sum(confs) / len(confs))
            titre.append(actuel)
            if page is not None:                             # le numéro clôt la colonne (le reste est du dessin)
                break
        cands = Counter()
        if page is not None:
            cands[page] += 3
        if page is None and 0 < len(lignes) <= 3:            # numéro non lu par l'OCR : zone sous le titre
            bas = max(m["y"] + m["h"] for m in lignes[-1])
            page = lire_numero(image_octets, (int(centre(e["m"])) - 110, bas + 4, 220, 60), marge=0)
            if page is not None:
                cands[page] += 2
        if im_rgb is not None and lignes:                    # le numéro relu seul (chiffres uniquement), normal et clair
            if page_boite is None:
                bas = max(m["y"] + m["h"] for m in lignes[-1])
                page_boite = (int(centre(e["m"])) - 70, bas + 2, int(centre(e["m"])) + 70, bas + 60) if len(lignes) <= 3 else None
            if page_boite is not None:
                for clair_ in (False, True):
                    try:
                        v = _lire_chiffres(im_rgb, page_boite, clair_)
                    except Exception:
                        v = None
                    if v is not None:
                        cands[v] += 2
        titre = re.sub(r"[()\[\]{}|]", " ", " ".join(t for t in titre if t))
        titre = re.sub(r"^l(?=[A-ZÉÈÀ])", "", re.sub(r"\s+", " ", titre).strip())
        titre = re.sub(r"\b(\d)(?:[°º]|[\"'‘’*®]+(?=\s|$))(?!\s*part)", r"\1e", titre)       # « 3"* » : 3e (exposant lu en symboles)
        titre = re.sub(r"\s+[^\W\d_]?[\"'‘’*%®]+(?=\s|$)", "", titre)
        if page is None and len(lignes) >= 2:                # dernière ligne = numéro de page mal lu, pas du titre
            titre = re.sub(r"\s+\S{1,3}$", "", titre) if not re.search(r"[A-Za-zÀ-ÿ]{4}", titre.split(" ")[-1]) else titre
        titre = re.sub(r"\b(\d{1,2})\s+(district|chapitre|étage|bataillon|niveau|régiment|escadron)\b", r"\1e \2", titre)
        titre = _ordinal_part(titre)
        titre = titre.strip(" .:-–—,'\"=~_")
        sortie.append({"num": e["num"], "titre": titre, "page": page, "_cands": dict(cands),
                       "_xy": (e["m"]["x"], e["m"]["y"])})
    if len(sortie) < 2:
        return []
    sortie = _ordonner(sortie)
    nums = [x["num"] for x in sortie]
    meilleure = []
    for k in range(len(nums)):
        if nums[k] is None:
            continue
        chaine = max(([*c, k] for c in (meilleure[j] for j in range(len(meilleure)))
                      if 0 < nums[k] - nums[c[-1]] <= (k - c[-1]) + 2), key=len, default=[k])
        meilleure.append(chaine)
    garde = set(max(meilleure, key=len, default=[]))
    if len(garde) == 1 and len(sortie) >= 3:                 # un seul numéro lu : les autres suivent dans l'ordre de la page
        k0 = next(iter(garde))
        for k, x in enumerate(sortie):
            sortie[k] = dict(x, num=nums[k0] + (k - k0))
        nums = [x["num"] for x in sortie]
        garde = set(range(len(sortie)))
    if len(garde) < max(2, len(sortie) // 2):
        return []
    reparee, dernier = [], None
    for k, x in enumerate(sortie):
        if k not in garde:
            suivant = next((nums[j] for j in sorted(garde) if j > k), None)
            nouveau = (dernier + 1) if dernier is not None else (suivant - 1 if suivant is not None else None)
            if nouveau is None or (suivant is not None and nouveau >= suivant):
                continue
            x = dict(x, num=nouveau)
        dernier = x["num"]
        reparee.append(x)
    sortie = reparee
    if len(sortie) < 2 or any(b["num"] != a["num"] + 1 for a, b in zip(sortie, sortie[1:])):
        return []                                            # chapitre manquant : on ne devine pas
    return [dict(x, num=int(x["num"]) if float(x["num"]).is_integer() else x["num"]) for x in _pages_sures(sortie)]


def _completer_ordinaux(chapitres):
    """Suite « Nightmare 1st part », « Nightmare 2nd part » dont les rangs n'ont pas tous été lus (symboles d'exposant) :
    déduits d'un voisin lu ; sans aucun rang lu, la suite de deux chapitres ou plus de même titre commence à 1."""
    def decoupe(c):
        m = re.match(r"^(.*?)(?:\s+(\d+)(?:st|nd|rd|th))?(?:\s+part)?$", (c.get("titre") or "").strip())
        return (m.group(1), int(m.group(2)) if m.group(2) else None) if m and m.group(1) else (None, None)
    k = 0
    while k < len(chapitres):
        base = decoupe(chapitres[k])[0]
        j = k
        while base and j + 1 < len(chapitres) and decoupe(chapitres[j + 1])[0] == base:
            j += 1
        groupe = chapitres[k:j + 1]
        if base and len(groupe) >= 2 and any(re.search(r"\bpart$", c["titre"]) or decoupe(c)[1] for c in groupe):
            connu = next(((i, decoupe(c)[1]) for i, c in enumerate(groupe) if decoupe(c)[1]), None)
            depart = connu[1] - connu[0] if connu else 1
            if depart >= 1:
                for i, c in enumerate(groupe):
                    c["titre"] = _ordinal_part(f"{base} {depart + i} part")
        k = j + 1


def _ordinal_part(titre):
    """« Nightmare 1=)part », « Nightmare 3"* part », « Nightmare 10°" part » → « Nightmare 1st part » ; « Nigh tmare » recollé."""
    titre = re.sub(r"\bNigh\s+tmare\b", "Nightmare", titre)
    titre = re.sub(r"\b(\d)[\"'‘’*]+\d{1,2}(?=\s+part\b)", r"\1", titre)      # « 2"4 part » : 2nd (les lettres lues en chiffre)
    def ordinal(m):
        n = int(m.group(1).translate(str.maketrans("SB", "58")))
        if n > 20:                                           # « 34th » pour « 3rd » : rang illisible, déduit des voisins
            return "part"
        return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')} part"
    return re.sub(r"\b([0-9SB]{1,2})\W{0,4}(?:st|nd|rd|th|e)?\W{0,3}\s*part\b", ordinal, titre)


def _ordonner(sortie):
    """Ordre des chapitres sur la page : le plus cohérent avec leurs numéros (en-têtes en quinconce, en lignes, en
    colonnes) parmi : haut en bas puis gauche à droite, une même rangée de gauche à droite, ou selon le numéro lu."""
    def lignes(seuil):
        tri = sorted(sortie, key=lambda x: x["_xy"][1])
        rangs, courant, dernier_y = [], [], None
        for x in tri:
            if dernier_y is not None and x["_xy"][1] - dernier_y > seuil:
                rangs.append(courant)
                courant = []
            courant.append(x)
            dernier_y = x["_xy"][1]
        rangs.append(courant)
        return [x for r in rangs for x in sorted(r, key=lambda x: x["_xy"][0])]

    def coherence(ordre):                                    # combien de numéros lus tombent sur une suite régulière
        decalages = Counter(x["num"] - i for i, x in enumerate(ordre) if x["num"] is not None)
        return max(decalages.values(), default=0)
    essais = [lignes(30), lignes(100), lignes(150), sorted(sortie, key=lambda x: (x["num"] is None, x["num"] or 0))]
    return max(essais, key=coherence)


def _pages_sures(sortie):
    """Pages imprimées : pour chaque chapitre, plusieurs lectures possibles (par segments, mot, numéro relu seul) ;
    on garde la suite croissante de plus fort poids (« 67 » lu « 68 », « 99 » lu « 8 » sont écartés), puis les pages
    manquantes sont estimées entre leurs voisines (le titre cherché dans les pages voisines tranchera ensuite).
    [] si moins de deux pages sûres."""
    cands = []
    for x in sortie:
        c = dict(x.get("_cands") or {})
        if x["page"] is not None and x["page"] not in c:
            c[x["page"]] = 3
        cands.append(c)
    # programmation dynamique : meilleur[k][v] = (poids, précédent) pour la page v du chapitre k
    meilleur = [dict() for _ in sortie]
    for k, c in enumerate(cands):
        for v, w in c.items():
            best = (w, None)
            for j in range(k):
                for u, (pw, _) in meilleur[j].items():
                    if u < v and pw + w > best[0]:
                        best = (pw + w, (j, u))
            meilleur[k][v] = best
    fin = max(((pw, k, v) for k, d in enumerate(meilleur) for v, (pw, _) in d.items()), default=None)
    chaine = {}
    if fin:
        _, k, v = fin
        while True:
            chaine[k] = v
            prec = meilleur[k][v][1]
            if prec is None:
                break
            k, v = prec
    sures = sorted(chaine)
    pages = [chaine.get(k) for k in range(len(sortie))]
    if len(sures) < 2 or len(sures) < len(sortie) // 2:
        return []
    pas = (pages[sures[-1]] - pages[sures[0]]) / max(1, sures[-1] - sures[0])
    sortie = [dict(x) for x in sortie]
    for k, x in enumerate(sortie):
        if k in chaine:
            x["page"] = chaine[k]
            continue
        g = max((j for j in sures if j < k), default=None)
        d = min((j for j in sures if j > k), default=None)
        if g is not None and d is not None:
            v = pages[g] + (pages[d] - pages[g]) * (k - g) / (d - g)
        elif g is not None:
            v = pages[g] + pas * (k - g)
        else:
            v = pages[d] - pas * (d - k)
        x["page"] = max(1, round(v))
        x["estimee"] = True
    for a, b in zip(sortie, sortie[1:]):
        if b["page"] <= a["page"]:
            b["page"] = a["page"] + 1
    for x in sortie:
        for k in ("_pos", "_xy", "_cands"):
            x.pop(k, None)
    return sortie


def lire(chemin, lire_page, nb_pages, noms=None, numeros=None) -> dict:
    """{"chapitres": [{"num", "titre", "page" (imprimée), "image" (position dans le fichier ou None)}], "page_sommaire"}
    lire_page(i) → octets de l'image i. Sans sommaire trouvé : chapitres vide."""
    textes, trouve, page_sommaire = {}, [], None
    for i in range(min(nb_pages, PAGES_MAX)):
        try:
            octets = lire_page(i)
            textes[i] = ocr(octets)
        except Exception as e:                               # image illisible, tesseract en panne : page suivante
            logger.info("Sommaire de %s, page %d : %s", chemin, i, e.__class__.__name__)
            continue
        if re.search(r"(?i)sommaire", textes[i]) and re.search(r"(?i)[ée]pisode", textes[i]) and _SUSPECT.search(textes[i]):
            try:                                             # figures de cartes (♠ ♣ ♥ ♦) dans les titres : remises d'après leur forme
                avec = texte_avec_cartes(octets)
                if avec:
                    textes[i] = avec
            except Exception as e:
                logger.info("Sommaire de %s, page %d (cartes) : %s", chemin, i, e.__class__.__name__)
        lignes = _numeros_suivis(analyser(textes[i]))
        clair = None
        if re.search(r"(?i)kapitel|chapitre|sommaire", textes[i]) and not _vraisemblable(lignes[:0]):
            try:                                             # lecture par mots : titres et pages plus fidèles que les lignes
                cols = _numeros_suivis(analyser_colonnes(octets, mots_fusionnes(octets)))
                if _vraisemblable(cols) and (not _vraisemblable(lignes) or [c["num"] for c in cols] == [c["num"] for c in lignes]):
                    lignes = cols
            except Exception as e:
                logger.info("Sommaire de %s, page %d (mots) : %s", chemin, i, e.__class__.__name__)
        if not _vraisemblable(lignes) and re.search(r"(?i)sommaire|kapitel|chapitre|table", textes[i]):
            try:                                             # colonnes côte à côte (Kapitel·1 … Kapitel·5)
                cols = _numeros_suivis(analyser_colonnes(octets))
                if _vraisemblable(cols):
                    lignes = cols
            except Exception as e:
                logger.info("Sommaire de %s, page %d (colonnes) : %s", chemin, i, e.__class__.__name__)
        if not _vraisemblable(lignes):                       # titre en blanc sur couleur : seconde lecture (canal bleu)
            try:
                clair = ocr(octets, clair=True)
                if _vraisemblable(_numeros_suivis(analyser(clair))) or (analyser(clair) and not lignes):
                    textes[i], lignes = clair, _numeros_suivis(analyser(clair))
            except Exception as e:
                logger.info("Sommaire de %s, page %d (couleur) : %s", chemin, i, e.__class__.__name__)
        if not _vraisemblable(lignes) and re.search(r"(?i)sommaire|s\s?o\s?m\s?m", textes[i]) and re.search(r"#\s?\w", textes[i]):
            try:                                             # « #1 Keiji Kiriya ..... 3 » en police stylisée
                rt = analyser_rangees_titrees(octets, _lire_gabarits().get(Path(str(chemin)).parts[-3] if len(Path(str(chemin)).parts) >= 3 else ""))
                if _vraisemblable(rt):
                    lignes = rt
            except Exception as e:
                logger.info("Sommaire de %s, page %d (rangées titrées) : %s", chemin, i, e.__class__.__name__)
        if not _vraisemblable(lignes) and re.search(r"(?i)sommaire", textes[i]) and re.search(r"(?i)r[ée]ponses|le[cç]on", textes[i]):
            try:                                             # feuille de copie posée de travers (Assassination Classroom)
                fe = analyser_feuille(octets)
                if _vraisemblable(fe):
                    lignes = fe
            except Exception as e:
                logger.info("Sommaire de %s, page %d (feuille) : %s", chemin, i, e.__class__.__name__)
        if not _vraisemblable(lignes) and re.search(r"(?i)tri[ck]k?[:.\s]|sommaire", textes[i]):
            try:                                             # une rangée par chapitre, sans titre (« Trick:6 ..... 5 »)
                rang = analyser_rangees(octets)
                if _vraisemblable(rang):
                    lignes = rang
            except Exception as e:
                logger.info("Sommaire de %s, page %d (rangées) : %s", chemin, i, e.__class__.__name__)
        if not _vraisemblable(lignes) and clair and re.search(r"(?i)kapitel|chapitre|sommaire", clair):
            try:                                             # texte clair sur dessin (Kapitel·12 vert pâle) en colonnes
                cols = _numeros_suivis(analyser_colonnes(octets, mots_ocr(octets, clair=True)))
                if _vraisemblable(cols):
                    textes[i], lignes = clair, cols
            except Exception as e:
                logger.info("Sommaire de %s, page %d (colonnes claires) : %s", chemin, i, e.__class__.__name__)
        if not _vraisemblable(lignes):
            rep = _reparer_lignes(textes[i])                 # quelques lignes « Chapitre » mal lues : numéros et pages rétablis
            if _vraisemblable(rep):
                lignes = rep
        if numeros and len(numeros) >= 2 and len(lignes) < len(numeros) and re.search(r"(?i)sommaire", textes[i]):
            try:                                             # lecture incomplète : « CHAPITRE N : » + titre + « P. 31 »
                pp = analyser_pages_p(octets, numeros)
                if _vraisemblable(pp):
                    lignes = pp
            except Exception as e:
                logger.info("Sommaire de %s, page %d (P.) : %s", chemin, i, e.__class__.__name__)
        if trouve and lignes and lignes[0]["num"] > trouve[-1]["num"] and _vraisemblable(trouve + lignes):
            trouve += lignes                                 # sommaire sur deux pages
        elif not trouve and _vraisemblable(lignes):
            trouve, page_sommaire = lignes, i
        elif trouve and i > page_sommaire + 2:
            break
    isbn = next((v for v in (isbn_du_texte(t) for t in textes.values()) if v), None)
    if not isbn and nb_pages > PAGES_MAX:                    # achevé d'imprimer / 4e de couverture : les dernières pages
        for i in range(nb_pages - 1, max(PAGES_MAX - 1, nb_pages - 6), -1):
            try:
                isbn = isbn_du_texte(ocr(lire_page(i)))
            except Exception as e:
                logger.info("ISBN de %s, page %d : %s", chemin, i, e.__class__.__name__)
                continue
            if isbn:
                break
    if not trouve:                                           # pastilles empilées sans titre (« Trick:24 ..... 5 »)
        for i in sorted(textes):
            try:
                octets = lire_page(i)
                past = _numeros_suivis(analyser_pastilles(octets))
            except Exception as e:
                logger.info("Sommaire de %s, page %d (pastilles) : %s", chemin, i, e.__class__.__name__)
                continue
            if _vraisemblable(past):
                trouve, page_sommaire = past, i
                break
    if not trouve:
        if cle_claude():                                   # sommaire stylisé (Bakuman) : lu par l'analyse d'image de Claude
            try:
                return lire_vision(lire_page, nb_pages, cle_claude())
            except Exception as e:
                logger.info("Sommaire par Claude impossible pour %s : %s", chemin, e)
        return {"chapitres": [], "page_sommaire": None, "decalage": None, **({"isbn": isbn} if isbn else {})}
    _completer_ordinaux(trouve)
    images, decalage = _images(trouve, textes, page_sommaire, lire_page, nb_pages, noms)
    for c, image in zip(trouve, images):
        c["image"] = image if image is not None and image < nb_pages else None
    return {"chapitres": trouve, "page_sommaire": page_sommaire, "decalage": decalage, **({"isbn": isbn} if isbn else {})}


def _proche(mot, morceaux):
    """Le mot du titre est dans le texte lu, à quelques lettres près (« tefrent » pour « torrent ») : l'OCR se trompe
    souvent sur les titres stylisés des pages d'ouverture."""
    for m in morceaux:
        if mot in m or (len(mot) >= 5 and abs(len(m) - len(mot)) <= 2 and difflib.SequenceMatcher(None, mot, m).ratio() >= 0.7):
            return True
    return False


def _mots_titre(titre):
    return [m for m in _simple(titre).split() if len(m) > 3][:4]


def _contient(t, mots):
    morceaux = _simple(t).split()
    return sum(_proche(m, morceaux) for m in mots) >= max(1, (len(mots) + 1) // 2)


def _score(texte, mots, num):
    """Ressemblance d'une page avec l'ouverture d'un chapitre : chaque mot du titre lu (entier = 1, à quelques lettres
    près = 0,7) et surtout la mention « Chapitre N » avec le bon numéro (+2), que portent les pages d'ouverture."""
    simple = _simple(texte)
    morceaux = simple.split()
    total = 0.0
    for m in mots:
        if any(m in x for x in morceaux):
            total += 1
        elif _proche(m, morceaux):
            total += 0.7
    if num is not None and re.search(r"\b(?:chap\w*|kapitel)\s+0*%d\b" % int(num), simple):
        total += 2
    return total


def numero_imprime(image_octets: bytes) -> int | None:
    """Numéro de page imprimé en bas de l'image (coin gauche ou droit), ou None (page sans numéro, pleine page…)."""
    from PIL import Image, ImageOps
    im = ImageOps.grayscale(Image.open(io.BytesIO(image_octets)))
    w, h = im.size
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    for x0, x1 in ((0, 0.3), (0.7, 1.0), (0.3, 0.7)):
        bande = im.crop((int(w * x0), int(h * 0.93), int(w * x1), h))
        bande = ImageOps.expand(bande.resize((bande.width * 2, bande.height * 2)), border=20, fill=255)
        buf = io.BytesIO()
        bande.save(buf, "PNG")
        r = subprocess.run(["nice", "-n", "10", "tesseract", "stdin", "stdout", "-l", "fra", "--psm", "7",
                            "-c", "tessedit_char_whitelist=0123456789"], input=buf.getvalue(), capture_output=True,
                           timeout=60, env=env)
        t = r.stdout.decode("utf-8", "replace").strip()
        if re.fullmatch(r"\d{1,3}", t):
            return int(t)
    return None


def _ecart_imprime(lire_page, nb_pages, page, image, apres=-1):
    """Écart (image - page imprimée) lu sur les numéros imprimés en bas des pages voisines de l'estimation, ou None.
    Les pages d'ouverture de chapitre n'ont souvent pas de numéro (ou une bannière qui trompe l'OCR) : on lit les pages
    autour et on garde l'écart que plusieurs d'entre elles confirment."""
    ecarts = Counter()
    for d in (-1, 0, 1, 2, 3, -2):
        i = image + d
        if i < 0 or i <= apres or (nb_pages and i >= nb_pages):    # pas le sommaire ni ce qui le précède
            continue
        try:
            n = numero_imprime(lire_page(i))
        except Exception:
            continue
        if n is not None and abs(n - page) <= 8:
            ecarts[i - n] += 1
    if not ecarts:
        return None
    ecart, fois = ecarts.most_common(1)[0]
    return ecart if fois >= 2 or len(ecarts) == 1 else None


def _images(chapitres, textes, page_sommaire, lire_page=None, nb_pages=0, noms=None):
    """Image où commence chaque chapitre, et décalage du 1er (pour information).
    1) Le nom de fichier donne l'image (« 077.jpg » = page imprimée 77, double page « 042-043.jpg » comprise).
    2) Sans nom exploitable : les pages proches de l'estimation (page imprimée + écart du chapitre précédent ; pour le
       1er, de -2 à +10) reçoivent un score (voir _score) et la meilleure est gardée.
    Les doubles pages font varier l'écart d'un chapitre à l'autre : la recherche se fait chapitre par chapitre."""
    images, decalage, ecart, precedente = [], None, None, page_sommaire
    confirme = {}                                           # chapitre → écart lu sur un numéro imprimé

    def meilleure(plage, mots, num, seuil, estimation=0):
        gagnante, maxi = None, 0.0
        for i in sorted(plage, key=lambda j: abs(j - estimation)):       # à score égal : la page la plus proche de l'estimation
            if i <= precedente or i < 0 or (nb_pages and i >= nb_pages):
                continue
            if i not in textes:
                if lire_page is None:
                    continue
                try:
                    textes[i] = ocr(lire_page(i))
                except Exception:
                    continue
            sc = _score(textes[i], mots, num)
            if sc >= seuil and sc > maxi:                    # à égalité : la plus proche de l'estimation
                gagnante, maxi = i, sc
        return gagnante

    generique = len(chapitres) >= 2 and lire_page is not None and all(
        re.fullmatch(r"[A-Za-zÀ-ÿ]+\s*:?\s*\d+(?:[.,]\d)?", c.get("titre") or "") for c in chapitres)
    glob = None
    if generique:                                            # « Trick 6 » : aucun titre à chercher, les numéros imprimés décident
        votes = Counter()
        for c in chapitres:
            for i in range(max(page_sommaire + 1, c["page"] - 2), min(nb_pages or 10 ** 6, c["page"] + 12)):
                try:
                    n = numero_imprime(lire_page(i))
                except Exception:
                    continue
                if n is not None and abs(n - c["page"]) <= 6:
                    votes[i - n] += 1
        if votes:
            glob = votes.most_common(1)[0][0]
    for k, c in enumerate(chapitres):
        mots = _mots_titre(c["titre"])
        par_nom = _image_par_nom(c["page"], noms, page_sommaire) if glob is None else c["page"] + glob
        if par_nom is not None:
            image = par_nom             # essayé : ajuster sur le titre des pages voisines accorde moins (23/45 contre 29/45)
        else:
            if ecart is None:
                plage = sorted(textes) if (k == 0 and lire_page is None) else range(c["page"] - 2, c["page"] + 11)
            else:
                plage = range(c["page"] + ecart - 3, c["page"] + ecart + 4)
            estimation = c["page"] + (ecart if ecart is not None else 1)
            image = meilleure(plage, mots, c.get("num"), max(1.0, len(mots) / 2), estimation)
            if image is None and ecart is not None:
                image = c["page"] + ecart                    # estimation, sans titre lu
            if image is None and k == 0:                     # aucun titre lu : numéro du fichier en dernier recours
                e = _decalage_par_nom(c["page"], noms, page_sommaire)
                image = c["page"] + e if e is not None else None
        if image is not None and lire_page is not None:
            ecart_lu = _ecart_imprime(lire_page, nb_pages, c["page"], image, page_sommaire)   # le numéro imprimé tranche
            if ecart_lu is not None and 0 <= c["page"] + ecart_lu < (nb_pages or 10 ** 6) and c["page"] + ecart_lu > page_sommaire:
                image = c["page"] + ecart_lu
                confirme[k] = ecart_lu
        images.append(image)
        if image is not None:
            precedente = max(precedente, image)
            ecart = image - c["page"]
            if decalage is None:
                decalage = ecart
    for k, c in enumerate(chapitres):                        # chapitre sans numéro lu : l'écart confirmé le plus proche
        if k in confirme or images[k] is None or not confirme:
            continue
        proche = confirme[min(confirme, key=lambda j: abs(j - k))]
        if abs(images[k] - c["page"] - proche) <= 4 and c["page"] + proche > page_sommaire:
            images[k] = c["page"] + proche
    return images, decalage


def _decalage(chapitres, textes, page_sommaire, lire_page=None, nb_pages=0, noms=None):
    """Décalage du 1er chapitre seulement (voir _images)."""
    return _images(chapitres, textes, page_sommaire, lire_page, nb_pages, noms)[1]


def _image_par_nom(page, noms, page_sommaire):
    """Image dont le nom porte la page imprimée (« 077.jpg », ou « 042-043.jpg » pour une double page) : la plupart des
    scans sont nommés ainsi, et les doubles pages y sont déjà comptées pour une seule image."""
    for i, nom in enumerate(noms or []):
        m = re.match(r"(\d{2,4})(?:-(\d{2,4}))?(?!\d)", os.path.basename(nom))
        if m and i > page_sommaire and int(m.group(1)) <= page <= int(m.group(2) or m.group(1)):
            return i
    return None


def _decalage_par_nom(page, noms, page_sommaire):
    """Dernier recours : beaucoup de scans nomment les images d'après la page imprimée (« 005.jpg »). Un fichier
    dont le numéro est la page du 1er chapitre, après le sommaire, donne le décalage."""
    for i, nom in enumerate(noms or []):
        m = re.match(r"(\d{2,4})", os.path.basename(nom))
        if m and i > page_sommaire and int(m.group(1)) == page:
            return i - page
    return None


def etat(serie, tome):
    with _VERROU:
        return dict(_ETAT.get((serie, int(tome))) or {})


def lancer(serie, tome, chemin, lire_page, nb_pages, enregistrer, noms=None, numeros=None):
    """Lit le sommaire en arrière-plan ; enregistrer(resultat) le garde. Renvoie False si déjà en cours."""
    cle = (serie, int(tome))
    with _VERROU:
        if (_ETAT.get(cle) or {}).get("en_cours"):
            return False
        _ETAT[cle] = {"en_cours": True, "message": "Lecture du sommaire…"}

    def travail():
        with _FILE:
            try:
                r = lire(chemin, lire_page, nb_pages, noms, numeros)
                r["date"] = time.strftime("%Y-%m-%d")
                r["version"] = VERSION
                enregistrer(r)
                msg = f"{len(r['chapitres'])} chapitre(s) lus dans le sommaire" if r["chapitres"] else "Pas de sommaire trouvé dans les premières pages"
                logger.info("Sommaire de « %s » tome %s : %s", serie, tome, msg)
            except Exception as e:
                msg = f"Lecture impossible : {e.__class__.__name__}"
                logger.warning("Sommaire de « %s » tome %s : %s", serie, tome, e)
            with _VERROU:
                _ETAT[cle] = {"en_cours": False, "message": msg}
    threading.Thread(target=travail, daemon=True).start()
    return True


# ---------------------------------------------------------------- Rangées « Trick:6 ........ 5 » (sans titre : Air Gear)

_MOT_CLE_RANGEE = ("trick", "chapitre", "kapitel", "chapter", "episode", "épisode", "scene", "scène", "acte", "round", "stage",
                   "mission", "file", "level", "lesson", "leçon")


def analyser_rangees(image_octets: bytes, mots=None) -> list[dict]:
    """Sommaire fait d'une rangée par chapitre, « Trick:6 ........ 5 » : le chapitre n'a pas de titre, il s'appelle « Trick 6 ».
    [{"num", "titre", "page"}] ou []. Les numéros se déduisent de la suite (les rangées se suivent)."""
    mots = mots if mots is not None else mots_ocr(image_octets, psm=6)
    rangees = []
    for m in sorted(mots, key=lambda m: (m["y"] + m["h"] / 2, m["x"])):
        cy = m["y"] + m["h"] / 2
        if rangees and abs(cy - rangees[-1][0]) <= max(10, m["h"] * 0.6):
            rangees[-1][1].append(m)
        else:
            rangees.append([cy, [m]])
    lignes = []
    for _, r in rangees:
        r.sort(key=lambda m: m["x"])
        cle = None
        for k, m in enumerate(r):
            lettres = re.sub(r"[^a-zéè]", "", m["t"].lower().split(":")[0].split(".")[0])
            lettres = re.sub(r"^c(?=trick)", "", lettres)
            if len(lettres) >= 4 and any(difflib.SequenceMatcher(None, lettres, c).ratio() >= .8 for c in _MOT_CLE_RANGEE):
                cle = k
                break
        if cle is None or len(r) < 2:
            continue
        reste = r[cle + 1:]
        chiffres = re.sub(r"^[^:.\-–—]*[:.\-–—]?", "", r[cle]["t"])
        num_txt = re.sub(r"\W", "", chiffres)
        # tokens voisins du mot-clé (« Trick:1 » puis « 1 ») : suite du numéro
        while reste and re.fullmatch(r"[0-9OolI|]{1,2}", reste[0]["t"]) and reste[0]["x"] - (r[cle]["x"] + r[cle]["w"]) < 60 \
                and len(reste) > 1:
            num_txt += reste[0]["t"]
            r[cle] = dict(r[cle], w=r[cle]["w"] + reste[0]["w"] + 5)
            reste = reste[1:]
        page = None
        for m in reversed(reste):
            t = re.sub(r"[^\dOolIS|]", "", m["t"])
            if t and re.fullmatch(r"[\dOolIS|]{1,3}", t):
                page = _numero(t)
                break
        if page is None:
            continue
        lignes.append({"num": _numero(num_txt) if num_txt else None, "page": int(page), "y": r[0]["y"]})
    if len(lignes) < 2:
        return []
    # les rangées se suivent : numéro = début + rang ; le début est le plus souvent lu
    bases = Counter(int(x["num"]) - i for i, x in enumerate(lignes) if x["num"] is not None)
    if not bases:
        return []
    base = bases.most_common(1)[0][0]
    mot = "Trick"
    sortie = [{"num": float(base + i), "titre": f"{mot} {base + i}", "page": x["page"]} for i, x in enumerate(lignes)]
    return sortie if _vraisemblable(sortie) else []


def _pastilles(image_octets: bytes, inverse: bool = False) -> list[dict]:
    """Sommaire en pastilles empilées (Air Gear : « Trick:24 ......... 5 » dans une pilule par chapitre, sans titre) :
    chaque pastille est repérée à ses deux traits horizontaux, puis le nom et la page sont lus séparément.
    [{"num", "titre": "Trick 24", "page", "_cands"}] ou []."""
    import numpy as np
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(image_octets))
    gris = ImageOps.grayscale(im)
    g = np.asarray(ImageOps.invert(gris) if inverse else gris).astype(int)
    h, w = g.shape
    x0, x1 = int(.40 * w), int(.95 * w)
    bord = (g[:, x0:x1] < 110).mean(axis=1) > .6
    if bord.sum() < 8:                                       # pastilles plus à gauche sur cette page
        x0 = int(.34 * w)
        bord = (g[:, x0:x1] < 110).mean(axis=1) > .6
    groupes, i = [], 0
    while i < h:
        if bord[i]:
            j = i
            while j < h and bord[j]:
                j += 1
            groupes.append((i, j))
            i = j
        else:
            i += 1
    rangs = [(a1, b0) for (_, a1), (b0, _) in zip(groupes, groupes[1:]) if 18 <= b0 - a1 <= 0.06 * h]
    # une pastille sur deux est un vrai rang (l'autre est l'espace entre deux pastilles) : on prend les plus hautes
    if len(rangs) < 3:
        return []
    haut = sorted(b - a for a, b in rangs)[len(rangs) // 2 + len(rangs) // 4]
    rangs = [(a, b) for a, b in rangs if b - a >= haut * .8]
    if len(rangs) < 2:
        return []
    lignes_bord = np.where(bord)[0]                          # étendue des pastilles : là où les traits horizontaux ont de l'encre
    cols = (g[lignes_bord, :] < 110).mean(axis=0) > .6
    xs = np.where(cols)[0]
    if not len(xs):
        return []
    px0, px1 = int(xs.min()), int(xs.max())

    def lire_zone(img, liste_blanche=None, psm=7):
        img = ImageOps.expand(img.resize((img.width * 3, img.height * 3), Image.LANCZOS), border=30, fill=255)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        cmd = ["nice", "-n", "10", "tesseract", "stdin", "stdout", "-l", "fra", "--psm", str(psm)]
        if liste_blanche:
            cmd += ["-c", "tessedit_char_whitelist=" + liste_blanche]
        return subprocess.run(cmd, input=buf.getvalue(), capture_output=True, timeout=60,
                              env=dict(os.environ, OMP_THREAD_LIMIT="1")).stdout.decode("utf-8", "replace").strip()
    lignes = []
    for r0, r1 in rangs:
        coupe = g[r0 + 3:r1 - 3, px0:px1].astype("uint8")
        if coupe.size == 0:
            continue
        bande = Image.fromarray(coupe).point(lambda v: 255 if v > 100 else 0)
        gauche = bande.crop((0, 0, int(bande.width * .55), bande.height))
        droite = bande.crop((int(bande.width * .6), 0, bande.width, bande.height))
        etiquette = lire_zone(gauche)
        cands = Counter()
        for psm in (7, 8):
            t = lire_zone(droite, "0123456789", psm)
            if re.fullmatch(r"\d{1,3}", t):
                cands[int(t)] += 2
        if not re.search(r"(?i)ri?c?k|ick|rick", etiquette) and not (cands and re.search(r"\d", etiquette)):
            continue                                         # bandeau noir, pied de page… : pas une pastille de chapitre
        m = re.search(r"(\d{1,3})\s*$", etiquette)
        num = int(m.group(1)) if m else None
        lignes.append({"num": num, "cands": cands})
    if len(lignes) < 2 or len(lignes) < 0.8 * len(rangs) - 1:   # des pastilles illisibles : liste incomplète, on ne la garde pas
        return []
    bases = Counter(x["num"] - i for i, x in enumerate(lignes) if x["num"] is not None)
    if not bases:
        return []
    base = bases.most_common(1)[0][0]
    sortie = [{"num": float(base + i), "titre": f"Trick {base + i}", "page": None, "_cands": dict(x["cands"]), "_xy": (0, i)}
              for i, x in enumerate(lignes)]
    sortie = _pages_sures(sortie)
    return [{"num": x["num"], "titre": x["titre"], "page": x["page"]} for x in sortie] if sortie and _vraisemblable(sortie) else []


def analyser_pastilles(image_octets: bytes) -> list[dict]:
    """Voir _pastilles ; essaie aussi les pastilles noires à texte blanc."""
    r = _pastilles(image_octets)
    if len(r) < 3:
        r2 = _pastilles(image_octets, inverse=True)
        if len(r2) > len(r):
            r = r2
    return r


def analyser_rangees_titrees(image_octets: bytes, gabarits: dict | None = None, boites: list | None = None) -> list[dict]:
    """Sommaire en rangées « #1 Keiji Kiriya ......... 3 » (police stylisée, texte clair sur fond sombre) : lu par mots
    (normal + clair), numéros déduits de la suite, pages choisies parmi leurs lectures possibles. [{"num","titre","page"}] ou []."""
    mots = mots_fusionnes(image_octets)
    try:
        normaux = mots_ocr(image_octets, psm=6) + mots_ocr(image_octets, clair=True, psm=6)
    except Exception:
        normaux = []
    rangees = []
    for m in sorted(mots, key=lambda m: (m["y"] + m["h"] / 2, m["x"])):
        cy = m["y"] + m["h"] / 2
        if rangees and abs(cy - rangees[-1][0]) <= max(10, m["h"] * 0.6):
            rangees[-1][1].append(m)
        else:
            rangees.append([cy, [m]])
    marques = [(cy, r) for cy, r in rangees if re.fullmatch(r"#\s?[0-9A-Za-z|]{1,3}[.:]?", sorted(r, key=lambda m: m["x"])[0]["t"])]
    if len(marques) < 3:
        return []
    xs_marque = sorted(sorted(r, key=lambda m: m["x"])[0]["x"] for _, r in marques)
    x_marque = xs_marque[len(xs_marque) // 2]
    y_min, y_max = min(cy for cy, _ in marques), max(cy for cy, _ in marques)
    for cy, r in rangees:                                    # rang dont le « #9 » a été lu « HA » : même colonne, entre deux autres
        premier = sorted(r, key=lambda m: m["x"])[0]
        if (cy, r) not in marques and abs(premier["x"] - x_marque) <= 25 and len(premier["t"]) <= 4 and y_min - 5 <= cy <= y_max + 5 \
                and not premier["t"].startswith("#") and len(r) >= 2:
            marques.append((cy, r))
    marques.sort(key=lambda x: x[0])
    nombres = sorted(m["x"] for _, r in marques for m in r[1:] if re.fullmatch(r"\.*\d{2,4}\.*", m["t"]) and m["x"] > 0)
    if not nombres:
        return []
    colonne = nombres[len(nombres) // 2] - 40                # début de la colonne des pages (les pointillés lus « 0 » n'en font pas partie)
    try:
        from PIL import Image
        im_rgb = Image.open(io.BytesIO(image_octets)).convert("RGB")
    except Exception:
        im_rgb = None
    lignes = []
    for cy, r in marques:
        r = sorted(r, key=lambda m: m["x"])
        marque = r[0]["t"]
        chiffres = marque.lstrip("#").strip(" .:").translate(str.maketrans({"I": "1", "l": "1", "|": "1", "b": "6", "o": "0", "O": "0"}))
        num = int(chiffres) if re.fullmatch(r"\d{1,3}", chiffres) else None
        titre_mots = [m for m in r[1:] if m["x"] < colonne - 6 and re.search(r"[A-Za-zÀ-ÿ]{2}", m["t"])
                      and not re.fullmatch(r"[.\W]+", m["t"]) and (m["c"] >= 40 or len(re.sub(r"[^A-Za-zÀ-ÿ]", "", m["t"])) >= 4)]
        cands = Counter()
        for m in normaux + mots:
            if abs((m["y"] + m["h"] / 2) - cy) <= max(10, m["h"] * 0.6) and m["x"] + m["w"] >= colonne - 10:
                for d in re.findall(r"\d{1,4}", m["t"]):
                    if len(d) <= 3 and int(d) > 0:
                        cands[int(d)] += 2 if m["c"] >= 50 else 1
        if im_rgb is not None:                               # la colonne des pages relue seule, chiffres clairs sur fond sombre
            hauteur = max(m["h"] for m in r)
            boite = (colonne, int(cy - hauteur * .8), im_rgb.width, int(cy + hauteur * .8))
            if boites is not None:
                boites.append(boite)
            if gabarits:                                      # chiffres appris d'après tes corrections : le plus sûr
                try:
                    v = lire_nombre_appris(im_rgb, (colonne, int(cy - hauteur * .6), im_rgb.width, int(cy + hauteur * .6)), gabarits)
                except Exception:
                    v = None
                if v:
                    cands[v] += 6
            for inverser in (True, False):
                try:
                    v = _lire_chiffres(im_rgb, boite, False, inverser)
                except Exception:
                    v = None
                if v is not None and v > 0:
                    cands[v] += 3
        gardes = []
        titre_mots = [m for m in titre_mots if m["c"] >= 25 or len(titre_mots) == 1]      # « loire » lu à 13 % : parcelle de dessin
        for m in titre_mots:
            t = re.sub(r"[.…]{2,}.*$", "", m["t"]).strip(".,:;")
            lettres = re.sub(r"[^A-Za-zÀ-ÿ]", "", t)
            if not lettres or (len(lettres) <= 3 and t.lower() not in _PETITS_MOTS and not t[:1].isupper()) \
                    or (len(lettres) <= 2 and t.lower() not in _PETITS_MOTS) or re.search(r"[—–]", t):
                continue                                     # pointillés lus « css », « ss », « BC »
            gardes.append(t)
        titre = " ".join(gardes).strip()
        if len(re.sub(r"[^A-Za-zÀ-ÿ]", "", titre)) <= 2:     # cadre blanc sur le sommaire (titre caché) : pas de titre
            titre = ""
        lignes.append({"num": num, "titre": titre, "cands": cands, "y": cy})
    if len(lignes) < 3:
        return []
    bases = Counter(x["num"] - i for i, x in enumerate(lignes) if x["num"] is not None)
    if not bases:
        return []
    base = bases.most_common(1)[0][0]
    sortie = [{"num": float(base + i), "titre": x["titre"], "page": None, "_cands": dict(x["cands"]), "_xy": (0, i)}
              for i, x in enumerate(lignes)]
    sortie = _pages_sures(sortie)
    return [{"num": x["num"], "titre": x["titre"], "page": x["page"]} for x in sortie] if sortie and _vraisemblable(sortie) else []


# ---------------------------------------------------------------- Chiffres appris (police stylisée d'une série)
# Quand la police des numéros de page n'est pas lue par l'OCR (« #6 Mûrir ..... 173 »), l'appli apprend ses chiffres
# d'après les chapitres que tu as corrigés ou validés à la main (data/gabarits-chiffres.json, jamais sur GitHub).

GABARITS = Path(__file__).resolve().parent / "data" / "gabarits-chiffres.json"
_TAILLE_GLYPHE = (12, 20)


def _lire_gabarits() -> dict:
    try:
        return json.loads(GABARITS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _glyphes_nombre(image, boite):
    """Chiffres d'un nombre écrit dans la boîte (x0, y0, x1, y1) : liste de vecteurs 12×20 (0..1), de gauche à droite.
    Texte clair sur fond sombre ou l'inverse : le texte est la couleur la moins fréquente."""
    import numpy as np
    from PIL import Image, ImageOps
    x0, y0, x1, y1 = (int(v) for v in boite)
    c = ImageOps.autocontrast(ImageOps.grayscale(image.crop((max(0, x0), max(0, y0), min(image.width, x1), min(image.height, y1)))))
    g = np.asarray(c).astype(float)
    if g.size == 0 or g.max() - g.min() < 60:
        return []
    m = g > (g.min() + g.max()) / 2
    if m.mean() > .5:                                         # majorité de clair : le texte est le sombre
        m = ~m
    colonnes = m.sum(axis=0) > 0
    out, debut = [], None
    for i, v in enumerate(list(colonnes) + [False]):
        if v and debut is None:
            debut = i
        elif not v and debut is not None:
            if i - debut >= 2:
                sous = m[:, debut:i]
                lignes = np.where(sous.sum(axis=1) > 0)[0]
                if len(lignes) >= 8:
                    pav = sous[lignes[0]:lignes[-1] + 1]
                    v = np.asarray(Image.fromarray((pav * 255).astype("uint8")).resize(_TAILLE_GLYPHE, Image.BILINEAR)) / 255.0
                    out.append(v.reshape(-1))
            debut = None
    return out


def lire_nombre_appris(image, boite, gabarits: dict):
    """Nombre lu avec les chiffres appris, ou None : chaque chiffre est celui du gabarit le plus proche (écart assez petit)."""
    import numpy as np
    if not gabarits:
        return None
    echantillons = [(int(d), np.asarray(v)) for d, vs in gabarits.items() for v in vs]
    if len(echantillons) < 10:
        return None
    lu = ""
    for g in _glyphes_nombre(image, boite):
        d, e = min(((d, float(np.mean((g - v) ** 2))) for d, v in echantillons), key=lambda x: x[1])
        if e > 0.09:
            return None
        lu += str(d)
    return int(lu) if lu and len(lu) <= 3 else None


def apprendre_chiffres(serie: str, image, boites_valeurs) -> int:
    """Apprend les chiffres de la série : boites_valeurs = [((x0, y0, x1, y1), valeur), …] (la valeur est ce que tu as
    validé). Un nombre n'est appris que si son nombre de signes est bien celui de ses chiffres. Renvoie le nombre de
    chiffres appris."""
    g = _lire_gabarits()
    s = g.setdefault(serie, {})
    appris = 0
    for boite, valeur in boites_valeurs:
        txt = str(int(valeur))
        glyphes = _glyphes_nombre(image, boite)
        if len(glyphes) != len(txt):
            continue
        for ch, v in zip(txt, glyphes):
            lot = s.setdefault(ch, [])
            lot.append([round(float(x), 2) for x in v])
            del lot[:-6]                                      # six exemplaires par chiffre au plus (les plus récents)
            appris += 1
    if appris:
        GABARITS.parent.mkdir(parents=True, exist_ok=True)
        tmp = GABARITS.with_suffix(".tmp")
        tmp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
        tmp.replace(GABARITS)
    return appris


# ---------------------------------------------------------------- Feuille penchée « Leçon 1 : Assassinat = 005 » (Assassination Classroom)

def _nettoyer_feuille(crop):
    """Image d'une feuille manuscrite : texte seul (traits longs des cadres et des étiquettes retirés), agrandi."""
    import numpy as np
    import cv2
    from PIL import Image
    b = (np.asarray(crop) < 140).astype(np.uint8)
    hor = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (70, 1)))
    ver = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 70)))
    t = b - np.minimum(b, cv2.dilate(hor | ver, np.ones((3, 3), np.uint8)))
    out = Image.fromarray((255 - t * 255).astype("uint8"))
    return out.resize((out.width * 2, out.height * 2), Image.LANCZOS)


_CHIFFRES_FEUILLE = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "|": "1", "l": "1", "I": "1", "!": "1", "j": "1", "J": "1",
                                   "i": "1", "Z": "2", "z": "2", "A": "2", "S": "5", "$": "5", "s": "5", "G": "6", "b": "6", "B": "8"})


def _ligne_feuille(texte: str):
    """« ASSASSINAT = 005 | » → ("Assassinat", {5}) ; None si ce n'est pas une ligne de sommaire."""
    jetons = [j for j in re.split(r"\s+", texte.strip()) if j]
    while jetons and re.fullmatch(r"[|\\/_.,;:'’`´{}()\[\]¦!-]{1,2}", jetons[-1]):
        jetons = jetons[:-1]                                  # restes des cadres lus « | | »
    if len(jetons) < 2:
        return None
    dernier = re.sub(r"\W", "", jetons[-1]).translate(_CHIFFRES_FEUILLE)
    pages, corps = set(), jetons
    if re.fullmatch(r"[0-2]\d{2}", dernier) and int(dernier) > 0:
        pages.add(int(dernier))
        corps = jetons[:-1]
    while corps and (re.fullmatch(r"[=:<>×*«|x.\-]+", corps[-1]) or (re.fullmatch(r"[a-z]{2,5}", corps[-1]) and pages)):
        corps = corps[:-1]                                    # séparateur ou mot-réponse (« = », « is », « when »)
    titre = re.sub(r"[|{}()\[\]]", " ", " ".join(corps))
    titre = re.sub(r"^\W*(?:[0-9]\s+)?", "", re.sub(r"\s+", " ", titre)).strip(" .:=")
    titre = re.sub(r"\s*[=:<>×]\s*\S{0,4}$", "", titre).strip(" .:=")     # « BASES = ol » : le numéro mal lu n'est pas du titre
    if len(re.sub(r"[^A-Za-zÀ-ÿ]", "", titre)) < 3 or len(titre) > 70:
        return None
    if not pages and not re.search(r"[=<×:]", texte):         # ni numéro ni séparateur : pas une ligne de sommaire
        return None
    return titre, pages


def _feuille_barres(image_octets: bytes) -> list[dict]:
    """Sommaire écrit sur une feuille de copie posée de travers (« Leçon 1 / Assassinat = 005 ») : l'angle est cherché,
    la feuille redressée, chaque barre (entre deux traits horizontaux) est lue seule à trois angles voisins, puis les
    lectures de chaque barre sont fusionnées (titre le plus fréquent, numéros de page votés).
    [{"num" (1, 2, 3… relatif au tome), "titre", "page", "relatif": True}] ou []."""
    import numpy as np
    import cv2
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(image_octets)).convert("L")
    w, h = im.size
    crop = im.crop((int(.04 * w), int(.12 * h), int(.92 * w), int(.9 * h)))
    petit = crop.copy()
    petit.thumbnail((500, 700))
    scores = []
    for a in range(-14, 15):
        r = petit.rotate(a, expand=True, fillcolor=255, resample=Image.BILINEAR)
        scores.append((float((np.asarray(r) < 110).sum(axis=1).astype(float).var()), a))
    a0 = max(scores)[1]
    barres = {}                                               # rang de la barre → lectures [(titre, pages)]
    inter = False
    for a in (a0 - 1, a0, a0 + 1):
        r = crop.rotate(a, expand=True, fillcolor=255, resample=Image.BICUBIC)
        g = np.asarray(r)
        noir = (g < 140).astype(np.uint8)
        largeur = g.shape[1]
        hor = cv2.morphologyEx(noir, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, largeur // 4), 1)))
        profil = hor.sum(axis=1)
        lignes = np.where(profil > largeur * .25)[0]
        if not len(lignes):
            continue
        traits, debut = [], lignes[0]
        for u, v in zip(lignes, lignes[1:]):
            if v - u > 2:
                traits.append((debut + u) // 2)
                debut = v
        traits.append((debut + lignes[-1]) // 2)
        # barres = intervalles entre traits successifs assez hauts (les espaces entre barres sont plus bas)
        ecarts = [(t1, t2) for t1, t2 in zip(traits, traits[1:]) if 18 <= t2 - t1 <= 90]
        if len(ecarts) < 3:
            continue
        hauteurs = sorted(t2 - t1 for t1, t2 in ecarts)
        typique = hauteurs[len(hauteurs) // 2]
        ecarts = [(t1, t2) for t1, t2 in ecarts if abs((t2 - t1) - typique) <= typique * .35]
        propre = (noir - np.minimum(noir, cv2.dilate(hor, np.ones((3, 3), np.uint8))))
        ver = cv2.morphologyEx(propre, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40)))
        propre = propre - np.minimum(propre, cv2.dilate(ver, np.ones((3, 3), np.uint8)))
        for rang, (t1, t2) in enumerate(ecarts):
            bande = propre[max(0, t1 + 2):t2 - 1, int(largeur * .12):]
            if bande.size == 0 or bande.sum() < 30:
                continue
            img = Image.fromarray((255 - bande * 255).astype("uint8"))
            img = ImageOps.expand(img.resize((img.width * 3, img.height * 3), Image.LANCZOS), border=25, fill=255)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            for psm in (7, 13):
                try:
                    t = subprocess.run(["nice", "-n", "10", "tesseract", "stdin", "stdout", "-l", "fra", "--psm", str(psm)],
                                       input=buf.getvalue(), capture_output=True, timeout=60,
                                       env=dict(os.environ, OMP_THREAD_LIMIT="1")).stdout.decode("utf-8", "replace")
                except Exception:
                    continue
                if re.search(r"(?i)inter-?\s*classe", t):
                    inter = True
                lu = _ligne_feuille(t)
                if lu:
                    barres.setdefault(rang, []).append(lu)
    if len(barres) < 3:
        return []
    sortie = []
    for i, rang in enumerate(sorted(barres)):
        lectures = barres[rang]
        titres = Counter(t for t, _ in lectures)
        # titre le plus fréquent ; à égalité, le plus long (une lecture coupée est plus courte)
        titre = max(titres, key=lambda t: (titres[t], len(t)))
        pages = Counter(p for _, ps in lectures for p in ps)
        titre = titre.title() if titre.isupper() else titre
        sortie.append({"num": float(i + 1), "titre": titre, "page": None, "_cands": dict(pages), "_xy": (0, i)})
    sortie = _pages_sures(sortie)
    if not sortie or not _vraisemblable(sortie):
        return []
    res = [{"num": x["num"], "titre": x["titre"], "page": x["page"], "relatif": True} for x in sortie]
    if inter and len(res) >= 3:                               # dernière barre « Interclasse » : hors numérotation des leçons
        res[-1].update(num=round(res[-2]["num"] + 0.1, 1), titre="Interclasse : " + res[-1]["titre"])
    return res


def _feuille_lignes(image_octets: bytes) -> list[dict]:
    """Même feuille lue ligne par ligne (cadres effacés), à plusieurs angles, lectures fusionnées sur la plus complète."""
    import numpy as np
    from PIL import Image
    im = Image.open(io.BytesIO(image_octets)).convert("L")
    w, h = im.size
    crop = im.crop((int(.04 * w), int(.15 * h), int(.9 * w), int(.88 * h)))
    petit = crop.copy()
    petit.thumbnail((500, 700))
    scores = []
    for a in range(-14, 15):
        r = petit.rotate(a, expand=True, fillcolor=255, resample=Image.BILINEAR)
        scores.append((float((np.asarray(r) < 110).sum(axis=1).astype(float).var()), a))
    a0 = max(scores)[1]
    lectures, inter = [], False
    for a in (a0 - 1, a0, a0 + 1, a0 + 2):
        propre = _nettoyer_feuille(crop.rotate(a, expand=True, fillcolor=255, resample=Image.BICUBIC))
        buf = io.BytesIO()
        propre.save(buf, "PNG")
        for psm in (6, 4):
            texte = subprocess.run(["nice", "-n", "10", "tesseract", "stdin", "stdout", "-l", "fra", "--psm", str(psm)],
                                   input=buf.getvalue(), capture_output=True, timeout=90,
                                   env=dict(os.environ, OMP_THREAD_LIMIT="1")).stdout.decode("utf-8", "replace")
            if re.search(r"(?i)inter-?\s*classe", texte):
                inter = True
            lues = [x for x in (_ligne_feuille(l) for l in texte.splitlines()) if x]
            if len(lues) >= 3:
                lectures.append(lues)
    if not lectures:
        return []
    base = max(lectures, key=len)
    sq = [{"titres": Counter([t]), "pages": Counter(p)} for t, p in base]
    for lecture in lectures:
        if lecture is base:
            continue
        for t, p in lecture:
            i = max(range(len(sq)), key=lambda k: difflib.SequenceMatcher(None, t.lower(), sq[k]["titres"].most_common(1)[0][0].lower()).ratio())
            if difflib.SequenceMatcher(None, t.lower(), sq[i]["titres"].most_common(1)[0][0].lower()).ratio() >= .6:
                sq[i]["titres"][t] += 1
                sq[i]["pages"].update(p)
    sortie = []
    for i, g in enumerate(sq):
        titre = max(g["titres"], key=lambda t: (g["titres"][t], len(t)))
        sortie.append({"num": float(i + 1), "titre": titre.title() if titre.isupper() else titre, "page": None,
                       "_cands": dict(g["pages"]), "_xy": (0, i)})
    sortie = _pages_sures(sortie)
    if not sortie or not _vraisemblable(sortie):
        return []
    res = [{"num": x["num"], "titre": x["titre"], "page": x["page"], "relatif": True} for x in sortie]
    if inter and len(res) >= 3:
        res[-1].update(num=round(res[-2]["num"] + 0.1, 1), titre="Interclasse : " + res[-1]["titre"])
    return res


def analyser_feuille(image_octets: bytes) -> list[dict]:
    """La feuille est lue par barres et par lignes ; on garde la lecture la plus complète et la plus propre."""
    def qualite(r):
        if not r:
            return -1
        propres = sum(1 for x in r if re.fullmatch(r"[A-Za-zÀ-ÿ'’ .:&-]{3,}", x["titre"]) and len(x["titre"]) <= 40)
        return propres * 2 + len(r) - sum(1 for x in r if re.search(r"\d|=", x["titre"])) * 3
    candidats = []
    for f in (_feuille_lignes, _feuille_barres):
        try:
            candidats.append(f(image_octets))
        except Exception as e:
            logger.info("Feuille (%s) : %s", f.__name__, e.__class__.__name__)
    return max(candidats, key=qualite) if candidats else []


# ---------------------------------------------------------------- Symboles de cartes (Alice in Borderland)
# Les titres portent des figures de cartes (« K♣ - Première partie ») que l'OCR lit n'importe comment (« Ÿ », « # », « & ») :
# la forme du signe est classée d'après l'image (cœur, carreau, pique, trèfle).

def couleur_de_carte(image) -> str | None:
    """♠ ♣ ♥ ♦ d'après la forme d'un signe noir (image PIL découpée autour du signe), ou None."""
    import numpy as np
    from PIL import Image
    g = np.asarray(image.convert("L")).astype(float)
    if g.size == 0 or g.max() - g.min() < 60:
        return None
    m = g < (g.min() + g.max()) / 2
    if m.sum() < 25:
        return None
    ys, xs = np.where(m)
    m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    r = np.asarray(Image.fromarray((m * 255).astype("uint8")).resize((40, 40), Image.BILINEAR)) > 110
    w = r.sum(axis=1).astype(float)
    w = w / max(w.max(), 1)
    w20 = w.reshape(20, 2).mean(axis=1)
    pic = int(np.argmax(w20))
    chute = max((w20[i] - w20[i + 1] for i in range(11, 19)), default=0)       # tige : le calice s'arrête net
    if chute >= .3:
        return "♣" if np.ptp(w20[2:7]) <= .22 else "♠"
    return "♥" if pic <= 6 else "♦"


_RANG = re.compile(r"^(?:10|[2-9]|[AJQKajqk])$")
_SUSPECT = re.compile(r"(?:\b(?:10|[2-9]|[AJQK])\s*[^\w\s'’\-–:.,;!?()«»]|[ÿŸ#&@€¢♠♣♥♦])")


def texte_avec_cartes(image_octets: bytes) -> str | None:
    """Texte de la page, ligne par ligne, avec les figures de cartes remises à leur place ; None si rien à corriger."""
    from PIL import Image
    mots = mots_ocr(image_octets, psm=6)
    if not mots:
        return None
    im = Image.open(io.BytesIO(image_octets)).convert("RGB")
    lignes = []
    for m in sorted(mots, key=lambda m: (m["y"] + m["h"] / 2, m["x"])):
        cy = m["y"] + m["h"] / 2
        if lignes and abs(cy - lignes[-1][0]) <= max(10, m["h"] * 0.6):
            lignes[-1][1].append(m)
        else:
            lignes.append([cy, [m]])
    change = False
    sortie = []
    for _, ligne in lignes:
        ligne.sort(key=lambda m: m["x"])
        for k, m in enumerate(ligne):
            t = m["t"]
            suspect = (k > 0 and _RANG.match(ligne[k - 1]["t"]) and len(re.sub(r"\w", "", t)) >= 1 and len(t) <= 2
                       and not re.fullmatch(r"[:\-–—.,;!?]", t) and 0 <= m["x"] - (ligne[k - 1]["x"] + ligne[k - 1]["w"]) <= 1.5 * m["h"]) \
                or (k > 0 and _RANG.match(ligne[k - 1]["t"]) and t in ("Ÿ", "ÿ") )
            if not suspect:
                continue
            c = couleur_de_carte(im.crop((m["x"] - 3, m["y"] - 3, m["x"] + m["w"] + 3, m["y"] + m["h"] + 3)))
            if c:
                m["t"], change = c, True
                ligne[k - 1]["t"] = ligne[k - 1]["t"].upper()          # « j » → « J »
                ligne[k - 1]["colle"] = True                         # « K♣ » : pas d'espace entre le rang et la couleur
        texte = ""
        for m in ligne:
            texte += ("" if m.get("t") in "♠♣♥♦" and texte.endswith(" ") is False else "") + m["t"] + ("" if m.get("colle") else " ")
        sortie.append(texte.strip())
    return "\n".join(sortie) if change else None


# ---------------------------------------------------------------- Lecture par Claude (facultative, clé payante)

MODELE_VISION = "claude-haiku-5-5"
API_CLAUDE = "https://api.anthropic.com/v1"
_CONSIGNE = (
    "Voici les premières pages d'un tome de manga, numérotées à partir de 0 dans l'ordre du fichier. "
    "Trouve la page de sommaire (table des matières). Réponds UNIQUEMENT par un objet JSON, sans autre texte : "
    '{"page_sommaire": <numéro de l\'image du sommaire ou null>, '
    '"chapitres": [{"num": <numéro du chapitre>, "titre": "<titre en français tel qu\'écrit>", "page": <numéro de page imprimé>}], '
    '"image_chapitre_1": <numéro de l\'image où commence le premier chapitre listé, si tu la vois, sinon null>}. '
    "Sans sommaire : chapitres = []. N'invente rien.")


def cle_claude() -> str:
    return os.getenv("CLAUDE_API_KEY", "").strip()


def verifier_cle_claude(cle: str) -> tuple[bool, str]:
    """(ok, message) : la clé est-elle acceptée par l'API de Claude ? (liste des modèles : gratuit, rien n'est lu)"""
    import requests
    try:
        r = requests.get(API_CLAUDE + "/models", headers={"x-api-key": cle, "anthropic-version": "2023-06-01"}, timeout=15)
    except requests.RequestException:
        return False, "API de Claude injoignable depuis le serveur"
    if r.status_code == 200:
        return True, "Clé acceptée par Claude"
    if r.status_code == 401:
        return False, "Claude refuse cette clé (vérifie qu'elle est complète)"
    return False, f"L'API de Claude a répondu {r.status_code}"


def lire_vision(lire_page, nb_pages, cle) -> dict:
    """Envoie les premières pages (réduites) à Claude, qui lit le sommaire même stylisé (texte blanc sur noir…)."""
    import base64
    import json
    import requests
    from PIL import Image
    contenu = []
    for i in range(min(nb_pages, PAGES_MAX)):
        im = Image.open(io.BytesIO(lire_page(i)))
        im.thumbnail((800, 1200))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=70)
        contenu += [{"type": "text", "text": f"Image {i}"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}]
    contenu.append({"type": "text", "text": _CONSIGNE})
    r = requests.post(API_CLAUDE + "/messages", timeout=120,
                      headers={"x-api-key": cle, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json={"model": MODELE_VISION, "max_tokens": 2000, "messages": [{"role": "user", "content": contenu}]})
    if r.status_code != 200:
        raise RuntimeError(f"Claude a répondu {r.status_code}")
    texte = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    debut, fin = texte.find("{"), texte.rfind("}")
    d = json.loads(texte[debut:fin + 1]) if debut >= 0 else {}
    chap = [{"num": float(c["num"]), "titre": str(c.get("titre") or "").strip(), "page": int(c["page"])}
            for c in d.get("chapitres") or [] if str(c.get("num", "")).replace(".", "", 1).isdigit() and str(c.get("page", "")).isdigit()]
    if not _vraisemblable(chap):
        return {"chapitres": [], "page_sommaire": None, "decalage": None, "source": "Claude"}
    decalage = None
    if isinstance(d.get("image_chapitre_1"), int):
        decalage = d["image_chapitre_1"] - chap[0]["page"]
    for c in chap:
        c["image"] = c["page"] + decalage if decalage is not None and 0 <= c["page"] + decalage < nb_pages else None
    return {"chapitres": chap, "page_sommaire": d.get("page_sommaire"), "decalage": decalage, "source": "Claude"}
