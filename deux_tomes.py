"""
Fichiers qui contiennent deux tomes (« Kenichi T45-46 ») : coupés en deux fichiers de tome.

Le second tome commence juste avant sa « table des matières » (page de titre puis sommaire) : le sommaire est
cherché au milieu du fichier, depuis le centre vers les bords. Si on ne le trouve pas, rien n'est coupé
(le fichier reste tel quel : on ne devine jamais une coupure).
"""
import logging
import re
import zipfile
from pathlib import Path

import archives
import sommaire

logger = logging.getLogger(__name__)
_PLAGE = re.compile(r"(?:^|[\s_\-.(\[])(?:t|tomes?|vol(?:umes?)?|v)[\s._-]*0*(\d{1,3})\s*(?:[-–]|à|et|&)\s*(?:t|tomes?)?[\s._-]*0*(\d{1,3})(?=$|[\s_\-.)\]])", re.I)
_SOMMAIRE = re.compile(r"table\s+des\s+mati|sommaire|contents", re.I)
MARGE = (0.30, 0.70)             # le milieu du fichier : où chercher le début du second tome
PAGES_MIN = 30                   # un tome plus court n'est pas un tome : coupure refusée


def numeros(nom: str):
    """« Kenichi T45-46 (…) » → (45, 46) ; None si ce n'est pas exactement deux tomes qui se suivent."""
    nom = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", nom).strip()
    m = _PLAGE.search(nom)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return (a, b) if b == a + 1 else None


def _texte(lire_page, i):
    """Texte d'une page (image réduite : plus rapide, assez net pour un titre ou un sommaire)."""
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(lire_page(i))).convert("L")
    tampon = io.BytesIO()
    im.save(tampon, "PNG")
    ancien = getattr(sommaire._LOCAL, "mode", "tesseract")
    sommaire._LOCAL.mode = "moderne"                  # lit les titres posés sur un dessin, que tesseract déforme (« BATAILLE 448 »)
    try:
        return sommaire.ocr(tampon.getvalue())
    finally:
        sommaire._LOCAL.mode = ancien


def _chercher(lire_page, nb_pages, test):
    """Première page du milieu (depuis le centre vers les bords) dont le texte passe « test » : (index, texte) ou None."""
    bas, haut = int(nb_pages * MARGE[0]), int(nb_pages * MARGE[1])
    centre = nb_pages // 2
    for i in sorted(range(bas, haut), key=lambda k: abs(k - centre)):
        try:
            texte = _texte(lire_page, i)
        except Exception:
            continue
        if test(texte):
            return i, texte
    return None


def premier_chapitre(info, tome):
    """Numéro (entier) du premier chapitre du tome d'après la fiche de la série, ou None."""
    nums = [float(n) for n, t in ((info or {}).get("tomes") or {}).items() if t is not None and int(t) == int(tome)]
    return int(min(nums)) if nums else None


def point_de_coupe(lire_page, nb_pages: int, chapitre=None):
    """Index (à partir de 0) de la première page du second tome, ou None.
    Avec le numéro de son premier chapitre : page de titre de ce chapitre (« BATAILLE 448 »), puis on remonte devant
    la page de titre et le sommaire du tome. Sans lui (ou sans résultat) : on cherche le sommaire du second tome."""
    def coupe_valide(c):
        return c if c is not None and c >= PAGES_MIN and nb_pages - c >= PAGES_MIN else None

    if chapitre:
        motif = re.compile(r"^\W*[^\W\d_]{3,12}\s*0*%d\b" % chapitre, re.I | re.M)
        trouve = _chercher(lire_page, nb_pages, lambda t: bool(motif.search(t)))
        if trouve:
            i, texte = trouve
            if _SOMMAIRE.search(texte):                       # la page trouvée est le sommaire du tome : la page de titre le précède
                return coupe_valide(i - 1)
            try:
                if _SOMMAIRE.search(_texte(lire_page, i - 1)):
                    return coupe_valide(i - 2)
            except Exception:
                pass
            return coupe_valide(i)
    trouve = _chercher(lire_page, nb_pages, lambda t: bool(_SOMMAIRE.search(t)))
    return coupe_valide(trouve[0] - 1) if trouve else None


def separer(chemin: Path, cibles: list, chapitre=None):
    """Écrit le premier tome dans cibles[0] et le second dans cibles[1]. « chapitre » : premier chapitre du second tome.
    Renvoie True si les deux fichiers sont écrits ; jamais d'écrasement d'un fichier existant."""
    chemin = Path(chemin)
    noms = archives.pages(chemin)
    coupe = point_de_coupe(lambda i: archives.read_page(chemin, i)[0], len(noms), chapitre)
    if coupe is None:
        logger.info("Deux tomes dans %s : début du second introuvable, fichier laissé tel quel", chemin.name)
        return False
    parties = [noms[:coupe], noms[coupe:]]
    ecrits = []
    try:
        with zipfile.ZipFile(chemin) as src:
            for cible, liste in zip(cibles, parties):
                cible = Path(cible)
                if cible.exists():
                    raise FileExistsError(cible.name)
                cible.parent.mkdir(parents=True, exist_ok=True)
                tmp = cible.with_name(cible.name + ".tmp")
                with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
                    for k, nom in enumerate(liste, 1):
                        dst.writestr(f"{k:04d}{Path(nom).suffix.lower()}", src.read(nom))
                ecrits.append((tmp, cible))
        for tmp, cible in ecrits:
            tmp.replace(cible)
    except Exception as e:
        for tmp, cible in ecrits:
            tmp.unlink(missing_ok=True)
        logger.warning("Deux tomes dans %s : coupure impossible (%s)", chemin.name, e)
        return False
    logger.info("Deux tomes dans %s : coupé en %d + %d pages", chemin.name, len(parties[0]), len(parties[1]))
    return True
