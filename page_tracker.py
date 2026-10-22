"""
Page d'un torrent sur son tracker : lire sa présentation et son NFO tout seul.

Les propositions de torrents (suivi.py) et les résultats de recherche donnent l'adresse de la page du torrent sur son tracker. Les
trackers privés demandent une connexion pour l'afficher, mais ils ont presque tous une API prévue pour leurs membres, qui s'ouvre avec la
clé que Prowlarr possède déjà pour y chercher : C411 (/api/torrents/<empreinte>), TR4KER (/api/torrents/<nom>), The Old School et les
autres sites UNIT3D (/api/torrents/<numéro>), ABN (/api/Release/<numéro>). C'est l'accès normal d'un membre : aucune connexion
simulée, aucune protection contournée, une requête par page lue, au rythme que chaque tracker demande (reseau.py).

Règles de sécurité :
- Seules les adresses d'un tracker de Prowlarr sont lues (même nom de site) : MouFlanga ne va jamais chercher une page ailleurs.
- La clé d'un tracker est lue dans Prowlarr quand il le faut, gardée dix minutes en mémoire, et n'est ni écrite, ni journalisée, ni
  envoyée au navigateur. Seuls les champs utiles de la réponse sont gardés (jamais un lien de téléchargement : il contient une clé).
- Le texte d'une présentation vient d'un inconnu : il est converti en texte simple (presentation.py), jamais affiché comme du HTML.
- Une panne du tracker n'est pas « page vide » : `PageIllisible` dit pourquoi, et rien n'est gardé.
"""
import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import presentation
import reseau

logger = logging.getLogger("mouflanga")

FICHIER = Path("torrent-pages.json")          # réglé par app.py (data/torrent-pages.json)
DUREE = 7 * 86400                              # une page lue est gardée une semaine
GARDER = 300                                   # nombre de pages gardées
MAX_PRESENTATION, MAX_NFO, MAX_FICHIERS = 6000, 20000, 80
TTL_INDEXEURS = 600

_VERROU = threading.Lock()                     # fichier de pages et liste des trackers
_INDEXEURS = {"quand": 0.0, "liste": []}
_EN_LECTURE = {}                               # adresse → verrou : deux demandes pour la même page n'interrogent le tracker qu'une fois


class PageIllisible(Exception):
    """La page n'a pas pu être lue. `message` : une phrase française pour l'écran ; `definitif` : inutile de réessayer (pas d'accès prévu
    pour ce tracker, torrent supprimé) ; `reprise` : heure (epoch) conseillée pour réessayer."""

    def __init__(self, message, definitif=False, reprise=None):
        super().__init__(message)
        self.message, self.definitif, self.reprise = message, definitif, reprise


# ---------------------------------------------------------------- Les trackers de Prowlarr

def _prowlarr():
    import torrents
    r = torrents.reglages()
    return r["prowlarr"], r["prowlarr_cle"]


def _champs(indexeur: dict) -> dict:
    return {c.get("name"): c.get("value") for c in indexeur.get("fields") or [] if isinstance(c, dict)}


def indexeurs(force: bool = False) -> list:
    """Trackers actifs de Prowlarr : [{nom, definition, hote, base, api, cle}] (dix minutes en mémoire). Les clés ne sortent pas de ce
    module. Lève PageIllisible si Prowlarr n'est pas réglé ou ne répond pas."""
    with _VERROU:
        if not force and _INDEXEURS["liste"] and time.monotonic() - _INDEXEURS["quand"] < TTL_INDEXEURS:
            return _INDEXEURS["liste"]
    url, cle = _prowlarr()
    if not url or not cle:
        raise PageIllisible("Prowlarr n'est pas réglé (⚙️ Réglages → Connexions).", definitif=True)
    try:
        rep = reseau.get(url + "/api/v1/indexer", entetes={"X-Api-Key": cle}, service="prowlarr", timeout=20)
    except reseau.Panne as e:
        raise PageIllisible(f"Prowlarr n'a pas répondu ({e.raison}).", reprise=e.reprise)
    liste = []
    for i in rep.json() if isinstance(rep.json(), list) else []:
        if not i.get("enable"):
            continue
        champs = _champs(i)
        base = str(champs.get("baseUrl") or (i.get("indexerUrls") or [""])[0] or "")
        hote = (urlparse(base).hostname or "").lower()
        if not hote:
            continue
        liste.append({"nom": i.get("name") or hote, "definition": str(i.get("definitionName") or champs.get("definitionFile") or ""),
                      "hote": hote, "base": f"https://{hote}", "api": str(champs.get("apiurl") or ""),
                      "cle": str(champs.get("apikey") or champs.get("apiKey") or "")})
    with _VERROU:
        _INDEXEURS.update(quand=time.monotonic(), liste=liste)
    return liste


