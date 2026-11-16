"""
🧠 Restauration IA des petits scans (écrit le 16/11/2026, réglée sur la page 35 du tome 1 de Nori Taka : 566 × 924 px, 49 Ko).

Un petit scan (moins de 1700 px de haut) est agrandi ×2 par Real-CUGAN (un réseau de neurones fait pour les mangas, modèles « se » livrés avec le
paquet realcugan-ncnn-py, calcul sur processeur) : les bords de bulles et les lettres redeviennent francs, le grain et les carrés de la compression
JPEG disparaissent, au lieu d'un simple agrandissement flou. Puis une finition : le papier devient blanc et le noir le plus profond devient noir (histogramme
de la page), et un léger masque flou redonne du mordant aux traits (sans amplifier le grain des aplats).

Trois niveaux (mêmes réglages que les exemples montrés le 16/11) :
- 1 « Naturel » : débruitage léger, 30 % de la texture d'origine gardée (dégradés et trames plus naturels, un peu plus doux) ;
- 2 « Net » : débruitage moyen (texte et contours les plus francs) ;
- 3 « Maximum » : comme « Net » avec huit passes (le même agrandissement sous huit orientations, moyenné : moins d'artefacts), huit fois plus lent.
Environ 10 s par page pour 1 et 2, 75 s pour 3 (processeur seul, 8 cœurs). Pas de carte graphique sur ce serveur.

Optionnel : sans le paquet (ou sans la bibliothèque système libomp5) `disponible()` rend False et l'appli se comporte comme avant.
Installer : « apt install libomp5 » puis « venv/bin/pip install --no-deps realcugan-ncnn-py » (--no-deps : le paquet réclame opencv-python, déjà là en version « headless »).
"""
import hashlib
import logging
import os
import threading
from collections import OrderedDict

import cv2
import numpy as np

logger = logging.getLogger("mouflanga")

HAUTEUR_MAX = 1700               # une page déjà plus haute n'est pas doublée (fichier énorme, aucun gain)
THREADS = max(1, int(os.environ.get("MOUFLANGA_IA_THREADS") or 4))     # la moitié des cœurs : le serveur reste réactif pendant un tome entier
NIVEAUX = {1: {"nom": "Naturel", "bruit": 1, "tta": False, "texture": 0.3},
           2: {"nom": "Net", "bruit": 2, "tta": False, "texture": 0.0},
           3: {"nom": "Maximum", "bruit": 2, "tta": True, "texture": 0.0}}
_VERROU = threading.Lock()       # le réseau n'est pas fait pour tourner dans plusieurs fils à la fois
_MODELES = {}
_CACHE = OrderedDict()           # {(empreinte de la page, niveau, niveaux auto) : page agrandie} : changer un autre réglage ne refait pas l'agrandissement
_CACHE_MAX = 6
_DISPO = None


def disponible() -> bool:
    """Le paquet (et libomp5) sont-ils là ? Vérifié une fois."""
    global _DISPO
    if _DISPO is None:
        try:
            import realcugan_ncnn_py  # noqa: F401
            _DISPO = True
        except Exception as e:                                 # ImportError, ou bibliothèque système absente
            logger.info("Restauration IA indisponible : %s: %s", e.__class__.__name__, e)
            _DISPO = False
    return _DISPO


def _modele(bruit: int, tta: bool):
    cle = (bruit, tta)
    if cle not in _MODELES:
        from realcugan_ncnn_py import Realcugan
        _MODELES[cle] = Realcugan(gpuid=-1, num_threads=THREADS, noise=bruit, scale=2, model="models-se", tta_mode=tta)
    return _MODELES[cle]


def _niveaux(L: np.ndarray) -> np.ndarray:
    """Le papier (pic de l'histogramme clair) devient blanc, le noir le plus profond (0,3e centile) devient noir. Une page presque toute noire n'est pas touchée."""
    if float(np.percentile(L, 90)) < 150:
        return L
    h = np.bincount(L[L > 170].ravel(), minlength=256)
    blanc = float(np.argmax(h)) if h.sum() else 255.0
    bas = float(np.percentile(L, 0.3))
    x = np.clip((L.astype(np.float32) - bas) / max(blanc - bas, 1.0), 0, 1)
    return (255 * x).astype(np.uint8)


def _nettete(L: np.ndarray, sigma=1.0, force=0.6, seuil=6) -> np.ndarray:
    f = L.astype(np.float32)
    d = f - cv2.GaussianBlur(f, (0, 0), sigma)
    d = np.where(np.abs(d) < seuil, 0, d)                       # pas de grain amplifié dans les aplats
    return np.clip(f + force * d, 0, 255).astype(np.uint8)


def agrandir(g: np.ndarray, niveau: int, niveaux_auto: bool = True) -> np.ndarray:
    """Page en niveaux de gris (uint8) agrandie ×2 et finie, au niveau 1, 2 ou 3. Une page déjà haute est rendue telle quelle.
    niveaux_auto=False : pas de recalage du papier et du noir (quand l'uniformité de la série a déjà fixé les niveaux)."""
    n = NIVEAUX[max(1, min(3, int(niveau)))]
    if g.shape[0] >= HAUTEUR_MAX:
        return g
    cle = (hashlib.blake2b(g.tobytes(), digest_size=16).hexdigest(), g.shape, niveau, niveaux_auto)
    with _VERROU:
        if cle in _CACHE:
            _CACHE.move_to_end(cle)
            return _CACHE[cle]
        from PIL import Image
        sortie = _modele(n["bruit"], n["tta"]).process_pil(Image.fromarray(g).convert("RGB")).convert("L")
        grand = np.asarray(sortie, dtype=np.uint8)
        if n["texture"]:                                        # un peu de la texture d'origine : dégradés et trames plus naturels
            base = cv2.resize(g, (grand.shape[1], grand.shape[0]), interpolation=cv2.INTER_LANCZOS4).astype(np.float32)
            grand = np.clip((1 - n["texture"]) * grand + n["texture"] * base, 0, 255).astype(np.uint8)
        if niveaux_auto:
            grand = _niveaux(grand)
        grand = _nettete(grand)
        _CACHE[cle] = grand
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
        return grand
