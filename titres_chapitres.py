"""
Titres des chapitres d'une série, avec un nom régulier comme « Trick 12 ».

Le nom est appris sur les tomes déjà bien nommés de la série (le mot fixe devant le numéro, et le numéro qui
correspond au chapitre). Il est ensuite proposé pour les chapitres sans titre, ceux dont le titre n'est qu'un
numéro, et ceux dont le numéro ne correspond plus au chapitre. Les vrais titres (« La valeur de la vie ») ne sont
jamais touchés. Rien n'est écrit sans validation : on montre d'abord l'aperçu.
"""
import re
from collections import Counter

MINIMUM_APPRIS = 3          # nombre de chapitres bien nommés qu'il faut pour apprendre un modèle


def _entier(num):
    """Le numéro du chapitre s'il est entier (ex. 12.0 → 12), sinon None (chapitre « 12.5 », bonus…)."""
    try:
        f = float(num)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else None


def apprendre(chapitres_par_tome: dict) -> tuple[str, int]:
    """Renvoie (mot fixe, nombre de chapitres qui le confirment). Le mot fixe peut être vide (titres en chiffres seuls)."""
    compte = Counter()
    for chapitres in chapitres_par_tome.values():
        for c in chapitres or []:
            n = _entier(c.get("num"))
            m = re.fullmatch(r"(.*?)\s*(\d+)", (c.get("titre") or "").strip())
            if n is None or not m or int(m.group(2)) != n:
                continue
            compte[m.group(1)] += 1
    if not compte:
        return "", 0
    mot, nb = compte.most_common(1)[0]
    return (mot, nb) if nb >= MINIMUM_APPRIS else ("", 0)


def _titre(mot: str, n: int) -> str:
    return f"{mot} {n}" if mot else str(n)


def _avec_prefixe(prefixe: str, n: int, actuel: str, officiel: str = "") -> str:
    """« Kill 12 : La nuit des assassins » : le mot choisi, le numéro, puis le vrai titre s'il y en a un. Le début déjà
    écrit (« Chapitre 12 », « Kill:12 », « 12. ») est remplacé, pas doublé."""
    reste = re.sub(r"^\s*(?:[^\W\d_]{1,15}\s*[:.\-–—]?\s*)?0*%d\b(?:\s*[:.\-–—]\s*|\s*$)" % n, "", actuel or "", count=1).strip()
    reste = reste or (officiel or "").strip()                  # pas de vrai titre lu dans le tome : celui de la fiche (Wikipédia français)
    return f"{prefixe} {n} : {reste}" if reste else f"{prefixe} {n}"


def proposer(infos_sommaires: dict, prefixe: str = "", officiels: dict | None = None) -> dict:
    """Avec un préfixe choisi par la personne (« Kill ») : TOUS les chapitres numérotés le reçoivent, vrais titres compris.
    Sans préfixe, aperçu : le modèle appris et la liste des changements (tome, numéro, titre actuel, titre proposé).
    infos_sommaires = le dictionnaire « sommaires » du fichier .mouflanga-infos.json de la série."""
    chapitres_par_tome = {str(t): (s or {}).get("chapitres") or [] for t, s in (infos_sommaires or {}).items()}
    prefixe = (prefixe or "").strip()
    if prefixe:
        changements = []
        for tome in sorted(chapitres_par_tome, key=lambda t: float(t) if re.fullmatch(r"[\d.]+", t) else 0):
            for c in chapitres_par_tome[tome]:
                n = _entier(c.get("num"))
                if n is None:
                    continue
                actuel = (c.get("titre") or "").strip()
                cible = _avec_prefixe(prefixe, n, actuel, (officiels or {}).get(n, ""))
                if cible != actuel:
                    changements.append({"tome": tome, "num": n, "avant": actuel, "apres": cible})
        return {"modele": f"{prefixe} N : titre", "nb_appris": 0, "choisi": True, "changements": changements}
    mot, nb = apprendre(chapitres_par_tome)
    if nb == 0:
        return {"modele": None, "nb_appris": 0, "changements": []}
    regle = re.compile(r"(?:" + re.escape(mot) + r"\s*)?\d+" if mot else r"\d+")     # « Trick 12 » ou « 12 »
    changements = []
    for tome in sorted(chapitres_par_tome, key=lambda t: float(t) if re.fullmatch(r"[\d.]+", t) else 0):
        for c in chapitres_par_tome[tome]:
            n = _entier(c.get("num"))
            if n is None:
                continue
            actuel = (c.get("titre") or "").strip()
            cible = _titre(mot, n)
            if actuel == cible:
                continue
            # Seuls les titres vides, en chiffres ou au même modèle mais avec un mauvais numéro sont proposés.
            if actuel and not regle.fullmatch(actuel):
                continue
            changements.append({"tome": tome, "num": n, "avant": actuel, "apres": cible})
    return {"modele": _titre(mot, "N"), "nb_appris": nb, "changements": changements}


def appliquer(infos_sommaires: dict, changements: list) -> int:
    """Écrit les nouveaux titres dans le dictionnaire des sommaires (en place). Renvoie le nombre de titres écrits."""
    ecrits = 0
    for ch in changements:
        sommaire = (infos_sommaires or {}).get(str(ch["tome"])) or {}
        for c in sommaire.get("chapitres") or []:
            if _entier(c.get("num")) == ch["num"]:
                c["titre"] = ch["apres"]
                ecrits += 1
                break
    return ecrits
