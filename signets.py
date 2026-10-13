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
    for balise, texte in (infos or {}).items():
        if not texte:
            continue
        ancien = racine.find(balise)
        if balise == "Notes" and ancien is not None and ancien.text:
            texte = "\n".join([l for l in ancien.text.splitlines() if not l.startswith(MARQUE)] + [texte])
        for x in racine.findall(balise):
            racine.remove(x)
        ET.SubElement(racine, balise).text = str(texte)
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
    notes = {}
    for ligne in (racine.findtext("Notes") or "").splitlines():
        if ligne.startswith(MARQUE):
            try:
                notes = json.loads(ligne[len(MARQUE):].strip())
            except ValueError:
                notes = {}
    titre = texte("Title")
    return {"titre": "" if re.match(r"^(Tome \d+|Hors tome)$", titre) else titre, "resume": resume, "notes": notes}


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
