"""Conversion d'un .cbr (RAR, ou ZIP mal nommé) en .cbz : les pages sont recopiées telles quelles, sans aucune retouche.

Un .cbz est un ZIP : MouFlanga peut y écrire les infos du tome (ComicInfo.xml : résumé, chapitres, ISBN, fiche…),
ce qu'elle ne peut pas faire dans un RAR. Rien n'est remplacé avant que la copie ait été relue et comparée page par page.
"""
import zipfile
import zlib
from pathlib import Path

import archives


def vers_cbz(src: Path, destination: Path) -> int:
    """Écrit « destination » (.cbz) avec les mêmes fichiers que « src ». Relit et compare chaque page (somme de contrôle).
    Renvoie le nombre de pages ; lève RuntimeError au moindre écart (la destination est alors effacée)."""
    src, destination = Path(src), Path(destination)
    crc, noms = {}, []
    source = archives._open(src)
    try:
        zip_source = isinstance(source, zipfile.ZipFile)
        with zipfile.ZipFile(destination, "w") as sortie:
            for info in source.infolist():
                nom = info.filename
                if info.is_dir() or "__MACOSX" in nom:
                    continue
                donnees = source.read(info)
                if nom in crc:
                    raise RuntimeError(f"nom en double dans l'archive : {nom}")
                z = zipfile.ZipInfo(nom, date_time=tuple(info.date_time) if getattr(info, "date_time", None) else (1980, 1, 1, 0, 0, 0))
                images = nom.lower().endswith(archives.IMAGE_EXT)
                z.compress_type = (info.compress_type if zip_source else zipfile.ZIP_STORED) if images else zipfile.ZIP_DEFLATED
                sortie.writestr(z, donnees)
                crc[nom] = zlib.crc32(donnees) & 0xFFFFFFFF
                noms.append(nom)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        try:
            source.close()
        except Exception:
            pass
    try:
        with zipfile.ZipFile(destination) as z:
            if z.testzip() is not None:
                raise RuntimeError("archive illisible après écriture")
            relus = {i.filename: i.CRC for i in z.infolist()}
        if relus != crc:
            raise RuntimeError("pages différentes après écriture")
        pages = sum(1 for n in noms if n.lower().endswith(archives.IMAGE_EXT))
        if not pages:
            raise RuntimeError("aucune image dans l'archive")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return pages
