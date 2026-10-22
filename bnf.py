"""
Catalogue général de la Bibliothèque nationale de France (API SRU, données ouvertes, licence ouverte) : pour chaque tome
d'une série éditée en France, son ISBN, son numéro, son éditeur, son nombre de pages et très souvent son résumé (la
« quatrième de couverture »). Aucun quota à craindre : on y va doucement (une requête toutes les 5 s, comme le demande
son robots.txt) et ce qu'on y lit est gardé pour de bon.

Format UNIMARC : 010 ou 073 = ISBN, 200 $a titre / $e complément / $h numéro du tome / $i titre du tome, 205 mention
d'édition, 210 $c éditeur / $d date, 215 $a pages, 330 $a résumé, 461 $v numéro du tome dans la série.
"""
import html
import logging
import re
import xml.etree.ElementTree as ET

import correspondance
import noms_editions
import reseau

logger = logging.getLogger("mouflanga")

URL = "https://catalogue.bnf.fr/api/SRU"
NS = "{info:lc/xmlns/marcxchange-v2}"
PAGE = 50
PAGES_MAX = 8


def isbn13(texte: str) -> str:
    """ISBN-13 (chiffres seuls) d'un texte « 978-2-36852-245-5 » ou ISBN-10 « 2-84599-668-3 » ; "" si la somme de contrôle est fausse."""
    c = re.sub(r"[^0-9Xx]", "", texte or "").upper()
    if len(c) == 10 and re.fullmatch(r"\d{9}[\dX]", c):
        base = "978" + c[:9]
        c = base + str((10 - sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(base)) % 10) % 10)
    if re.fullmatch(r"97[89]\d{10}", c):
        somme = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(c[:12]))
        if (10 - somme % 10) % 10 == int(c[12]):
            return c
    return ""


def _resume_propre(texte: str) -> str:
    """Le résumé (zone 330) sans balises ni codes HTML (« Takemichi&comma; … &excl;&NewLine; ») et sur une seule ligne d'espaces."""
    t = html.unescape(re.sub(r"<[^>]+>", " ", texte or ""))
    t = re.sub(r"\s+", " ", t.replace("\xa0", " ")).strip()
    elisions = r"\b([cdjlmnst]|qu|jusqu|lorsqu|puisqu) (?=[aeiouyàâéèêîôûh])"
    if not re.search(r"[’']", t) and len(re.findall(elisions, t, re.I)) >= 2:       # certaines notices ont perdu leurs apostrophes (« l humanité »)
        t = re.sub(elisions, r"\1'", t, flags=re.I)
    return t


def _champs(rec):
    """{étiquette: [ {code: valeur} ]} d'une notice UNIMARC (la première valeur de chaque sous-zone)."""
    out = {}
    for df in rec.iter(NS + "datafield"):
        sous = {}
        for sf in df.iter(NS + "subfield"):
            sous.setdefault(sf.get("code"), (sf.text or "").strip())
        out.setdefault(df.get("tag"), []).append(sous)
    return out


_ROMAINS = {"I": 1, "V": 5, "X": 10, "L": 50}


def _numero(texte: str):
    """« 11 », « Vol. 10 », « T. 3 », « II » (chiffres romains) → 11, 10, 3, 2 ; None pour « 1-3 » (un coffret / une intégrale),
    « 4bis » ou rien."""
    t = (texte or "").strip()
    if re.search(r"\d\s*(?:-|–|à|et|&)\s*\d", t):
        return None
    m = re.fullmatch(r"(?:t(?:ome)?|vol(?:ume)?)?\.?\s*0*(\d{1,3})", t, re.I)
    if m:
        return int(m.group(1))
    r = re.fullmatch(r"(?:t(?:ome)?|vol(?:ume)?)?\.?\s*([IVXL]{1,6})", t)
    if r:
        total = 0
        for i, c in enumerate(r.group(1)):
            v = _ROMAINS[c]
            total += -v if i + 1 < len(r.group(1)) and _ROMAINS[r.group(1)[i + 1]] > v else v
        return total or None
    return None


