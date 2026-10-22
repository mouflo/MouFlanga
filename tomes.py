"""
Ce qu'Internet sait d'une série : statut et résumé (AniList, MangaDex, Wikipédia), répartition des chapitres en tomes (Wikipédia en
anglais, liste française de Wikipédia, MangaDex), titres et chapitres des tomes (Wikipédia en français), fiche (auteurs, éditeurs…).

Tout est gardé dans data/tomes/<série>.json ; les écritures passent par `modifier` ; tout ce qui sort sur Internet passe par
reseau.py. Les règles (trouvé / rien trouvé / panne, rien n'est jamais effacé) et le parcours complet : docs/identification.md et
identification.py. Les ISBN et résumés des tomes : notices.py (Wikipédia, BnF, Google Books).
"""
import json
import logging
import os
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path

import requests

import bnf
import correspondance
import googlebooks
import reseau
import wikifr

logger = logging.getLogger(__name__)
DOSSIER = Path(__file__).resolve().parent / "data" / "tomes"
if reseau.EN_TEST:                              # tests automatiques : jamais les vrais caches de la bibliothèque (un test avait vidé celui d'une vraie série)
    import atexit
    import shutil
    import tempfile
    DOSSIER = Path(tempfile.mkdtemp(prefix="mouflanga-tests-tomes-"))
    atexit.register(shutil.rmtree, DOSSIER, ignore_errors=True)
DUREE = 7 * 86400                      # série en cours : répartition en tomes revue au plus une fois par semaine
TERMINES = ("FINISHED", "CANCELLED")   # statuts qui ne bougent plus : ce qui est trouvé est gardé pour toujours
ESSAIS_JOURS = (1, 3, 7, 30)           # réessais d'une recherche sans résultat : de plus en plus espacés


def serie_terminee(garde) -> bool:
    st = (garde or {}).get("statut_officiel") or {}
    return st.get("statut") in TERMINES


def attente_essai(essais) -> int:
    """Secondes à attendre avant de réessayer une recherche restée sans résultat (« essais » échecs déjà faits)."""
    return ESSAIS_JOURS[min(max(int(essais or 0), 0), len(ESSAIS_JOURS) - 1)] * 86400


def garde_a_jour(entree, garde, duree_en_cours, trouve=True) -> bool:
    """Une information gardée est-elle encore bonne ? Trouvée : pour toujours si la série est terminée, sinon « duree_en_cours ».
    Sans résultat : réessai espacé selon le nombre d'échecs déjà faits (champ « essais »)."""
    if not entree:
        return False
    age = time.time() - (entree.get("date") or 0)
    if not trouve:
        return age < attente_essai(entree.get("essais"))
    return serie_terminee(garde) or age < duree_en_cours
_SESSION = reseau.SESSION             # une seule session pour tout Internet (voir reseau.py : rythme, pauses, pannes)
WIKI = "https://en.wikipedia.org/w/api.php"
WIKI_FR = "https://fr.wikipedia.org/w/api.php"
VERSION_TITRES = 3          # monte quand la lecture des pages Wikipédia change : les séries déjà gardées sont relues


def _simple(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", (texte or "").translate(correspondance._TRANSLITTERATION)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", texte).strip()


SERIES_EXISTANTES = lambda: ()               # noms des séries de la bibliothèque (rempli par app.py)


# Mentions d'édition : « Gantz : Perfect », « Gantz - Perfect Édition », « Cat's Eye Édition de luxe » (pas une suite)
import noms_editions

EDITION = noms_editions.FIN
_MENTION = noms_editions.MENTION


def mention_edition(texte: str) -> str:
    """« Gantz - Perfect Édition (01-18) … » → « Perfect Édition » (première mention d'édition du nom), sinon ""."""
    m = _MENTION.search(texte or "")
    return " ".join(w[:1].upper() + w[1:] for w in m.group(0).split()) if m else ""


def sans_edition(titre: str) -> str:
    """« Gantz : Perfect Édition » → « Gantz » ; un titre sans mention d'édition reste tel quel."""
    t = EDITION.sub("", titre or "").strip(" -–:,")
    return t if t and t != (titre or "").strip() else (titre or "").strip()


def _noms_series(titre: str):
    """(noms du dossier, morceaux du nom) : « Gantz : Perfect » → (« Gantz : Perfect », « Gantz »), []. Un nom « Série : Suite » a
    en plus ses morceaux (« Frieren », « Sousou no Frieren ») : noms faibles, sauf celui qui est une autre série de la
    bibliothèque (« Kuroko's Basket » dans « Kurokos Basket : Extra Game » : la série mère n'est pas la suite)."""
    out = [titre.strip()]
    base = sans_edition(titre)
    if base != titre.strip():                   # « Gantz : Perfect » : on cherche « Gantz » (même si une autre édition est là)
        out.append(base)
    v = re.sub(r"\s*n[°º]\s*", " No. ", titre, flags=re.I).strip()
    if v not in out:
        out.append(re.sub(r"\s+", " ", v))
    parties = []
    if " : " in titre:                          # « Frieren : Sousou no Frieren » → chaque partie (la plus longue d'abord)
        autres = [correspondance.jetons(x) for x in SERIES_EXISTANTES() if x != titre]
        for part in sorted((x.strip() for x in titre.split(" : ")), key=len, reverse=True):
            if EDITION.sub("", part).strip(" -–:,") == "":       # « Perfect » seul : une édition, pas un titre à chercher
                continue
            if part and part not in out and not any(correspondance._meme_mots(correspondance.jetons(part), a) for a in autres) \
                    and (len(part.split()) >= 2 or len(part) >= 6):   # « Frieren » oui, « Zero » tout seul non
                parties.append(part)
    return out, parties


def _parties_meres(titre: str) -> list[str]:
    """Morceaux d'un nom « Série : Suite » qui peuvent être la série mère (« Akame ga Kill ! » pour « Akame ga Kill ! : Zero »), même
    quand la bibliothèque a aussi la série mère : sa page Wikipédia contient souvent la section de la suite."""
    if " : " not in titre:
        return []
    return [p.strip() for p in titre.split(" : ")[:1] if EDITION.sub("", p).strip(" -–:,") and (len(p.split()) >= 2 or len(p.strip()) >= 6)]


def _variantes(titre: str) -> list[str]:
    """Le nom tel quel, puis quelques écritures courantes (« N°8 » → « No. 8 »), puis sans la mention d'édition, puis ses morceaux."""
    noms, parties = _noms_series(titre)
    return noms + parties


def noms_de_recherche(serie: str, st: dict = None):
    """(noms sûrs, noms faibles, autres séries de la bibliothèque) pour reconnaître la série sur Internet. Sûrs : le nom du dossier et
    ce qu'AniList en dit (titre, titre anglais, synonymes : le titre français y est souvent). Faibles : les morceaux d'un nom
    « Série : Suite », qui ne comptent que si le titre est exactement l'un d'eux."""
    st = st if st is not None else ((_charger(serie) or {}).get("statut_officiel") or {})
    noms, parties = _noms_series(serie)
    fortes = list(dict.fromkeys(n for n in noms + [st.get("titre"), st.get("titre_en"), *(st.get("synonymes") or [])]
                                if n and correspondance.jetons(n)))
    return fortes, parties, [x for x in SERIES_EXISTANTES() if x != serie]


def _noms_anglais(titre: str) -> list[str]:
    """Noms anglais / romaji de la série d'après AniList. Lève reseau.Panne si AniList ne répond pas."""
    q = "query($s:String){Page(perPage:3){media(search:$s,type:MANGA,format_not:NOVEL){title{romaji english} synonyms}}}"
    noms = []
    for v in _variantes(titre):
        medias = ((reseau.anilist(q, {"s": v}) or {}).get("Page") or {}).get("media") or []
        if medias:
            t = medias[0]["title"]
            for n in (t.get("english"), t.get("romaji")):
                if n and n not in noms:
                    noms.append(n)
            break
    return noms


# ---------------------------------------------------------------- Wikipédia

TropDeRequetes = reseau.Panne            # ancien nom


def _wiki(params: dict) -> dict:
    """Une requête à Wikipédia en anglais. Lève reseau.Panne si elle ne répond pas (jamais un résultat vide à la place)."""
    return reseau.get(WIKI, params={**params, "format": "json", "formatversion": 2, "maxlag": 5}, memo=600).json()


def _wiki_fr(params: dict) -> dict:
    """Une requête à Wikipédia en français. Lève reseau.Panne si elle ne répond pas ; une page qui n'existe pas rend le JSON
    avec sa clé « error » (l'appelant lit « parse » ou « query » : vide)."""
    return reseau.get(WIKI_FR, params={**params, "format": "json"}, memo=600).json()


def _wikitexte(page: str, fr: bool = False) -> str:
    """Wikitexte d'une page (redirections suivies), "" si la page n'existe pas. Lève reseau.Panne si Wikipédia ne répond pas."""
    if fr:
        r = _wiki_fr({"action": "parse", "page": page, "prop": "wikitext", "redirects": 1})
        return (r.get("parse") or {}).get("wikitext", {}).get("*", "") or ""
    r = _wiki({"action": "parse", "page": page, "prop": "wikitext", "redirects": 1})
    return (r.get("parse") or {}).get("wikitext", "") or ""


def _pages_wiki(noms: list[str]) -> list[str]:
    """Pages Wikipédia de la liste des chapitres (une ou plusieurs pour les longues séries)."""
    for nom in noms:
        motif = re.compile(r"^lists? of " + re.escape(_simple(nom)) + r" chapters", re.I)
        res = _wiki({"action": "query", "list": "search", "srsearch": f"List of {nom} chapters", "srlimit": 20})
        titres = [x["title"] for x in res.get("query", {}).get("search", [])]
        pages = [t for t in titres if motif.match(_simple(t).replace(" s chapters", " chapters")) and not t.lower().startswith("lists of")]
        if pages:
            return pages
        # Série courte : la liste des tomes est dans l'article principal
        principal = [t for t in titres if _simple(t) == _simple(nom)]
        if principal:
            return principal
    return []


def _items(bloc: str) -> list[str]:
    """Éléments d'un {{Numbered list|…}} (un par ligne commençant par « | »)."""
    items, profondeur = [], 0
    for ligne in bloc.splitlines()[1:]:
        if profondeur == 0 and ligne.strip().startswith("}}"):
            break
        if profondeur == 0 and ligne.lstrip().startswith("|") and not re.match(r"\s*\|\s*start\s*=", ligne):
            items.append(ligne)
        profondeur += ligne.count("{{") - ligne.count("}}")
        profondeur = max(profondeur, 0)
    return items


def _titre_item(item: str) -> str:
    m = re.search(r'"([^"]+)"', item)
    t = m.group(1) if m else ""
    return re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", t).replace("''", "").strip()


