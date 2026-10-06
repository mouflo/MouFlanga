"""
Lecture des fichiers de BD : .cbz / .zip (ZIP) et .cbr / .rar (RAR).
Beaucoup de fichiers « .cbr » sont en réalité des ZIP : on regarde le début du fichier, pas l'extension.
Le RAR demande le module « rarfile » et un outil (unrar, 7z ou bsdtar) ; sans eux, un message clair est renvoyé.
"""
import re
import threading
import zipfile
from collections import OrderedDict
from pathlib import Path

ARCHIVE_EXT = (".cbz", ".cbr", ".zip", ".rar")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif", ".avif": "image/avif"}


class ArchiveError(Exception):
    """Erreur lisible par l'utilisateur."""


def natural_key(text):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", str(text))]


def _kind(path: Path):
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError as e:
        raise ArchiveError(f"Fichier illisible ({e.__class__.__name__})")
    if head[:4] == b"PK\x03\x04" or head[:4] == b"PK\x05\x06":
        return "zip"
    if head[:6] == b"Rar!\x1a\x07":
        return "rar"
    raise ArchiveError("Format non reconnu (ni ZIP ni RAR)")


def rar_available():
    try:
        import rarfile
        import shutil
        return any(shutil.which(t) for t in ("unrar", "unar", "7z", "7zz", "bsdtar"))
    except ImportError:
        return False


def _open(path: Path):
    kind = _kind(path)
    if kind == "zip":
        try:
            return zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            raise ArchiveError("Archive ZIP abîmée")
    try:
        import rarfile
    except ImportError:
        raise ArchiveError("Ce fichier est un vrai RAR : le module « rarfile » n'est pas installé sur le serveur.")
    if not rar_available():
        raise ArchiveError("Ce fichier est un vrai RAR : aucun outil de décompression sur le serveur (installe « unrar-free » ou « p7zip-full »).")
    try:
        return rarfile.RarFile(str(path))
    except Exception as e:
        raise ArchiveError(f"RAR illisible : {e.__class__.__name__}")


def _names(zf):
    out = []
    for info in zf.infolist():
        name = info.filename
        if info.is_dir() or "__MACOSX" in name or Path(name).name.startswith("."):
            continue
        if name.lower().endswith(IMAGE_EXT):
            out.append(name)
    return sorted(out, key=natural_key)


_cache = OrderedDict()
_lock = threading.Lock()


def pages(path: Path):
    """Noms des pages (triés « naturellement ») ; mis en mémoire tant que le fichier ne change pas."""
    path = Path(path)
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    with _open(path) as zf:
        names = _names(zf)
    with _lock:
        _cache[key] = names
        while len(_cache) > 64:
            _cache.popitem(last=False)
    return names


def read_page(path: Path, index: int):
    """(octets, type MIME) de la page « index » (à partir de 0)."""
    names = pages(path)
    if index < 0 or index >= len(names):
        raise ArchiveError("Page introuvable")
    name = names[index]
    with _open(Path(path)) as zf:
        data = zf.read(name)
    return data, MIME.get(Path(name).suffix.lower(), "application/octet-stream")
