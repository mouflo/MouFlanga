"""
Glénat (glenat.com) : la page d'un tome de l'éditeur dit son ISBN, son résumé, sa date, son nombre de pages et sa couverture, et
renvoie vers les autres tomes de la MÊME édition (« Rave - Édition originale », 384 pages par tome, au lieu des tomes standard de 190).

Servi par « ✏️ Mon édition » : l'adresse de la page d'un tome est donnée par la personne, jamais cherchée (le robots.txt de glenat.com,
groupe « * », n'interdit que les adresses avec paramètres, /api/ et /_next/ : on ne lit que des pages de tomes, sans paramètre, et jamais
la recherche du site). Les autres tomes sont retrouvés dans les liens de la page, puis, pour ceux qu'elle ne cite pas, par le numéro
d'ISBN qui se suit d'un tome à l'autre, vérifié sur la page elle-même (jamais deviné sans preuve).
Tout passe par `reseau` (rythme, pannes) : une panne lève `reseau.Panne`, jamais prise pour « rien trouvé ».
"""
import html
import json
import re

import ankama
import reseau

BASE = "https://www.glenat.com"
PAGES_MAX = 30                      # pages de tomes lues au plus pour une édition
_ADRESSE = re.compile(r"^https://(?:www\.)?glenat\.com/(?P<categorie>[a-z0-9-]+)/(?P<base>[a-z0-9-]+?)-tome-(?P<tome>\d{1,3})-(?P<isbn>97[89]\d{10})/?$")


class PageIllisible(Exception):
    """L'adresse n'est pas la page d'un tome Glénat, ou la page ne donne rien d'exploitable."""


def adresse(url) -> dict:
    """{url, categorie, base, tome, isbn} d'une adresse de page de tome (« …/glenat-manga/rave-edition-originale-tome-01-978…/ »),
    ou {} : autre site, adresse avec paramètres, page qui n'est pas un tome."""
    m = _ADRESSE.match(str(url or "").strip().split("#")[0])
    if not m or not ankama._isbn_valide(m["isbn"]):
        return {}
    d = m.groupdict()
    d["tome"] = int(d["tome"])
    d["url"] = _url(d["categorie"], d["base"], d["tome"], d["isbn"])
    return d


def _url(categorie: str, base: str, tome: int, isbn: str) -> str:
    return f"{BASE}/{categorie}/{base}-tome-{tome:02d}-{isbn}/"


def _cle_isbn(douze: str) -> str:
    return douze + str((10 - sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(douze))) % 10)


def isbn_du_tome(a: dict, tome: int) -> str:
    """L'ISBN du tome `tome` d'une édition dont on connaît un tome (`a` : résultat d'`adresse`), si les ISBN se suivent comme chez Glénat
    (Rave : …0414, …0421, …0438…). À vérifier sur la page avant de s'y fier."""
    return _cle_isbn(str(int(a["isbn"][:12]) + (tome - a["tome"])))


def _texte(h: str) -> str:
    h = re.sub(r"</p>|<br\s*/?>", " ", h or "", flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(h)))).strip()


def _donnees(page: str) -> tuple:
    """(données de la page, fiche « Book » en JSON-LD) : ce que Glénat met dans __NEXT_DATA__ et dans ses données structurées."""
    data, livre = {}, {}
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if m:
        try:
            data = (((json.loads(m.group(1), strict=False).get("props") or {}).get("pageProps") or {}).get("data")) or {}
        except ValueError:
            data = {}
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(m.group(1), strict=False)
        except ValueError:
            continue
        for o in (d.get("@graph") if isinstance(d, dict) and d.get("@graph") else [d]):
            if isinstance(o, dict) and o.get("@type") == "Book" and o.get("name") and not o.get("bookFormat") and "isbn" in o and not livre:
                livre = o
    return data, livre


def _edition(titre: str, serie: str) -> str:
    """« Rave - Édition originale - Tome 01 » → « Édition originale » ; « Rave - Tome 30 » → «  » (édition standard)."""
    t = re.sub(r"\s*[-–]\s*tome\s*\d+\s*$", "", titre or "", flags=re.I).strip()
    if serie and t.lower().startswith(serie.lower()):
        t = t[len(serie):]
    return t.strip(" -–:")


