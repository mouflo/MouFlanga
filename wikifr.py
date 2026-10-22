"""
Wikipédia en français : les pages d'une série (article, « Liste des chapitres de … ») et la liste de ses volumes (modèle
TomeBD : titre, date et ISBN français, résumé, couverture, chapitres avec leurs titres).

Tout ce qui lit Internet passe par reseau.py : une panne lève `reseau.Panne`, elle n'est jamais prise pour « page absente ».
Les fonctions de lecture du texte (`lire_volumes`, `section_de_serie`) ne touchent pas à Internet : on les essaie sur des
pages enregistrées (tests/fixtures).
"""
import logging
import re

import correspondance
import reseau

logger = logging.getLogger("mouflanga")

URL = "https://fr.wikipedia.org/w/api.php"


# ---------------------------------------------------------------- Internet

def requete(params: dict, memo: int = 600) -> dict:
    return reseau.get(URL, params={**params, "format": "json"}, memo=memo).json()


def rechercher(texte: str, limite: int = 5) -> list:
    """Titres des pages qui répondent à la recherche (les plus pertinents d'abord)."""
    r = requete({"action": "query", "list": "search", "srsearch": texte, "srlimit": limite})
    return [x["title"] for x in (r.get("query") or {}).get("search") or []]


def wikitexte(page: str) -> str:
    """Wikitexte d'une page (redirections suivies) ; "" si elle n'existe pas."""
    r = requete({"action": "parse", "page": page, "prop": "wikitext", "redirects": 1})
    return ((r.get("parse") or {}).get("wikitext") or {}).get("*", "") or ""


def extrait(page: str, intro: bool = False) -> str:
    """Texte brut de la page (ou de son introduction)."""
    params = {"action": "query", "prop": "extracts", "explaintext": 1, "titles": page, "formatversion": 2}
    if intro:
        params["exintro"] = 1
    d = requete(params)
    return ((d.get("query", {}).get("pages") or [{}])[0].get("extract") or "")


def liens_listes(pages: list) -> list:
    """Pages « Liste des chapitres / volumes / tomes de … » liées depuis ces pages (une série longue est coupée en parties)."""
    out = []
    for page in [p for p in pages if p][:4]:
        r = requete({"action": "query", "prop": "links", "titles": page, "pllimit": 500, "plnamespace": 0, "redirects": 1})
        for pg in (r.get("query", {}).get("pages") or {}).values():
            out += [x["title"] for x in pg.get("links", []) if re.match(r"Liste des (chapitres|volumes|tomes) d", x["title"])
                    and "dérivé" not in x["title"] and "hors-série" not in x["title"].lower()]
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- Quelle page est celle de la série ?

def titre_nu(titre: str) -> str:
    """« Liste des chapitres de Naruto (1re partie) » → « Naruto » ; « Arago (manga) » → « Arago »."""
    t = re.sub(r"^Liste des (?:chapitres|volumes|tomes)(?: et épisodes)?\s+(?:de |du |des |d['’])\s*", "", titre or "")
    return re.sub(r"\s*\((?:manga|série|[^)]*partie|[^)]*saison[^)]*)\)\s*$", "", t).strip()


def page_de_la_serie(titre: str, fortes, faibles=(), autres=()) -> bool:
    return correspondance.titre_de_la_serie(titre_nu(titre), fortes, autres, faibles=faibles)


