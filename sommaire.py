"""Sommaire d'un tome lu dans ses premières pages (OCR avec tesseract, en français).

Un tome complet (torrent, achat) n'a pas de liste de chapitres : on cherche la page « Sommaire » parmi les premières
images, on en lit les lignes « Chapitre 12 : Titre ...... 45 » et on retrouve où commence chaque chapitre dans le
fichier (décalage entre le numéro imprimé et la position de l'image, trouvé d'après le titre du 1er chapitre).
Le résultat est gardé dans <série>/.mouflanga-infos.json (« sommaires ») : rien n'est relu ensuite.
"""
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
    clair=True : texte blanc sur fond coloré (sommaire d'un tome, « SOMMAIRE » sur orange) : on ne lit que le canal bleu,
    où le blanc est très clair et le fond sombre."""
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(image_octets))
    if clair and im.mode in ("RGB", "RGBA"):
        im = im.convert("RGB").split()[2].point(lambda v: 255 if v > 170 else 0)
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
    out = []
    for ligne in (texte or "").splitlines():
        ligne = ligne.strip()
        m = _LIGNE_MOT.match(ligne)
        num = titre = page = None
        if m:
            num, titre, page = _numero(m.group(1)), m.group(2), int(m.group(3))
        else:
            m = _LIGNE_NUM.match(ligne)
            if m:
                num, titre, page = float(m.group(1)), m.group(2), int(m.group(3))
        if page is None:
            continue
        titre = re.sub(r"[.·…_]{2,}.*$", "", titre or "").strip(" .:-–—,'\"‘’")
        titre = re.sub(r"^[@©®°•·\s]+", "", titre)                      # le sceau « @ » devant chaque chapitre
        if num is None and out:
            num = out[-1]["num"] + 1
        if num is None:
            continue
        out.append({"num": num, "titre": titre, "page": page})
    return out


def _vraisemblable(lignes) -> bool:
    """Au moins 2 chapitres, numéros et pages qui augmentent : c'est bien un sommaire."""
    if len(lignes) < 2:
        return False
    nums = [x["num"] for x in lignes]
    pages = [x["page"] for x in lignes]
    return all(b > a for a, b in zip(nums, nums[1:])) and all(b > a for a, b in zip(pages, pages[1:]))


def lire(chemin, lire_page, nb_pages) -> dict:
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
        lignes = analyser(textes[i])
        if not lignes:                                       # titre en blanc sur couleur : seconde lecture (canal bleu)
            try:
                clair = ocr(octets, clair=True)
                if analyser(clair):
                    textes[i], lignes = clair, analyser(clair)
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
    decalage = _decalage(trouve, textes, page_sommaire, lire_page, nb_pages)
    for c in trouve:
        c["image"] = c["page"] + decalage if decalage is not None and c["page"] + decalage < nb_pages else None
    return {"chapitres": trouve, "page_sommaire": page_sommaire, "decalage": decalage}


def _decalage(chapitres, textes, page_sommaire, lire_page=None, nb_pages=0):
    """Image où commence le 1er chapitre (son titre y est écrit, APRÈS le sommaire : la couverture porte souvent
    le même titre) moins sa page imprimée. Pas vu dans les pages déjà lues : quelques images autour de la page annoncée."""
    mots = [m for m in _simple(chapitres[0]["titre"]).split() if len(m) > 3][:4]
    if not mots:
        return None
    def contient(t):
        s = _simple(t)
        return sum(m in s for m in mots) >= max(1, (len(mots) + 1) // 2)
    for i, t in sorted(textes.items()):
        if i > page_sommaire and contient(t):
            return i - chapitres[0]["page"]
    if lire_page is None:
        return None
    for o in (0, 1, 2, -1, 3, 4, -2):
        i = chapitres[0]["page"] + o
        if i <= page_sommaire or i >= nb_pages or i in textes:
            continue
        try:
            textes[i] = ocr(lire_page(i))
        except Exception:
            continue
        if contient(textes[i]):
            return o
    return None


def etat(serie, tome):
    with _VERROU:
        return dict(_ETAT.get((serie, int(tome))) or {})


def lancer(serie, tome, chemin, lire_page, nb_pages, enregistrer):
    """Lit le sommaire en arrière-plan ; enregistrer(resultat) le garde. Renvoie False si déjà en cours."""
    cle = (serie, int(tome))
    with _VERROU:
        if (_ETAT.get(cle) or {}).get("en_cours"):
            return False
        _ETAT[cle] = {"en_cours": True, "message": "Lecture du sommaire…"}

    def travail():
        with _FILE:
            try:
                r = lire(chemin, lire_page, nb_pages)
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
