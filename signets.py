"""📝 Chapitres d'un tome écrits DANS le fichier .cbz, pour qu'ils suivent quand la série est partagée.

Les chapitres vont dans le ComicInfo.xml standard (balises <Pages><Page Image="63" Bookmark="2. La valeur de la vie"/>),
lu par Komga, Kavita, etc., et relu par MouFlanga chez la personne qui reçoit le fichier. Les pages ne sont pas
retouchées : elles sont recopiées telles quelles (même compression). On n'ajoute jamais chapitres.json, réservé aux
tomes que MouFlanga assemble lui-même chapitre par chapitre.
"""
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

COMICINFO = "ComicInfo.xml"
MARQUE = "MouFlanga:"
_LIGNE = re.compile(r"^(\d{1,4}(?:[.,]\d)?)\s*[.)\-:–]*\s*(.*)$")


def _a_nous(balise: str, texte: str) -> bool:
    """Valeur posée autrefois par MouFlanga elle-même (avant la liste « ecrits » des Notes) : titre « Tome 5 », liste « Chapitres … »."""
    texte = (texte or "").strip()
    if balise == "Title":
        return bool(re.match(r"^(Tome \d+|Hors tome)$", texte))
    if balise == "Summary":
        return texte.startswith("Chapitres ")
    return False


def _notes_mf(racine) -> dict:
    import json
    for ligne in (racine.findtext("Notes") or "").splitlines():
        if ligne.startswith(MARQUE):
            try:
                return json.loads(ligne[len(MARQUE):].strip())
            except ValueError:
                return {}
    return {}


def _balises_ecrites(racine) -> set:
    """Balises posées par MouFlanga (liste « ecrits » de sa ligne dans les Notes) : elles seules peuvent être remplacées."""
    return set(_notes_mf(racine).get("ecrits") or [])


def _noter_ecrits(racine, ecrits: set):
    import json
    n = racine.find("Notes")
    if n is None or not n.text or not ecrits:
        return
    lignes = []
    for l in n.text.splitlines():
        if l.startswith(MARQUE):
            try:
                d = json.loads(l[len(MARQUE):].strip())
                d["ecrits"] = sorted(ecrits)
                l = MARQUE + " " + json.dumps(d, ensure_ascii=False, separators=(",", ":"))
            except ValueError:
                pass
        lignes.append(l)
    n.text = "\n".join(lignes)


def _xml(donnees: bytes | None, chapitres: list[dict] | None, infos: dict | None = None) -> bytes:
    """ComicInfo.xml avec la liste des signets (le reste du fichier existant est gardé). « chapitres » None : signets
    existants gardés. « infos » : {balise: texte} (Title, Summary, Notes, Year…) ; la ligne « MouFlanga: … » des Notes
    est remplacée, les autres lignes de Notes sont gardées."""
    try:
        racine = ET.fromstring(donnees) if donnees else ET.Element("ComicInfo")
    except ET.ParseError:
        racine = ET.Element("ComicInfo")
    if chapitres is not None:
        for p in racine.findall("Pages"):
            racine.remove(p)
        pages = ET.SubElement(racine, "Pages")
        for c in chapitres:
            if c.get("image") is None:
                continue
            titre = f"{c['num']:g}. {c.get('titre') or ''}".strip()
            ET.SubElement(pages, "Page", {"Image": str(int(c["image"])), "Bookmark": titre})
    anciens = _balises_ecrites(racine)
    ecrits = set()
    try:
        import json
        nouvelles = json.loads(((infos or {}).get("Notes") or "").partition(MARQUE)[2].strip() or "{}")
    except ValueError:
        nouvelles = {}
    forces = {"Summary"} if nouvelles.get("resume") == "manuel" else set()     # résumé écrit à la main : prioritaire sur celui de l'équipe
    for balise, texte in (infos or {}).items():
        if not texte:
            continue
        ancien = racine.find(balise)
        if balise == "Notes":
            if ancien is not None and ancien.text:
                texte = "\n".join([l for l in ancien.text.splitlines() if not l.startswith(MARQUE)] + [texte])
        elif ancien is not None and (ancien.text or "").strip() and balise not in anciens and balise not in forces and not _a_nous(balise, ancien.text):
            continue                         # écrit par l'équipe : jamais écrasé (seulement les balises que MouFlanga a posées)
        else:
            ecrits.add(balise)
        for x in racine.findall(balise):
            racine.remove(x)
        ET.SubElement(racine, balise).text = str(texte)
    _noter_ecrits(racine, anciens | ecrits)
    sortie = io.BytesIO()
    ET.ElementTree(racine).write(sortie, encoding="utf-8", xml_declaration=True)
    return sortie.getvalue()