def lire_notices(xml: str):
    """(nombre total de notices trouvées, [notice]) d'une réponse SRU en UNIMARC. Une notice : tome, isbn, titre, sous_titre,
    partie, editeur, date, pages, resume, edition, ark. Les notices sans numéro de tome sont gardées (tome=None)."""
    racine = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    total = 0
    for el in racine.iter():
        if el.tag.endswith("}numberOfRecords"):
            total = int((el.text or "0").strip() or 0)
            break
    out = []
    for rec in racine.iter(NS + "record"):
        c = _champs(rec)
        t200 = (c.get("200") or [{}])[0]
        t461 = (c.get("461") or [{}])[0]
        brut_isbn = ((c.get("073") or [{}])[0].get("a") or "") or ((c.get("010") or [{}])[0].get("a") or "")
        t210 = (c.get("210") or [{}])[0]
        pages = re.search(r"(\d{2,4})\s*p\.", (c.get("215") or [{}])[0].get("a") or "")
        date = re.search(r"(1[89]\d\d|20\d\d)", t210.get("d") or "")
        tome = _numero(t200.get("h")) if t200.get("h") else _numero(t461.get("v"))
        out.append({
            "tome": tome, "isbn": isbn13(brut_isbn), "titre": t200.get("a", ""), "sous_titre": t200.get("e", ""),
            "partie": t200.get("i", ""), "serie": t461.get("t", ""), "editeur": re.sub(r"\s*\(.*\)\s*$", "", t210.get("c", "")).strip(),
            "date": date.group(1) if date else "", "pages": int(pages.group(1)) if pages else None,
            "resume": _resume_propre(((c.get("330") or [{}])[0].get("a")) or ""),
            "edition": (c.get("205") or [{}])[0].get("a", ""), "ark": rec.get("id", ""),
        })
    return total, out


def _titre_complet(n: dict) -> str:
    return " : ".join(x for x in (n.get("titre"), n.get("sous_titre"), n.get("partie")) if x)


def requete(nom: str) -> str:
    """Requête CQL : tous les mots du nom dans le titre, livres imprimés seulement."""
    mots = " ".join(correspondance.mots_bruts(noms_editions.FIN.sub("", nom) or nom))
    return f'bib.title all "{mots}" and bib.doctype any "a"'


def interroger(cql: str, debut: int = 1, reserve: int = 0):
    """Une page de résultats : (total, [notice]). Lève reseau.Panne si la BnF ne répond pas."""
    rep = reseau.get(URL, params={"version": "1.2", "operation": "searchRetrieve", "query": cql, "recordSchema": "unimarcxchange",
                                  "maximumRecords": PAGE, "startRecord": debut}, attendu="xml", timeout=30)
    if rep.statut != 200:
        return 0, []
    try:
        return lire_notices(rep.texte)
    except ET.ParseError as e:
        raise reseau.Panne("BnF (catalogue)", f"réponse illisible ({e.__class__.__name__})")


def _titres_candidats(n: dict) -> list:
    """Les façons dont la série est nommée dans une notice : le titre complet (« Red eyes sword : akame ga kill ! »), et le titre de la
    série du lien 461 avec le complément (« Beelzebub » pour un tome intitulé « Banane », « Red eyes sword : Akame ga kill ! Zero »)."""
    complet = _titre_complet(n)
    serie = n.get("serie") or ""
    out = [complet]
    if serie:
        out.append(" : ".join(x for x in (serie, n.get("sous_titre")) if x))
    return list(dict.fromkeys(x for x in out if x))