def _lire_listes(texte: str, tome, tomes: dict, titres: dict):
    """Mises en page rencontrées sur Wikipédia :
    {{Numbered list|start=N | … }} ; « *12. "Titre" » ou « *Days 12: … » ; « * Chapter: 1–7 » (plage sans titres) ;
    « # "Titre" » (liste numérotée implicite : on continue après le dernier chapitre connu)."""
    def noter(n, item=""):
        if tome is not None or n not in tomes:
            tomes[n] = tome
        t = _titre_item(item)
        if t:
            titres.setdefault(n, t)
    trouve = False
    for m in re.finditer(r"\{\{\s*Numbered list\s*\|\s*start\s*=\s*(\d+)", texte, re.I):
        trouve = True
        debut = int(m.group(1))
        for k, item in enumerate(_items(texte[m.start():])):
            noter(float(debut + k), item)
    for m in re.finditer(r"^\*\s*(?:[A-Za-z][A-Za-z ]{0,14}?\s*)?(\d+(?:\.\d+)?)\s*[.:)]\s*(.*)$", texte, re.M):
        trouve = True
        noter(float(m.group(1)), m.group(2))
    for m in re.finditer(r"^\*\s*Chapters?\s*:?\s*(\d+)\s*(?:[–—-]\s*(\d+))?\s*$", texte, re.M | re.I):
        trouve = True
        for n in range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1):
            noter(float(n))
    if not trouve:
        lignes = re.findall(r"^#\s*(.+)$", texte, re.M)
        suivant = int(max([n for n in tomes if n == int(n)], default=0)) + 1
        for k, item in enumerate(lignes):
            noter(float(suivant + k), item)


def _wikipedia(noms: list[str]) -> dict | None:
    pages = _pages_wiki(noms)
    if not pages:
        return None
    tomes, titres = {}, {}
    for page in pages:
        texte = _wiki({"action": "parse", "page": page, "prop": "wikitext", "redirects": 1}).get("parse", {}).get("wikitext", "")
        texte = re.sub(r"<!--.*?-->", "", texte, flags=re.S)       # tomes « en préparation » cachés en commentaire
        blocs = re.split(r"\{\{\s*Graphic novel list", texte)
        for bloc in blocs[1:]:
            vol = re.search(r"\|\s*VolumeNumber\s*=\s*(\d+)", bloc)
            if not vol:
                continue
            fin = re.search(r"\n={2,}\s*[^=\s]", bloc)   # le bloc s'arrête au titre de section suivant
            _lire_listes(bloc[:fin.start()] if fin else bloc, int(vol.group(1)), tomes, titres)
        hors = re.search(r"=+\s*Chapters not yet in[^\n]*\n(.*?)(\n={2,}\s*[^=\s]|\Z)", texte, re.S | re.I)
        if hors:
            _lire_listes(hors.group(1), None, tomes, titres)
    if not any(v is not None for v in tomes.values()):
        return None
    return {"source": "Wikipédia (" + ", ".join(pages) + ")", "tomes": tomes, "titres": titres}


# ---------------------------------------------------------------- MangaDex

def _mangadex(noms: list[str]) -> dict | None:
    """Répartition en tomes d'après MangaDex (fiche au titre identique : jamais une autre série). None : MangaDex ne la connaît
    pas. Lève reseau.Panne s'il ne répond pas."""
    for nom in noms:
        r = reseau.get("https://api.mangadex.org/manga", params={"title": nom, "limit": 50}, memo=300).json()
        if not r.get("data"):
            continue

        def titres_md(d):                           # titre principal et autres titres de la fiche MangaDex
            a = d.get("attributes") or {}
            return [*(a.get("title") or {}).values(), *(v for x in a.get("altTitles") or [] for v in x.values())]
        # « Akame ga Kill! Zero » : la fiche au titre identique, pas la série principale renvoyée en premier ;
        # « The Breaker » est loin dans la liste (après « … Rule Breaker ») : on en demande 50 et on ne prend jamais une autre série
        ident = next((d["id"] for d in r["data"] if any(_simple(t) == _simple(nom) for t in titres_md(d))), None)
        if ident is None:
            continue
        rep = reseau.get(f"https://api.mangadex.org/manga/{ident}/aggregate", memo=300, timeout=20)
        if rep.statut == 404:
            continue
        ag = rep.json()
        tomes = {}
        vols = ag.get("volumes") or {}
        # MangaDex renvoie un objet {"1": {...}} ou, parfois, une liste [{"volume": "1", "chapters": ...}]
        for d in (vols.values() if isinstance(vols, dict) else vols):
            if not isinstance(d, dict):
                continue
            vol = str(d.get("volume") or "none")
            chs = d.get("chapters") or {}
            for c in (chs.values() if isinstance(chs, dict) else chs):
                ch = c.get("chapter") if isinstance(c, dict) else c
                try:
                    tomes[float(ch)] = int(float(vol)) if vol not in ("none", "") else None
                except (TypeError, ValueError):
                    continue
        if any(v is not None for v in tomes.values()):
            return {"source": "MangaDex", "tomes": tomes, "titres": {}}
    return None


# ---------------------------------------------------------------- Interface

def _fichier(serie: str) -> Path:
    return DOSSIER / (re.sub(r"[^\w.-]+", "_", serie).strip("_")[:100] + ".json")


_VERROUS = {}
_VERROUS_VERROU = threading.Lock()


def _verrou(serie: str):
    with _VERROUS_VERROU:
        return _VERROUS.setdefault(serie, threading.RLock())


def modifier(serie: str, fonction):
    """Relit le fichier de la série, applique `fonction(brut)` (elle modifie le dictionnaire en place ; rendre False pour ne rien
    écrire), puis réécrit tout d'un coup. Un seul fil à la fois par série : deux recherches qui finissent ensemble (le statut
    et les titres des tomes) ne s'écrasent plus l'une l'autre, ce qui perdait des données sans rien dire."""
    with _verrou(serie):
        f = _fichier(serie)
        try:
            brut = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            brut = {}
        if not isinstance(brut, dict):
            brut = {}
        if fonction(brut) is False:
            return brut
        DOSSIER.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f"{f.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(brut, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)
        _CACHE_FICHES.pop(serie, None)
        return brut


def _enregistrer(serie: str, info: dict):
    """Garde la répartition en tomes trouvée. Rien trouvé : l'ancienne répartition reste (un échec ou une source qui ne connaît
    pas la série n'efface jamais ce qu'on savait), et le prochain essai est repoussé."""
    def appliquer(brut):
        if info.get("tomes"):
            brut.update(date=time.time(), source=info.get("source"),
                        tomes={str(k): v for k, v in info["tomes"].items()}, titres={str(k): v for k, v in (info.get("titres") or {}).items()})
            brut.pop("essais", None)
        else:
            brut["date"] = time.time()
            brut["essais"] = int(brut.get("essais") or 0) + 1
            brut.setdefault("tomes", {})
            brut.setdefault("titres", {})
            brut.setdefault("source", info.get("source"))
    modifier(serie, appliquer)


def oublier(serie: str):
    """Efface le cache d'une série : seulement quand la série n'existe plus ou change d'identité (renommée, autre fiche choisie).
    Une simple réidentification n'efface rien : elle complète et corrige."""
    with _verrou(serie):
        _fichier(serie).unlink(missing_ok=True)
        _CACHE_FICHES.pop(serie, None)


def deplacer(ancien: str, nouveau: str):
    """Série renommée : son cache la suit (ce qu'on a appris ne se perd pas) ; s'il y en a déjà un au nouveau nom, il reste."""
    with _verrou(ancien):
        src, dst = _fichier(ancien), _fichier(nouveau)
        if src.exists() and not dst.exists():
            DOSSIER.mkdir(parents=True, exist_ok=True)
            src.replace(dst)
        else:
            src.unlink(missing_ok=True)
        _CACHE_FICHES.pop(ancien, None)
        _CACHE_FICHES.pop(nouveau, None)


_CACHE_FICHES = {}              # série → ((date, taille du fichier), contenu) : relu seulement si le fichier a changé


def _carte_francaise(d: dict):
    """{n° de chapitre: tome} d'après la page Wikipédia française (chapitres de chaque tome), ou None. Les tomes français ne
    regroupent pas toujours les chapitres comme la liste anglaise (Akame ga Kill : le tome 10 français contient les chapitres
    44 à 48, la liste anglaise y met les 55 à 59). Utilisée seulement si elle forme une vraie suite (numéros qui montent d'un
    tome à l'autre) et couvre presque tous les chapitres entiers connus de la série."""
    details = ((d.get("titres_tomes") or {}).get("details")) or {}
    fr = {}
    for tome, det in details.items():
        nums = det.get("numeros") or [float(m.group(1)) for ligne in det.get("chapitres") or []
                                      for m in [re.match(r"^(\d+(?:\.\d+)?)\.", ligne)] if m]
        for n in nums:
            if str(tome).isdigit():
                fr.setdefault(float(n), int(tome))
    if len({t for t in fr.values()}) < 3:
        return None
    par_tome = {}
    for n, t in fr.items():
        par_tome.setdefault(t, []).append(n)
    ordre = sorted(par_tome)
    if any(max(par_tome[a]) >= min(par_tome[b]) for a, b in zip(ordre, ordre[1:])):
        return None                                       # numérotation qui repart à chaque tome, ou mélangée
    entiers = [n for n in d.get("tomes", {}) if float(n).is_integer()]
    if not entiers or sum(1 for n in entiers if n in fr) < 0.9 * len(entiers):
        return None
    return fr


def numeros_du_tome(serie: str, tome) -> list:
    """Numéros des chapitres annoncés pour ce tome : la liste française de Wikipédia si elle est fiable, sinon la fiche."""
    d = _charger(serie) or {}
    carte = _carte_francaise(d) or {}
    if carte:
        return sorted(n for n, t in carte.items() if int(t) == int(tome))
    return sorted(n for n, t in (d.get("tomes") or {}).items() if t is not None and int(t) == int(tome))


def _charger(serie: str) -> dict | None:
    """Contenu de data/tomes/<série>.json. Gardé en mémoire tant que le fichier ne change pas : la liste de la
    bibliothèque le demande des milliers de fois. Le résultat est une copie de premier niveau (on peut y ajouter des clés)."""
    f = _fichier(serie)
    try:
        st = f.stat()
        cle = (st.st_mtime_ns, st.st_size)
    except OSError:
        _CACHE_FICHES.pop(serie, None)
        return None
    c = _CACHE_FICHES.get(serie)
    if c and c[0] == cle:
        return dict(c[1])
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    d["tomes"] = {float(k): v for k, v in d.get("tomes", {}).items()}
    d["titres"] = {float(k): v for k, v in d.get("titres", {}).items()}
    if len(_CACHE_FICHES) > 1000:
        _CACHE_FICHES.clear()
    _CACHE_FICHES[serie] = (cle, d)
    return dict(d)