def trouver_pages(fortes, faibles=(), autres=(), liste: bool = False, limite: int = 5, meres=()) -> list:
    """Pages Wikipédia de la série (article, ou listes de chapitres si liste=True), les plus sûres d'abord. Chaque nom est cherché
    tel quel puis avec « manga » (le moteur de Wikipédia ne voit pas « Ken-ichi » dans « Kenichi » : les autres noms d'AniList
    et le lien depuis l'article rattrapent). `meres` : noms de la série mère d'une « Série : Suite » (« Akame ga Kill ! » pour
    « Akame ga Kill ! : Zero ») ; leurs pages sont rendues à la fin, pour qu'on y cherche la SECTION de la suite
    (voir section_stricte). Lève reseau.Panne si Wikipédia ne répond pas."""
    trouvees = []
    for nom in [n for n in dict.fromkeys(fortes) if correspondance.jetons(n)][:4]:
        requetes = [f'intitle:"Liste des chapitres" {nom}', f'intitle:"Liste des volumes" {nom}'] if liste else [f"{nom} manga"]
        for q in requetes:
            for titre in rechercher(q, limite):
                if not liste and titre.startswith(("Liste des ", "Liste de ", "Liste d'")):
                    continue                                       # l'article de la série, pas ses listes (l'infobox est dans l'article)
                if titre not in trouvees and page_de_la_serie(titre, fortes, faibles, autres):
                    trouvees.append(titre)
        if trouvees and not liste:
            break
    for nom in [n for n in dict.fromkeys(meres) if correspondance.jetons(n)][:2]:
        for q in ([f'intitle:"Liste des chapitres" {nom}'] if liste else []) + [f"{nom} manga"]:
            for titre in rechercher(q, limite):
                if titre not in trouvees and page_de_la_serie(titre, [nom], (), autres):
                    trouvees.append(titre)
    return trouvees


# ---------------------------------------------------------------- Lire la liste des volumes (modèle TomeBD)

def propre(v: str) -> str:
    """Texte wiki → texte simple (liens, modèles, notes retirés)."""
    v = re.sub(r"\{\{\s*(\d+)\s*(?:e|er|re|ème)\s*\|\s*([^}|]*)\}\}", lambda m: m.group(1) + "e " + m.group(2), v or "")   # {{7e|district}}
    v = re.sub(r"\{\{\s*(1e|1re|1er|e|er|re)\s*\|([^}]*)\}\}", lambda m: ("1re " if m.group(1).startswith("1") else "e ") + m.group(2), v or "")
    v = re.sub(r"<ref.*?(</ref>|/>)|<[^>]+>", "", v or "", flags=re.S)
    v = re.sub(r"\{\{\s*(?:nowrap|lang|nihongo|japonais)\s*\|(?:[a-z]{2}\|)?([^|}]*)[^}]*\}\}", r"\1", v, flags=re.I)
    v = re.sub(r"\{\{[^}]*\}\}", "", v)
    v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", v).replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", v).strip(" .,-–—")


def champs(bloc: str) -> dict:
    """Paramètres d'un modèle TomeBD (valeurs sur plusieurs lignes comprises)."""
    out = {}
    for m in re.finditer(r"\n\s*\|\s*([\wé]+)\s*=(.*?)(?=\n\s*\|\s*[\wé]+\s*=|\n\}\}|\Z)", "\n" + bloc, re.S):
        out.setdefault(m.group(1), m.group(2).strip())
    return out


def _dates(v: str) -> str:
    return re.sub(r"\{\{\s*date\s*\|([^|}]*)\|([^|}]*)\|([^|}]*)[^}]*\}\}", r"\1 \2 \3", v or "", flags=re.I)


def _puces(v: str) -> str:
    return re.sub(r"^\*\s*", " • ", v or "", flags=re.M)


def isbn(v: str) -> str:
    """ISBN-13 (chiffres seuls) d'une valeur « 978-2-368-52044-4 » ou « 2-84599-668-3 » ; "" s'il est faux ou absent."""
    import bnf
    m = re.search(r"[\dXx][\dXx\- ]{8,16}[\dXx]", re.sub(r"<ref.*?(</ref>|/>)", "", v or "", flags=re.S))
    return bnf.isbn13(m.group(0)) if m else ""


_ORDINAUX = {"premier": 1, "première": 1, "deuxième": 2, "second": 2, "seconde": 2, "troisième": 3, "quatrième": 4, "cinquième": 5,
             "sixième": 6, "septième": 7, "huitième": 8, "neuvième": 9, "dixième": 10, "onzième": 11, "douzième": 12,
             "treizième": 13, "quatorzième": 14, "quinzième": 15, "seizième": 16}
