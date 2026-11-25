"""Aperçu AMÉLIORÉ d'une page pour l'écran de rognage (début du chantier « angle manuel sur la page améliorée »).

Principe retenu avec l'utilisatrice : les premières pages s'affichent en quelques secondes (calcul immédiat), le reste se calcule en
arrière-plan, dans l'ordre, pendant qu'on travaille sur les premières. Une page calculée est gardée sur disque (cache), clé = source,
date du fichier, réglages et largeur : changer un réglage refait les pages, rien d'autre.

Pour l'instant : les réglages du tome (retouches, redressement automatique compris), pas le cadre ni l'uniformisation (ils dépendent du
tome entier). L'angle manuel n'est pas encore pris en compte ici.
"""
import hashlib
import json
import threading
from pathlib import Path

import archives
import optimiser

PREMIERES = 10                       # pages calculées tout de suite
_verrou = threading.Lock()           # une seule page améliorée à la fois (IA = un seul processeur graphique)
_en_cours = {}                       # clé de tome -> thread de calcul de fond


def _cle(source, reglages, n, largeur):
    st = Path(source).stat()
    brut = json.dumps([str(source), st.st_mtime_ns, st.st_size, sorted((reglages or {}).items()), n, largeur], sort_keys=True)
    return hashlib.sha256(brut.encode()).hexdigest()[:24]


def _fichier(dossier_cache, cle):
    return Path(dossier_cache) / (cle + ".jpg")


def calculer(source, reglages, n, largeur, dossier_cache):
    """JPEG de la page n améliorée (gardé sur disque). Renvoie les octets."""
    dossier_cache = Path(dossier_cache)
    dossier_cache.mkdir(parents=True, exist_ok=True)
    cle = _cle(source, reglages, n, largeur)
    f = _fichier(dossier_cache, cle)
    if f.exists():
        return f.read_bytes()
    with _verrou:
        if f.exists():
            return f.read_bytes()
        import io
        from PIL import Image
        data, _ = archives.read_page(Path(source), n)
        im = Image.open(io.BytesIO(data))
        im.load()
        ameliore = optimiser.ameliorer(im, reglages or {})     # ameliorer gère seule le noir et blanc et la couleur
        if ameliore.width > largeur:
            ameliore = ameliore.resize((largeur, round(ameliore.height * largeur / ameliore.width)), Image.LANCZOS)
        sortie = io.BytesIO()
        ameliore.convert("RGB").save(sortie, "JPEG", quality=88)
        octets = sortie.getvalue()
        tmp = f.with_suffix(".part")
        tmp.write_bytes(octets)
        tmp.replace(f)
        return octets


def lancer_fond(source, reglages, nombre, largeur, dossier_cache):
    """Calcule les pages PREMIERES..nombre-1 en arrière-plan, une par une. Ne relance pas un calcul déjà en cours pour le même tome."""
    cle = _cle(source, reglages, 0, largeur)[:12]
    if cle in _en_cours and _en_cours[cle].is_alive():
        return False

    def travail():
        for n in range(0, nombre):                # dans l'ordre : les premières pages sont prêtes en premier
            try:
                calculer(source, reglages, n, largeur, dossier_cache)
            except Exception:
                continue            # une page qui échoue ne bloque pas les suivantes
    t = threading.Thread(target=travail, daemon=True, name="apercu-ameliore")
    _en_cours[cle] = t
    t.start()
    return True
