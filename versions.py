"""
↩️ Revenir aux versions d'avant : quand l'appli réécrit un tome (alléger, améliorer, couper ou assembler des doubles pages, retirer des pages
parasites…), l'ancien fichier part à la corbeille « <dossier des mangas>/.corbeille/<date>/<même chemin> » (30 jours par défaut). Ce module
retrouve ces anciennes versions et les remet en place.

- Une même page peut avoir été réécrite plusieurs fois : la corbeille garde chaque version (« Tome 01.cbz.avant », puis
  « Tome 01.cbz (1794829825).avant »…). La plus ancienne par date d'écriture est la version d'ORIGINE (celle d'avant toutes les modifications).
- Remettre une version = la COPIER à côté du tome, la vérifier, envoyer le tome actuel à la corbeille (il y reste 30 jours : on peut
  encore revenir en arrière), puis la mettre à sa place. La copie de la corbeille reste là. Si quoi que ce soit échoue, le tome actuel n'a pas bougé.
"""
import logging
import os
import re
import shutil
import zipfile
from pathlib import Path

logger = logging.getLogger("mouflanga")


def nom_de_base(nom: str) -> str:
    """Le nom qu'avait le fichier avant la corbeille : « Tome 01.cbz (1794829825).avant » et « Tome 01 (1794829825).cbz » → « Tome 01.cbz »."""
    n = re.sub(r" \(\d{6,}\)", "", nom)
    return n[:-len(".avant")] if n.endswith(".avant") else n


def versions_gardees(manga_dir: Path, corbeille: str, fichier: Path) -> list:
    """[{chemin, jour, ecrit, taille}] des versions de ce tome gardées à la corbeille, la plus ancienne (l'origine) en premier.
    Seuls les vrais fichiers zip/cbz comptent (un fichier incomplet n'est jamais proposé)."""
    racine = Path(manga_dir) / corbeille
    if not racine.is_dir():
        return []
    rel = Path(fichier).relative_to(manga_dir)
    out = []
    for jour in sorted(p for p in racine.iterdir() if p.is_dir()):
        dossier = jour / rel.parent
        if not dossier.is_dir():
            continue
        for f in dossier.iterdir():
            try:
                if f.is_file() and nom_de_base(f.name) == rel.name and zipfile.is_zipfile(f):
                    st = f.stat()
                    out.append({"chemin": f, "jour": jour.name, "ecrit": st.st_mtime, "taille": st.st_size})
            except OSError:
                continue
    out.sort(key=lambda v: (v["ecrit"], v["jour"], v["chemin"].name))
    return out


def est_meme(fichier: Path, version: dict) -> bool:
    """Le tome actuel est-il déjà cette version (même taille, même date d'écriture) ? Alors il n'y a rien à remettre."""
    try:
        st = Path(fichier).stat()
    except OSError:
        return False
    return st.st_size == version["taille"] and abs(st.st_mtime - version["ecrit"]) < 2


def _valide(chemin: Path) -> bool:
    try:
        with zipfile.ZipFile(chemin) as z:
            return bool(z.namelist()) and z.testzip() is None
    except (zipfile.BadZipFile, OSError):
        return False


def copier(source: Path, destination: Path) -> None:
    """Copie le contenu et la date, JAMAIS les droits : sur le NAS (NFS), un chmod (donc shutil.copy2, copymode, copystat) rend le fichier impossible à renommer
    et à effacer (« Permission denied »), l'allègement, l'IA et toute autre réécriture du tome échouent ensuite. Constaté le 16/11/2026."""
    shutil.copyfile(source, destination)
    st = Path(source).stat()
    os.utime(destination, ns=(st.st_atime_ns, st.st_mtime_ns))


def restaurer(fichier: Path, version: Path, vers_corbeille) -> None:
    """Remet `version` (un fichier de la corbeille) à la place du tome `fichier`. `vers_corbeille(p)` range le tome actuel à la corbeille.
    Lève OSError / ValueError si ce n'est pas possible ; dans ce cas le tome actuel est laissé tel quel."""
    fichier, version = Path(fichier), Path(version)
    tmp = fichier.with_name("." + fichier.name + ".restauration")        # caché (commence par un point) : la bibliothèque l'ignore
    try:
        copier(version, tmp)
        if not _valide(tmp):
            raise ValueError(f"« {version.name} » est abîmé : le tome actuel n'a pas été touché.")
        vers_corbeille(fichier)
        try:
            os.replace(tmp, fichier)
        except OSError:                                                   # le tome actuel est déjà à la corbeille : on recopie la version
            copier(version, fichier)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