def _carte_liste_francaise(serie: str):
    """Répartition d'après la liste française de Wikipédia (chapitres de chaque tome de la série) : {"source", "tomes", "titres"},
    ou None si elle manque ou ne forme pas une vraie suite : numéros qui repartent de 1 à chaque tome, ou mélangés, ou un tome dont
    aucun chapitre n'est numéroté. Les chapitres qu'elle ne cite pas (bonus) manquent, c'est tout."""
    details = ((_charger(serie) or {}).get("titres_tomes") or {}).get("details") or {}
    fr, titres = {}, {}
    for tome, det in details.items():
        if not str(tome).isdigit():
            continue
        numeros = [float(n) for n in det.get("numeros") or []]
        for ligne in det.get("chapitres") or []:
            m = re.match(r"^(\d+(?:\.\d+)?)\.\s*(.*)$", ligne)
            if m:
                numeros.append(float(m.group(1)))
                if m.group(2):
                    titres.setdefault(float(m.group(1)), m.group(2))
        for n in set(numeros):
            if n in fr and fr[n] != int(tome):
                return None                                   # le même numéro dans deux tomes : la numérotation repart à chaque tome
            fr[n] = int(tome)
    if len(set(fr.values())) < 3:
        return None
    par_tome = {}
    for n, t in fr.items():
        par_tome.setdefault(t, []).append(n)
    ordre = sorted(par_tome)
    if any(max(par_tome[a]) >= min(par_tome[b]) for a, b in zip(ordre, ordre[1:])):
        return None                                           # numéros mélangés d'un tome à l'autre
    return {"source": "Wikipédia (liste française)", "tomes": fr, "titres": titres}


def chercher(serie: str, forcer: bool = False) -> dict | None:
    """Répartition des tomes de la série : {"source", "tomes": {n° chapitre: tome ou None}, "titres": {n°: titre}}.
    None si aucune source ne la connaît (les chapitres restent alors un fichier chacun).
    Sources : Wikipédia en anglais, puis la liste française de Wikipédia, puis MangaDex (qui complète aussi la première).
    Une source qui ne répond pas n'est jamais prise pour « elle ne connaît pas » : on garde l'ancienne répartition, et si seule
    MangaDex a répondu, sa répartition est provisoire (refaite dans l'heure)."""
    return chercher_bilan(serie, forcer)[0]


def _nb_tomes(info) -> int:
    return len({t for t in ((info or {}).get("tomes") or {}).values() if t is not None})


def _repartition_pauvre(garde) -> bool:
    """La répartition gardée n'a que quelques tomes alors qu'AniList en annonce bien plus (une page Wikipédia mal lue, MangaDex incomplet) :
    on la refait, avec des essais de plus en plus espacés si les sources ne font pas mieux."""
    vol = ((garde or {}).get("statut_officiel") or {}).get("volumes")
    return bool(garde and garde.get("tomes") and vol and _nb_tomes(garde) < 0.6 * int(vol))


def chercher_bilan(serie: str, forcer: bool = False):
    """(répartition ou None, état, pannes) ; état : « deja », « ok », « partiel » (provisoire : Wikipédia n'a pas répondu), « vide »
    (aucune source ne connaît la série) ou « panne » (aucune source n'a répondu : l'ancienne répartition reste)."""
    garde = _charger(serie)
    if garde and not forcer:
        recent = garde_a_jour(garde, garde, DUREE, trouve=bool(garde.get("tomes")))
        provisoire_perime = garde.get("provisoire") and time.time() - garde.get("date", 0) > 3600
        pauvre_a_refaire = _repartition_pauvre(garde) and time.time() - garde.get("date", 0) > attente_essai(garde.get("pauvre_essais"))
        if recent and not provisoire_perime and not pauvre_a_refaire:
            return (garde if garde.get("tomes") else None), "deja", []
    st = (garde or {}).get("statut_officiel") or {}
    noms = list(dict.fromkeys([x for x in (st.get("titre"), st.get("titre_en")) if x] + _variantes(serie)))   # titre AniList d'abord
    pannes, en, wiki_a_repondu = [], None, False
    try:
        en = _wikipedia(noms)
        if en is None:
            anglais = [n for n in _noms_anglais(serie) if n not in noms]
            en = _wikipedia(anglais) if anglais else None
            noms += anglais
        wiki_a_repondu = True
    except reseau.Panne as e:
        pannes.append(e)
    dex = None
    try:
        dex = _mangadex(noms)
    except reseau.Panne as e:
        pannes.append(e)
    fr = None
    try:
        titres_tomes(serie)                                         # la liste française de Wikipédia, si on ne l'a pas encore
        fr = _carte_liste_francaise(serie)
    except reseau.Panne as e:
        pannes.append(e)
    # La meilleure des répartitions : Wikipédia anglais d'abord, sauf s'il en donne bien moins que la liste française ou MangaDex
    # (page mal lue, liste en cours de rédaction) ; la liste française dit comment l'édition française range les chapitres.
    candidats = [c for c in (fr, dex) if c]
    meilleur_autre = max(candidats, key=_nb_tomes) if candidats else None
    if en and meilleur_autre and _nb_tomes(en) < 0.8 * _nb_tomes(meilleur_autre):
        info = meilleur_autre
    else:
        info = en or (fr if fr else dex)
    provisoire = bool(info) and info is dex and not wiki_a_repondu         # Wikipédia n'a pas répondu : à refaire bientôt
    if info is not None and dex and info is not dex:
        # MangaDex complète les chapitres que la liste ne range pas (bonus, chapitres « .5 »)
        for n, t in dex["tomes"].items():
            info["tomes"].setdefault(n, t)
    if info is None and pannes:
        logger.info("Tomes de %s : recherche impossible pour l'instant (%s), l'ancienne répartition reste", serie,
                    "; ".join(str(p) for p in pannes))
        return (garde if garde and garde.get("tomes") else None), "panne", pannes
    _enregistrer(serie, info or {"source": None})
    if info:
        def noter(brut):
            if provisoire:
                brut["provisoire"] = True
            else:
                brut.pop("provisoire", None)
            if _repartition_pauvre({**brut, "tomes": info["tomes"]}):          # toujours pauvre : prochain essai plus tard
                brut["pauvre_essais"] = int(brut.get("pauvre_essais") or 0) + 1
            else:
                brut.pop("pauvre_essais", None)
        modifier(serie, noter)
    if info:
        logger.info("Tomes de %s : %d tome(s), %d chapitre(s) rangés (%s)%s", serie, _nb_tomes(info), len(info["tomes"]), info["source"],
                    " — provisoire" if provisoire else "")
    else:
        logger.info("Tomes de %s : aucune source ne les connaît", serie)
    return info, ("partiel" if provisoire else ("ok" if info else "vide")), pannes


def tome_de(num: float, info: dict | None):
    """Tome d'un chapitre (None : pas encore sorti en tome). Un chapitre « 12.5 » suit le tome du 12."""
    if not info or num is None:
        return None
    tomes = info["tomes"]
    if num in tomes:
        return tomes[num]
    entier = float(int(num))
    if entier in tomes and tomes[entier] is not None:
        return tomes[entier]
    return None


# ---------------------------------------------------------------- Statut officiel (fini / en cours)

RESUME_VERSION = 2                    # 2 : résumés non tronqués (le dernier mot n'est plus coupé)
STATUT_DUREE = 7 * 86400


def statut_a_jour(st) -> bool:
    """Le statut gardé est-il encore bon ? Série terminée ou abandonnée avec son résumé en français : pour toujours. En cours :
    7 jours. Résumé seulement en anglais (ou pris au tome 1) : un vrai résumé français est recherché de nouveau chaque mois. Une source qui n'avait pas répondu
    pendant la recherche : refait dans l'heure. Série introuvable ou sans résumé : réessais espacés (1, 3, 7 puis 30 jours)."""
    if not st or "resume" not in st:
        return False
    if st.get("resume_v", 1) < RESUME_VERSION and st.get("resume"):    # gardé par l'ancien code (dernier mot coupé) : refait
        return False
    if st.get("statut") and "synonymes" not in st:                     # gardée avant qu'on retienne les autres noms (le titre français) : refaite une fois
        return False
    age = time.time() - st.get("date", 0)
    if st.get("resume_incomplet"):                                     # une source n'a pas répondu : on réessaie bientôt
        return age < 3600
    complet = bool(st.get("statut")) and len(st.get("resume") or "") >= 40       # un mot seul : refait
    if complet and st.get("statut") in TERMINES:
        return True if st.get("resume_langue") in ("fr", None) and st.get("resume_source") != "Tome 1" else age < 30 * 86400
    if complet:
        return age < STATUT_DUREE
    return age < attente_essai(st.get("essais"))


def _choisir(medias, serie, tome_max):
    """Parmi les résultats AniList, celui qui correspond le mieux : même titre, puis nombre de tomes compatible
    avec ce qu'on a (« Kenichi » 61 tomes → « Shijou Saikyou no Deshi Kenichi », pas « Kenichi Tantei Chou »)."""
    cles = [c for c in {_simple(serie), _simple(sans_edition(serie)), *(_simple(x) for x in serie.split(" : "))} if c]
    def note(m):
        titres = [_simple(t) for t in (m["title"].get("romaji"), m["title"].get("english")) if t] + [_simple(x) for x in m.get("synonyms") or []]
        exact = any(c in titres for c in cles)
        contient = any(c in t for c in cles for t in titres)
        vol = m.get("volumes")
        assez = not (tome_max and vol and vol < tome_max)        # 1 tome alors qu'on en a 14 : pas la bonne série
        compatible = bool(tome_max and vol and vol >= tome_max)
        proche = -abs((vol or 0) - (tome_max or 0)) if tome_max and vol else -999
        return (assez, exact, compatible, contient, m.get("format") == "MANGA", proche)
    return max(medias, key=note) if medias else None


def _texte_propre(t):
    t = re.sub(r"<br\s*/?>", "\n", t or "", flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)              # liens au format [texte](adresse)
    t = re.sub(r"\(Source:[^)]*\)|\n---.*$", "", t, flags=re.S | re.I)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _resume(m, serie=""):
    """Résumé de la série : en français d'après MangaDex (même série, reconnue par l'identifiant AniList), puis Wikipédia en
    français, sinon en anglais d'après AniList. → (texte, langue « fr » ou « en », services qui n'ont pas répondu, source). Quand
    un service n'a pas répondu, le français a peut-être été manqué : l'appelant refera la recherche bientôt."""
    titre = m["title"].get("romaji") or m["title"].get("english") or ""
    pannes = []
    try:
        r = reseau.get("https://api.mangadex.org/manga", params={"title": titre, "limit": 10}, memo=300).json()
        for d in r.get("data", []):
            a = d.get("attributes", {})
            if str((a.get("links") or {}).get("al", "")) == str(m.get("id")):
                desc = a.get("description") or {}
                fr = _sans_suites(_texte_propre(desc.get("fr") or ""))
                if len(fr) >= 60:                       # « [Wikipedia](lien) » devient « Wikipedia » : pas un résumé
                    return fr, "fr", pannes, "MangaDex"
                break
    except reseau.Panne as e:
        pannes.append(e.service)
    try:
        fr = _wikipedia_fr(m, serie)
    except reseau.Panne as e:
        pannes.append(e.service)
        fr = ""
    if fr:
        return fr, "fr", pannes, "Wikipédia"
    return _texte_propre(m.get("description") or ""), ("en" if m.get("description") else ""), pannes, "AniList"


