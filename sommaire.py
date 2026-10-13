"""Sommaire d'un tome lu dans ses premières pages (OCR avec tesseract, en français).

Un tome complet (torrent, achat) n'a pas de liste de chapitres : on cherche la page « Sommaire » parmi les premières
images, on en lit les lignes « Chapitre 12 : Titre ...... 45 » et on retrouve où commence chaque chapitre dans le
fichier (décalage entre le numéro imprimé et la position de l'image, trouvé d'après le titre du 1er chapitre).
Le résultat est gardé dans <série>/.mouflanga-infos.json (« sommaires ») : rien n'est relu ensuite.
"""
import difflib
from collections import Counter
import io
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata

logger = logging.getLogger("mouflanga")

PAGES_MAX = 14                  # images lues au début du tome
VERSION = 2                     # version du lecteur : un tome « sans sommaire » lu par une version plus ancienne est relu
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


def analyser(texte: str) -> list[dict]:
    """Lignes de sommaire d'une page : [{"num", "titre", "page"}] (numéro illisible → suite du précédent)."""
    out, attente = [], None
    for ligne in (texte or "").splitlines():
        ligne = ligne.strip()
        if not ligne:                                         # ligne vide entre les deux morceaux d'un titre
            continue
        m = _LIGNE_MOT.match(ligne)
        num = titre = page = None
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
    return out


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


# ---------------------------------------------------------------- Sommaire en colonnes (titres décoratifs)
# « Kapitel·1 / La fuite / 5 » côte à côte : l'OCR par lignes mélange les colonnes et lit mal les chiffres d'une police
# carrée. Ici : mots avec leurs positions (tesseract TSV), regroupés sous chaque « Kapitel N », et numéros de page lus
# par segments (7 segments, « 1 » reconnu à sa finesse), voté sur plusieurs seuils.

_SEGMENTS = {"abcdef": "0", "bc": "1", "abdeg": "2", "abcdg": "3", "bcfg": "4", "acdfg": "5", "acdefg": "6", "abc": "7",
             "abcdefg": "8", "abcdfg": "9"}
_ENTETE = re.compile(r"^\W*" + _MOTS + r"\W*([0-9OoIl|]{1,3})?\W*$", re.I)