_UNITES = {"un": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11,
           "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16}
_DIZAINES = {"vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60, "cent": 100}


def ordinal(mot: str):
    """« Cinquième » → 5, « Trente-deuxième » → 32, « Vingt et unième » → 21 ; None si ce n'est pas un ordinal."""
    m = re.sub(r"[-\s]+", " ", (mot or "").lower().replace("œ", "oe")).strip()
    m = m.replace(" et ", " ").replace("ième", "").replace("ieme", "")
    if m in _ORDINAUX:
        return _ORDINAUX[m]
    brut = re.sub(r"[-\s]+", " ", (mot or "").lower()).strip().replace(" et ", " ")
    if not re.search(r"(ième|ieme)$", brut):
        return None
    mots = brut[:-4].split()
    total, ok = 0, bool(mots)
    for w in mots:
        w = {"quatr": "quatre", "cinqu": "cinq", "neuv": "neuf", "onz": "onze", "douz": "douze", "treiz": "treize", "quatorz": "quatorze",
             "quinz": "quinze", "seiz": "seize"}.get(w, w)
        if w in _DIZAINES:
            total += _DIZAINES[w]
        elif w in _UNITES:
            total += _UNITES[w]
        elif w == "vingts":
            total += 20
        else:
            ok = False
    return total if ok and total else None


_ROMAINS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def romain(t: str):
    """« VI » → 6, « XIV » → 14 ; None si ce n'est pas un nombre romain."""
    if not t or not re.fullmatch(r"[IVXLC]{1,7}", t):
        return None
    total = 0
    for i, c in enumerate(t):
        v = _ROMAINS[c]
        total += -v if i + 1 < len(t) and _ROMAINS[t[i + 1]] > v else v
    return total or None


def _marquer(ligne: str) -> str:
    """Ligne wiki → texte plat où le titre français d'un modèle {{japonais|Titre|日本語|romaji}} est entouré de ⟦ ⟧."""
    l = ligne.strip().lstrip("*#").strip().replace("'" * 3, "").replace("''", "")
    l = re.sub(r"<ref.*?(</ref>|/>)|</?(?:small|br\s*/?|div|span)[^>]*>", " ", l, flags=re.S)
    l = re.sub(r"\{\{\s*c(pique|coeur|cœur|trèfle|carreau)\s*\}\}", lambda m: {"pique": "♠", "coeur": "♥", "cœur": "♥", "trèfle": "♣", "carreau": "♦"}[m.group(1)], l)
    l = re.sub(r"\{\{\s*[Cc]hap(?:itre)?\.?\s*\|\s*(\d+(?:\.\d+)?)\s*\}\}", r"Chapitre \1", l)           # {{Chap.|5}}
    l = re.sub(r"\{\{\s*(\d+)\s*(?:e|er|re|ème|è|nd|nde)\s*(?:\|\s*([^}]*))?\}\}", lambda m: f"{m.group(1)}e {m.group(2) or ''}", l)
    l = re.sub(r"\{\{\s*(?:japonais|nihongo)\s*\|\s*(?:[a-z]{2}\|)?([^|}]*)(?:\|[^}]*)?\}\}", lambda m: f"⟦{m.group(1).strip()}⟧", l, flags=re.I)
    l = re.sub(r"\{\{\s*(?:lang|langue)\s*\|\s*[a-z-]+\s*\|([^}]*)\}\}", r"⟦\1⟧", l, flags=re.I)
    l = re.sub(r"\{\{[^{}]*\}\}", "", l)
    l = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", l)
    return re.sub(r"\s+", " ", l).strip()


_LIGNE = re.compile(
    r"^(?P<mot>[^\W\d_][^\W\d_'’]*[.-]?(?: [^\W\d_][^\W\d_'’]*[.-]?)?\s*[:=]?\s*)?(?:n°\s*|no\.?\s*|#\s*)?"
    r"(?P<n>\d+(?:\.\d+)?|[IVXLC]{1,7}\b)(?:e|er|re|ème)?\b(?:\s+(?P<apres>[^\W\d_]+)(?=\s*[-–:.)]|\s*⟦))?"
    r"\s*(?:[-–:.)=]\s*|\s+(?=⟦|[A-Za-zÀ-ÿ\"«“(\[])|$)(?P<t>.*)$")


def ligne_de_chapitre(ligne: str):
    """(numéro, titre) d'une ligne de liste de chapitres, ou None ; le titre est "" quand la liste ne donne que le numéro
    (« * Chapitre 24 », « * Trick:25 », ou un titre japonais seul). Le titre français est celui du modèle {{japonais|Titre|…}} quand
    il y en a un, sinon le texte qui suit le numéro."""
    l = _marquer(ligne)
    m0 = re.fullmatch(r"⟦([^⟧]*)⟧", l)
    if m0:
        l = m0.group(1).strip()                          # {{langue|en|Episode 20 : Titre}} : toute la ligne est le modèle
    if not l or l.startswith(("♭", "♯", "[")):
        return None
    m = _LIGNE.match(l)
    n = None
    if m:
        brut = m.group("n")
        n = float(brut) if brut[0].isdigit() else (float(romain(brut)) if romain(brut) else None)
        if n is not None and brut[0].isalpha() and not (m.group("mot") or "").strip():
            n = None                                   # « I » ou « V » seuls : pas un numéro
    if n is None:
        mo = re.match(r"^([A-Za-zÀ-ÿ\- ]+?)\s+(?:épisode|chapitre|acte|scène)\s*[:\-–]?\s*(.*)$", l, re.I)
        if mo and ordinal(mo.group(1)):
            titre = re.search(r"⟦([^⟧]*)⟧", mo.group(2))
            texte = (titre.group(1) if titre else re.sub(r"[⟦⟧]", "", mo.group(2))).strip(" .,-–—:")
            return float(ordinal(mo.group(1))), texte
        return None
    fr = re.search(r"⟦([^⟧]*)⟧", m.group("t"))
    titre = (fr.group(1) if fr else re.sub(r"[⟦⟧]", "", m.group("t"))).strip(" .,-–—:")
    return n, titre


def chapitres(brut: str) -> list:
    """[(numéro, titre)] des chapitres d'un volume d'après le champ « chapitre » de TomeBD. Formes rencontrées : « * Ch.1 : titre »,
    « * \'\'\'Kill 1 -\'\'\' {{japonais|titre|…}} », « * Battle 3 - titre », « * Précepte 5 - titre », « * 12. titre », « * {{Chap.|5}} : … »,
    « * \'\'\'{{8e|geôle}}\'\'\' : … », « * Retrace VI : … » (chiffres romains), « * Premier épisode : … » (en toutes lettres),
    « Kapitel.1 {{japonais|…}}<br /> »."""
    brut = brut or ""
    lignes = [l for l in brut.split("\n") if l.strip().startswith(("*", "#"))]
    if not lignes:                                               # « Kapitel.1 … <br /> Kapitel.2 … » : une ligne par <br />
        lignes = [x for x in re.split(r"<br\s*/?>|\n", brut) if x.strip()]
    out = []
    for l in lignes:
        r = ligne_de_chapitre(l)
        if r:
            out.append(r)
    return out


def section_de_serie(wikitexte: str, serie: str) -> str:
    """Une page Wikipédia qui liste les volumes de plusieurs séries (« Red Eyes Sword: Akame ga Kill! », « … Zero », « Blue Eyes
    Sword: Hinowa ga Crush! », chacune sous son titre ====) : ne garde que la section de CETTE série. Le titre de la section
    doit contenir tous les mots du nom de la série ; à égalité, celui qui a le moins de mots en plus (la série principale ne
    prend pas la section « Zero »). Une page à une seule liste, ou sans correspondance, reste telle quelle."""
    coupes = [m.start() for m in re.finditer(r"\{\{\s*TomeBD/Entête", wikitexte)]
    if len(coupes) < 2:
        return wikitexte
    mots = set(correspondance.jetons(serie))
    if not mots:
        return wikitexte
    candidats = []
    for k, debut in enumerate(coupes):
        fin = coupes[k + 1] if k + 1 < len(coupes) else len(wikitexte)
        titres = [m for m in re.finditer(r"^={3,4}\s*(.+?)\s*={3,4}\s*$", wikitexte[:debut], re.M)]
        titre = correspondance.simple(titres[-1].group(1)) if titres else ""
        # fin = la section suivante OU le prochain titre de même niveau (la page continue avec « Anime »…)
        suite = re.search(r"^={2,4}[^=\n]+={2,4}\s*$", wikitexte[debut:fin], re.M)
        if suite:
            fin = debut + suite.start()
        mots_titre = set(titre.split())
        if mots <= mots_titre:
            candidats.append((len(mots_titre - mots), wikitexte[debut:fin]))
    if not candidats:
        return wikitexte
    return min(candidats, key=lambda c: c[0])[1]


def section_stricte(wikitexte: str, serie: str):
    """La section de CETTE série dans une page qui liste les volumes de plusieurs séries, ou None : page à une seule liste, ou aucune
    section dont le titre contient tous les mots du nom (c'est alors la page d'une autre série, jamais la sienne)."""
    if len(re.findall(r"\{\{\s*TomeBD/Entête", wikitexte)) < 2:
        return None
    mots = set(correspondance.jetons(serie))
    if not mots:
        return None
    morceau = section_de_serie(wikitexte, serie)
    return morceau if morceau is not wikitexte and morceau != wikitexte else None


def lire_volumes(wikitexte: str, deja: dict = None) -> dict:
    """{numéro de volume (texte): {titre, sortie, isbn, couverture, resume, chapitres}} d'une page de liste de volumes. `deja` :
    volumes déjà lus (la première apparition d'un volume gagne : la 1re édition, pas la « perfect » plus bas)."""
    details = deja if deja is not None else {}
    langue_fr = "2"                                   # quel champ « titre_N » / « isbn_N » est en français (d'après TomeBD/Entête)
    for bloc in re.split(r"\{\{\s*TomeBD", wikitexte)[1:]:
        if bloc.startswith("/Entête"):
            m = re.search(r"\|\s*langue_(\d)\s*=\s*Fran", bloc)
            langue_fr = m.group(1) if m else "1"
            continue
        vol = re.search(r"\|\s*volume\s*=\s*(\d+)", bloc)
        if not vol or vol.group(1) in details:
            continue
        c = champs(bloc)
        titre = propre(c.get("titre_" + langue_fr, ""))
        extra = c.get("extra", "")
        m_t = re.search(r"Titre du volume\s*:?\s*'*\s*(?:<br\s*/?>)?(.+?)(?:<br|$)", extra, re.S | re.I)
        if not titre and m_t:
            titre = propre(m_t.group(1))
        m_c = re.search(r"Personnages en couverture\s*:?\s*'*\s*(?:<br\s*/?>)?(.+?)(?:<br|$)", extra, re.S | re.I)
        resume = re.sub(r"'{3}\s*Résumé\s*:?\s*'{3}", "", c.get("résumé", ""), flags=re.I)
        lus = chapitres(c.get("chapitre", ""))
        sortie = propre(_dates(c.get("sortie_" + langue_fr, "")))
        d = {"titre": titre, "sortie": sortie if re.search(r"\d", sortie) else "",              # « _ » : date pas encore connue
             "isbn": isbn(c.get("isbn_" + langue_fr, "")),
             "couverture": propre(m_c.group(1)) if m_c else "",
             "resume": propre(_puces(resume)),
             "chapitres": [f"{n:g}. {t}" for n, t in lus if t][:40],
             "numeros": [n for n, _ in lus]}
        details[vol.group(1)] = {k: v for k, v in d.items() if v}
    return details
