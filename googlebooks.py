"""
Google Books (clé API dans ⚙️ Réglages → Règles de recherche) : ISBN, résumé (la « quatrième de couverture ») et éditeur des
tomes d'une série, en français. Google limite à 1 000 requêtes par jour : on s'en sert en dernier, pour les tomes que Wikipédia
et la BnF n'ont pas donnés, et une seule recherche de toute la série (40 notices par requête) remplace une requête par tome.

Rien n'est jamais pris pour « pas trouvé » quand Google n'a pas répondu : `reseau.Panne` / `reseau.Quota` remontent à l'appelant,
qui garde ce qu'il avait. Le compteur du jour et les pauses sont dans reseau.py (le quota se remet à zéro à minuit, heure du Pacifique).
"""
import logging
import os
import re

import bnf
import correspondance
import reseau

logger = logging.getLogger("mouflanga")

URL = "https://www.googleapis.com/books/v1/volumes"
PAGE = 40
PAGES_MAX = 5
PAR_TOME_MAX = 3                    # requêtes « un tome à la fois » au plus par passe, seulement si la recherche de la série a trouvé quelque chose


def cle() -> str:
    """Clé API Google Books (Réglages → 📏 Règles de recherche), lue à chaque appel."""
    return os.getenv("GOOGLE_BOOKS_API_KEY", "").strip()


def verifier_cle(cle_: str) -> tuple:
    """(ok, message) : Google accepte-t-il la clé pour l'API Books ? Ne renvoie jamais la clé."""
    try:
        r = reseau.SESSION.get(URL, params={"q": "one piece", "maxResults": 1, "key": cle_}, timeout=10)
    except reseau.requests.exceptions.RequestException:
        return False, "Google Books injoignable depuis le serveur"
    if r.status_code == 200:
        return True, "Clé acceptée par Google Books"
    raison = ""
    try:
        erreurs = (r.json().get("error") or {}).get("errors") or []
        raison = erreurs[0].get("reason", "") if erreurs else ""
    except ValueError:
        pass
    if r.status_code == 429:
        return False, "Quota dépassé pour cette clé : réessaie plus tard"
    if raison == "accessNotConfigured":
        return False, "L'API Books n'est pas activée dans le projet Google (Google Cloud → Bibliothèque d'API → Books API)"
    if r.status_code in (400, 403):
        return False, "Google refuse cette clé (vérifie qu'elle est complète et sans espace)"
    return False, f"Google Books a répondu {r.status_code}"


_MARQUE_TOME = re.compile(r"[-–,:.]?\s*\b(?:tome|t|vol\.?|volume|band)\s*0*(\d{1,3})\b", re.I)


def tome_du_titre(titre: str):
    m = _MARQUE_TOME.search(titre or "")
    return int(m.group(1)) if m else None