def _sans_suites(texte: str) -> str:
    """Le résumé MangaDex de « The Breaker » enchaîne ceux des suites (« The Breaker: New Waves est la suite directe… ») :
    on s'arrête au premier paragraphe qui présente une suite."""
    paras = re.split(r"\n\s*\n", texte or "")
    garde = []
    for p in paras:
        if garde and re.search(r"\best la suite\b|\bis the sequel\b|\bsuite directe\b", p, re.I):
            break
        garde.append(p)
    return "\n\n".join(garde).strip()


def _titres_mangaupdates(serie: str) -> list[str]:
    """Noms d'origine d'une série que MangaUpdates connaît sous ce nom (« Prisonnier Riku » → « Shuujin Riku »). Lève
    reseau.Panne si MangaUpdates ne répond pas."""
    r = reseau.post("https://api.mangaupdates.com/v1/series/search", json={"search": serie, "perpage": 10}).json()
    return list(dict.fromkeys(x["record"]["title"] for x in r.get("results") or []
                              if x.get("record", {}).get("title") and _simple(x.get("hit_title") or "") == _simple(serie)
                              and _simple(x["record"]["title"]) != _simple(serie)))


def _resume_sans_anilist(serie: str):
    """Série absente d'AniList : résumé de Wikipédia en français, sinon celui de MangaUpdates (anglais).
    → (texte, langue, services qui n'ont pas répondu, source)."""
    pannes = []
    try:
        fr = _wikipedia_fr({"title": {}}, serie)
    except reseau.Panne as e:
        pannes.append(e.service)
        fr = ""
    if fr:
        return fr, "fr", pannes, "Wikipédia"
    try:
        for titre in [serie, *_titres_mangaupdates(serie)]:
            mu = _mangaupdates([titre])
            if mu and mu.get("description"):
                return mu["description"], "en", pannes, "MangaUpdates"
    except reseau.Panne as e:
        pannes.append(e.service)
    return "", "", pannes, ""


def page_correspond(page: str, noms) -> bool:
    """La page Wikipédia est-elle bien celle de la série ? (« Arago » → « Arago (manga) » oui ; « Akame ga Kill! Zero » →
    « Red Eyes Sword: Akame ga Kill! » non : c'est la série principale ; « Golden Kamuy » → « Golden Kamui » oui.) Les morceaux d'un
    nom « Série : Suite » comptent seulement si le titre est exactement l'un d'eux, sauf celui qui est une autre série de la
    bibliothèque. Voir correspondance.titre_de_la_serie."""
    noms = [n for n in noms if n]
    autres = [x for x in SERIES_EXISTANTES()]
    faibles = []
    for n in noms:
        if " : " in n:
            faibles += [x.strip() for x in n.split(" : ")
                        if correspondance.jetons(x) and not any(correspondance._meme_mots(correspondance.jetons(x), correspondance.jetons(a)) for a in autres)]
    return wikifr.page_de_la_serie(page, noms, faibles, [a for a in autres if a not in noms])


def _wikipedia_fr(m, serie=""):
    """Synopsis (ou introduction) de l'article Wikipédia en français sur la série, si c'est bien un article de manga ; "" s'il n'y
    en a pas. Le nom du dossier (souvent le titre français : « Arago ») passe avant les titres d'AniList (« AR∀GO »).
    Lève reseau.Panne si Wikipédia ne répond pas : « il n'y a pas d'article » est une autre réponse."""
    titres = m.get("title") or {}
    fortes, faibles, autres = noms_de_recherche(serie or titres.get("romaji") or "", {
        "titre": titres.get("romaji"), "titre_en": titres.get("english"), "synonymes": m.get("synonyms") or []})
    if not fortes:
        return ""
    for page in wikifr.trouver_pages(fortes, faibles, autres)[:3]:
        texte = wikifr.extrait(page)
        if "manga" not in texte[:1500].lower():
            continue
        # La section « Synopsis » (l'histoire) plutôt que l'introduction (auteur, magazine…)
        m_syn = re.search(r"\n==+\s*(Synopsis|Histoire|Résumé|Intrigue|Scénario|Univers et synopsis)\s*==+\n(.*?)(?=\n==[^=]|\Z)",
                          texte, re.S | re.I)
        if m_syn:
            corps = re.sub(r"\n===+[^=]+===+\n", "\n", m_syn.group(2)).strip()
            if len(corps) > 80:
                return corps if len(corps) <= 1500 else corps[:1500].rsplit(" ", 1)[0] + "…"
        intro = texte.split("\n==", 1)[0].strip()
        if len(intro) > 80:
            return intro
    return ""


_INTRO_FR = {}


def introduction_fr(serie: str) -> str:
    """Introduction de l'article Wikipédia en français sur la série (« » si introuvable). Gardée en mémoire, sauf si Wikipédia
    n'a pas répondu (alors on réessaiera)."""
    if serie in _INTRO_FR:
        return _INTRO_FR[serie]
    try:
        fortes, faibles, autres = noms_de_recherche(serie)
        for page in wikifr.trouver_pages(fortes, faibles, autres)[:3]:
            texte = wikifr.extrait(page, intro=True)
            if "manga" in texte[:1500].lower():
                _INTRO_FR[serie] = texte
                return texte
        _INTRO_FR[serie] = ""
    except reseau.Panne:
        return ""
    return _INTRO_FR.get(serie, "")


def meme_serie_sous_titre(serie: str, reste: str) -> bool:
    """« Kenichi » + « Le Disciple Ultime Matsuena » : le sous-titre est le titre français complet de la même série (l'article
    Wikipédia en français l'écrit : « Ken-ichi, le disciple ultime »), pas une suite. Les mots en trop au bout (le nom de
    l'auteur) sont ignorés ; il faut au moins deux mots qui se suivent dans l'article."""
    mots = (reste or "").split()
    if len(mots) < 2:
        return False
    intro = f" {_simple(introduction_fr(serie))} "
    return any(f" {_simple(' '.join(mots[:k]))} " in intro for k in range(len(mots), 1, -1))


ID_CHOISI = lambda serie: None          # remplacé par l'appli : identifiant AniList choisi à la main pour la série
TITRES_FICHIERS = lambda serie: []      # remplacé par l'appli : nom de la série écrit dans le ComicInfo.xml des tomes (équipe)
ID_INDICE = lambda serie: None          # remplacé par l'appli : identifiant AniList noté dans les fichiers des tomes (série reçue)


_REQ_FICHE = ("{id title{romaji english native} synonyms status volumes chapters format description(asHtml:false)}")


def chercher_anilist(texte: str) -> list[dict]:
    """Recherche AniList pour « 🔎 Choisir la fiche » : 12 résultats avec couverture, titres, année, statut, tomes.
    Lève reseau.Panne si AniList ne répond pas."""
    q = ("query($s:String){Page(perPage:12){media(search:$s,type:MANGA){id title{romaji english native} synonyms status "
         "volumes chapters format startDate{year} coverImage{medium} siteUrl}}}")
    out = []
    for m in ((reseau.anilist(q, {"s": texte}) or {}).get("Page") or {}).get("media") or []:
        t = m.get("title") or {}
        out.append({"id": m["id"], "titre": t.get("romaji") or t.get("english") or "", "anglais": t.get("english") or "",
                    "natif": t.get("native") or "", "annee": (m.get("startDate") or {}).get("year"), "statut": m.get("status"),
                    "tomes": m.get("volumes"), "chapitres": m.get("chapters"), "format": m.get("format"),
                    "couverture": (m.get("coverImage") or {}).get("medium") or "", "lien": m.get("siteUrl") or ""})
    return out


def _media_anilist(serie: str, tome_max=None):
    """La fiche AniList de la série (dictionnaire), ou None si AniList ne la connaît pas. Lève reseau.Panne si AniList (ou
    MangaUpdates, consulté pour trouver le nom d'origine) ne répond pas : « inconnue » n'est jamais dit à tort."""
    choisi = ID_CHOISI(serie) or ID_INDICE(serie)
    if choisi:                                         # fiche choisie à la main (🔎 Choisir la fiche) ou notée dans les fichiers : jamais de recherche
        return (reseau.anilist("query($i:Int){Media(id:$i,type:MANGA)" + _REQ_FICHE + "}", {"i": int(choisi)}) or {}).get("Media")
    q = "query($s:String){Page(perPage:6){media(search:$s,type:MANGA,format_not:NOVEL)" + _REQ_FICHE + "}}"
    medias = []
    essais = _variantes(serie) + [t for t in (TITRES_FICHIERS(serie) or []) if t not in _variantes(serie)]
    for v in essais:
        medias = ((reseau.anilist(q, {"s": v}) or {}).get("Page") or {}).get("media") or []
        if medias:
            break
    m = _choisir(medias, serie, tome_max)
    if not m:                                          # titre français inconnu d'AniList (« Prisonnier Riku ») : nom d'origine d'après MangaUpdates
        for titre_mu in _titres_mangaupdates(serie):
            medias = ((reseau.anilist(q, {"s": titre_mu}) or {}).get("Page") or {}).get("media") or []
            m = _choisir(medias, titre_mu, tome_max)
            if m:
                break
    return m


def statut_officiel(serie: str, tome_max=None, forcer=False) -> dict | None:
    """{"statut": FINISHED | RELEASING | HIATUS | CANCELLED | NOT_YET_RELEASED, "volumes", "chapitres", "titre"}
    d'après AniList, gardé 7 jours dans data/tomes/<série>.json ; None si inconnu. Quand AniList ne répond pas, l'ancienne fiche
    est rendue telle quelle (jamais effacée, jamais remplacée par « inconnu »)."""
    return statut_officiel_bilan(serie, tome_max, forcer)[0]


def statut_officiel_bilan(serie: str, tome_max=None, forcer=False):
    """(statut ou None, état, pannes) ; état : « deja », « ok », « partiel » (une source du résumé n'a pas répondu), « vide » (AniList
    ne connaît pas la série) ou « panne » (AniList n'a pas répondu : l'ancienne fiche reste)."""
    garde = _charger(serie) or {}
    st = garde.get("statut_officiel")
    if not forcer and statut_a_jour(st):
        return (st if st.get("statut") else None), "deja", []
    ancien = st if st and st.get("statut") else None
    try:
        m = _media_anilist(serie, tome_max)
    except reseau.Panne as e:
        logger.info("Statut de %s : %s (l'ancienne fiche reste)", serie, e)
        return ancien, "panne", [e]
    nouveau = _garder_statut(serie, m) or ancien                      # « inconnue » ne retire pas une fiche déjà trouvée
    resultat = (_charger(serie) or {}).get("statut_officiel") or {}
    if resultat.get("resume_incomplet"):
        return nouveau, "partiel", []
    return nouveau, ("ok" if m else "vide"), []


def resume_de_serie_depuis_le_tome(serie: str, texte: str, source: str = "Tome 1") -> bool:
    """Une série dont le résumé n'existe qu'en anglais prend en français celui de son tome 1 (BnF, Google Books), qui présente la
    série : mieux vaut du français que de l'anglais. Jamais à la place d'un résumé français de MangaDex ou de Wikipédia. → True si posé."""
    if len(texte or "") < 60:
        return False
    fait = []

    def appliquer(brut):
        st = brut.get("statut_officiel")
        if not st or st.get("resume_langue") == "fr":
            return False
        st["resume"], st["resume_langue"], st["resume_source"] = texte, "fr", source
        fait.append(True)
    modifier(serie, appliquer)
    return bool(fait)


