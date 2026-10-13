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
_MOTS = r"(?:chapitre|chap|ch|sc[eè]ne|[ée]pisode|ep|acte|round|le[cç]on|lesson|partie|nuit|jour|histoire|file|stage|level|#)"
_CHIFFRES_OCR = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "A": "4", "B": "8", "Z": "2"})
# « SCÈNE 1 La tueuse aux yeux d'argent .......5 », « Chapitre 12 : Le retour 45 », « 12. Le retour ...... 45 »
_LIGNE_MOT = re.compile(r"^\W*" + _MOTS + r"\.?\s*([0-9OoIlSABZ|]{1,4})\b\s*[:.\-–—]?\s*(.*?)[\s.·…_,]+(\d{1,3})\s*$", re.I)
_LIGNE_NUM = re.compile(r"^\W*(\d{1,4})\s*[.):\-–—]\s*(.+?)\s*[.·…_,]{3,}\s*(\d{1,3})\s*$")

_DEBUT_CHAPITRE = re.compile(r"^\W*" + _MOTS + r"\.?\s*([0-9OoIlSABZ|]{1,4})\b\s*[:.\-–—]?\s*(.*)$", re.I)
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
        titre = re.sub(r"^[@©®°•·\s]+", "", titre)                      # le sceau « @ » devant chaque chapitre
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
    if num is not None and re.search(r"\bchap\w*\s+0*%d\b" % int(num), simple):
        total += 2
    return total


def _images(chapitres, textes, page_sommaire, lire_page=None, nb_pages=0, noms=None):
    """Image où commence chaque chapitre, et décalage du 1er (pour information).
    1) Le nom de fichier donne l'image (« 077.jpg » = page imprimée 77, double page « 042-043.jpg » comprise).
    2) Sans nom exploitable : les pages proches de l'estimation (page imprimée + écart du chapitre précédent ; pour le
       1er, de -2 à +10) reçoivent un score (voir _score) et la meilleure est gardée.
    Les doubles pages font varier l'écart d'un chapitre à l'autre : la recherche se fait chapitre par chapitre."""
    images, decalage, ecart, precedente = [], None, None, page_sommaire

    def meilleure(plage, mots, num, seuil):
        gagnante, maxi = None, 0.0
        for i in plage:
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
            image = meilleure(plage, mots, c.get("num"), max(1.0, len(mots) / 2))
            if image is None and ecart is not None:
                image = c["page"] + ecart                    # estimation, sans titre lu
            if image is None and k == 0:                     # aucun titre lu : numéro du fichier en dernier recours
                e = _decalage_par_nom(c["page"], noms, page_sommaire)
                image = c["page"] + e if e is not None else None
        images.append(image)
        if image is not None:
            precedente = max(precedente, image)
            ecart = image - c["page"]
            if decalage is None:
                decalage = ecart
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