def de_la_serie(notices, noms, autres_series=(), edition: str = "") -> list:
    """Notices de tomes de la série : numéro de tome, ISBN français valide, titre qui est bien celui de la série (le titre du tome
    ou celui de sa série : beaucoup de notices ne portent que « Banane » avec la série en lien)."""
    out = []
    for n in notices:
        if n["tome"] is None or not n["isbn"] or not n["isbn"].startswith(("9782", "97910")):
            continue
        if any(correspondance.titre_de_la_serie(t, noms, autres_series, edition) for t in _titres_candidats(n)):
            out.append(n)
    return out


def meilleure_par_tome(notices) -> dict:
    """{tome: notice} : une notice par tome. Plusieurs (réimpressions, autre ISBN) : l'éditeur le plus fréquent d'abord, puis
    la plus ancienne, puis celle qui a un résumé. Les autres ISBN sont gardés dans « autres_isbn »."""
    editeurs = {}
    for n in notices:
        editeurs[n["editeur"]] = editeurs.get(n["editeur"], 0) + 1
    principal = max(editeurs, key=editeurs.get) if editeurs else ""
    par_tome = {}
    for n in notices:
        par_tome.setdefault(n["tome"], []).append(n)
    out = {}
    for t, liste in par_tome.items():
        liste = sorted(liste, key=lambda n: (n["editeur"] != principal, bool(n["edition"]), n["date"] or "9999", not n["resume"]))
        choisie = dict(liste[0])
        if not choisie["resume"]:
            choisie["resume"] = next((n["resume"] for n in liste if n["resume"]), "")
        choisie["autres_isbn"] = [n["isbn"] for n in liste[1:] if n["isbn"] != choisie["isbn"]]
        out[t] = choisie
    return out


def _requetes_de_secours(noms) -> list:
    """Quand rien n'a été retenu : le nom sans son premier mot (« Samouraï Deeper Kyo » → « deeper kyo » : la BnF écrit « Samurai »), pour les
    noms de trois mots ou plus. Le tri des notices reste le même : seul un titre qui est bien celui de la série est gardé."""
    out = []
    for n in noms:
        mots = correspondance.mots_bruts(noms_editions.FIN.sub("", n) or n)
        if len(mots) >= 3:
            q = 'bib.title all "%s" and bib.doctype any "a"' % " ".join(mots[1:])
            if q not in out:
                out.append(q)
    return out[:2]


def chercher(noms, *, autres_series=(), edition: str = "", voulus=None, pages_max: int = PAGES_MAX) -> dict:
    """{tome: notice} des tomes de la série d'après la BnF. `noms` : du plus précis au plus court (le nom du dossier, puis les
    titres d'AniList et ses synonymes). On s'arrête dès que tous les tomes `voulus` sont trouvés. Lève reseau.Panne si la BnF ne
    répond pas avant d'avoir trouvé quelque chose ; {} si elle ne connaît pas la série."""
    voulus = {int(t) for t in voulus or ()}
    noms = [n for n in noms if n and correspondance.jetons(n)]
    trouvees = []
    vus = set()

    def interroger_tout(cql):
        debut = 1
        for _ in range(pages_max):
            try:
                total, page = interroger(cql, debut)
            except reseau.Panne:
                if trouvees:
                    return                                       # on garde ce qu'on a déjà : la suite viendra à la prochaine passe
                raise
            trouvees.extend(de_la_serie(page, noms, autres_series, edition))
            debut += PAGE
            if debut > total or not page:
                return
            if voulus and voulus <= {n["tome"] for n in trouvees}:
                return

    for nom in noms[:3]:
        cql = requete(nom)
        if cql in vus:
            continue
        vus.add(cql)
        interroger_tout(cql)
        if trouvees and (not voulus or voulus <= {n["tome"] for n in trouvees}):
            break
    if not trouvees:
        for cql in _requetes_de_secours(noms[:2]):
            if cql not in vus:
                vus.add(cql)
                interroger_tout(cql)
                if trouvees:
                    break
    return meilleure_par_tome(trouvees)
