"""
Accès à Internet pour tout ce qui identifie une série : AniList, Wikipédia, MangaDex, MangaUpdates, Google Books, BnF…

Un seul endroit décide comment parler à chaque service, pour que les échecs ne soient plus jamais pris pour « rien trouvé » :
- une réponse exploitable est rendue telle quelle (même « 404, ça n'existe pas ») ;
- tout le reste (réseau coupé, 429, 5xx, quota du jour, réponse illisible, clé refusée…) lève `Panne` : l'appelant sait alors
  que la recherche n'a PAS eu lieu, garde ce qu'il avait et réessaie plus tard (`Panne.reprise` = heure conseillée) ;
- chaque service a son rythme (AniList 90 requêtes/minute, BnF 1 toutes les 5 s…), partagé par tous les fils de l'appli ;
- une pause décidée par un service (quota, « réessaie dans une heure ») est gardée dans data/reseau.json : elle survit
  à un redémarrage, et personne n'insiste pendant ce temps ;
- Google Books : compteur de requêtes du jour (le quota se remet à zéro à minuit, heure du Pacifique) avec une réserve pour
  les demandes faites à la main.
"""
import json
import logging
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger("mouflanga")

AGENT = "MouFlanga/1.0 (https://github.com/mouflo/MouFlanga; bibliotheque de mangas personnelle)"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = AGENT

# Tests automatiques : lancés par « python -m unittest » (le module remplace alors sys.argv[0] par « python -m unittest ») ou avec
# MOUFLANGA_TEST=1. Jamais déduit de la seule présence du module unittest : une bibliothèque qui l'importerait dans l'appli bloquerait
# alors tout Internet.
EN_TEST = os.environ.get("MOUFLANGA_TEST") == "1" or ("unittest" in sys.modules and "unittest" in (sys.argv[0] or ""))
FICHIER_ETAT = None if EN_TEST else Path(__file__).resolve().parent / "data" / "reseau.json"
MEMO_MAX = 120
MEMO_ACTIF = not EN_TEST             # les tests ne se resservent pas les réponses les uns des autres


class Panne(Exception):
    """Le service n'a pas pu répondre : la recherche n'a pas eu lieu. `reprise` : heure (epoch) conseillée pour réessayer."""

    def __init__(self, service, raison, reprise=None):
        super().__init__(f"{service} : {raison}")
        self.service, self.raison, self.reprise = service, raison, reprise


class Quota(Panne):
    """Quota atteint (Google Books : 1 000 requêtes par jour) : inutile de réessayer avant `reprise`."""


class Reponse:
    """Ce que le service a répondu (statut 2xx, ou 404 : « ça n'existe pas »)."""

    def __init__(self, statut, texte, entetes, url, attendu_json, lecteur_json=None):
        self.statut, self.texte, self.entetes, self.url = statut, texte, entetes or {}, url
        self._json, self._lu = None, False
        self._attendu_json, self._lecteur = attendu_json, lecteur_json

    def json(self):
        if not self._lu:
            self._json = self._lecteur() if self._lecteur else json.loads(self.texte)
            self._lu = True
        return self._json


def _maintenant():
    return time.time()


def _prochain_minuit_pacifique(depuis=None):
    """Heure (epoch) où le quota Google se remet à zéro : minuit à Los Angeles."""
    now = datetime.fromtimestamp(depuis or _maintenant(), _fuseau_pacifique())
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _fuseau_pacifique():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Los_Angeles")
    except Exception:
        return timezone(timedelta(hours=-8))


def _jour_pacifique():
    return datetime.fromtimestamp(_maintenant(), _fuseau_pacifique()).strftime("%Y-%m-%d")


class Service:
    def __init__(self, nom, libelle, delai, hotes=(), quota_jour=None, pause_429=60):
        self.nom, self.libelle, self.delai = nom, libelle, delai
        self.hotes, self.quota_jour, self.pause_429 = tuple(hotes), quota_jour, pause_429
        self.verrou = threading.Lock()
        self.prochain = 0.0                    # prochaine heure (horloge monotone) où une requête est permise
        self.pause_jusqua, self.pause_raison = 0.0, ""
        self.jour, self.n_jour = "", 0         # requêtes du jour (quota)
        self.echecs_de_suite = 0
        self.erreurs = deque(maxlen=12)        # (heure, texte) des dernières pannes

    def etat(self):
        pause = self.pause_jusqua if self.pause_jusqua > _maintenant() else 0
        return {"nom": self.nom, "libelle": self.libelle, "pause_jusqua": pause, "pause_raison": self.pause_raison if pause else "",
                "requetes_du_jour": self.n_jour if self.jour == self._jour() else 0, "quota_jour": self.quota_jour,
                "dernieres_pannes": list(self.erreurs)}

    def _jour(self):
        return _jour_pacifique() if self.nom == "google" else time.strftime("%Y-%m-%d")