def _garder_statut(serie, m):
    """Enregistre la fiche AniList et le résumé (à côté de la répartition en tomes, même fichier). Le résumé trouvé n'en remplace
    jamais un meilleur : un résumé en français reste si la recherche de cette fois n'a trouvé que l'anglais ou rien."""
    resume, langue, pannes, source = _resume(m, serie) if m else _resume_sans_anilist(serie)
    st = {"date": time.time(), "statut": m["status"] if m else None, "volumes": m.get("volumes") if m else None,
          "chapitres": m.get("chapters") if m else None,
          "titre": (m["title"].get("romaji") or m["title"].get("english")) if m else None,
          "titre_en": m["title"].get("english") if m else None, "anilist": m.get("id") if m else None,
          "synonymes": [x for x in (m.get("synonyms") or []) if x][:30] if m else [],
          "natif": m["title"].get("native") if m else None,
          "choisi": bool(m and ID_CHOISI(serie)), "resume": resume, "resume_langue": langue, "resume_source": source, "resume_v": RESUME_VERSION}
    if pannes:
        st["resume_incomplet"] = sorted(set(pannes))
    rang_source = {"MangaDex": 5, "Wikipédia": 4, "Tome 1": 3, "MangaUpdates": 2, "AniList": 1, "": 0}

    def rang(langue_, source_):
        return rang_source.get(source_ or ("MangaDex" if langue_ == "fr" else "AniList" if langue_ == "en" else ""), 0)

    def appliquer(brut):
        ancien = brut.get("statut_officiel") or {}
        # le résumé trouvé n'en remplace jamais un meilleur : MangaDex (français) > Wikipédia (français) > le tome 1 (français) > MangaUpdates > AniList (anglais)
        if ancien.get("resume") and ancien.get("anilist") == st["anilist"] \
                and rang(ancien.get("resume_langue"), ancien.get("resume_source")) > rang(st["resume_langue"], st["resume_source"]):
            st["resume"], st["resume_langue"], st["resume_source"] = ancien["resume"], ancien["resume_langue"], ancien.get("resume_source", "")
        if not (st["statut"] and len(st["resume"] or "") >= 40):          # incomplet : on compte les échecs pour espacer les essais
            st["essais"] = int(ancien.get("essais") or 0) + 1
        if not st["statut"] and ancien.get("statut") and m is None:
            return False                                                 # « inconnue » ne remplace pas une fiche trouvée
        brut["statut_officiel"] = st
    modifier(serie, appliquer)
    return (_charger(serie) or {}).get("statut_officiel") if st["statut"] else None


# ---------------------------------------------------------------- Fiche détaillée (bouton ℹ️)

FICHE_DUREE = 30 * 86400
_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
_GENRES = {"Action": "action", "Adventure": "aventure", "Comedy": "comédie", "Drama": "drame", "Fantasy": "fantasy",
           "Horror": "horreur", "Mystery": "mystère", "Psychological": "psychologique", "Romance": "romance",
           "Sci-Fi": "science-fiction", "Slice of Life": "tranche de vie", "Sports": "sport", "Supernatural": "surnaturel",
           "Thriller": "thriller", "Mecha": "mecha", "Music": "musique", "Ecchi": "ecchi", "Mahou Shoujo": "magical girl"}


def _infobox(titre_page: str) -> dict:
    """Champs utiles de l'infobox Wikipédia (première occurrence = partie manga). Lève reseau.Panne si Wikipédia ne répond pas."""
    w = wikifr.wikitexte(titre_page)
    out = {}
    for cle in ("auteur", "scénariste", "dessinateur", "genre", "éditeur", "éditeur_francophone", "prépublication"):
        m = re.search(r"^[ \t]*\|[ \t]*" + cle + r"[ \t]*=[ \t]*(.+)$", w, re.M)      # jamais la ligne suivante
        if m:
            v = re.sub(r"\{\{[^}]*\}\}|<ref.*?(</ref>|/>)|<[^>]+>", "", m.group(1))
            v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", v).strip(" ,")
            if v:
                out[cle] = v
    return out


def _page_wikipedia(serie: str, st: dict = None) -> str:
    """Titre de l'article Wikipédia en français de la série, "" s'il n'y en a pas. Lève reseau.Panne si Wikipédia ne répond pas."""
    fortes, faibles, autres = noms_de_recherche(serie, st)
    pages = wikifr.trouver_pages(fortes, faibles, autres)
    return pages[0] if pages else ""


# ---------------------------------------------------------------- Sources complémentaires (ré-identification)

GOOGLE_BOOKS = googlebooks.URL


cle_google_books = googlebooks.cle                    # clé API Google Books (Réglages → 📏 Règles de recherche)
verifier_cle_google = googlebooks.verifier_cle
_tome_du_titre = googlebooks.tome_du_titre


def _mangaupdates(titres: list[str]) -> dict | None:
    """MangaUpdates (sans clé) : éditeurs (originaux, anglais…), auteurs et nombre de volumes d'après sa fiche. Une fiche qui n'a
    pas le même titre n'est jamais prise (le premier résultat n'est pas forcément la bonne série). None : MangaUpdates ne la connaît
    pas. Lève reseau.Panne s'il ne répond pas."""
    for titre in dict.fromkeys(t for t in titres if t):
        r = reseau.post("https://api.mangaupdates.com/v1/series/search", json={"search": titre, "perpage": 5}).json()
        trouves = r.get("results") or []
        ident = next((x["record"]["series_id"] for x in trouves
                      if correspondance.titre_de_la_serie(x["record"].get("title") or "", [titre])
                      or correspondance.titre_de_la_serie(x.get("hit_title") or "", [titre])), None)
        if ident is None:
            continue
        rep = reseau.get(f"https://api.mangaupdates.com/v1/series/{ident}")
        if rep.statut == 404:
            continue
        d = rep.json()
        vol = re.search(r"(\d+)\s*Volumes?", d.get("status") or "", re.I)
        return {"id": ident, "description": _texte_propre(d.get("description") or ""), "editeurs": [p.get("publisher_name") for p in d.get("publishers") or [] if p.get("publisher_name")],
                "auteurs": list(dict.fromkeys(a.get("name") for a in (d.get("authors") or []) if a.get("name"))),
                "volumes": int(vol.group(1)) if vol else None}
    return None


def _google_books(titre: str) -> dict | None:
    """Google Books : éditeur et auteur d'une édition française, et le plus grand numéro de tome trouvé (None : pas de clé).
    Lève reseau.Panne / reseau.Quota si Google n'a pas répondu."""
    return googlebooks.infos_serie(titre)


def _isbn13_valide(c: str) -> bool:
    return bool(c) and bnf.isbn13(c) == re.sub(r"\D", "", c)


def _isbn_de_notice(v: dict, titres: list[str], edition: str = ""):
    """(tome, ISBN-13 français) d'une notice Google Books « <série> - Tome 12 » ou « <série> - Édition originale - T12 », ou None :
    un autre mot dans le titre (« Doors », « Édition limitée », « fanbook ») veut dire un autre livre."""
    n = googlebooks.notice({"volumeInfo": v}, titres, edition)
    return (n["tome"], n["isbn"]) if n and n["isbn"] else None


def _cle_texte(t: str) -> str:
    return _simple(t or "")[:160]


_ABREVIATIONS = {"m", "mm", "mme", "mlle", "mr", "dr", "pr", "st", "ste", "me", "mgr", "cie", "vol", "no", "n"}


def _debut_de_phrase(reste: str) -> bool:
    """Le texte restant commence comme une phrase (majuscule, chiffre, guillemet), pas par un « et des coups de feu ! »."""
    reste = reste.lstrip()
    return bool(reste) and not reste[0].islower()


def _fin_de_phrase(texte: str, commun: str) -> int:
    """Indice (dans texte) où commence la phrase qui suit la dernière VRAIE fin de phrase du début commun « commun »,
    ou -1. Ne coupe ni après des points de suspension (« des élèves... et des coups de feu ! » est une seule phrase),
    ni après une abréviation (« M. Koro »), ni avant une minuscule."""
    meilleur = -1
    for m in re.finditer(r"[.!?…]+\s", commun):
        signe = m.group(0).rstrip()
        if m.start() < 40:
            continue
        if signe.endswith("…") or (set(signe) == {"."} and len(signe) > 1) or signe.endswith("..."):
            continue                                        # points de suspension
        mot = re.search(r"([A-Za-zÀ-ÿ]+)$", commun[:m.start()])
        if signe == "." and mot and mot.group(1).lower() in _ABREVIATIONS:
            continue
        if m.end() < len(texte) and not _debut_de_phrase(texte[m.end():m.end() + 1]):
            continue
        meilleur = m.end()
    return meilleur


def _espacer(texte: str) -> str:
    """« abattre !Découvrez » -> « abattre ! Découvrez » : certaines notices perdent l'espace après la ponctuation.
    Les variantes typographiques d'une même phrase sont ramenées à une seule (apostrophe droite, pas d'espace avant « : »),
    pour reconnaître la présentation de la série d'une notice à l'autre (« jamais : le Night Raid » / « jamais: le Night Raid »)."""
    texte = (texte or "").replace("’", "'").replace("\u00a0", " ")
    texte = re.sub(r"\s+:", ":", texte)
    return re.sub(r"([.!?…])(?=[A-ZÀ-ÝŒ«])", r"\1 ", texte)


def _cle_doublon(texte: str) -> str:
    """Le texte réduit à ses lettres et chiffres : « d’un » (apostrophe typographique) et « d'un » comptent pour le même."""
    return re.sub(r"[^a-z0-9]+", "", _simple((texte or "").replace("’", "").replace("'", "")))


def _apres_intro(texte: str, intro: str):
    """Ce qui suit « intro » au début de « texte », ou None. La comparaison ne regarde que les lettres et les chiffres : une
    virgule, un espace ou une apostrophe de plus ou de moins entre deux notices ne cache pas la même présentation."""
    cible = _cle_doublon(intro)
    if not cible or not intro.strip():
        return None
    vu = ""
    for i, c in enumerate(texte):
        vu += _cle_doublon(c)
        if len(vu) >= len(cible):
            return re.sub(r"^[\s.!?…:;,]+", "", texte[i + 1:]) if vu == cible else None
    return None