def oublier_indexeurs():
    with _VERROU:
        _INDEXEURS.update(quand=0.0, liste=[])


def adresse_propre(page) -> tuple:
    """(adresse sans fragment, hôte) d'une page de tracker, ou PageIllisible : en https, sans identifiant ni port."""
    page = str(page or "").strip()
    u = urlparse(page)
    if len(page) > 600 or u.scheme != "https" or not u.hostname or u.username or u.password or u.port not in (None, 443):
        raise PageIllisible("Adresse de page non valide.", definitif=True)
    return u._replace(fragment="").geturl(), u.hostname.lower()


def tracker_de(hote: str) -> dict:
    for ind in indexeurs():
        if hote == ind["hote"] or hote.endswith("." + ind["hote"]):
            return ind
    raise PageIllisible("Cette adresse n'est pas celle d'un tracker de Prowlarr : MouFlanga ne la lit pas.", definitif=True)


def _appeler(ind: dict, service: str, url: str, **kw):
    """Une requête au tracker. 404 : le torrent n'existe plus (PageIllisible définitive) ; panne : PageIllisible avec l'heure de reprise."""
    try:
        rep = reseau.get(url, service=service, **kw)
    except reseau.Panne as e:
        if "accès refusé" in e.raison:
            raise PageIllisible(f"{ind['nom']} refuse la clé que Prowlarr lui donne : vérifie-la dans Prowlarr (Indexeurs → {ind['nom']}).",
                                reprise=e.reprise)
        raise PageIllisible(f"{ind['nom']} n'a pas répondu ({e.raison}).", reprise=e.reprise)
    if rep.statut == 404:
        raise PageIllisible(f"{ind['nom']} ne connaît plus ce torrent (supprimé ?).", definitif=True)
    return rep


def _entetes_jeton(ind: dict) -> dict:
    return {"Authorization": "Bearer " + ind["cle"], "Accept": "application/json"}


def _exiger_cle(ind: dict):
    if not ind["cle"]:
        raise PageIllisible(f"Prowlarr n'a pas de clé API pour {ind['nom']} : MouFlanga ne peut pas lire ses pages.", definitif=True)


def _fichiers(liste, nom_de, taille_de) -> list:
    out = []
    for f in (liste or [])[:MAX_FICHIERS]:
        if isinstance(f, dict):
            out.append({"nom": str(nom_de(f) or "")[:200], "taille": int(taille_de(f) or 0)})
    return out


# ---------------------------------------------------------------- Un lecteur par famille de trackers
# Chacun rend {titre, presentation (texte), nfo (texte), fichiers, taille, sources, date, equipe} et RIEN d'autre : ni lien de téléchargement
# (il contient la clé), ni identifiant, ni champ inconnu.

def _lire_c411(ind: dict, chemin: str, requete: dict) -> dict:
    m = re.fullmatch(r"/torrents/([0-9a-fA-F]{40})", chemin)
    if not m:
        raise PageIllisible("Adresse de page C411 non reconnue.", definitif=True)
    j = _appeler(ind, "c411", f"{ind['base']}/api/torrents/{m.group(1).lower()}", entetes=_entetes_jeton(ind)).json()
    meta = j.get("metadata") or {}
    return {"titre": j.get("name"), "presentation": presentation.en_texte(j.get("description"), j.get("descriptionFormat")),
            "nfo": meta.get("nfoContent") or "",
            "fichiers": _fichiers(j.get("files"), lambda f: "/".join(f.get("path") or []), lambda f: f.get("length")),
            "taille": j.get("size"), "sources": j.get("seeders"), "date": str(j.get("createdAt") or "")[:10], "equipe": j.get("uploader")}


