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
_LIGNE = re.compile(r"^(\d{1,4}(?:[.,]\d)?)\s*[.)\-:–]*\s*(.*)$")


def _xml(donnees: bytes | None, chapitres: list[dict]) -> bytes:
    """ComicInfo.xml avec la liste des signets (le reste du fichier existant est gardé)."""
    try:
        racine = ET.fromstring(donnees) if donnees else ET.Element("ComicInfo")
    except ET.ParseError:
        racine = ET.Element("ComicInfo")
    for p in racine.findall("Pages"):
        racine.remove(p)
    pages = ET.SubElement(racine, "Pages")
    for c in chapitres:
        if c.get("image") is None:
            continue
        titre = f"{c['num']:g}. {c.get('titre') or ''}".strip()
        ET.SubElement(pages, "Page", {"Image": str(int(c["image"])), "Bookmark": titre})
    sortie = io.BytesIO()
    ET.ElementTree(racine).write(sortie, encoding="utf-8", xml_declaration=True)
    return sortie.getvalue()


def nb_signets(chapitres: list[dict]) -> int:
    return sum(1 for c in chapitres if c.get("image") is not None)


def ecrire(chemin: Path, chapitres: list[dict], destination: Path) -> int:
    """Écrit à « destination » une copie de « chemin » avec les signets ; relit et vérifie. Renvoie le nombre de signets."""
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
        dst.writestr(c, _xml(ancien, chapitres))
    with zipfile.ZipFile(destination) as z, zipfile.ZipFile(chemin) as o:
        if z.testzip() is not None:
            destination.unlink()
            raise RuntimeError("archive illisible après écriture")
        if sorted(z.namelist()) != sorted(set(o.namelist()) | {COMICINFO}):
            destination.unlink()
            raise RuntimeError("pages différentes après écriture")
    return nb_signets(chapitres)


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