def _resume_de_serie(texte: str, brut: dict, n: int) -> str:
    """Résumé propre du tome : la notice Google Books commence souvent par la présentation de la série entière
    (« Avec son subtil mélange d'action… Fullmetal Alchemist est le titre incontournable… »), la même sur tous les tomes.
    On retire le début commun aux autres tomes gardés en mémoire (coupé à la fin d'une phrase) ; s'il ne reste rien
    de propre à ce tome, on ne met rien."""
    texte = _espacer(texte or "")
    cle = _cle_doublon(texte)
    identiques = [int(re.search(r"\d+", k).group()) for k, v in (brut.get("resumes_tomes") or {}).items()
                  if cle and k != str(n) and re.search(r"\d+", k) and _cle_doublon(v.get("texte") or "") == cle]
    if identiques:
        # La même notice sur plusieurs tomes : c'est la présentation de la série, ou une notice recopiée d'un tome à l'autre.
        # Elle ne vaut que pour le plus petit de ces tomes ; ailleurs mieux vaut rien qu'un résumé faux.
        if not (n < min(identiques) and len(texte) >= 40):
            return ""
    for k, v in (brut.get("resumes_tomes") or {}).items():   # fin commune (liste de prix de la série, etc.) : coupée aussi
        autre = _espacer(v.get("texte") or "")
        if k == str(n) or not autre or not texte:
            continue
        j = 0
        while j < min(len(texte), len(autre)) and texte[-1 - j] == autre[-1 - j]:
            j += 1
        if j >= 60 and len(texte) - j >= 40:
            texte = texte[:len(texte) - j].rstrip(" -–—\n")
    intros = brut.setdefault("intros", [])
    for intro in intros:                               # début déjà reconnu comme parasite sur d'autres tomes
        reste = _apres_intro(texte, intro)
        if reste is not None and _debut_de_phrase(reste):   # une coupe au milieu d'une phrase est ignorée
            texte = reste.lstrip()
    for k, v in (brut.get("resumes_tomes") or {}).items():
        autre = _espacer(v.get("texte") or "")
        if k == str(n) or not autre or not texte:
            continue
        i = 0
        while i < min(len(texte), len(autre)) and texte[i] == autre[i]:
            i += 1
        commun = texte[:i]
        if i == len(texte) == len(autre):
            if re.search(r"\d+", k) and int(re.search(r"\d+", k).group()) > n:
                continue                               # recopié plus loin : il reste au plus petit tome (décidé plus haut)
            return ""                                  # exactement le même texte : présentation de la série
        coupe = _fin_de_phrase(texte, commun)
        if coupe >= 40:
            intro = texte[:coupe]
            if intro not in intros:
                intros.append(intro)
            texte = texte[coupe:].lstrip()
    st = brut.get("statut") or brut.get("statut_officiel") or {}
    if texte and st.get("resume") and _simple(texte)[:160] == _simple(st["resume"])[:160]:
        return ""
    return texte if len(texte) >= 40 else ""


def resume_propre_du_fichier(serie: str, tome, texte: str, autres: dict) -> str:
    """Résumé écrit dans le fichier du tome, sans la présentation de la série : « autres » = {tome: résumé écrit dans le fichier
    des autres tomes}. Un texte identique ailleurs est la présentation de la série (rien ici) ; un début commun est coupé."""
    def specifique(t):                                    # « Présentation de la série… >Tome 9< Mine commence… » : la partie du tome
        morceaux = re.split(r"\n\s*>?\s*(?:Volume|Tome|Vol\.?)\s*\d+\s*<?[ \t]*\n", t or "")
        return morceaux[-1].strip() if len(morceaux) > 1 and len(morceaux[-1].strip()) >= 40 else (t or "")
    texte = specifique(texte)
    brut = dict(_charger(serie) or {})
    pool = dict(brut.get("resumes_tomes") or {})
    for k, v in (autres or {}).items():
        pool[f"fichier-{k}"] = {"texte": specifique(v)}
    brut["resumes_tomes"] = pool
    brut["intros"] = list(brut.get("intros") or [])
    return _resume_de_serie(texte, brut, int(tome))


def resume_tome_memoire(serie: str, tome) -> str:
    """Résumé du tome déjà gardé (Wikipédia, BnF ou Google Books ; aucun appel Internet), sans la présentation de la série."""
    import notices
    return notices.resume_du_tome(serie, tome)[0]


_MARQUEURS_DERIVES = correspondance.MARQUEURS_DERIVES            # (ancien nom)


def _autre_serie(nom: str, titre: str) -> bool:
    """Le titre Google contient, en plus de celui de la série, un mot de série dérivée (« Akame ga Kill ! Zero, tome 10 » pour
    « Akame ga Kill ! ») : c'est un autre livre, sa notice ne vaut pas pour ce tome."""
    return correspondance.est_derive(nom, [titre])








def _editeurs_propres(v: str) -> str:
    """« J'ai lu (2002-2005)Tonkam (depuis 2007) » → « J'ai lu · Tonkam » : les dates entre parenthèses partent."""
    v = re.sub(r"\s*\([^)]*\)\s*", " · ", v or "")
    return " · ".join(x.strip() for x in v.split("·") if x.strip())


def fiche(serie: str, forcer=False) -> dict:
    """Dates de parution, auteurs, genres, éditeurs (AniList + Wikipédia FR + MangaUpdates + Google Books) ; gardée pour de bon
    une fois trouvée (data/tomes/<série>.json) : seul « 🔄 Relancer l'identification » la refait. Sans résultat : réessais
    espacés. Une source qui ne répond pas ne fait rien perdre : ses champs restent comme avant."""
    return fiche_bilan(serie, forcer)[0]


def fiche_bilan(serie: str, forcer=False):
    """(fiche, état, pannes) ; état : « deja », « ok », « partiel » (une source n'a pas répondu : refaite dans l'heure) ou « vide »."""
    garde = _charger(serie) or {}
    f = garde.get("fiche")
    trouvee = f and any(f.get(k) for k in ("genres", "editeur_fr", "editeur_jp", "debut"))
    st_actuel = (garde.get("statut_officiel") or {}).get("statut")
    fin_annoncee = trouvee and st_actuel in TERMINES and not f.get("fin")   # la série vient de se terminer : date de fin à prendre
    partielle_a_refaire = bool(f and f.get("partielle")) and time.time() - f.get("date", 0) > 3600          # un service n'avait pas répondu : dans l'heure
    if f and not forcer and not partielle_a_refaire and ((trouvee and not fin_annoncee) or (not trouvee and garde_a_jour(f, garde, FICHE_DUREE, trouve=False))):
        return f, "deja", []
    st = garde.get("statut_officiel") or {}
    if st.get("statut") and not st.get("anilist"):        # fiche AniList d'avant (sans identifiant) : on la refait une fois
        st = statut_officiel(serie, forcer=True) or st
    out = {k: v for k, v in (f or {}).items()}              # un échec (AniList qui demande de ralentir…) garde l'ancien
    out.pop("partielle", None)
    roles, pannes, ont_repondu = {}, [], set()
    out["date"] = time.time()
    if st.get("anilist"):
        q = ("query($i:Int){Media(id:$i){startDate{year month} endDate{year month} status genres title{native romaji english} "
             "staff(perPage:8){edges{role node{name{full}}}}}}")
        try:
            m = (reseau.anilist(q, {"i": st["anilist"]}) or {}).get("Media") or {}
            date = lambda d: (f"{_MOIS[d['month'] - 1]} " if d.get("month") else "") + str(d["year"]) if d and d.get("year") else ""
            out.update(debut=date(m.get("startDate")), fin=date(m.get("endDate")), statut=m.get("status"),
                       titre_original=(m.get("title") or {}).get("native") or "", romaji=(m.get("title") or {}).get("romaji") or "",
                       genres=", ".join(_GENRES.get(g, g.lower()) for g in m.get("genres") or []))
            for e in ((m.get("staff") or {}).get("edges") or []):
                role = e.get("role") or ""
                for cle, mot in (("scenario", "Story"), ("dessin", "Art")):      # « Story & Art » : les deux
                    if mot in role and "Assist" not in role:
                        roles.setdefault(cle, []).append(e["node"]["name"]["full"])
            out.update({k: ", ".join(dict.fromkeys(v)) for k, v in roles.items()})
            ont_repondu.add("AniList")
        except reseau.Panne as e:
            pannes.append(e)
    try:
        page = _page_wikipedia(serie, st)
        ont_repondu.add("Wikipédia")
        if page:
            ib = _infobox(page)
            if out.get("wikipedia") and out["wikipedia"] != page:          # une autre page qu'avant : ce qu'on tenait de l'ancienne ne vaut plus
                for k in ("editeur_jp", "editeur_fr", "magazine"):
                    out.pop(k, None)
            out["wikipedia"] = page
            # AniList connaît les auteurs de CETTE série (une suite peut avoir un autre dessinateur que l'article Wikipédia)
            out["scenario"] = (", ".join(dict.fromkeys(roles.get("scenario", []))) if roles.get("scenario") else "") or ib.get("auteur") or ib.get("scénariste") or out.get("scenario", "")
            out["dessin"] = (", ".join(dict.fromkeys(roles.get("dessin", []))) if roles.get("dessin") else "") or ib.get("dessinateur") or out.get("dessin", "")
            out["genres"] = ib.get("genre") or out.get("genres", "")
            for cle, valeur in (("editeur_jp", _editeurs_propres(ib.get("éditeur", ""))), ("editeur_fr", _editeurs_propres(ib.get("éditeur_francophone", ""))),
                                ("magazine", ib.get("prépublication", ""))):
                if valeur:                                                 # jamais remplacé par du vide (l'éditeur peut venir de Google Books)
                    out[cle] = valeur
    except reseau.Panne as e:
        pannes.append(e)
        ont_repondu.discard("Wikipédia")
    # Sources complémentaires : MangaUpdates (éditeurs, auteurs, volumes) et Google Books (si une clé est réglée)
    titres = [serie, st.get("titre"), st.get("titre_en"), out.get("romaji")]
    mu = gb = None
    try:
        mu = _mangaupdates(titres)
        ont_repondu.add("MangaUpdates")
    except reseau.Panne as e:
        pannes.append(e)
    if mu:
        out["editeurs_mu"] = ", ".join(mu["editeurs"])
        out["volumes_mu"] = mu["volumes"]
        out["mangaupdates"] = mu["id"]
        if not out.get("scenario") and mu["auteurs"]:
            out["scenario"] = ", ".join(mu["auteurs"][:3])
    try:
        gb = _google_books(next((x for x in titres if x), ""))
        if gb is not None:
            ont_repondu.add("Google Books")
    except reseau.Panne as e:
        pannes.append(e)
    if gb:
        if not out.get("editeur_fr") and gb["editeur"]:
            out["editeur_fr"] = gb["editeur"]
        if not out.get("scenario") and gb["auteurs"]:
            out["scenario"] = gb["auteurs"]
        if gb["tomes"]:
            out["tomes_google"] = gb["tomes"]
    trouvees = {"AniList": bool(st.get("anilist")), "Wikipédia": bool(out.get("wikipedia")), "MangaUpdates": bool(mu), "Google Books": bool(gb)}
    anciennes = set((f or {}).get("sources") or [])
    manquantes = {s for s in ("AniList", "Wikipédia", "MangaUpdates", "Google Books") if s not in ont_repondu and s in anciennes}
    out["sources"] = [s for s in ("AniList", "Wikipédia", "MangaUpdates", "Google Books") if trouvees[s] or s in manquantes]
    if pannes:
        out["partielle"] = True
    modifier(serie, lambda brut: brut.__setitem__("fiche", out))
    return out, ("partiel" if pannes else ("ok" if any(trouvees.values()) else "vide")), pannes


# ---------------------------------------------------------------- Titres des tomes (« Romance Dawn »)