def _lire_unit3d(ind: dict, chemin: str, requete: dict) -> dict:
    m = re.fullmatch(r"/torrents/(\d{1,10})", chemin)
    if not m:
        raise PageIllisible(f"Adresse de page {ind['nom']} non reconnue.", definitif=True)
    a = (_appeler(ind, "unit3d", f"{ind['base']}/api/torrents/{m.group(1)}", entetes=_entetes_jeton(ind)).json().get("attributes") or {})
    return {"titre": a.get("name"), "presentation": presentation.en_texte(a.get("description")), "nfo": "",
            "fichiers": _fichiers(a.get("files"), lambda f: f.get("name"), lambda f: f.get("size")),
            "taille": a.get("size"), "sources": a.get("seeders"), "date": str(a.get("created_at") or "")[:10],
            "equipe": a.get("uploader") if a.get("uploader") not in (None, "Anonymous") else ""}


def _lire_tr4ker(ind: dict, chemin: str, requete: dict) -> dict:
    m = re.fullmatch(r"/torrent/([A-Za-z0-9_.\-]{3,200})", chemin)
    if not m:
        raise PageIllisible("Adresse de page TR4KER non reconnue.", definitif=True)
    # TR4KER attend sa clé dans l'adresse (comme pour son flux de recherche) ; l'adresse complète n'est jamais journalisée
    j = _appeler(ind, "tr4ker", f"{ind['base']}/api/torrents/{quote(m.group(1), safe='')}", params={"apikey": ind["cle"]},
                 entetes={"Accept": "application/json"}).json()
    corps = presentation.en_texte(j.get("classic_description"), j.get("classic_description_format"))
    plus = presentation.en_texte(j.get("extra_info") or j.get("description"), j.get("extra_info_format"))
    return {"titre": j.get("name"), "presentation": "\n\n".join(x for x in (corps, plus) if x), "nfo": j.get("nfo") or "",
            "fichiers": [], "taille": j.get("size_bytes"), "sources": j.get("seeders"), "date": str(j.get("created_at") or "")[:10],
            "equipe": j.get("uploader")}


def _lire_abn(ind: dict, chemin: str, requete: dict) -> dict:
    rid = (requete.get("ReleaseId") or [""])[0]
    if not rid.isdigit() or len(rid) > 10:
        raise PageIllisible("Adresse de page ABN non reconnue.", definitif=True)
    api = ind["api"].lower().strip("/")
    if not re.fullmatch(r"[a-z0-9.\-]+", api) or not (api == ind["hote"] or api.endswith("." + ind["hote"])):
        api = "api." + ind["hote"]                             # l'API d'ABN est « api.<site> » ; un autre nom n'est pas suivi
    j = _appeler(ind, "abn", f"https://{api}/api/Release/{rid}", entetes=_entetes_jeton(ind)).json()
    return {"titre": j.get("name"), "presentation": "", "nfo": str(j.get("infos") or ""), "fichiers": [], "taille": j.get("size"),
            "sources": j.get("seeders"), "date": str(j.get("created") or "")[:10], "equipe": ""}


# définition Prowlarr du tracker → (lecteur, service de reseau.py)
LECTEURS = {"c411": _lire_c411, "tr4ker": _lire_tr4ker, "theoldschool-api": _lire_unit3d, "abnormal-api": _lire_abn}


# ---------------------------------------------------------------- La page lue

def fusion(*analyses) -> dict:
    """Réunit plusieurs analyses de texte (presentation.analyser) : la première l'emporte, une clé manquante est prise dans la suivante ;
    les ISBN des tomes s'additionnent."""
    out = {}
    for a in analyses:
        for cle, v in (a or {}).items():
            if cle == "isbn":
                out.setdefault("isbn", {})
                for t, c in v.items():
                    out["isbn"].setdefault(t, c)
            elif cle not in out:
                out[cle] = v
    return out