def lire_page(url: str):
    """Fiche d'un tome d'après sa page : {url, serie, edition, tome, isbn, date, pages, resume, couverture, titre, autres_isbn,
    voisins: {tome: adresse}} ; None si Glénat répond autre chose qu'une page (introuvable). Lève reseau.Panne."""
    a = adresse(url)
    if not a:
        raise PageIllisible("Ce n'est pas l'adresse de la page d'un tome sur glenat.com.")
    rep = reseau.get(a["url"], attendu="texte", memo=600, service="glenat")
    if rep.statut != 200:
        return None
    data, livre = _donnees(rep.texte)
    isbn = str(data.get("ean") or livre.get("isbn") or "")
    if not ankama._isbn_valide(isbn):
        return None
    titre = html.unescape(str(data.get("titre_de_couverture") or livre.get("name") or ""))
    serie = html.unescape(str(data.get("serie_label") or "")) or re.split(r"\s+[-–]\s+", titre)[0]
    try:
        tome = int(data.get("numero_de_tome") or a["tome"])
    except (TypeError, ValueError):
        tome = a["tome"]
    date = str(livre.get("datePublished") or "")
    if not date and re.fullmatch(r"\d\d-\d\d-\d{4}", str(data.get("date_parution") or "")):
        j, mo, an = str(data["date_parution"]).split("-")
        date = f"{an}-{mo}-{j}"
    try:
        pages = int(data.get("page") or livre.get("numberOfPages") or 0) or None
    except (TypeError, ValueError):
        pages = None
    # le texte complet est dans la fiche structurée ou la présentation éditoriale ; « resume » n'est parfois que l'accroche
    resume = max((_texte(x) for x in (livre.get("description"), data.get("presentation_editoriale"), data.get("resume")) if x), key=len, default="")
    ebook = str(data.get("ean_numerique_lie") or "")
    motif = re.compile(r'href=\\?"(?:https://www\.glenat\.com)?/' + re.escape(a["categorie"]) + "/" + re.escape(a["base"])
                       + r'-tome-(\d{1,3})-(97[89]\d{10})/?\\?"')
    voisins = {int(n): _url(a["categorie"], a["base"], int(n), i) for n, i in motif.findall(rep.texte) if ankama._isbn_valide(i)}
    voisins[tome] = _url(a["categorie"], a["base"], tome, isbn)
    return {"url": a["url"], "serie": serie, "edition": _edition(titre, serie), "tome": tome, "isbn": isbn, "date": date, "pages": pages,
            "resume": resume if len(resume) >= 40 else "", "couverture": str(data.get("image_de_couverture_hd") or livre.get("image") or ""),
            "titre": titre, "autres_isbn": [ebook] if ankama._isbn_valide(ebook) and ebook != isbn else [], "voisins": voisins}


def lire_edition(url: str, voulus=None) -> dict:
    """{tome: fiche} des tomes de la même édition que la page donnée, pour les tomes `voulus` (tous ceux qu'on connaît si None). La page
    donnée et ses liens d'abord, puis l'ISBN qui se suit pour les tomes voulus que personne ne cite (vérifiés sur leur page : même
    édition, bon numéro, bon ISBN). Lève reseau.Panne et PageIllisible."""
    a = adresse(url)
    premiere = lire_page(url)
    if not premiere:
        raise PageIllisible("Glénat ne montre plus cette page : vérifie l'adresse.")
    fiches, connus = {premiere["tome"]: premiere}, dict(premiere["voisins"])
    attendus = sorted(set(voulus) if voulus else connus)
    lus = 1
    for t in attendus:
        if t in fiches or lus >= PAGES_MAX:
            continue
        adr = connus.get(t)
        if not adr and voulus:
            adr = _url(a["categorie"], a["base"], t, isbn_du_tome(a, t))         # ISBN qui se suit : la page dira si c'est le bon
        if not adr:
            continue
        lus += 1
        f = lire_page(adr)
        if f and f["tome"] == t and f["edition"] == premiere["edition"] and adresse(adr).get("isbn") == f["isbn"]:
            fiches[t] = f
            for n, u in f["voisins"].items():
                connus.setdefault(n, u)
    return {t: f for t, f in fiches.items() if not voulus or t in voulus}


def chercher(url: str, voulus=None) -> dict:
    """{tome: {isbn, resume, titre, date, pages, editeur}} pour les tomes `voulus`, au format des autres sources (notices). Lève
    reseau.Panne ; une adresse illisible ne donne rien."""
    try:
        fiches = lire_edition(url, voulus)
    except PageIllisible:
        return {}
    return {t: {k: v for k, v in {"isbn": f["isbn"], "resume": f["resume"], "titre": f["titre"], "date": f["date"], "pages": f["pages"],
                                  "editeur": "Glénat"}.items() if v} for t, f in fiches.items()}