_wiki_propre = wikifr.propre
_champs_tomebd = wikifr.champs
_section_de_serie = wikifr.section_de_serie
_dates = wikifr._dates
_puces = wikifr._puces











_liens_listes = wikifr.liens_listes


def details_tome(serie: str, tome) -> dict:
    """Infos d'un tome (titre, sortie en France, résumé, chapitres) d'après la mémoire de titres_tomes.
    Les chapitres n'apparaissent que s'ils ont un titre."""
    t = ((_charger(serie) or {}).get("titres_tomes") or {})
    d = {k: v for k, v in (t.get("details") or {}).get(str(int(tome)), {}).items() if k not in ("couverture", "isbn", "numeros")}
    if d.get("resume"):
        d["resume_source"] = "Wikipédia"
    if not d.get("chapitres"):                       # pas de liste en français : titres anglais connus pour ce tome
        info = _charger(serie) or {}
        titres_ch = info.get("titres") or {}
        nums = sorted(n for n, v in (info.get("tomes") or {}).items() if v is not None and int(v) == int(tome) and titres_ch.get(n))
        if nums:
            d["chapitres"] = [f"{n:g}. {titres_ch[n]}" for n in nums][:60]
            d["chapitres_langue"] = "en"
    if d.get("chapitres"):
        d["chapitres"] = [re.sub(r"(?<=\w)''(?=\w)", "'", c) for c in d["chapitres"]]
    if not d.get("titre") and (t.get("titres") or {}).get(str(int(tome))):
        d["titre"] = t["titres"][str(int(tome))]
    return d





def titres_tomes_bilan(serie: str, forcer=False, tome_max=None):
    """(titres, état, pannes) : l'état dit ce qui s'est passé — « deja » (déjà gardé et à jour), « ok » (trouvé), « partiel » (trouvé mais
    Wikipédia n'a pas répondu partout : refait dans l'heure), « vide » (Wikipédia ne connaît pas la série : réessais espacés) ou
    « panne » (Wikipédia n'a pas répondu : l'ancien contenu reste, rien n'est noté)."""
    garde = _charger(serie) or {}
    t = garde.get("titres_tomes") or {}
    anciens_titres, anciens_details = t.get("titres") or {}, t.get("details") or {}
    trouve = bool(anciens_titres or anciens_details)
    partiel_a_refaire = bool(t.get("partiel")) and time.time() - t.get("date", 0) > 3600
    if t and "details" in t and t.get("v") == VERSION_TITRES and not forcer and not partiel_a_refaire:
        manque = bool(tome_max) and trouve and any(str(n) not in (anciens_details or anciens_titres) for n in range(1, int(tome_max) + 1))
        if trouve and not (manque and time.time() - t.get("date", 0) > 7 * 86400):
            return anciens_titres, "deja", []
        if not trouve and garde_a_jour(t, garde, FICHE_DUREE, trouve=False):
            return anciens_titres, "deja", []
    st = garde.get("statut_officiel") or {}
    if st.get("statut") and not st.get("anilist"):        # fiche AniList d'avant (sans titre anglais) : refaite une fois
        st = statut_officiel(serie, forcer=True) or st
    fortes, faibles, autres = noms_de_recherche(serie, st)
    pannes, titres, details, pages_lues = [], {}, {}, []
    try:                                                  # anglais
        for page in (_pages_wiki(fortes[:6]) or [])[:8]:
            texte = _wikitexte(page)
            for bloc in re.split(r"\{\{\s*Graphic novel list", re.sub(r"<!--.*?-->", "", texte, flags=re.S))[1:]:
                vol = re.search(r"\|\s*VolumeNumber\s*=\s*(\d+)", bloc)
                tit = re.search(r"\|\s*LicensedTitle\s*=\s*([^\n|]+)", bloc) or re.search(r"\|\s*TranslitTitle\s*=\s*([^\n|]+)", bloc)
                if vol and tit and wikifr.propre(tit.group(1)):
                    titres[vol.group(1)] = wikifr.propre(tit.group(1))
    except reseau.Panne as e:
        pannes.append(e)
    fr = {}
    try:                                                  # français, prioritaire
        principale = wikifr.trouver_pages(fortes, faibles, autres)[:1]
        listes = wikifr.trouver_pages(fortes, faibles, autres, liste=True)
        # Liens de l'article et des pages « Liste… » qui renvoient vers leurs parties (One Piece : 6 parties)
        liens = [p for p in wikifr.liens_listes(principale) + wikifr.liens_listes(listes)
                 if wikifr.page_de_la_serie(p, fortes, faibles, autres)]       # seulement les listes de CETTE série (l'article de Boruto cite celles de Naruto)
        pages = list(dict.fromkeys(listes + liens + principale))
        for page in pages[:12]:
            avant = len(details)
            wikifr.lire_volumes(wikifr.section_de_serie(wikifr.wikitexte(page), serie), details)
            if len(details) > avant:
                pages_lues.append(page)
        meres = _parties_meres(serie)
        if meres and not details:                       # « Akame ga Kill ! : Zero » : sa liste est une section de la page de la série mère
            for page in wikifr.trouver_pages([], (), autres, liste=True, meres=meres)[:4]:
                if page not in pages:
                    section = wikifr.section_stricte(wikifr.wikitexte(page), serie)
                    if section:
                        wikifr.lire_volumes(section, details)
                        pages_lues.append(page + " (section)")
    except reseau.Panne as e:
        pannes.append(e)
    for vol, d in details.items():
        if d.get("titre"):
            fr[vol] = d["titre"]
    titres.update(fr)
    if not (titres or details):
        if pannes:
            logger.info("Titres des tomes de %s : Wikipédia n'a pas répondu (%s), l'ancien contenu reste", serie, pannes[0])
            return anciens_titres, "panne", pannes

        def vide(brut):                                   # Wikipédia a répondu : elle ne connaît pas la série
            ancien = brut.get("titres_tomes") or {}
            ancien.update(date=time.time(), v=VERSION_TITRES, essais=int(ancien.get("essais") or 0) + 1)
            ancien.setdefault("titres", {})
            ancien.setdefault("details", {})
            ancien.pop("partiel", None)
            brut["titres_tomes"] = ancien
        modifier(serie, vide)
        logger.info("Titres des tomes de %s : 0 trouvé(s)", serie)
        return anciens_titres, "vide", []

    def garder(brut):
        ancien = brut.get("titres_tomes") or {}
        memes_pages = bool(ancien.get("pages")) and sorted(ancien["pages"]) == sorted(pages_lues)
        if pannes or memes_pages:                                          # même source (ou source qui n'a pas tout donné) : rien ne se perd
            fusion = {}
            for vol in set(ancien.get("details") or {}) | set(details):
                fusion[vol] = {**((ancien.get("details") or {}).get(vol) or {}), **(details.get(vol) or {})}
            anciens = ancien.get("titres") or {}
        else:                                                              # d'autres pages, toutes lues : ce qu'on tenait d'ailleurs (un ancien mauvais
            fusion, anciens = details, {}                                  # rapprochement, Boruto avec les tomes de Naruto) est remplacé
        brut["titres_tomes"] = {"date": time.time(), "titres": {**anciens, **titres}, "details": fusion, "pages": pages_lues,
                                "v": VERSION_TITRES, **({"partiel": True} if pannes else {})}
    modifier(serie, garder)
    logger.info("Titres des tomes de %s : %d titre(s), %d volume(s) détaillé(s)%s", serie, len(titres), len(details),
                " (Wikipédia n'a pas répondu partout)" if pannes else "")
    return _charger(serie)["titres_tomes"]["titres"], ("partiel" if pannes else "ok"), pannes


def titres_tomes(serie: str, forcer=False, tome_max=None) -> dict:
    """{numéro de tome (texte): titre} : Wikipédia français (TomeBD, titre_2 = titre français) en priorité,
    sinon Wikipédia anglais (Graphic novel list : LicensedTitle, sinon TranslitTitle). La liste des volumes (dates, ISBN, résumés,
    chapitres) est gardée à côté dans « details ». Gardés pour de bon une fois trouvés ; redemandés seulement s'il manque un tome
    qu'on a (tome_max : nouveau tome), au plus une fois par semaine. Rien trouvé : réessais espacés."""
    return titres_tomes_bilan(serie, forcer, tome_max)[0]


# ---------------------------------------------------------------- Œuvres liées (hors-série, spin-off, gaiden…)
# AniList liste pour chaque manga ses œuvres liées (SIDE_STORY, SPIN_OFF…), avec titres, nombre de tomes et date
# de sortie au Japon. Elles servent à reconnaître un fichier (« Tokyo Revengers Letter from Keisuke Baji T01 ») et à
# le placer dans l'ordre de lecture d'après les dates japonaises des tomes (Wikipédia anglais), comme les épisodes
# spéciaux de TVDB (« après l'épisode 4 »).

_TYPES_LIES = {"SIDE_STORY", "SPIN_OFF", "ALTERNATIVE", "SEQUEL", "PREQUEL", "PARENT", "SUMMARY", "COMPILATION", "OTHER"}
_MOTS_VIDES = {"the", "a", "an", "of", "no", "to", "de", "la", "le", "les", "du", "des", "et", "and", "from", "kara", "manga",
               "fr", "vf", "cbz", "cbr", "digital", "ebook", "french", "integrale", "tome", "tomes", "vol", "volume", "edition"}


def _cle_connaissance(serie):
    """Clé d'une série dans data/connaissances.sqlite : son numéro AniList (il ne change pas si on renomme la série)."""
    ident = ((_charger(serie) or {}).get("statut_officiel") or {}).get("anilist")
    return f"anilist:{ident}" if ident else None


def relations(serie: str, forcer=False) -> list[dict]:
    """Œuvres liées à la série sur AniList (romans exclus) : [{id, relation, format, volumes, debut "AAAA-MM-JJ", titres}].
    Apprises une fois pour toutes (data/connaissances.sqlite) ; forcer=True (un fichier porte un titre inconnu : il y a
    peut-être une nouvelle œuvre) redemande à AniList, au plus une fois par jour. [] si la série n'est pas sur AniList."""
    import connaissances
    cle = _cle_connaissance(serie)
    if not cle:
        return []
    ident = int(cle.split(":")[1])
    garde = connaissances.oeuvres_liees(cle)
    if garde is not None and connaissances.derniere_demande(cle, "mangaupdates") is None:
        try:                                             # liste apprise avant que MangaUpdates ne serve : complétée une fois
            connaissances.garder_oeuvres_liees(cle, _relations_mangaupdates(serie, garde))
            connaissances.garder_demande(cle, "mangaupdates")
            garde = connaissances.oeuvres_liees(cle)
        except Exception as e:
            logger.info("Œuvres liées de %s (MangaUpdates) : %s", serie, e.__class__.__name__)
    if garde is not None and (not forcer or time.time() - (connaissances.derniere_demande(cle, "oeuvres_liees") or 0) < 86400):
        return garde
    q = ("query($i:Int){Media(id:$i,type:MANGA){relations{edges{relationType node{id type format volumes "
         "title{romaji english native} synonyms startDate{year month day}}}}}}")
    try:
        aretes = ((reseau.anilist(q, {"i": ident}) or {}).get("Media") or {})["relations"]["edges"]
    except (reseau.Panne, KeyError, TypeError) as e:
        logger.info("Œuvres liées de %s : %s", serie, e.__class__.__name__)
        return garde or []
    liste = []
    for a in aretes:
        n = a.get("node") or {}
        if n.get("type") != "MANGA" or n.get("format") == "NOVEL" or a.get("relationType") not in _TYPES_LIES:
            continue
        d = n.get("startDate") or {}
        t = n.get("title") or {}
        liste.append({"id": n.get("id"), "relation": a["relationType"], "format": n.get("format"), "volumes": n.get("volumes"),
                      "debut": "%04d-%02d-%02d" % (d["year"], d.get("month") or 1, d.get("day") or 1) if d.get("year") else "",
                      "titres": [x for x in (t.get("english"), t.get("romaji"), *(n.get("synonyms") or [])) if x]})
    try:
        liste += _relations_mangaupdates(serie, liste)
        connaissances.garder_demande(cle, "mangaupdates")
    except Exception as e:
        logger.info("Œuvres liées de %s (MangaUpdates) : %s", serie, e.__class__.__name__)
    connaissances.garder_oeuvres_liees(cle, liste)
    return connaissances.oeuvres_liees(cle) or []