def tomes_du_titre(titre: str) -> list:
    import suivi
    return sorted(suivi.tomes_du_titre(titre or ""))


def _normaliser(brut: dict, url: str, ind: dict) -> dict:
    texte = (brut.get("presentation") or "")[:MAX_PRESENTATION]
    nfo = presentation.en_texte(brut.get("nfo"), "texte")[:MAX_NFO] if brut.get("nfo") else ""
    infos = fusion(presentation.analyser(texte), presentation.analyser(nfo))
    titre = str(brut.get("titre") or "")[:250]
    tomes = tomes_du_titre(titre)
    if infos.get("isbn_unique") and not infos.get("isbn") and len(tomes) == 1:      # un seul tome, un seul ISBN : c'est le sien
        infos["isbn"] = {str(tomes[0]): infos.pop("isbn_unique")}
    if infos.get("synopsis_langue") == "en":                   # un résumé anglais ne remplace pas un synopsis : on le garde de côté
        infos["synopsis_en"] = infos.pop("synopsis")
    infos.pop("synopsis_langue", None)
    return {"url": url, "hote": ind["hote"], "tracker": ind["nom"], "titre": titre, "tomes": tomes, "presentation": texte, "nfo": nfo,
            "fichiers": brut.get("fichiers") or [], "taille": int(brut.get("taille") or 0), "sources": int(brut.get("sources") or 0),
            "date": brut.get("date") or "", "equipe": str(brut.get("equipe") or "")[:60], "infos": infos,
            "lu_le": datetime.now().strftime("%Y-%m-%d %H:%M")}


def _lire_cache() -> dict:
    try:
        d = json.loads(Path(FICHIER).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _ecrire_cache(d: dict):
    if len(d) > GARDER:
        recents = sorted(d.items(), key=lambda kv: kv[1].get("lu", 0), reverse=True)[:GARDER]
        d.clear()
        d.update(dict(recents))
    f = Path(FICHIER)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f"{f.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)


def en_memoire(page) -> dict:
    """Page déjà lue (gardée une semaine), sans interroger le tracker ; None sinon."""
    try:
        url, _ = adresse_propre(page)
    except PageIllisible:
        return None
    with _VERROU:
        e = _lire_cache().get(url)
    return e["page"] if e and time.time() - e.get("lu", 0) < DUREE else None


def lisible(page) -> bool:
    """Cette page peut-elle être lue (tracker de Prowlarr dont on sait lire les pages, avec sa clé) ? N'interroge aucun tracker."""
    try:
        url, hote = adresse_propre(page)
        ind = tracker_de(hote)
    except PageIllisible:
        return False
    return ind["definition"] in LECTEURS and bool(ind["cle"])


def lire(page, force: bool = False) -> dict:
    """La page d'un torrent sur son tracker, lue par l'API du tracker (voir plus haut), gardée une semaine. Lève PageIllisible avec un
    message français quand ce n'est pas possible (tracker sans API connue, clé refusée, tracker en panne, torrent supprimé)."""
    url, hote = adresse_propre(page)
    if not force:
        deja = en_memoire(url)
        if deja:
            return deja
    with _VERROU:
        verrou = _EN_LECTURE.setdefault(url, threading.Lock())
    with verrou:
        if not force:
            deja = en_memoire(url)                             # lue pendant qu'on attendait son tour
            if deja:
                return deja
        ind = tracker_de(hote)
        lecteur = LECTEURS.get(ind["definition"])
        if not lecteur:
            raise PageIllisible(f"MouFlanga ne sait pas lire les pages de {ind['nom']} : ouvre le lien dans ton navigateur.", definitif=True)
        _exiger_cle(ind)
        u = urlparse(url)
        brut = lecteur(ind, u.path.rstrip("/"), parse_qs(u.query))
        resultat = _normaliser(brut, url, ind)
        with _VERROU:
            d = _lire_cache()
            d[url] = {"lu": time.time(), "page": resultat}
            _ecrire_cache(d)
        logger.info("Page de tracker lue : %s (%s)", ind["nom"], resultat["titre"][:80])
        return resultat