def nb_signets(chapitres: list[dict]) -> int:
    return sum(1 for c in chapitres if c.get("image") is not None)


def ecrire(chemin: Path, chapitres: list[dict] | None, destination: Path, infos: dict | None = None) -> int:
    """Écrit à « destination » une copie de « chemin » avec les signets et les infos du tome ; relit et vérifie.
    Renvoie le nombre de signets (1 s'il n'y a que des infos)."""
    with zipfile.ZipFile(chemin) as src, zipfile.ZipFile(destination, "w") as dst:
        ancien = src.read(COMICINFO) if COMICINFO in src.namelist() else None
        for info in src.infolist():
            if info.filename == COMICINFO:
                continue
            copie = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            copie.compress_type = info.compress_type
            dst.writestr(copie, src.read(info.filename))
        c = zipfile.ZipInfo(COMICINFO, date_time=__import__("time").localtime()[:6])
        c.compress_type = zipfile.ZIP_DEFLATED
        dst.writestr(c, _xml(ancien, chapitres, infos))
    with zipfile.ZipFile(destination) as z, zipfile.ZipFile(chemin) as o:
        if z.testzip() is not None:
            destination.unlink()
            raise RuntimeError("archive illisible après écriture")
        if sorted(z.namelist()) != sorted(set(o.namelist()) | {COMICINFO}):
            destination.unlink()
            raise RuntimeError("pages différentes après écriture")
    return nb_signets(chapitres or []) or (1 if infos else 0)


def lire_infos(chemin: Path) -> dict:
    """Infos du tome écrites dans le fichier : {"titre", "resume", "notes": {…}} (vide si rien).
    « notes » est la ligne « MouFlanga: {…} » : provenance, validation du sommaire, source du résumé…"""
    import json
    try:
        with zipfile.ZipFile(chemin) as z:
            if COMICINFO not in z.namelist():
                return {}
            racine = ET.fromstring(z.read(COMICINFO))
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError):
        return {}
    texte = lambda b: ((racine.findtext(b) or "").strip())
    resume = texte("Summary")
    resume = resume.split("\n\nChapitres ")[0] if not resume.startswith("Chapitres ") else ""   # liste de chapitres d'un tome assemblé
    notes = _notes_mf(racine)
    titre = texte("Title")
    autres = "\n".join(l for l in (racine.findtext("Notes") or "").splitlines() if not l.startswith(MARQUE))
    isbn = ""
    for source in (texte("GTIN"), autres, texte("Web")):
        m = re.search(r"(?<![\d-])(97[89][\d -]{9,14}\d|\d{9}[\dXx])(?![\d])", source.replace("‑", "-"))
        if m and len(re.sub(r"\D", "", m.group(1))) in (10, 13):
            isbn = re.sub(r"[^\dXx]", "", m.group(1))
            break
    nombre = lambda b: int(float(texte(b))) if re.match(r"^\d+(\.0+)?$", texte(b)) else None
    return {"titre": "" if re.match(r"^(Tome \d+|Hors tome)$", titre) else titre, "resume": resume, "notes": notes,
            "serie": texte("Series"), "auteur": texte("Writer"), "dessin": texte("Penciller"), "editeur": texte("Publisher"),
            "annee": texte("Year"), "mois": texte("Month"), "genres": texte("Genre"), "lien": texte("Web"), "isbn": isbn,
            "langue": texte("LanguageISO"), "format": texte("Format"), "tome": nombre("Number") if nombre("Number") is not None else nombre("Volume"),
            "nb_tomes": nombre("Count"), "equipe": texte("Teams") or texte("ScanInformation"), "autres_notes": autres}


def lire(chemin: Path) -> list[dict]:
    """Chapitres notés dans le fichier : [{"num", "titre", "image"}] (vide si aucun signet de la forme « 2. Titre »)."""
    try:
        with zipfile.ZipFile(chemin) as z:
            if COMICINFO not in z.namelist():
                return []
            racine = ET.fromstring(z.read(COMICINFO))
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError):
        return []
    out = []
    for p in racine.iter("Page"):
        m = _LIGNE.match((p.get("Bookmark") or "").strip())
        if m and (p.get("Image") or "").isdigit():
            out.append({"num": float(m.group(1).replace(",", ".")), "titre": m.group(2).strip(), "image": int(p.get("Image"))})
    return sorted(out, key=lambda c: c["num"])
