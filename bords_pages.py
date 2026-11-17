"""
✂️ Propositions de bords pour le rognage manuel (17/11/2026). Rien n'est appliqué d'office : l'écran de rognage montre ces positions en pointillés et c'est
la personne qui les accepte ou les corrige.

Le bord d'une page de tome relié scanné à plat est le fin trait sombre, presque vertical, juste avant la bande de la page voisine. On le cherche dans les 10 % de chaque côté :
segments quasi verticaux (LSD), regroupés en droites x = a + b·y soutenues sur au moins 35 % de la hauteur, et on garde la droite la plus INTÉRIEURE (la bande de la page
voisine est derrière le trait, jamais devant). Mesuré sur Nori Taka tome 2 : le bord varie de 1189 à 1269 px d'une page à l'autre, ce n'est donc pas une constante.
Un bord n'est proposé que s'il est cohérent avec les autres pages de même parité (même côté du dos) : à moins de 30 px de leur position médiane. Limites connues : un bord
sans trait continu (dessin pleine page) n'est pas trouvé ; un trait de cadre plus à l'extérieur que le vrai bord peut être pris pour lui (p93 du tome 2) : d'où la validation.
"""
import io
import threading
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import archives

ZONE = 0.10                # part de la largeur explorée de chaque côté
SOUTIEN = 0.35             # part de la hauteur que la droite doit couvrir
ETENDUE = 0.45             # part de la hauteur entre son premier et son dernier segment
PENTE_MAX = 3.0            # degrés : au-delà, ce n'est pas le bord
TOL_X = 30.0               # px : écart maxi au bord médian des pages de même parité
TOL_ANGLE = 1.0            # degrés : écart maxi à l'inclinaison médiane des pages de même parité
MINI_REF = 5               # pages nécessaires pour fixer le bord habituel d'un côté
ACCORD = 0.30              # degrés : écart maxi entre les deux bords pour proposer un angle
ANGLE_MINI = 0.15          # degrés : en dessous, la page est droite, on ne propose rien

_CACHE = {}
_VERROU = threading.Lock()


def _segments(g, cote):
    h, w = g.shape
    z = int(ZONE * w)
    x0 = 0 if cote == "gauche" else w - z
    seg = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(g[:, x0:x0 + z])[0]
    res = []
    if seg is None:
        return res
    for xa, ya, xb, yb in seg.reshape(-1, 4):
        longueur = float(np.hypot(xb - xa, yb - ya))
        if longueur >= 0.04 * h and abs(abs(np.degrees(np.arctan2(yb - ya, xb - xa))) - 90) <= 5.0:
            res.append((xa + x0, ya, xb + x0, yb))
    return res


def _union(intervalles):
    total, fin = 0.0, -1e9
    for a, b in sorted(intervalles):
        if b <= fin:
            continue
        total += b - max(a, fin)
        fin = b
    return total


def trait_bord(g, cote):
    """Droite la plus intérieure soutenue par les segments du bord : {"xm" (x à mi-hauteur), "pente" (degrés, positif : x augmente avec y)} ou None."""
    h, w = g.shape
    segs = _segments(g, cote)
    if len(segs) < 2:
        return None
    candidats = []
    for xa, ya, xb, yb in segs:
        if yb == ya:
            continue
        b = (xb - xa) / (yb - ya)
        a = xa - b * ya
        if abs(np.degrees(np.arctan(b))) > PENTE_MAX:
            continue
        inter = [(min(yc, yd), max(yc, yd)) for xc, yc, xd, yd in segs if max(abs(xc - (a + b * yc)), abs(xd - (a + b * yd))) <= 6]
        if _union(inter) / h >= SOUTIEN and (max(i[1] for i in inter) - min(i[0] for i in inter)) / h >= ETENDUE:
            candidats.append((a + b * h / 2, float(np.degrees(np.arctan(b)))))
    if not candidats:
        return None
    sens = 1 if cote == "gauche" else -1                     # intérieur : le plus à droite pour le bord gauche, le plus à gauche pour le bord droit
    xm, pente = max(candidats, key=lambda c: sens * c[0])
    return {"xm": float(xm), "pente": pente}


def proposer(chemin, progres=None) -> dict:
    """Bords proposés pour chaque page simple du tome : {"pages": {numéro: {"g": x du bord gauche ou None, "d": x du bord droit ou None, "a": angle à appliquer
    (degrés, sens horaire, 0 si rien de sûr)}}, "largeur": largeur médiane entre les deux bords (ou None), "analysees": n}. Le résultat est gardé tant que le fichier ne change pas."""
    chemin = Path(chemin)
    st = chemin.stat()
    cle = (str(chemin), st.st_mtime_ns, st.st_size)
    with _VERROU:
        if cle in _CACHE:
            return _CACHE[cle]
    nb = len(archives.pages(chemin))
    mesures = {}
    for i in range(nb):
        data, _ = archives.read_page(chemin, i)
        im = Image.open(io.BytesIO(data))
        if im.width > 1.1 * im.height or min(im.size) < 200:
            if progres:
                progres(i + 1, nb)
            continue
        g = np.array(im.convert("L"))
        mesures[i] = {c: trait_bord(g, c) for c in ("gauche", "droite")}
        if progres:
            progres(i + 1, nb)
    ref = {}
    for par in (0, 1):
        for c in ("gauche", "droite"):
            vals = [(m[c]["xm"], m[c]["pente"]) for i, m in mesures.items() if i % 2 == par and m[c]]
            ref[(par, c)] = (float(np.median([v[0] for v in vals])), float(np.median([v[1] for v in vals]))) if len(vals) >= MINI_REF else None
    pages, largeurs = {}, []
    for i, m in mesures.items():
        bons = {}
        for c in ("gauche", "droite"):
            r, t = ref[(i % 2, c)], m[c]
            if r and t and abs(t["xm"] - r[0]) <= TOL_X and abs(t["pente"] - r[1]) <= TOL_ANGLE:
                bons[c] = t
        if not bons:
            continue
        angle = 0.0
        if len(bons) == 2 and abs(bons["gauche"]["pente"] - bons["droite"]["pente"]) <= ACCORD:
            moyenne = (bons["gauche"]["pente"] + bons["droite"]["pente"]) / 2
            angle = moyenne if abs(moyenne) >= ANGLE_MINI else 0.0              # la droite penche en « \ » (x croît avec y) : on la redresse en tournant dans le sens horaire
        pages[i] = {"g": round(bons["gauche"]["xm"], 1) if "gauche" in bons else None, "d": round(bons["droite"]["xm"], 1) if "droite" in bons else None,
                    "a": round(float(angle), 2)}
        if len(bons) == 2:
            largeurs.append(bons["droite"]["xm"] - bons["gauche"]["xm"])
    res = {"pages": pages, "largeur": int(round(float(np.median(largeurs)))) if len(largeurs) >= MINI_REF else None, "analysees": len(mesures)}
    with _VERROU:
        _CACHE.clear()
        _CACHE[cle] = res
    return res
