"""
Sites d'éditeurs : dès qu'un tome a un ISBN, on le cherche chez son éditeur (le plus fiable : le résumé, la date, le nombre de pages et la
couverture viennent de celui qui a publié le livre). Écrit le 16/11/2026.

Comment on trouve la page d'un tome (aucune recherche du site n'est lancée, seulement des pages et des plans de site autorisés) :
- Pika, Glénat, Kurokawa (lisez.com) : le plan du site (sitemap.xml) donne l'adresse de chaque livre, l'ISBN y est dans l'adresse. Le plan
  est gardé 7 jours dans « data/editeurs/index-<éditeur>.json » ;
- Kana : « /produit/<série>-t<N>/ », avec le nom de la série ; la page est refusée si son ISBN n'est pas celui du tome ;
- Kazé / Crunchyroll (boutique Shopify) : la suggestion de recherche du site pour l'ISBN, puis la page du produit ;
- Ki-oon : pas de page par tome, mais la couverture est à une adresse fondée sur l'ISBN.

Règle de fer : une page n'est prise que si elle PROUVE son ISBN (données structurées de la page, tableau « ISBN / EAN » ou adresse qui finit
par l'ISBN), jamais seulement parce que le numéro est écrit quelque part (une fiche cite les ISBN des autres tomes). Tout passe par
`reseau` (rythme, pannes) : une panne lève `reseau.Panne`, jamais prise pour « rien trouvé ».

Pour ajouter un éditeur : un lecteur `_nom(isbn, noms, tome)` qui rend une observation (ou None), une ligne dans REGISTRE, ses préfixes ISBN
dans PREFIXES et son service dans reseau.SERVICES.

Examinés et refusés : Delcourt / Tonkam / Tokebi (leur robots.txt interdit expressément anthropic-ai et Claude-Web), Panini (salle d'attente
Queue-it devant tout le site), Crunchyroll Éditions et J'ai lu (site inaccessible ou protégé).
"""
import html
import json
import logging
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

import glenat
import reseau

logger = logging.getLogger("mouflanga")

DOSSIER = Path(__file__).resolve().parent / "data" / "editeurs"
DUREE_INDEX = 7 * 86400
DUREE_ESSAI = 30 * 86400            # un tome cherché chez son éditeur n'est pas recherché avant un mois (sauf demande à la main)
ATTENTES = 3                        # adresses de séries essayées au plus pour Kana (une requête chacune)

# 8 premiers chiffres de l'ISBN → éditeur (ceux qu'on a vus dans la bibliothèque, vérifiés par les notices de la BnF)
PREFIXES = {
    "97828116": "pika", "97828459": "pika", "97910433": "pika",
    "97827234": "glenat", "97823440": "glenat", "97823310": "glenat",
    "97825050": "kana", "97825051": "kana", "97828712": "kana",
    "97828203": "kaze", "97828496": "kaze",
    "97823559": "kioon", "97910327": "kioon",
    "97823514": "kurokawa", "97823685": "kurokawa", "97910420": "kurokawa",
}
# Repli quand le préfixe est inconnu : le nom de l'éditeur donné par une source (« Pika éd. », « Glénat Manga »…)
MOTS = (("pika", r"\bpika"), ("glenat", r"gl[eé]nat"), ("kana", r"\bkana\b"), ("kaze", r"kaz[eé]|crunchyroll"),
        ("kioon", r"ki-?oon"), ("kurokawa", r"kurokawa"))
# Où se trouvent les images des éditeurs : seules ces adresses sont téléchargées comme couvertures (voir couvertures_tomes.telecharger)
IMAGES_OK = ("https://www.images.hachette-livre.fr/", "https://media.hachette.fr/", "https://bdi.dlpdomain.com/album/",
             "https://api.ki-oon.com/images/", "https://img.lisez.com/", "https://kazemanga.fr/cdn/shop/",
             "https://cdn.shopify.com/s/files/")

_MOIS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
         "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12}
_VERROU = threading.Lock()
_MEMOIRE = {}


def image_autorisee(url: str) -> bool:
    return str(url or "").startswith(IMAGES_OK)


