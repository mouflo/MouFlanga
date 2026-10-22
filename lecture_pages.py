"""
Lecture automatique des pages de tracker des propositions de torrents (suivi.py).

Chaque nouvelle proposition a sa page lue (page_tracker.py : présentation et NFO) : la ligne de la proposition dit tout de suite l'éditeur,
le nombre de pages et la résolution, et la fiche de la série suivie reçoit ce qui lui manque (synopsis, auteur, éditeur, genre, parution).

- Un seul fil à la fois : chaque tracker fixe son rythme (reseau.py) et on ne le dépasse pas.
- Rien n'est jamais remplacé : seule une information absente de la fiche est ajoutée, et seulement si la page est bien celle de la série
  (le nom du torrent doit être celui de la série, pas « One Piece Party » pour « One Piece »).
- Un échec n'est pas une page vide : il est gardé avec l'heure sur la proposition (`lu.erreur`), puis réessayé plus tard quand le tracker
  était seulement en panne (jamais quand il n'a pas d'accès prévu pour ça).
"""
import logging
import re
import threading
import time

import correspondance
import page_tracker
import suivi

logger = logging.getLogger("mouflanga")

NOMS = lambda nom: []              # réglé par app.py : les autres noms connus d'une série (AniList, synonymes)
MAX_PAR_PASSE = 5                  # pages lues après une recherche de nouveautés
PAR_SERIE_AU_DEMARRAGE = 2         # rattrapage des propositions déjà gardées
ATTENTE_ECHEC = 6 * 3600           # un échec provisoire n'est pas retenté avant 6 h

_FIL = threading.Lock()

# Ce qui, dans le nom d'un torrent, vient après le nom de la série : tome, pack, intégrale, saison, année, langue, format, qualité
_APRES_LE_NOM = re.compile(r"(?i)(?:^|[\s\-])(?:t\.?\s?\d{1,3}\b|tomes?\b|vol(?:ume)?s?\b|pack\b|int[ée]grale|complet|complete|s\d{1,2}(?:e\d+)?\b|"
                           r"(?:19|20)\d\d\b|french|truefrench|vf\b|fr\b|multi\b|vostfr|cbz|cbr|pdf|epub|ebook|digital|scan\b)")


