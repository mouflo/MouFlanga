"""
Ce qu'Internet dit de chaque tome (ISBN, résumé, titre, éditeur, pages), source par source.

Chaque source (Wikipédia, BnF, Google Books) a sa propre « observation » par tome, gardée dans data/tomes/<série>.json sous
« notices ». Une nouvelle recherche remplace seulement l'observation de CETTE source pour CE tome : un échec, une réponse vide ou
un quota atteint n'effacent jamais ce qu'une autre source (ou la même, une autre fois) avait donné. Le choix de ce qu'on affiche
se fait à la lecture :
- ISBN : le même ISBN chez deux sources compte pour sûr ; sinon Wikipédia (relue par des humains) puis la BnF (le catalogue
  officiel des livres français) puis Google ;
- résumé : Wikipédia, puis la BnF, puis Google (le premier qui en a un, sans la présentation de la série répétée sur chaque tome).
Les données d'avant (la liste des volumes de Wikipédia dans « titres_tomes », les résumés Google dans « resumes_tomes ») sont lues
comme des observations de leur source : rien à convertir.
"""
import logging
import time

import tomes

logger = logging.getLogger("mouflanga")

SOURCES = ("wikipedia", "bnf", "google")                 # ordre de confiance
LIBELLES = {"wikipedia": "Wikipédia", "bnf": "BnF", "google": "Google Books"}


def enregistrer(serie: str, source: str, par_tome: dict):
    """Garde les observations d'une source : {tome: {isbn, resume, titre, editeur, date, pages, autres_isbn}}. Pour chaque tome
    donné, l'observation de cette source est remplacée ; les tomes non cités gardent la leur."""
    if not par_tome:
        return

    def appliquer(brut):
        notices = brut.setdefault("notices", {})
        for tome, obs in par_tome.items():
            propre = {k: v for k, v in obs.items() if v not in (None, "", [])}
            if propre:
                notices.setdefault(str(int(tome)), {})[source] = {**propre, "vu": time.time()}
    tomes.modifier(serie, appliquer)


def observations(serie: str) -> dict:
    """{tome (texte): {source: observation}} avec les sources d'avant (liste de Wikipédia, résumés Google) mêlées aux nouvelles."""
    brut = tomes._charger(serie) or {}
    out = {t: {s: dict(o) for s, o in par.items()} for t, par in (brut.get("notices") or {}).items()}
    if brut.get("edition_differente"):                    # Perfect, Deluxe… : les tomes de Wikipédia et les anciens résumés sont d'une autre édition
        return out
    for t, d in (((brut.get("titres_tomes") or {}).get("details")) or {}).items():
        mots = {k: d[k] for k in ("isbn", "resume", "titre", "sortie") if d.get(k)}
        if mots:
            out.setdefault(str(t), {}).setdefault("wikipedia", mots)
    for t, g in (brut.get("resumes_tomes") or {}).items():
        if (g or {}).get("texte"):
            out.setdefault(str(t), {}).setdefault("google", {"resume": g["texte"], "vu": g.get("date", 0)})
    return out


def isbn_du_tome(obs_du_tome: dict):
    """(isbn, [sources], [autres isbn]) d'après les observations d'un tome, ou ("", [], []) : le même ISBN chez deux sources gagne ;
    sinon la source la plus sûre."""
    candidats = {}
    for s in SOURCES:
        o = (obs_du_tome or {}).get(s) or {}
        for i in [o.get("isbn")] + list(o.get("autres_isbn") or []):
            if i:
                candidats.setdefault(i, [])
                if s not in candidats[i]:
                    candidats[i].append(s)
    if not candidats:
        return "", [], []
    principaux = [(o.get("isbn"), s) for s in SOURCES for o in [(obs_du_tome or {}).get(s) or {}] if o.get("isbn")]
    choisi = max(candidats, key=lambda i: (len(candidats[i]), -min((SOURCES.index(s) for s in candidats[i]), default=9),
                                           i in [p[0] for p in principaux]))
    return choisi, candidats[choisi], [i for i in candidats if i != choisi]


def isbn_web(serie: str) -> dict:
    """{tome (texte): ISBN} trouvés sur Internet (Wikipédia, BnF, Google)."""
    return {t: i for t, par in observations(serie).items() for i in [isbn_du_tome(par)[0]] if i}


def isbn_details(serie: str, tome) -> dict:
    """{isbn, sources (libellés), autres} d'un tome, ou {}."""
    i, sources, autres = isbn_du_tome(observations(serie).get(str(int(tome))) or {})
    return {"isbn": i, "sources": [LIBELLES[s] for s in sources], "autres": autres} if i else {}


def resumes_de(serie: str, tomes_voulus) -> dict:
    """{tome: (résumé, libellé de la source)} de ces tomes (("", "") quand il n'y en a pas) : le premier des sources qui en a un —
    Wikipédia, puis la BnF, puis Google Books —, sans la présentation de la série qui se répète sur chaque tome (voir
    tomes._resume_de_serie). Le travail de comparaison entre tomes n'est fait qu'une fois pour tous."""
    obs = observations(serie)
    brut = dict(tomes._charger(serie) or {})
    pool = {}
    for t, par in obs.items():                           # le meilleur texte de chaque tome : sert à reconnaître ce qui se répète
        texte = next((par[s]["resume"] for s in SOURCES if (par.get(s) or {}).get("resume")), "")
        if texte:
            pool[t] = {"texte": texte}
    brut["resumes_tomes"] = pool
    brut["intros"] = list(brut.get("intros") or [])
    out = {}
    for n in sorted({int(t) for t in tomes_voulus}):
        out[n] = ("", "")
        if str(n) not in pool:
            continue                                      # aucune source n'a de résumé pour ce tome
        for s in SOURCES:
            texte = ((obs.get(str(n)) or {}).get(s) or {}).get("resume") or ""
            if not texte:
                continue
            propre = tomes._resume_de_serie(texte, brut, n)
            if propre:
                out[n] = (propre, LIBELLES[s])
                break
    return out


def resume_du_tome(serie: str, tome):
    """(résumé, libellé de la source) du tome, ou ("", "") : voir resumes_de."""
    return resumes_de(serie, [tome])[int(tome)]


def manquants(serie: str, tomes_voulus, champ: str = "isbn") -> list:
    """Parmi ces tomes, ceux pour lesquels aucune source n'a le champ (« isbn » ou « resume »)."""
    voulus = sorted({int(x) for x in tomes_voulus})
    if champ == "isbn":
        obs = observations(serie)
        return [t for t in voulus if not isbn_du_tome(obs.get(str(t)) or {})[0]]
    resumes = resumes_de(serie, voulus)
    return [t for t in voulus if not resumes[t][0]]


def a_cherche(serie: str, source: str, tome) -> bool:
    """Cette source a-t-elle déjà une observation pour ce tome ?"""
    return bool((observations(serie).get(str(int(tome))) or {}).get(source))