_RELATIONS_MU = {"side story": "SIDE_STORY", "spin-off": "SPIN_OFF", "sequel": "SEQUEL", "prequel": "PREQUEL",
                 "alternate story": "ALTERNATIVE", "main story": "PARENT"}


def _deja_connue(titres, liste):
    """Une œuvre MangaUpdates est-elle déjà dans la liste d'AniList (mêmes mots de titre) ?"""
    for titre in titres:
        mt = set(_mots(titre))
        for o in liste:
            for t in o.get("titres") or []:
                mo = set(_mots(t))
                if mt and mo and len(mt & mo) / max(len(mt), len(mo)) >= 0.6:
                    return True
    return False


def _relations_mangaupdates(serie: str, liste: list[dict]) -> list[dict]:
    """Œuvres liées d'après MangaUpdates, que la fiche AniList de la série ne cite pas (liens à sens unique : « Naruto
    Gaiden » ne figure pas dans la fiche AniList de Naruto, mais MangaUpdates le donne comme suite). Romans exclus.
    Date : l'année seulement (fin d'année, faute de mieux)."""
    mu = ((_charger(serie) or {}).get("fiche") or {}).get("mangaupdates")
    if not mu:
        return []
    d = reseau.get(f"https://api.mangaupdates.com/v1/series/{mu}").json()
    out = []
    for z in d.get("related_series") or []:
        rel = _RELATIONS_MU.get((z.get("relation_type") or "").lower())
        nom = z.get("related_series_name") or ""
        if not rel or re.search(r"\((?:novel|light novel)\)|\bdj\b", nom, re.I) or _deja_connue([nom], liste):
            continue
        try:
            x = reseau.get(f"https://api.mangaupdates.com/v1/series/{z['related_series_id']}").json()
        except reseau.Panne:
            continue
        if (x.get("type") or "").lower() not in ("manga", "manhwa", "manhua"):
            continue
        vol = re.search(r"(\d+)\s*Volumes?", x.get("status") or "", re.I)
        titres = [x.get("title") or nom] + [a.get("title") for a in x.get("associated") or [] if a.get("title")][:8]
        if _deja_connue(titres, liste):
            continue
        out.append({"id": int(z["related_series_id"]), "relation": rel, "format": "MANGA",
                    "volumes": int(vol.group(1)) if vol else (0 if re.search(r"chapter|oneshot", x.get("status") or "", re.I) else None),
                    "debut": f"{x['year']}-12-31" if str(x.get("year") or "").isdigit() else "", "titres": titres})
        time.sleep(0.3)
    return out


def _mots(texte: str) -> list[str]:
    return [m for m in _simple(texte).split() if m not in _MOTS_VIDES and not m.isdigit() and not re.fullmatch(r"t\d+", m)]


def reste_du_nom(serie: str, nom: str) -> list[str]:
    """Mots du nom de fichier qui ne sont pas ceux de la série, avant le numéro de tome et sans les mots d'édition :
    « Tokyo.Revengers.Letter.from.Keisuke.Baji.T01.Ken.Wakui » → [letter, keisuke, baji]. [] si rien de plus."""
    import noms_editions
    t = re.sub(r"[._]+", " ", nom)
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", t)
    t = noms_editions.MENTION.sub(" ", t)
    t = re.split(r"\b(?:t|tome|vol\.?|volume)\s*\d", t, maxsplit=1, flags=re.I)[0]
    mots_serie = set(_simple(serie).split())
    return [m for m in _mots(t) if m not in mots_serie]


def classer(serie: str, nom: str, liste=None) -> dict | None:
    """Œuvre liée dont le nom du fichier porte le titre (au moins la moitié de ses mots distinctifs), ou None."""
    reste = set(reste_du_nom(serie, nom))
    if not reste:
        return None
    mots_serie = set(_simple(serie).split())
    meilleure, score = None, 0.0
    for rel in (liste if liste is not None else relations(serie)):
        for titre in rel.get("titres") or []:
            mt = {m for m in _mots(titre) if m not in mots_serie}
            if not mt:
                continue
            communs = {m for m in mt & reste if len(m) >= 4}
            s = len(mt & reste) / len(mt)
            if communs and s >= 0.5 and s > score:
                meilleure, score = rel, s
    if meilleure:
        return meilleure
    # « Naruto Gaiden » : tous les mots du nom sont dans le titre d'une œuvre (« NARUTO Gaiden: Nanadaime Hokage… ») ;
    # gardé seulement si une seule œuvre de ce genre fait au moins un tome (sinon : impossible de choisir)
    if not any(len(m) >= 4 for m in reste):
        return None
    candidates = [rel for rel in (liste if liste is not None else relations(serie))
                  if (rel.get("volumes") or 0) >= 1 and any(reste <= {m for m in _mots(t)} for t in rel.get("titres") or [])]
    return candidates[0] if len(candidates) == 1 else None


def chercher_oeuvre(serie: str, nom: str):
    """Recherche « dans l'autre sens » : le nom du fichier sur AniList, quand la fiche de la série ne cite pas l'œuvre.
    Gardée si son titre commence par le nom de la série et contient tous les mots du nom ; ajoutée pour de bon aux
    œuvres liées de la série. Une même recherche n'est jamais refaite."""
    import connaissances
    cle = _cle_connaissance(serie)
    reste = reste_du_nom(serie, nom)
    if not cle or not reste:
        return None
    sujet = "recherche:" + " ".join(reste)
    if connaissances.derniere_demande(cle, sujet) is not None:
        return None
    relations(serie)                                     # la liste complète d'abord : la trouvaille s'y ajoute
    q = ("query($s:String){Page(perPage:8){media(search:$s,type:MANGA,format_not:NOVEL){id format volumes "
         "title{romaji english} synonyms startDate{year month day}}}}")
    try:
        medias = ((reseau.anilist(q, {"s": f"{serie} {' '.join(reste)}"}) or {}).get("Page") or {}).get("media")
    except reseau.Panne:
        medias = None
    if medias is None:
        return None
    base = _simple(serie)
    trouvees = []
    for m in medias:
        titres = [x for x in (m["title"].get("english"), m["title"].get("romaji"), *(m.get("synonyms") or [])) if x]
        if any(_simple(t).startswith(base) and set(reste) <= set(_mots(t)) for t in titres) and (m.get("volumes") or 0) >= 1:
            d = m.get("startDate") or {}
            trouvees.append({"id": m["id"], "relation": "SIDE_STORY", "format": m.get("format"), "volumes": m.get("volumes"),
                             "debut": "%04d-%02d-%02d" % (d["year"], d.get("month") or 1, d.get("day") or 1) if d.get("year") else "",
                             "titres": titres})
    connaissances.garder_demande(cle, sujet)
    if len(trouvees) != 1:
        return None
    connaissances.garder_oeuvres_liees(cle, trouvees)
    return trouvees[0]


def dates_japon(serie: str, tome_max=None, forcer=False) -> dict:
    """{tome (texte): "AAAA-MM-JJ"} : sortie au Japon de chaque tome (Wikipédia anglais, OriginalRelDate). Apprises une
    fois pour toutes (data/connaissances.sqlite) ; redemandées seulement s'il manque la date d'un tome qu'on a
    (tome_max : un nouveau tome est sorti), au plus une fois par semaine."""
    import connaissances
    cle = _cle_connaissance(serie) or f"nom:{_simple(serie)}"
    garde = connaissances.dates_tomes(cle)
    derniere = connaissances.derniere_demande(cle, "dates_tomes")
    manque = bool(tome_max) and any(str(t) not in garde for t in range(1, int(tome_max) + 1))
    if derniere is not None and not forcer and not (manque and time.time() - derniere > 7 * 86400):
        return garde
    st = (_charger(serie) or {}).get("statut_officiel") or {}
    noms = list(dict.fromkeys([x for x in (st.get("titre"), st.get("titre_en")) if x] + _variantes(serie)))
    dates = {}
    try:
        for page in _pages_wiki(noms):
            texte = _wiki({"action": "parse", "page": page, "prop": "wikitext", "redirects": 1}).get("parse", {}).get("wikitext", "")
            for bloc in re.split(r"\{\{\s*Graphic novel list", re.sub(r"<!--.*?-->", "", texte, flags=re.S))[1:]:
                vol = re.search(r"\|\s*VolumeNumber\s*=\s*(\d+)", bloc)
                d = _date_wiki((re.search(r"\|\s*OriginalRelDate\s*=\s*([^\n<]*)", bloc) or [None, ""])[1])
                if vol and d:
                    dates.setdefault(vol.group(1), d)           # 1re liste = édition d'origine (pas les rééditions plus bas)
    except Exception as e:
        logger.info("Dates japonaises de %s : %s", serie, e.__class__.__name__)
        return garde
    connaissances.garder_dates_tomes(cle, dates)
    return connaissances.dates_tomes(cle)


def place_par_date(serie: str, debut: str, tome_max=None):
    """Dernier tome sorti au Japon avant (ou le même jour que) l'œuvre liée : elle se lit après lui. None si inconnu."""
    if not debut:
        return None
    avant = [int(t) for t, d in dates_japon(serie, tome_max).items() if d and d <= debut]
    return max(avant) if avant else None


_MOIS_EN = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                        "october", "november", "december"], 1)}


def _date_wiki(v: str) -> str:
    """« {{Start date|2017|5|17}} », « May 17, 2017 » ou « 17 May 2017 » → « 2017-05-17 » ; "" sinon."""
    m = re.search(r"(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})", v)
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", v) or re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", v)
    if m:
        a, b, annee = m.groups()
        mois, jour = (a, b) if a.isalpha() else (b, a)
        if mois.lower() in _MOIS_EN:
            return "%s-%02d-%02d" % (annee, _MOIS_EN[mois.lower()], int(jour))
    return ""