def mots_ocr(image_octets: bytes, clair: bool = False) -> list[dict]:
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
    r = subprocess.run(["nice", "-n", "10", "tesseract", "stdin", "stdout", "-l", "fra", "--psm", "11", "tsv"],
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
        if .3 < v < seuil:
            douteux.append(v)
        return v >= seuil

    def barre(y0, y1):
        return mesure(g[int(y0 * h):max(int(y0 * h) + 1, int(y1 * h)), int(.2 * w):max(int(.2 * w) + 1, int(.8 * w))], 1, .8)

    def montant(y0, y1, x0, x1):
        return mesure(g[int(y0 * h):max(int(y0 * h) + 1, int(y1 * h)), int(x0 * w):max(int(x0 * w) + 1, int(x1 * w))], 0, .75)
    etat = (barre(0, .22), montant(.22, .42, .65, 1), montant(.58, .8, .65, 1), barre(.78, 1),
            montant(.58, .8, 0, .35), montant(.22, .42, 0, .35), barre(.38, .62))
    if douteux:
        return "?"
    return "".join(k for k, v in zip("abcdefg", etat) if v)


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
    if d.max() < 90:
        return None
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
        for a, b in gl:
            sub = m[:, a:b]
            lignes = np.where(sub.any(axis=1))[0]
            g = sub[lignes[0]:lignes[-1] + 1]
            if g.shape[0] < 8:
                lu = ""
                break
            lu += "1" if (b - a) < 0.45 * g.shape[0] else _SEGMENTS.get(_segments(g), "?")
        if lu and "?" not in lu:
            votes[lu] += 1
    return int(votes.most_common(1)[0][0]) if votes else None


_LETTRES_CHIFFRES = str.maketrans({"O": "0", "o": "0", "D": "0", "I": "1", "l": "1", "|": "1", "i": "1", "S": "5", "s": "5",
                                   "B": "8", "Z": "2", "z": "2", "b": "6", "G": "6", "g": "9", "q": "9"})


def _page_de_ligne(image_octets, ligne):
    """Numéro de page au bout d'une ligne de mots, ou None : le mot de l'OCR s'il est fait de chiffres sûrs, sinon la
    lecture par segments, sinon le mot avec les confusions courantes (« 1D1 » → 101)."""
    m = ligne[-1]
    brut = m["t"]
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
        if not (re.fullmatch(_MOTS, mot, re.I) or any(difflib.SequenceMatcher(None, mot, r).ratio() >= .75
                                                       for r in ("kapitel", "chapitre", "chapter"))):
            continue
        if not re.search(r"[0-9OoIlBSZ|]", reste) and i + 1 < len(mots):      # « Kapitel » puis « 1 » séparés
            n = mots[i + 1]
            if abs(n["y"] - m["y"]) < 20 and 0 < n["x"] - (m["x"] + m["w"]) < 60:
                reste, suite = n["t"], n
        chiffres = re.findall(r"[0-9OoIlBSZ|]", re.sub(r"^[\W_]*", "", reste))
        num = _numero("".join(chiffres)) if 1 <= len(chiffres) <= 3 else None
        entetes.append({"m": m, "num": num, "suite": suite})
    if len(entetes) < 2:
        return []
    utilises = {id(e["m"]) for e in entetes} | {id(e["suite"]) for e in entetes if e["suite"]}
    centre = lambda m: m["x"] + m["w"] / 2
    blocs = {id(e["m"]): [] for e in entetes}
    for m in mots:                                           # chaque mot va sous l'en-tête le plus proche au-dessus
        if id(m) in utilises:
            continue
        for e in sorted((e for e in entetes if e["m"]["y"] < m["y"] < e["m"]["y"] + 450
                         and abs(centre(m) - centre(e["m"])) <= 170), key=lambda e: -e["m"]["y"])[:1]:
            blocs[id(e["m"])].append(m)
    sortie = []
    for e in entetes:
        titre, page = [], None
        lignes = _lignes_de(blocs[id(e["m"])])
        for n, ligne in enumerate(lignes):
            if n >= 1:
                p = _page_de_ligne(image_octets, ligne)
                if p is not None:
                    page = p
                    ligne = ligne[:-1]
            titre.append(" ".join(m["t"] for m in ligne if m.get("c", 100) >= 30))
            if page is not None:                             # le numéro clôt la colonne (le reste est du dessin)
                break
        if page is None and 0 < len(lignes) <= 3:            # numéro non lu par l'OCR : zone sous le titre
            bas = max(m["y"] + m["h"] for m in lignes[-1])
            page = lire_numero(image_octets, (int(centre(e["m"])) - 110, bas + 4, 220, 60), marge=0)
        if page is None:
            continue                                         # colonne illisible : le chapitre manquera
        titre = re.sub(r"\s+", " ", " ".join(t for t in titre if t)).strip(" .:-–—,'\"")
        sortie.append({"num": e["num"], "titre": titre, "page": page})
    sortie.sort(key=lambda x: x["page"])
    # numéros : on garde la plus longue suite croissante des numéros lus (« Kapitel·6 » lu « B »), le reste s'en déduit
    nums = [x["num"] for x in sortie]
    meilleure = []
    for k in range(len(nums)):
        if nums[k] is None:
            continue
        chaine = max(([*c, k] for c in (meilleure[j] for j in range(len(meilleure))) if nums[c[-1]] < nums[k]),
                     key=len, default=[k])
        meilleure.append(chaine)
    garde = set(max(meilleure, key=len, default=[]))
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
    if len(sortie) < 2 or any(b["num"] != a["num"] + 1 or b["page"] <= a["page"] for a, b in zip(sortie, sortie[1:])):
        return []                                            # chapitre manquant ou page douteuse : on ne devine pas
    return sortie


def lire(chemin, lire_page, nb_pages, noms=None) -> dict:
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
        lignes = _numeros_suivis(analyser(textes[i]))
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
        if trouve and lignes and lignes[0]["num"] > trouve[-1]["num"] and _vraisemblable(trouve + lignes):
            trouve += lignes                                 # sommaire sur deux pages
        elif not trouve and _vraisemblable(lignes):
            trouve, page_sommaire = lignes, i
        elif trouve and i > page_sommaire + 2:
            break
    if not trouve:
        if cle_claude():                                   # sommaire stylisé (Bakuman) : lu par l'analyse d'image de Claude
            try:
                return lire_vision(lire_page, nb_pages, cle_claude())
            except Exception as e:
                logger.info("Sommaire par Claude impossible pour %s : %s", chemin, e)
        return {"chapitres": [], "page_sommaire": None, "decalage": None}
    images, decalage = _images(trouve, textes, page_sommaire, lire_page, nb_pages, noms)
    for c, image in zip(trouve, images):
        c["image"] = image if image is not None and image < nb_pages else None
    return {"chapitres": trouve, "page_sommaire": page_sommaire, "decalage": decalage}


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


def _ecart_imprime(lire_page, nb_pages, page, image):
    """Écart (image - page imprimée) lu sur les numéros imprimés en bas des pages voisines de l'estimation, ou None.
    Les pages d'ouverture de chapitre n'ont souvent pas de numéro (ou une bannière qui trompe l'OCR) : on lit les pages
    autour et on garde l'écart que plusieurs d'entre elles confirment."""
    ecarts = Counter()
    for d in (-1, 0, 1, 2, 3, -2):
        i = image + d
        if i < 0 or (nb_pages and i >= nb_pages):
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

    for k, c in enumerate(chapitres):
        mots = _mots_titre(c["titre"])
        par_nom = _image_par_nom(c["page"], noms, page_sommaire)
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
            ecart_lu = _ecart_imprime(lire_page, nb_pages, c["page"], image)   # le numéro imprimé tranche
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


def lancer(serie, tome, chemin, lire_page, nb_pages, enregistrer, noms=None):
    """Lit le sommaire en arrière-plan ; enregistrer(resultat) le garde. Renvoie False si déjà en cours."""
    cle = (serie, int(tome))
    with _VERROU:
        if (_ETAT.get(cle) or {}).get("en_cours"):
            return False
        _ETAT[cle] = {"en_cours": True, "message": "Lecture du sommaire…"}

    def travail():
        with _FILE:
            try:
                r = lire(chemin, lire_page, nb_pages, noms)
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