def editeur_de(isbn: str, nom: str = "") -> str:
    """Clé de l'éditeur du livre (« pika », « kana »…), ou "" quand on n'a pas de lecteur pour lui."""
    cle = PREFIXES.get(str(isbn or "")[:8])
    if cle:
        return cle
    for cle, motif in MOTS:
        if re.search(motif, (nom or "").lower()):
            return cle
    return ""


# ---------------------------------------------------------------- Lecture d'une page

def _slug(texte: str) -> str:
    t = unicodedata.normalize("NFKD", html.unescape(texte or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def _texte(fragment) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(str(fragment or ""))))
    return re.sub(r"\s+", " ", t.replace("\xa0", " ")).strip()


def _noeuds_ld(page: str) -> list:
    """Tous les objets des données structurées (JSON-LD) de la page, « @graph » et listes dépliés."""
    out = []

    def deplier(x):
        if isinstance(x, list):
            for y in x:
                deplier(y)
        elif isinstance(x, dict):
            if isinstance(x.get("@graph"), list):
                deplier(x["@graph"])
            out.append(x)
    for m in re.finditer(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', page or "", re.S):
        try:
            deplier(json.loads(m.group(1), strict=False))
        except ValueError:
            continue
    return out


def _est(noeud: dict, *genres) -> bool:
    t = noeud.get("@type")
    return any(g in (t if isinstance(t, list) else [t]) for g in genres)


def _chiffres(valeur) -> str:
    return re.sub(r"\D", "", str(valeur or ""))


def _isbn_du_noeud(n: dict) -> set:
    return {c for c in (_chiffres(n.get(k)) for k in ("isbn", "gtin13", "gtin", "productId")) if len(c) == 13}


def _isbn_de_la_page(page: str, noeuds: list, url: str) -> set:
    """Les ISBN que la page donne comme SIENS (jamais ceux des tomes cités ailleurs dans la page)."""
    propres = set()
    for n in noeuds:
        if _est(n, "Book", "Product"):
            propres |= _isbn_du_noeud(n)
    m = re.search(r"ISBN(?:&nbsp;|\s|/)*(?:/|&nbsp;|\s)*(?:EAN)?\s*</t[dh]>\s*<td[^>]*>\s*(97[89]\d{10})", page or "")
    if m:
        propres.add(m.group(1))
    m = re.search(r"(97[89]\d{10})/?(?:[?#].*)?$", url or "")
    if m:
        propres.add(m.group(1))
    return propres


def _image(valeur) -> str:
    if isinstance(valeur, list):
        valeur = valeur[0] if valeur else ""
    if isinstance(valeur, dict):
        valeur = valeur.get("url") or valeur.get("contentUrl") or ""
    valeur = str(valeur or "").strip()
    if valeur.startswith("http://"):                       # Kazé donne « http:// » : ses images sont aussi en https
        return "https://" + valeur[len("http://"):]
    return ("https:" + valeur) if valeur.startswith("//") else valeur


def _grande(url: str) -> str:
    """Les images « media.hachette.fr/fit-in/500x500/… » existent aussi en taille d'origine chez images.hachette-livre.fr."""
    m = re.search(r"imgArticle/([A-Za-z0-9_-]+)/(\d{4})/(97[89]\d{10}-\d{3}-[A-Za-z]\.jpe?g)", url or "")
    return f"https://www.images.hachette-livre.fr/media/imgArticle/{m[1]}/{m[2]}/{m[3]}" if m else url


def _date_fr(texte: str) -> str:
    m = re.search(r"(\d{1,2})(?:er)?\s+([a-zéèêûô]+)\s+(\d{4})", (texte or "").lower())
    mois = _MOIS.get(m[2]) if m else None
    return f"{m[3]}-{mois:02d}-{int(m[1]):02d}" if mois else ""


def analyser(page: str, url: str, isbn: str, nom_editeur: str):
    """Observation {isbn, resume, titre, date, pages, couverture, editeur, url} d'une page de livre, ou None si la page ne prouve pas
    son ISBN (autre tome, autre édition, page de série…). Les champs que la page ne donne pas restent absents."""
    noeuds = _noeuds_ld(page)
    if isbn not in _isbn_de_la_page(page, noeuds, url):
        return None
    # les nœuds de CE livre : ceux qui annoncent l'ISBN, ou qui n'en annoncent aucun (la fiche Kana n'en met pas)
    miens = [n for n in noeuds if _est(n, "Book", "Product") and (not _isbn_du_noeud(n) or isbn in _isbn_du_noeud(n))]

    def premier(*cles):
        for n in miens:
            for k in cles:
                if n.get(k):
                    return n[k]
        return None
    meta = lambda nom: next(iter(re.findall(rf'<meta[^>]+(?:property|name)="{nom}"[^>]+content="([^"]*)"', page or "")), "")
    titre = _texte(premier("name", "headline") or meta("og:title"))
    # Le résumé : le plus long des textes que la page donne et que le site n'a pas coupés (« … les plus grands aventuriers du ... » : coupé).
    # Données structurées d'abord, puis le bloc de présentation de la fiche (Kana), puis les balises meta (toujours courtes).
    textes = [_texte(premier("description") or "")]
    textes += [_texte(m) for m in re.findall(r'class="hero-area__description"[^>]*>(.*?)</div>', page or "", re.S)[:1]]
    textes += [_texte(meta("og:description") or meta("description"))]
    resume = max((t for t in textes if len(t) >= 40 and not re.search(r"\s(\.\.\.|…)$", t)), key=len, default="")
    pages = premier("numberOfPages")
    if not pages:
        m = re.search(r"Nb de pages</t[dh]>\s*<td[^>]*>\s*(\d{2,4})\b", page) or re.search(r"numberOfPages\W+(\d{2,4})", page)
        pages = m[1] if m else None
    date = str(premier("datePublished", "releaseDate") or "")[:10]
    m = re.search(r"Parution</t[dh]>\s*<td[^>]*>\s*([^<]+)<", page)
    if m and _date_fr(m[1]):                                       # la date du tableau (« 2 juillet 2010 ») vaut mieux que celle du billet
        date = _date_fr(m[1])
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        date = ""
    couverture = _image(premier("image")) or _image(meta("og:image"))
    obs = {"isbn": isbn, "titre": titre, "resume": resume, "date": date, "editeur": nom_editeur, "url": url,
           "pages": int(pages) if str(pages or "").isdigit() else None, "couverture": _grande(couverture)}
    return {k: v for k, v in obs.items() if v not in (None, "")}


DELAIS = {"lisez": 60}              # secondes : lisez.com met longtemps à répondre (pages et plans de site énormes)


def _lire(cle: str, url: str, isbn: str, nom: str):
    rep = reseau.get(url, attendu="texte", service=cle, memo=300, timeout=DELAIS.get(cle, 20))
    return None if rep.statut == 404 else analyser(rep.texte, url, isbn, nom)


# ---------------------------------------------------------------- Plans de site (ISBN dans l'adresse)

def _fichier_index(cle: str) -> Path:
    return DOSSIER / f"index-{cle}.json"


def _locs(texte: str) -> list:
    return [html.unescape(x) for x in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", texte or "")]


def _construire_index(cle: str, plan: str, prefixes) -> dict:
    """{isbn: adresse} d'après un plan de site (ou un plan de plans de site, un niveau). Lève reseau.Panne."""
    delai = DELAIS.get(cle, 30)
    rep = reseau.get(plan, attendu="texte", service=cle, timeout=delai)
    adresses = _locs(rep.texte)
    if adresses and all(re.search(r"sitemap[^/]*\.xml(\?|$)", a) for a in adresses):
        adresses = [a for sous in adresses for a in _locs(reseau.get(sous, attendu="texte", service=cle, timeout=delai).texte)]
    index = {}
    for a in adresses:
        m = re.search(r"/(97[89]\d{10})/?$", a) or re.search(r"-(97[89]\d{10})/?$", a)
        if m and (not prefixes or m[1][:8] in prefixes):
            index[m[1]] = a
    return index


def index(cle: str, plan: str, prefixes=None) -> dict:
    """{isbn: adresse} des livres de l'éditeur, gardé 7 jours (en mémoire et sur disque). Si le site ne répond pas, l'ancien plan sert
    encore ; sans ancien plan, la panne est rendue."""
    with _VERROU:
        garde = _MEMOIRE.get(cle)
        if not garde:
            try:
                garde = json.loads(_fichier_index(cle).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                garde = None
        if garde and time.time() - garde.get("date", 0) < DUREE_INDEX:
            _MEMOIRE[cle] = garde
            return garde["urls"]
        try:
            urls = _construire_index(cle, plan, prefixes)
        except reseau.Panne:
            if garde:
                return garde["urls"]
            raise
        if not urls:                                   # plan vide ou illisible : on ne garde pas « aucun livre »
            if garde:
                return garde["urls"]
            raise reseau.Panne(reseau.SERVICES[cle].libelle, "plan du site vide ou illisible", time.time() + 3600)
        garde = {"date": time.time(), "urls": urls}
        _MEMOIRE[cle] = garde
        try:
            DOSSIER.mkdir(parents=True, exist_ok=True)
            tmp = _fichier_index(cle).with_suffix(".tmp")
            tmp.write_text(json.dumps(garde, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, _fichier_index(cle))
        except OSError as e:
            logger.info("Plan du site %s non gardé sur disque : %s", cle, e)
        return urls


# ---------------------------------------------------------------- Un lecteur par éditeur

def _pika(isbn, noms, tome):
    url = index("pika", "https://www.pika.fr/products.xml").get(isbn)
    return _lire("pika", url, isbn, "Pika") if url else None


def _glenat(isbn, noms, tome):
    url = index("glenat", "https://www.glenat.com/products.xml").get(isbn)
    if not url:
        return None
    try:
        f = glenat.lire_page(url)
    except glenat.PageIllisible:
        return None
    if isbn not in [f.get("isbn"), *(f.get("autres_isbn") or [])]:
        return None
    obs = {"isbn": f["isbn"], "resume": f.get("resume"), "titre": f.get("titre"), "date": f.get("date"), "pages": f.get("pages"),
           "couverture": f.get("couverture"), "editeur": "Glénat", "url": url}
    return {k: v for k, v in obs.items() if v not in (None, "")}


def _kana(isbn, noms, tome):
    base = "https://www.kana.fr/produit/"
    essais = []
    for nom in noms:
        for variante in (nom, re.split(r"\s*[:：]\s*", nom or "")[0]):
            s = _slug(variante)
            if s and s not in essais:
                essais.append(s)
    for s in essais[:ATTENTES]:
        obs = _lire("kana", f"{base}{s}-t{int(tome)}/", isbn, "Kana")
        if obs:
            return obs
    # pas de page à ce nom (édition particulière, titre différent) : la couverture, elle, est à une adresse fondée sur l'ISBN
    couv = f"https://bdi.dlpdomain.com/album/{isbn}-couv-M480x676.jpg"
    return {"isbn": isbn, "couverture": couv, "editeur": "Kana"} if reseau.get(couv, attendu="texte", service="kana").statut != 404 else None


def _kaze(isbn, noms, tome):
    rep = reseau.get("https://kazemanga.fr/search/suggest.json", params={"q": isbn, "resources[type]": "product", "resources[limit]": 3},
                     attendu="json", service="kaze")
    for p in ((rep.json().get("resources") or {}).get("results") or {}).get("products") or []:
        chemin = str(p.get("url") or "").split("?")[0]
        if chemin.startswith("/products/"):
            obs = _lire("kaze", "https://kazemanga.fr" + chemin, isbn, "Kazé")
            if obs:
                return obs
    return None


def _kioon(isbn, noms, tome):
    couv = f"https://api.ki-oon.com/images/volumes/{isbn}.webp"
    return {"isbn": isbn, "couverture": couv, "editeur": "Ki-oon"} if reseau.get(couv, attendu="texte", service="kioon").statut != 404 else None


def _kurokawa(isbn, noms, tome):
    prefixes = {p for p, c in PREFIXES.items() if c == "kurokawa"}
    url = index("lisez", "https://www.lisez.com/sitemap.xml", prefixes).get(isbn)
    return _lire("lisez", url, isbn, "Kurokawa") if url else None


REGISTRE = {"pika": ("Pika", _pika), "glenat": ("Glénat", _glenat), "kana": ("Kana", _kana), "kaze": ("Kazé", _kaze),
            "kioon": ("Ki-oon", _kioon), "kurokawa": ("Kurokawa", _kurokawa)}


def trouver(cle: str, isbn: str, noms: list, tome: int):
    """Observation d'un tome chez son éditeur, ou None. Lève reseau.Panne."""
    return REGISTRE[cle][1](isbn, [n for n in noms if n], tome)


def chercher(noms: list, cibles: dict) -> tuple:
    """cibles : {tome: (isbn, clé de l'éditeur)}. Rend ({tome: observation}, {tomes cherchés pour de bon}, [pannes]). Un éditeur qui ne
    répond pas est laissé de côté pour cette fois ; ses tomes ne comptent pas comme « cherchés »."""
    trouves, cherches, pannes, hors = {}, set(), [], set()
    for tome, (isbn, cle) in sorted(cibles.items()):
        if cle in hors or cle not in REGISTRE:
            continue
        try:
            obs = trouver(cle, isbn, noms, tome)
        except reseau.Panne as e:
            pannes.append(e)
            hors.add(cle)
            continue
        except Exception as e:                      # un lecteur cassé (le site a changé de forme) n'arrête pas les autres éditeurs
            logger.warning("Éditeur %s, tome %s (ISBN %s) : %s: %s", cle, tome, isbn, e.__class__.__name__, e)
            hors.add(cle)
            continue
        cherches.add(tome)
        if obs:
            trouves[tome] = obs
    return trouves, cherches, pannes


# ---------------------------------------------------------------- Une série entière

def _cibles(serie: str, voulus, essayes: dict, forcer: bool) -> dict:
    import notices
    obs = notices.observations(serie)
    out = {}
    for t in sorted({int(x) for x in voulus} if voulus else {int(x) for x in obs}):
        par = obs.get(str(t)) or {}
        isbn = notices.isbn_du_tome(par)[0]
        if not isbn or (not forcer and time.time() - essayes.get(t, 0) < DUREE_ESSAI):
            continue
        cle = editeur_de(isbn, next((o.get("editeur") for o in par.values() if o.get("editeur")), ""))
        if cle:
            out[t] = (isbn, cle)
    return out


def chercher_serie(serie: str, noms: list, voulus=None, forcer: bool = False) -> tuple:
    """Cherche chez leur éditeur les tomes de la série dont l'ISBN est connu, et garde ce qui est trouvé (source « editeur » des notices).
    Rend (nombre de tomes trouvés, nombre cherchés, [pannes]). Un tome cherché sans succès n'est pas redemandé avant un mois."""
    import notices
    import tomes
    avant = ((tomes._charger(serie) or {}).get("recherches") or {}).get("editeurs") or {}
    essayes = {int(t): ts for t, ts in (avant.get("essayes") or {}).items()}
    cibles = _cibles(serie, voulus, essayes, forcer)
    if not cibles:
        return 0, 0, []
    trouves, cherches, pannes = chercher(noms, cibles)
    notices.enregistrer(serie, "editeur", trouves)
    for t in cherches:
        essayes[t] = time.time()

    def noter(brut):
        brut.setdefault("recherches", {})["editeurs"] = {"date": time.time(), "essayes": {str(t): ts for t, ts in essayes.items()}}
    tomes.modifier(serie, noter)
    return len(trouves), len(cherches), pannes


def couvertures(serie: str) -> dict:
    """{tome: [{url, vignette, langue, source}]} : les couvertures que les éditeurs ont données (déjà cherchées, aucune requête ici)."""
    import notices
    out = {}
    for t, par in notices.observations(serie).items():
        o = par.get("editeur") or {}
        if o.get("couverture") and image_autorisee(o["couverture"]):
            out[int(t)] = [{"url": o["couverture"], "vignette": o["couverture"], "langue": "fr", "source": o.get("editeur") or "Éditeur"}]
    return out
