"""
🪄 Cadres proposés pour le rognage à la main (rognage.py). Rien n'est appliqué d'office : chaque proposition est marquée « à vérifier » dans l'éditeur.

Le bord d'une page de tome relié scanné à plat est le fin trait sombre, presque vertical, juste avant la bande de la page voisine. On le cherche dans les 10 % de chaque côté :
segments quasi verticaux (LSD), regroupés en droites x = a + b·y soutenues sur au moins 35 % de la hauteur, et on garde la droite la plus INTÉRIEURE (la bande de la page
voisine est derrière le trait, jamais devant).

Le bord bouge d'une page à l'autre (l'épaisseur des pages déjà tournées change au fil du tome) : un bord trouvé n'est gardé que s'il est proche de ceux des pages voisines
du même côté du dos ; sans trait, il n'y a en général pas de bande : le cadre va jusqu'au bord de la page (mesuré : prendre les voisines coupait 15 à 26 px de trop). Les cadres déjà réglés à la main servent de repères (ils priment sur la détection),
et la hauteur du cadre vient d'eux (sinon la page entière). Mesuré le 18/11/2026 sur Nori Taka tome 3 contre les cadres tracés à la main : environ 6 px d'écart médian sur
une page de 638 px quand le trait est trouvé ; une page sans trait continu (dessin pleine page) reste approximative : d'où la vérification.
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
VOISINES = 10              # pages voisines (de même parité) comparées de chaque côté
TOL = 0.025                # part de la largeur : écart maxi d'un bord trouvé à la médiane des voisines
ACCORD = 0.30              # degrés : écart maxi entre les deux bords pour proposer un angle
ANGLE_MINI = 0.15          # degrés : en dessous, la page est droite

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


def mesurer(chemin, progres=None) -> dict:
    """{numéro: {"gauche": trait ou None, "droite": trait ou None}} pour chaque page simple du fichier (gardé tant que le fichier ne change pas)."""
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
        if im.width <= 1.1 * im.height and min(im.size) >= 200:
            g = np.array(im.convert("L"))
            mesures[i] = {c: trait_bord(g, c) for c in ("gauche", "droite")}
        if progres:
            progres(i + 1, nb)
    with _VERROU:
        _CACHE.clear()
        _CACHE[cle] = mesures
    return mesures


def _mediane_voisines(valeurs, i, toutes=False):
    """Médiane des valeurs connues des pages de même parité à moins de VOISINES pages (élargi si rien), ou None. « toutes » : à défaut, les pages de
    l'autre parité aussi."""
    for portee in (VOISINES, 3 * VOISINES, 10 ** 6):
        v = [x for j, x in valeurs.items() if j != i and j % 2 == i % 2 and abs(j - i) <= 2 * portee]
        if len(v) >= 2 or (v and portee == 10 ** 6):
            return float(np.median(v))
    v = [x for j, x in valeurs.items() if j != i]
    return float(np.median(v)) if toutes and v else None


def proposer(mesures, tailles, boites) -> dict:
    """Cadres proposés {numéro: {x, y, w, h, a}} pour les pages simples sans cadre réglé. `boites` : cadres déjà réglés (repères, jamais remplacés ;
    ceux marqués « c » ou « d » ne servent pas de repères)."""
    reperes = {int(k): b for k, b in boites.items() if not (b.get("c") or b.get("d"))}
    simples = [i for i, t in enumerate(tailles) if t[0] <= 1.1 * t[1]]
    bords = {"gauche": {}, "droite": {}}
    for i in simples:                                        # bords trouvés, puis gardés seulement s'ils ressemblent à ceux des voisines
        for c in bords:
            t = (mesures.get(i) or {}).get(c)
            if t:
                bords[c][i] = t["xm"]
    gardes = {c: {} for c in bords}
    for c in bords:
        for i, x in bords[c].items():
            m = _mediane_voisines(bords[c], i)
            if m is None or abs(x - m) <= TOL * tailles[i][0]:
                gardes[c][i] = x
        for i, b in reperes.items():                         # un cadre réglé à la main dit où est le bord (il prime)
            if i in simples:
                gardes[c][i] = b["x"] if c == "gauche" else b["x"] + b["w"]
    hauts = {i: b["y"] for i, b in reperes.items() if i in simples}
    bas = {i: b["y"] + b["h"] for i, b in reperes.items() if i in simples}
    out = {}
    for i in simples:
        if str(i) in boites and not boites[str(i)].get("d"):
            continue
        w, h = tailles[i]
        g, d = gardes["gauche"].get(i), gardes["droite"].get(i)              # pas de trait (ou un trait isolé) : pas de bande de ce côté, le bord de la page
        g = 0.0 if g is None else max(-0.05 * w, min(0.3 * w, g))
        d = float(w) if d is None else max(0.7 * w, min(1.05 * w, d))
        y0 = hauts.get(i, _mediane_voisines(hauts, i, toutes=True))
        y1 = bas.get(i, _mediane_voisines(bas, i, toutes=True))
        y0 = 0.0 if y0 is None else max(-0.05 * h, min(0.2 * h, y0))
        y1 = float(h) if y1 is None else max(0.8 * h, min(1.05 * h, y1))
        angle = 0.0
        m = mesures.get(i) or {}
        if m.get("gauche") and m.get("droite") and abs(m["gauche"]["pente"] - m["droite"]["pente"]) <= ACCORD:
            moyenne = (m["gauche"]["pente"] + m["droite"]["pente"]) / 2
            angle = moyenne if abs(moyenne) >= ANGLE_MINI else 0.0
        out[i] = {"x": int(round(g)), "y": int(round(y0)), "w": int(round(d - g)), "h": int(round(y1 - y0)), "a": round(float(angle), 2)}
    return out