def _propre(t: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", t or "", flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _titre(item: dict) -> str:
    v = item.get("volumeInfo") or {}
    return " ".join(x for x in (v.get("title"), v.get("subtitle")) if x)


def notice(item: dict, noms, edition: str = "", autres=(), isbn_tomes=None):
    """Notice d'un résultat Google si c'est bien un tome de la série : {tome, isbn, titre, resume, editeur, date}, sinon None.
    Refusés : un autre livre (« Doors », « Édition limitée », « fanbook », série dérivée), une autre langue, sans numéro de tome,
    un ISBN qui n'est pas français ou dont la somme de contrôle est fausse.
    isbn_tomes {ISBN-13: tome} : ce que Wikipédia et la BnF savent déjà ; Google omet parfois le numéro (« Air Gear » tout court), et
    l'ISBN, lui, dit de quel tome il s'agit."""
    v = item.get("volumeInfo") or {}
    titre = _titre(item)
    if (v.get("language") or "fr") != "fr":
        return None
    ids = {x.get("type"): x.get("identifier", "") for x in v.get("industryIdentifiers") or []}
    brut = ids.get("ISBN_13", "") or ids.get("ISBN_10", "")
    isbn = bnf.isbn13(brut)
    if brut and (not isbn or not isbn.startswith(("9782", "97910"))):
        return None                                           # somme fausse, ou édition étrangère
    n = tome_du_titre(titre)
    if n is None and isbn and isbn_tomes:
        n = isbn_tomes.get(isbn)
    if n is None:
        return None
    if not correspondance.titre_de_la_serie(_MARQUE_TOME.sub("", titre), noms, autres, edition):
        return None
    resume = _propre(v.get("description") or "")
    if len(resume) > 1500:
        resume = resume[:1500].rsplit(" ", 1)[0] + "…"
    return {"tome": int(n), "isbn": isbn, "titre": titre, "resume": resume if len(resume) > 60 else "",
            "editeur": v.get("publisher") or "", "date": (v.get("publishedDate") or "")[:4]}


def parle_de_la_serie(item: dict, noms) -> bool:
    """Le résultat parle de la série (même sans numéro de tome) : sert à savoir si la page de résultats est encore pertinente."""
    titre = _MARQUE_TOME.sub("", _titre(item))
    return any(correspondance.contient_nom(titre, n) for n in noms if n and correspondance.jetons(n))


def _interroger(q: str, debut: int = 0, taille: int = PAGE, reserve: int = 0) -> list:
    """Une page de résultats Google (liste d'items). Lève reseau.Panne / reseau.Quota."""
    rep = reseau.get(URL, params={"q": q, "langRestrict": "fr", "maxResults": taille, "startIndex": debut, "printType": "books",
                                  "key": cle()}, reserve=reserve)
    if rep.statut != 200:
        return []
    return rep.json().get("items") or []


def chercher_serie(noms, *, edition: str = "", autres=(), voulus=(), reserve: int = reseau.RESERVE_FOND, pages_max: int = PAGES_MAX,
                   isbn_tomes=None) -> dict:
    """{tome: notice} des tomes de la série d'après Google Books : quelques pages de résultats pour toute la série. Google rend souvent
    20 résultats par page même quand on en demande 40 : la page suivante commence donc là où la précédente s'est arrêtée, et on s'arrête
    quand tous les tomes `voulus` sont trouvés, quand une page ne parle plus de la série (Google passe au hors-sujet) ou à `pages_max`.
    Lève reseau.Panne ou reseau.Quota si Google n'a pas répondu avant d'avoir trouvé quelque chose ; sinon rend ce qu'il a trouvé."""
    if not cle():
        return {}
    voulus = {int(t) for t in voulus}
    titre = next((n for n in noms if n and correspondance.jetons(n)), "")
    if not titre:
        return {}
    trouves, debut = {}, 0
    q = f"{titre} {edition} tome".replace("  ", " ")
    for _ in range(pages_max):
        try:
            items = _interroger(q, debut, PAGE, reserve)
        except reseau.Panne:
            if trouves:
                break
            raise
        if not items:
            break
        debut += len(items)
        for it in items:
            n = notice(it, noms, edition, autres, isbn_tomes)
            if n and n["tome"] not in trouves:
                trouves[n["tome"]] = n                         # même tome deux fois (papier / numérique) : le mieux classé
        if (voulus and voulus <= set(trouves)) or not any(parle_de_la_serie(it, noms) for it in items):
            break
    return trouves


def chercher_tome(noms, tome: int, *, edition: str = "", autres=(), reserve: int = reseau.RESERVE_FOND, isbn_tomes=None):
    """Notice d'un seul tome (requête « <série> tome N »), ou None. Lève reseau.Panne / reseau.Quota."""
    if not cle():
        return None
    titre = next((n for n in noms if n and correspondance.jetons(n)), "")
    for it in _interroger(f"{titre} {edition} tome {int(tome)}".replace("  ", " "), 0, 20, reserve):
        n = notice(it, noms, edition, autres, isbn_tomes)
        if n and n["tome"] == int(tome):
            return n
    return None


def infos_serie(titre: str):
    """{editeur, auteurs, tomes} d'une série d'après Google Books (l'éditeur et l'auteur d'une édition française, le plus grand
    numéro de tome trouvé), ou None si Google n'est pas utilisable. Lève reseau.Panne / reseau.Quota."""
    if not cle() or not titre:
        return None
    rep = reseau.get(URL, params={"q": f"{titre} tome", "langRestrict": "fr", "maxResults": 40, "key": cle()}, reserve=reseau.RESERVE_FOND)
    if rep.statut != 200:
        return None
    tomes, editeur, auteurs = [], "", []
    for it in rep.json().get("items") or []:
        v = it.get("volumeInfo") or {}
        nom = v.get("title") or ""
        if not correspondance.titre_de_la_serie(_MARQUE_TOME.sub("", nom), [titre]):
            continue
        n = tome_du_titre(nom)
        if n is not None:
            tomes.append(n)
        editeur = editeur or v.get("publisher") or ""
        auteurs = auteurs or v.get("authors") or []
    return {"editeur": editeur, "auteurs": ", ".join(auteurs), "tomes": max(tomes) if tomes else None}