SERVICES = {s.nom: s for s in (
    Service("anilist", "AniList", 0.8, ["graphql.anilist.co"], pause_429=65),
    Service("wikipedia", "Wikipédia", 0.6, ["en.wikipedia.org", "fr.wikipedia.org"], pause_429=30),
    Service("wikidata", "Wikidata", 1.0, ["www.wikidata.org", "query.wikidata.org"]),
    Service("mangadex", "MangaDex", 0.35, ["api.mangadex.org"], pause_429=30),
    Service("mangaupdates", "MangaUpdates", 1.0, ["api.mangaupdates.com"], pause_429=60),
    Service("google", "Google Books", 0.4, ["www.googleapis.com"], quota_jour=1000, pause_429=3600),
    Service("bnf", "BnF (catalogue)", 5.0, ["catalogue.bnf.fr", "data.bnf.fr"], pause_429=600),
    Service("openlibrary", "Open Library", 1.0, ["openlibrary.org"], pause_429=300),
    Service("kitsu", "Kitsu", 1.0, ["kitsu.io"]),
    Service("jikan", "MyAnimeList (Jikan)", 1.2, ["api.jikan.moe"], pause_429=60),
    Service("web", "Autres sites", 1.0),
    # Trackers de torrents (pages de présentation, voir page_tracker.py) : le rythme de chacun est celui qu'il demande
    Service("prowlarr", "Prowlarr", 0.2),
    Service("c411", "C411 (tracker)", 4.1, pause_429=300),            # 15 requêtes par minute au plus
    Service("tr4ker", "TR4KER (tracker)", 1.0, pause_429=120),
    Service("unit3d", "The Old School (tracker)", 1.0, pause_429=120),
    Service("abn", "ABN (tracker)", 2.1, pause_429=300),
)}
_PAR_HOTE = {h: s for s in SERVICES.values() for h in s.hotes}
RESERVE_FOND = 150            # requêtes Google gardées pour ce que tu demandes à la main (les travaux de fond s'arrêtent avant)

_MEMO = {}
_MEMO_VERROU = threading.Lock()
_ETAT_VERROU = threading.Lock()


def service_de(url):
    return _PAR_HOTE.get(urlparse(url).hostname or "", SERVICES["web"])


# ---------------------------------------------------------------- État gardé (pauses, compteur du jour)