def nom_dans_titre(titre: str) -> str:
    """Le nom de la série dans le nom d'un torrent : « Wind.Breaker.T07.Nii.Satoru.FR.[CBZ]-Dogbanov » → « Wind Breaker »."""
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", str(titre or ""))
    t = re.sub(r"[._]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    m = _APRES_LE_NOM.search(t)
    return (t[:m.start()] if m else t).strip(" -–:,")


def avec_sous_titres(noms) -> list:
    """Les noms connus, plus le titre français caché dans un nom « Série - Titre français » : AniList donne « Rooster Fighter - Coq de
    Baston », et les torrents français s'appellent « Coq de Baston ». Le morceau n'est ajouté que si ce qui le précède est déjà un nom de
    la série (« Kenichi - Le disciple ultime » donne « Le disciple ultime » ; « Bleach - Part 2 » n'ajoute rien : le morceau n'a pas deux mots distinctifs)."""
    noms = [n for n in noms if n]
    out = list(noms)
    for n in noms:
        morceaux = re.split(r"\s+[-–—:]\s+", n, maxsplit=1)
        distinctifs = [m for m in correspondance.jetons(morceaux[1]) if m not in correspondance.MOTS_VIDES and not m.isdigit() and len(m) >= 3] \
            if len(morceaux) == 2 else []
        if len(distinctifs) >= 2 and any(correspondance.titre_de_la_serie(morceaux[0], [x]) for x in noms if x != n):
            out.append(morceaux[1])
    return out


def est_la_serie(noms, titre_torrent: str) -> bool:
    """Le torrent est-il bien un torrent de cette série, d'après son nom ?"""
    extrait = nom_dans_titre(titre_torrent)
    return bool(extrait) and correspondance.titre_de_la_serie(extrait, avec_sous_titres(noms))


def resume_lecture(page: dict) -> dict:
    """Ce qu'on garde sur la proposition pour afficher sa ligne : l'essentiel de la page, pas la page."""
    i = page.get("infos") or {}
    isbn = next(iter((i.get("isbn") or {}).values()), "") or i.get("isbn_unique", "")
    brut = {"tracker": page.get("tracker"), "hote": page.get("hote"), "editeur": i.get("editeur"), "auteur": i.get("auteur"),
            "pages": i.get("pages"), "resolution": i.get("resolution"), "format": i.get("format"), "qualite": i.get("qualite"),
            "date": i.get("date"), "isbn": isbn, "synopsis": bool(i.get("synopsis")), "lu_le": page.get("lu_le")}
    return {k: v for k, v in brut.items() if v not in (None, "", False)}


def a_lire(p: dict) -> bool:
    """Faut-il lire la page de cette proposition ? Pas si elle l'a été, ni si la lecture est impossible pour de bon, ni juste après un échec."""
    if not p.get("page") or p.get("statut") != "attente":
        return False
    lu = p.get("lu")
    if not lu:
        return True
    if "erreur" not in lu or lu.get("definitif"):
        return False
    return time.time() >= max(float(lu.get("reprise") or 0), float(lu.get("essai") or 0) + ATTENTE_ECHEC)


def _message(nom: str, page: dict, serie_ok, ajoutes: list) -> str:
    base = f"Page lue sur {page['tracker']}"
    if serie_ok is False:
        return f"{base}, mais elle ne semble pas parler de « {nom} » : rien n'est ajouté à sa fiche."
    if ajoutes:
        noms = {"synopsis": "synopsis", "auteur": "auteur", "editeur": "éditeur", "genre": "genre", "date": "parution"}
        return f"{base} : ajouté à la fiche de « {nom} » → " + ", ".join(noms[c] for c in ajoutes) + "."
    if serie_ok:
        return f"{base} : la fiche de « {nom} » a déjà tout ce que la page apporte."
    return base + "."


def lire_page(nom: str, page: str, titre: str = "", pid: str = None, force: bool = False) -> dict:
    """Lit la page d'un torrent et, si `nom` est une série suivie, la complète avec ce qu'elle dit. Rend
    {ok, page, serie_ok, applique, message} ou {ok: False, error, definitif}. `pid` : la proposition à qui noter ce qui a été lu."""
    try:
        lue = page_tracker.lire(page, force=force)
    except page_tracker.PageIllisible as e:
        if pid:
            suivi.noter_lecture(nom, pid, {"erreur": e.message, "definitif": e.definitif, "essai": time.time(), "reprise": e.reprise or 0})
        return {"ok": False, "error": e.message, "definitif": e.definitif}
    serie_ok, ajoutes = None, []
    x = suivi.lire()["series"].get(nom) if nom else None
    if x is not None:
        serie_ok = est_la_serie([nom, *x.get("titres", []), *NOMS(nom)], titre or lue["titre"])
        if serie_ok:
            ajoutes = suivi.noter_tracker(nom, lue["infos"], lue["url"], lue["tracker"])
    if pid:
        suivi.noter_lecture(nom, pid, resume_lecture(lue))
    return {"ok": True, "page": lue, "serie_ok": serie_ok, "applique": ajoutes, "message": _message(nom, lue, serie_ok, ajoutes)}


def lire_proposition(nom: str, pid: str, force: bool = False) -> dict:
    p = suivi.proposition(nom, pid)
    if not p or not p.get("page"):
        return {"ok": False, "error": "Proposition introuvable.", "definitif": True}
    return lire_page(nom, p["page"], p.get("titre", ""), pid, force)


def _travail(nom: str, ids: list):
    with _FIL:                                     # une série après l'autre : les trackers fixent le rythme
        for pid in ids:
            p = suivi.proposition(nom, pid)
            if not p or not a_lire(p):
                continue
            try:
                lire_page(nom, p["page"], p.get("titre", ""), pid)
            except Exception as e:                 # une page qui pose problème n'arrête pas les suivantes
                logger.warning("Lecture de la page d'une proposition de %s : %s", nom, e.__class__.__name__)


def lire_en_fond(nom: str, propositions: list, maximum: int = MAX_PAR_PASSE):
    """Lit en arrière-plan la page des propositions données (cinq au plus). Ne bloque jamais l'appelant."""
    ids = [p["id"] for p in propositions if a_lire(p)][:maximum]
    if ids:
        threading.Thread(target=_travail, args=(nom, ids), daemon=True, name="pages-trackers").start()


def rattrapage(par_serie: int = PAR_SERIE_AU_DEMARRAGE):
    """Propositions déjà gardées dont la page n'a jamais été lue : deux par série au plus, les plus récentes d'abord, seulement celles
    d'un tracker dont on sait lire les pages. Rend le nombre de pages demandées."""
    total = 0
    for nom, x in list(suivi.lire()["series"].items()):
        choisies = []
        for p in reversed(x.get("propositions", [])):
            if len(choisies) >= par_serie:
                break
            try:
                if a_lire(p) and page_tracker.lisible(p["page"]):
                    choisies.append(p)
            except Exception:
                continue
        if choisies:
            lire_en_fond(nom, choisies, par_serie)
            total += len(choisies)
    return total