def _charger_etat():
    if not FICHIER_ETAT:
        return
    try:
        d = json.loads(Path(FICHIER_ETAT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for nom, e in (d.get("services") or {}).items():
        s = SERVICES.get(nom)
        if not s or not isinstance(e, dict):
            continue
        if float(e.get("pause_jusqua") or 0) > _maintenant():
            s.pause_jusqua, s.pause_raison = float(e["pause_jusqua"]), str(e.get("pause_raison") or "")
        if e.get("jour") == s._jour():
            s.jour, s.n_jour = e["jour"], int(e.get("n") or 0)


def _garder_etat():
    if not FICHIER_ETAT:
        return
    d = {"services": {s.nom: {"pause_jusqua": s.pause_jusqua if s.pause_jusqua > _maintenant() else 0, "pause_raison": s.pause_raison,
                              "jour": s.jour, "n": s.n_jour} for s in SERVICES.values()}}
    try:
        with _ETAT_VERROU:
            f = Path(FICHIER_ETAT)
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_name(f"{f.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps(d), encoding="utf-8")
            os.replace(tmp, f)
    except OSError:
        pass


def etat():
    """Pour le Journal et l'écran d'identification : où en est chaque service."""
    return [s.etat() for s in SERVICES.values()]


def en_pause(nom):
    """Heure de fin de pause du service (epoch), ou 0 s'il répond normalement."""
    s = SERVICES[nom]
    return s.pause_jusqua if s.pause_jusqua > _maintenant() else 0


def reste_du_jour(nom="google"):
    """Requêtes encore permises aujourd'hui pour un service à quota (None : pas de quota)."""
    s = SERVICES[nom]
    if not s.quota_jour:
        return None
    return max(0, s.quota_jour - (s.n_jour if s.jour == s._jour() else 0))


def poser_pause(nom, jusqua, raison):
    s = SERVICES[nom]
    if jusqua > s.pause_jusqua:
        s.pause_jusqua, s.pause_raison = jusqua, raison
        _garder_etat()


def lever_pause(nom):
    s = SERVICES[nom]
    s.pause_jusqua, s.pause_raison, s.echecs_de_suite = 0.0, "", 0
    _garder_etat()


def oublier_tout():
    """Pour les tests : remet tous les services à neuf."""
    for s in SERVICES.values():
        s.prochain, s.pause_jusqua, s.pause_raison, s.jour, s.n_jour, s.echecs_de_suite = 0.0, 0.0, "", "", 0, 0
        s.erreurs.clear()
    with _MEMO_VERROU:
        _MEMO.clear()


# ---------------------------------------------------------------- Requêtes

def _attendre_son_tour(s):
    """Réserve un créneau (un seul fil à la fois par service) puis dort jusque-là : le rythme est partagé par toute l'appli."""
    if EN_TEST:
        return
    with s.verrou:
        maintenant = time.monotonic()
        creneau = max(maintenant, s.prochain)
        s.prochain = creneau + s.delai
    if creneau > maintenant:
        time.sleep(creneau - maintenant)


def _compter(s):
    jour = s._jour()
    if s.jour != jour:
        s.jour, s.n_jour = jour, 0
    s.n_jour += 1


def _verifier_avant(s, reserve):
    if s.pause_jusqua > _maintenant():
        raise (Quota if "quota" in s.pause_raison.lower() else Panne)(s.libelle, s.pause_raison or "en pause", s.pause_jusqua)
    if s.quota_jour:
        jour = s._jour()
        if s.jour != jour:
            s.jour, s.n_jour = jour, 0
        if s.n_jour >= s.quota_jour - max(0, reserve):
            reprise = _prochain_minuit_pacifique()
            raise Quota(s.libelle, "quota du jour atteint" if not reserve else "quota du jour presque atteint (gardé pour tes demandes)",
                        reprise)


def _noter_panne(s, raison, pause=0.0, quota=False):
    """Retient la panne ; trois échecs d'affilée mettent le service en pause (on ne frappe pas à une porte fermée)."""
    s.echecs_de_suite += 1
    s.erreurs.append((_maintenant(), raison))
    if pause <= 0 and s.echecs_de_suite >= 3:
        pause = 600.0
    if pause > 0:
        poser_pause(s.nom, _maintenant() + pause, ("quota : " if quota else "") + raison)
    reprise = _maintenant() + pause if pause > 0 else None
    return (Quota if quota else Panne)(s.libelle, raison, reprise)


def _delai_d_attente(r, defaut):
    entetes = getattr(r, "headers", None) or getattr(r, "entetes", None) or {}
    try:
        return max(1.0, min(float(entetes.get("Retry-After")), 86400.0))
    except (TypeError, ValueError):
        return defaut


def _quota_du_jour(r):
    """429 de Google : « Queries per day » (jusqu'à minuit, heure du Pacifique) ou « per minute » (une minute)."""
    t = getattr(r, "text", "")
    texte = (t if isinstance(t, str) else "")[:2000].lower()
    return "per day" in texte or "perday" in texte or "daily" in texte


def obtenir(methode, url, *, params=None, json=None, data=None, entetes=None, timeout=15, essais=3, memo=0,
            attendu="json", reserve=0, service=None):
    """Une requête. Rend une `Reponse` (statut 2xx, ou 404) ; lève `Panne` (ou `Quota`) dans tous les autres cas.
    attendu : "json" (une réponse qui n'en est pas un est une panne : page d'erreur, protection anti-robot…), "texte" ou "xml".
    memo : secondes pendant lesquelles une même demande GET est resservie sans retourner sur Internet.
    reserve : requêtes de quota à laisser pour les demandes faites à la main (travaux de fond : RESERVE_FOND)."""
    methode = methode.upper()
    s = SERVICES[service] if service else service_de(url)
    cle = None
    if memo and methode == "GET" and MEMO_ACTIF:
        cle = (url, tuple(sorted((params or {}).items())))
        with _MEMO_VERROU:
            trouve = _MEMO.get(cle)
        if trouve and trouve[0] > time.monotonic():
            return trouve[1]
    derniere = None
    for essai in range(max(1, essais)):
        _verifier_avant(s, reserve)
        _attendre_son_tour(s)
        try:
            appel = SESSION.get if methode == "GET" else SESSION.post
            if EN_TEST and not hasattr(appel, "assert_called"):       # un test oublie de simuler Internet : jamais de vraie requête
                raise Panne(s.libelle, "Internet est interdit pendant les tests (SESSION non simulée)")
            kw = {"timeout": timeout}
            if params is not None:
                kw["params"] = params
            if json is not None:
                kw["json"] = json
            if data is not None:
                kw["data"] = data
            if entetes:
                kw["headers"] = entetes
            r = appel(url, **kw)
        except (requests.Timeout, requests.ConnectionError) as e:
            derniere = f"pas de réponse ({e.__class__.__name__})"
            _compter(s)
            time.sleep(0 if EN_TEST else min(8.0, 1.5 * 2 ** essai))
            continue
        except requests.RequestException as e:
            raise _noter_panne(s, f"requête impossible ({e.__class__.__name__})")
        _compter(s)
        statut = getattr(r, "status_code", 200)
        if not isinstance(statut, int):                        # réponse simulée sans statut : tout va bien
            statut = 200
        texte = getattr(r, "text", None)
        if not isinstance(texte, str):                         # réponse simulée (tests) : pas de texte, seulement un JSON
            texte = ""
        lecteur = getattr(r, "json", None) if callable(getattr(r, "json", None)) else None
        if statut == 429:
            if s.nom == "google" and _quota_du_jour(r):
                pause = max(60.0, _prochain_minuit_pacifique() - _maintenant())
                _garder_etat()
                raise _noter_panne(s, "quota du jour dépassé (se remet à zéro à minuit, heure du Pacifique)", pause, quota=True)
            attente = _delai_d_attente(r, 65.0 if s.nom == "google" else s.pause_429)
            if attente <= 15 and essai + 1 < essais:          # une courte pause demandée : on patiente puis on réessaie
                time.sleep(0 if EN_TEST else attente)
                derniere = "trop de demandes"
                continue
            raise _noter_panne(s, "trop de demandes, il demande de patienter", attente, quota=(s.nom == "google"))
        if statut >= 500:
            derniere = f"HTTP {statut}"
            time.sleep(0 if EN_TEST else min(8.0, 1.5 * 2 ** essai))
            continue
        if statut in (401, 403):
            raise _noter_panne(s, f"accès refusé (HTTP {statut})", 3600.0)
        if statut == 400:
            logger.warning("Réseau : %s a refusé la demande (HTTP 400) : %s", s.libelle, texte[:200])
            raise _noter_panne(s, "demande refusée (HTTP 400)", 3600.0)
        if statut == 404:
            s.echecs_de_suite = 0
            return Reponse(404, texte, getattr(r, "headers", None), url, attendu == "json", lecteur)
        if statut >= 300 or statut < 200:
            raise _noter_panne(s, f"réponse inattendue (HTTP {statut})", 600.0)
        rep = Reponse(statut, texte, getattr(r, "headers", None), url, attendu == "json", lecteur if attendu == "json" else None)
        if attendu == "json":
            try:
                rep.json()
            except ValueError:
                derniere = "réponse illisible (ce n'est pas du JSON)"
                time.sleep(0 if EN_TEST else min(8.0, 1.5 * 2 ** essai))
                continue
            erreur = _erreur_dans_json(s, rep)
            if erreur:
                attente, raison = erreur
                if attente <= 15 and essai + 1 < essais:
                    time.sleep(0 if EN_TEST else attente)
                    derniere = raison
                    continue
                raise _noter_panne(s, raison, max(attente, 30.0))
        s.echecs_de_suite = 0
        if cle and MEMO_ACTIF:
            with _MEMO_VERROU:
                if len(_MEMO) > MEMO_MAX:
                    _MEMO.clear()
                _MEMO[cle] = (time.monotonic() + memo, rep)
        return rep
    raise _noter_panne(s, derniere or "pas de réponse")


def _erreur_dans_json(s, rep):
    """Réponse 200 qui est en fait un refus : Wikipédia « maxlag » / « ratelimited », AniList sans données.
    (attente en secondes, raison) ou None. Les autres « error » (page introuvable…) sont rendues à l'appelant."""
    j = rep.json()
    if not isinstance(j, dict):
        return None
    if s.nom in ("wikipedia", "wikidata") and isinstance(j.get("error"), dict):
        code = str(j["error"].get("code") or "")
        if code in ("maxlag", "ratelimited", "readonly", "internal_api_error_DBConnectionError") or code.startswith("internal_api_error"):
            return _delai_d_attente(rep, 10.0), f"Wikipédia demande de patienter ({code})"
    if s.nom == "anilist" and j.get("data") is None and j.get("errors"):
        statut = (j["errors"][0] or {}).get("status")
        if statut == 404:
            return None                                   # « Not Found » : aucune fiche, pas une panne
        return 30.0, "AniList a répondu par une erreur : " + str((j["errors"][0] or {}).get("message"))[:80]
    return None


def get(url, **kw):
    return obtenir("GET", url, **kw)


def post(url, **kw):
    return obtenir("POST", url, **kw)


def anilist(requete, variables=None, **kw):
    """Requête GraphQL à AniList : le contenu de « data », ou None si la fiche n'existe pas (404). Panne sinon."""
    rep = post("https://graphql.anilist.co", json={"query": requete, "variables": variables or {}}, **kw)
    if rep.statut == 404:
        return None
    return rep.json().get("data")


_charger_etat()
