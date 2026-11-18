"""
🧩 Recadrage aux cases d'un tome scanné à plat (deux pages par scan, coupé en deux moitiés), mis au point le 18/11/2026 avec l'utilisateur sur Nori Taka
tome 3. Tout part des pages d'origine (rognage.py) ; rien n'est demandé page par page.

1. Chaque moitié de scan est redressée (reliure.redressement, mesuré dans le cadre réglé à la main s'il y en a un).
2. Taille réelle de la page : le fond noir des flash-backs va d'un bord du papier à l'autre (mesuré : 1037 px de haut sur le tome 3) ; sans flash-back, la
   hauteur du bloc de cases (les traits de cadre sont presque au bord du papier).
3. Une boîte de cette taille est posée sur le trait du haut des cases et le bord extérieur de la page (jamais sur l'autre moitié du scan).
4. Page blanche (couper_cases) : coupée au ras des cadres de cases (le vrai cadre est le plus intérieur des longs traits du bord : la tranche des pages du
   dessous est dehors), cases fermées par leurs traits, gouttières et extérieur en blanc, côté reliure recoupé droit sans jamais couper un texte, un seul
   trait droit refait par côté (l'ancien effacé).
5. Flash-back (fond_cases) : les cases sont des rectangles droits entre les gouttières sombres (gouttières en biais suivies), leur intérieur n'est jamais
   touché, tout le reste devient noir franc sauf les lignes de texte. Demi flash-back (une grande case claire à fond perdu en bas) : remplissage depuis
   les bords puis même découpe, côtés coupés droit quelques px à l'intérieur du dernier trait.
6. Mise en page : page blanche recadrée sur ses cases et en plein écran ; flash-back au zoom médian des pages blanches (ses cases restent plus petites
   dans le cadre noir, comme dans le livre).

Les pages qui ne sont pas une moitié de scan (couverture, doubles pages, page seule) restent celles du tome actuel.
"""
import io
import shutil
import tempfile
import zipfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import archives
import reliure

BORD = 4                       # lignes du bord du scan ignorées (artefacts)
MARGE = 0.985                  # part de la page occupée par les cases d'une page blanche


# --- Outils --------------------------------------------------------------------------------------------------------------------------------

def runs(v):
    """(début, fin) des suites de True."""
    v = np.r_[False, v, False].astype(np.int8)
    dv = np.diff(v)
    return list(zip(np.where(dv == 1)[0], np.where(dv == -1)[0]))


def _suites(v, mini):
    return [(a, b) for a, b in runs(v) if b - a >= mini]


def lignes_fines(g):
    """Traits fins sombres : (horizontaux, verticaux)."""
    bh = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, np.ones((9, 9), np.uint8))
    m = (bh > 40).astype(np.uint8)
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((1, 15), np.uint8)), cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((15, 1), np.uint8))


def redresse(g, boite=None):
    """Moitié de scan redressée ; le redressement est mesuré dans le cadre réglé à la main (la tranche des pages voisines, dehors, fausserait la mesure)."""
    H, W = g.shape
    x, y, w, h = (0, 0, W, H) if not boite else (float(boite[k]) for k in ("x", "y", "w", "h"))
    cx0, cy0, cx1, cy1 = max(0, int(x)), max(0, int(y)), min(W, int(x + w)), min(H, int(y + h))
    if cx1 - cx0 < 200 or cy1 - cy0 < 200:
        cx0, cy0, cx1, cy1 = 0, 0, W, H
    c = reliure.redressement(np.ascontiguousarray(g[cy0:cy1, cx0:cx1]))
    if not c:
        return g
    T = np.array([[1, 0, -cx0], [0, 1, -cy0], [0, 0, 1.]])
    M = np.linalg.inv(T) @ reliure.matrice_redressement(c, cx1 - cx0, cy1 - cy0) @ T
    return cv2.warpPerspective(g, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def fond_sombre(g):
    """Bords du fond sombre d'un flash-back (haut, bas, gauche, droite) : premières lignes/colonnes, depuis le bord, dont la médiane est sombre."""
    h, w = g.shape
    papier = float(np.percentile(g, 95))
    s = 0.62 * papier
    rows = np.median(g[:, int(.2 * w):int(.8 * w)], 1) < s
    cols = np.median(g[int(.2 * h):int(.8 * h), :], 0) < s

    def premier(v, n):
        for k in range(n):
            if v[k] and v[k:k + 6].all():
                return k
        return None
    t, b = premier(rows, int(.1 * h)), premier(rows[::-1], int(.1 * h))
    l, r = premier(cols, int(.12 * w)), premier(cols[::-1], int(.12 * w))
    return {"haut": t, "bas": None if b is None else h - b, "gauche": l, "droite": None if r is None else w - r}


def traits(g):
    """Traits de cadre extérieurs de la page : haut, bas, gauche, droite (bord extérieur du trait) ou None."""
    h, w = g.shape
    hor, ver = lignes_fines(g)
    ch = cv2.dilate(hor, np.ones((3, 1), np.uint8)).sum(1) / w
    cv = cv2.dilate(ver, np.ones((1, 3), np.uint8)).sum(0) / h
    zh, zw = int(0.07 * h), int(0.12 * w)
    ok = lambda rs: [r for r in rs if r[0] >= BORD]
    okb = lambda rs, n: [r for r in rs if r[1] <= n - BORD]
    rt = ok(runs(ch[:zh] >= 0.22))
    rb = okb([(a + h - zh, b + h - zh) for a, b in runs(ch[h - zh:] >= 0.22)], h)
    rl = ok(runs(cv[:zw] >= 0.20))
    rr = okb([(a + w - zw, b + w - zw) for a, b in runs(cv[w - zw:] >= 0.20)], w)
    return {"haut": int(rt[0][0]) if rt else None, "bas": int(rb[-1][1]) if rb else None,
            "gauche": int(rl[0][0]) if rl else None, "droite": int(rr[-1][1]) if rr else None}


def gouttieres_relatives(g):
    """Nombre de gouttières horizontales plus sombres que les cases (flash-back délavé)."""
    h, w = g.shape
    bande = g[:, int(.1 * w):int(.9 * w)].astype(np.float32)
    papier = float(np.percentile(g, 95))
    med = np.median(bande, 1)
    clair = (bande > 0.8 * papier).mean(1)
    sombre = (med < 0.68 * papier) & ((bande < 0.72 * papier).mean(1) > 0.8)
    n, i, fin, m = 0, int(.05 * h), int(.95 * h), int(.03 * h)
    while i < fin:
        if not sombre[i]:
            i += 1
            continue
        j = i
        while j < fin and sombre[j]:
            j += 1
        if 0.006 * h <= j - i <= 0.06 * h and clair[max(0, i - m):i].max(initial=0) > 0.3 and clair[j:j + m].max(initial=0) > 0.3:
            n += 1
        i = j
    return n


def est_flashback(g):
    """Page sur fond noir (gris délavé compris), ou moitié de page (fond sombre en haut et au moins une gouttière sombre)."""
    if reliure.fond_noir(g):
        return True
    f = fond_sombre(g)
    return f["haut"] is not None and f["haut"] > BORD and gouttieres_relatives(g) >= 1


# --- Taille réelle et boîte --------------------------------------------------------------------------------------------------------------

def hauteur_reelle(pages):
    """Hauteur de la page en px du scan. `pages` : [(image redressée, flash-back ?)]. Fond noir des flash-backs (d'un bord du papier à l'autre), sinon
    bloc de cases des pages blanches (+ 4 px de trait). None si rien de sûr."""
    fb, blocs = [], []
    for g, est_fb in pages:
        h = g.shape[0]
        if est_fb:
            f = fond_sombre(g)
            if f["haut"] is not None and f["bas"] is not None and f["haut"] > BORD and f["bas"] < h - BORD:
                fb.append(f["bas"] - f["haut"])
        else:
            t = traits(g)
            if t["haut"] is not None and t["bas"] is not None:
                blocs.append(t["bas"] - t["haut"])
    if len(fb) >= 2:
        return int(round(float(np.median(fb))))
    if len(blocs) >= 5:
        return int(round(float(np.median(blocs)))) + 4
    return None


def boite(g, cote_ext, fb, HR):
    """(y0, bord extérieur, sûr) de la boîte HR de haut. cote_ext : côté opposé au dos ; sûr : haut ET bas trouvés et cohérents."""
    h, w = g.shape
    t = traits(g)
    f = fond_sombre(g) if fb else {}
    haut = f.get("haut") if fb and f.get("haut") is not None else t["haut"]
    bas = f.get("bas") if fb and f.get("bas") is not None and f["bas"] < h - BORD else t["bas"]
    if haut is not None and bas is not None and abs((bas - haut) - HR) > 30:      # incohérents : on garde le plus proche du bord du scan
        if haut < h - bas:
            bas = None
        else:
            haut = None
    sur = haut is not None and bas is not None
    y0 = haut if haut is not None else (bas - HR if bas is not None else None)
    ext = f.get(cote_ext) if fb else None
    if ext is None or (cote_ext == "gauche" and ext <= BORD) or (cote_ext == "droite" and ext >= w - BORD):
        ext = t[cote_ext]
    if ext is None:
        ext = 0 if cote_ext == "gauche" else w
    return y0, ext, sur


# --- Page blanche ---------------------------------------------------------------------------------------------------------------------------

def cadres(g):
    """Masque des traits de cadre (longs traits droits fins, en biais compris) avec leurs petits trous bouchés."""
    h, w = g.shape
    lisse = cv2.medianBlur(g, 3)
    k = max(9, (min(h, w) // 70) | 1)
    papier = float(np.percentile(g, 95))
    fin = ((cv2.morphologyEx(lisse, cv2.MORPH_BLACKHAT, np.ones((k, k), np.uint8)) > 40) | (lisse < 0.25 * papier)).astype(np.uint8)
    fin &= 1 - cv2.morphologyEx(fin, cv2.MORPH_OPEN, np.ones((11, 11), np.uint8))     # un trait est fin : pas les aplats noirs
    L = max(41, w // 25)
    hor = cv2.morphologyEx(cv2.morphologyEx(fin, cv2.MORPH_OPEN, np.ones((1, L), np.uint8)), cv2.MORPH_CLOSE, np.ones((1, 61), np.uint8))
    ver = cv2.morphologyEx(cv2.morphologyEx(fin, cv2.MORPH_OPEN, np.ones((L, 1), np.uint8)), cv2.MORPH_CLOSE, np.ones((61, 1), np.uint8))
    res = hor | ver
    seg = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(lisse)[0]
    if seg is not None:
        pres = cv2.dilate(fin, np.ones((5, 5), np.uint8))
        for xa, ya, xb, yb in seg.reshape(-1, 4):
            if np.hypot(xb - xa, yb - ya) < max(40, w // 12):
                continue
            xs = np.clip(np.linspace(xa, xb, 12).round().astype(int), 0, w - 1)
            ys = np.clip(np.linspace(ya, yb, 12).round().astype(int), 0, h - 1)
            if pres[ys, xs].mean() >= 0.8:
                cv2.line(res, (int(xa), int(ya)), (int(xb), int(yb)), 1, 3)
    return cv2.dilate(res, np.ones((5, 5), np.uint8)) > 0


def couper_cases(c, rempli, cote_dos, epaisseur=3):
    """Page blanche coupée aux cadres (voir l'en-tête). `rempli` : papier ajouté hors du scan. Retour : image, masque des traits tracés."""
    h, w = c.shape
    papier = 255
    hor, ver = lignes_fines(c)
    pres = cv2.dilate(rempli.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    hor[pres] = 0
    ver[pres] = 0
    ch = cv2.dilate(hor, np.ones((3, 1), np.uint8)).sum(1) / w
    cv = cv2.dilate(ver, np.ones((1, 3), np.uint8)).sum(0) / h
    zh, zw = int(0.06 * h), int(0.08 * w)

    def premier(prof):
        """Le plus INTÉRIEUR des longs traits du bord (la tranche des pages du dessous et le bord du scan sont dehors, souvent plus longs)."""
        r = [(a, b, float(prof[a:b].max())) for a, b in runs(prof >= 0.15)]
        if not r:
            return 0
        m = max(x[2] for x in r)
        return int([x for x in r if x[2] >= 0.4 * m][-1][0])
    lim = {"haut": premier(ch[:zh]), "bas": premier(ch[::-1][:zh]), "gauche": premier(cv[:zw]), "droite": premier(cv[::-1][:zw])}
    # côté reliure : bande parasite (gris lisse ou traits) depuis le bord, coupée juste après
    t = c.T
    lp = ver.T
    if cote_dos == "droite":
        t, lp = t[::-1], lp[::-1]
    f = t.astype(np.float32)
    ecart = np.sqrt(np.maximum(cv2.blur(f * f, (5, 5)) - cv2.blur(f, (5, 5)) ** 2, 0))
    score = (((t > 0.35 * papier) & (t < 0.88 * papier) & (ecart < 8)) | (lp > 0)).mean(1)
    zone = int(0.07 * t.shape[0])
    k0 = 0
    while k0 < zone and t[k0].mean() > 0.97 * papier:
        k0 += 1
    fin = 0
    for k in range(k0, zone + k0):
        if score[k] > 0.15:
            fin = k + 1
        elif k - max(fin, k0) > 4:
            break
    lim[cote_dos] = max(lim[cote_dos], fin + 3, k0 + int(0.015 * t.shape[0]))
    # jamais de texte coupé : une lettre (avec des voisines sur sa ligne) entre le bord et la coupe fait reculer la coupe juste avant elle
    enc = (c < 0.5 * papier).astype(np.uint8)
    blanc = cv2.blur((c > 0.8 * papier).astype(np.float32), (21, 21)) > 0.55
    nl, labl, stl, cen = cv2.connectedComponentsWithStats(enc, connectivity=8)
    lettres = [j for j in range(1, nl) if 5 <= stl[j, 3] <= 22 and 2 <= stl[j, 2] <= 22 and blanc[int(cen[j][1]), int(cen[j][0])]]
    pc = np.array([cen[j] for j in lettres]) if lettres else np.zeros((0, 2))
    texte = []
    for i_, j in enumerate(lettres):
        if np.sum((np.abs(pc[:, 1] - pc[i_, 1]) < 6) & (np.abs(pc[:, 0] - pc[i_, 0]) < 40)) - 1 < 2:
            continue
        x_, y_, ww_, hh_ = stl[j, 0], stl[j, 1], stl[j, 2], stl[j, 3]
        texte.append((x_, y_, ww_, hh_))
        dist = {"haut": y_, "bas": h - (y_ + hh_), "gauche": x_, "droite": w - (x_ + ww_)}
        for cote in lim:
            plancher = k0 if cote == cote_dos else 0
            if plancher <= dist[cote] < lim[cote]:
                lim[cote] = max(plancher, dist[cote] - 2)
    y0, y1, x0, x1 = lim["haut"], h - lim["bas"], lim["gauche"], w - lim["droite"]
    # cases fermées par les traits et le cadre de coupe ; le reste relié au cadre devient papier
    tr = cadres(c)
    tr[pres] = False
    bord = np.zeros((h, w), bool)
    bord[y0:y0 + epaisseur, x0:x1] = True
    bord[y1 - epaisseur:y1, x0:x1] = True
    bord[y0:y1, x0:x0 + epaisseur] = True
    bord[y0:y1, x1 - epaisseur:x1] = True
    dedans = np.zeros((h, w), bool)
    dedans[y0:y1, x0:x1] = True
    libre = dedans & ~tr & ~bord
    n, lab, st, _ = cv2.connectedComponentsWithStats(libre.astype(np.uint8), connectivity=4)
    dt = cv2.distanceTransform(libre.astype(np.uint8), cv2.DIST_L2, 3)
    large = np.zeros(n, np.float32)
    np.maximum.at(large, lab.ravel(), dt.ravel())
    case = (large >= 14) & (st[:, cv2.CC_STAT_AREA] >= 0.004 * h * w)
    case[0] = False
    touche = np.zeros(n, bool)
    touche[np.unique(lab[(cv2.dilate(bord.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) & libre])] = True
    dehors_lab = touche & ~case
    dehors_lab[0] = False
    s_ = c.copy()
    s_[~dedans] = papier
    s_[dehors_lab[lab]] = papier
    noir = int(np.percentile(c[tr & dedans], 20)) if (tr & dedans).any() else 20
    trace = np.zeros((h, w), bool)
    estcase = case[lab] & libre
    D = max(10, int(0.02 * h))

    def texte_avant(cote):
        d = [{"haut": y_ - y0, "bas": y1 - (y_ + hh_), "gauche": x_ - x0, "droite": x1 - (x_ + ww_)}[cote] for x_, y_, ww_, hh_ in texte
             if x0 <= x_ < x1 and y0 <= y_ < y1]
        d = [v for v in d if v >= 0]
        return min(d) if d else 10 ** 6
    final = {}
    for cote in ("haut", "bas", "gauche", "droite"):
        vues = [s_[y0:y1, x0:x1], tr[y0:y1, x0:x1], estcase[y0:y1, x0:x1], trace[y0:y1, x0:x1]]
        if cote == "bas":
            vues = [v[::-1] for v in vues]
        elif cote == "gauche":
            vues = [v.T for v in vues]
        elif cote == "droite":
            vues = [v.T[::-1] for v in vues]
        vs, vt, vc, tv = vues
        v = vc[:D + epaisseur + 4].any(0)                # une case arrive jusqu'à la coupe
        v = cv2.morphologyEx(v.astype(np.uint8).reshape(1, -1), cv2.MORPH_CLOSE, np.ones((1, 9), np.uint8)).ravel() > 0
        troncons = [(a_, b_) for a_, b_ in runs(v) if b_ - a_ >= 15]
        if not troncons:
            continue
        p = 0                                            # UN trait droit par côté, à la place de l'ancien trait le plus enfoncé ; devant : effacé
        for a_, b_ in troncons:
            prof = np.array([(np.where(vt[:D, j])[0][-1] if vt[:D, j].any() else -1) for j in range(a_, b_)])
            if (prof >= 0).mean() > 0.3:
                p = max(p, int(np.percentile(prof[prof >= 0], 90)) + 1)
        p = max(0, min(p, texte_avant(cote) - epaisseur - 2))
        final[cote] = p
        vs[:p, :] = papier
        for a_, b_ in troncons:
            vs[p:p + epaisseur, a_:b_] = np.minimum(vs[p:p + epaisseur, a_:b_], noir)
            tv[p:p + epaisseur, a_:b_] = True
    garde = np.zeros((h, w), bool)
    garde[y0 + final.get("haut", 0):y1 - final.get("bas", 0), x0 + final.get("gauche", 0):x1 - final.get("droite", 0)] = True
    s_[~garde] = papier
    trace[~garde] = False
    return s_, trace


# --- Flash-back -----------------------------------------------------------------------------------------------------------------------------

def liseres_noirs(g, papier):
    """Le mince liseré clair du bord du scan (papier hors du fond noir) devient noir ; une case claire qui va jusqu'au bord est plus longue."""
    g = g.copy()
    h, w = g.shape
    noir = int(min(25, np.percentile(g, 1)))
    lisse = cv2.medianBlur(g, 5)
    for vue, n in ((lisse, int(0.04 * w)), (lisse.T, int(0.03 * h))):
        cible = g if vue is lisse else g.T
        for sens in (1, -1):
            v, c = vue[:, ::sens], cible[:, ::sens]
            for i in range(v.shape[0]):
                ligne = v[i, :n + 8]
                d0 = 0
                while d0 < n and ligne[d0] < 0.6 * papier:
                    d0 += 1
                k = d0
                while k < n and ligne[k] >= 0.6 * papier:
                    k += 1
                if d0 < k < n and k - d0 <= 0.025 * w and (ligne[k:k + 8] < 0.6 * papier).mean() > 0.7:
                    c[i, d0:k] = noir
    return g


def fond_rempli(g, rempli=None):
    """Fond relié au bord de la page sans traverser un trait de cadre, sombre presque partout autour de lui : noir franc. Une case claire à fond perdu
    (pas fermée) l'arrête. Les restes clairs minces et longs du fond (bord de page, bord du scan) deviennent noirs aussi."""
    h, w = g.shape
    papier = float(np.percentile(g, 95))
    g = liseres_noirs(g, papier)
    tr = cadres(g)
    if rempli is not None:                               # la limite du scan est un bord droit : une case coupée par elle reste fermée
        r = rempli.astype(bool)
        tr |= (cv2.dilate(r.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0) & ~r
    n, lab = cv2.connectedComponents((~tr).astype(np.uint8), connectivity=4)
    touche = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    dehors = np.isin(lab, touche[touche > 0])
    sombre = dehors & (cv2.medianBlur(g, 7) < 0.82 * papier) & (g < 0.88 * papier)
    r = max(25, w // 25) | 1
    D = cv2.blur(sombre.astype(np.float32), (r, r)) / np.maximum(cv2.blur(dehors.astype(np.float32), (r, r)), 1e-3)
    zone = cv2.morphologyEx((sombre & (D > 0.55)).astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    nz0, labz0, stz0, _ = cv2.connectedComponentsWithStats(zone, connectivity=8)
    e = max(4, w // 60)
    bordj = set(np.unique(np.concatenate([labz0[:e].ravel(), labz0[-e:].ravel(), labz0[:, :e].ravel(), labz0[:, -e:].ravel()]))) - {0}
    zone = np.isin(labz0, [j for j in bordj if stz0[j, cv2.CC_STAT_AREA] >= 0.01 * h * w])
    zone = cv2.dilate(zone.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & sombre
    zone |= tr & cv2.dilate(zone.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool) & (g < 0.6 * papier)
    noir = int(min(25, np.percentile(g, 1)))
    sortie = g.copy()
    sortie[zone] = noir
    clair = (dehors & (sortie >= 0.35 * papier)).astype(np.uint8)
    nc, labc, stc, _ = cv2.connectedComponentsWithStats(clair, connectivity=8)
    for j in range(1, nc):
        long_ = max(stc[j, cv2.CC_STAT_WIDTH], stc[j, cv2.CC_STAT_HEIGHT])
        if long_ >= 30 and stc[j, cv2.CC_STAT_AREA] <= 12 * long_:
            sortie[labc == j] = noir
    return sortie


def fond_cases(g, rempli=None, seuil_g=0.93):
    """Cases = rectangles droits entre les gouttières sombres (découpe alternée horizontale / verticale, gouttières droites en biais suivies) ; leur
    intérieur n'est jamais touché, tout le reste devient noir sauf les lignes de texte. Retour : image, masque des cases."""
    h, w = g.shape
    papier = float(np.percentile(g, 95))
    sombre = cv2.medianBlur(g, 5) < 0.6 * papier
    if rempli is not None:
        sombre |= rempli.astype(bool)
    cases = np.zeros((h, w), bool)
    rects = []
    mh, mw = int(0.02 * h), int(0.03 * w)

    def decouper(y0, y1, x0, x1, prof, poly=None):
        z = sombre[y0:y1, x0:x1] if poly is None else (sombre | ~poly)[y0:y1, x0:x1]
        for axe in ((0, 1) if prof % 2 == 0 else (1, 0)):
            pr = z.mean(1 - axe) > (seuil_g if prof == 0 else 0.9)
            parts = _suites(~pr, mh if axe == 0 else mw)
            if (len(parts) > 1 or (parts and (parts[0][0] > 0 or parts[-1][1] < len(pr)))) and prof < 6:
                for a_, b_ in parts:
                    if axe == 0:
                        decouper(y0 + a_, y0 + b_, x0, x1, prof + 1, poly)
                    else:
                        decouper(y0, y1, x0 + a_, x0 + b_, prof + 1, poly)
                return
        if poly is not None:
            cases[y0:y1, x0:x1] |= poly[y0:y1, x0:x1]
        elif not biais(y0, y1, x0, x1, prof):
            cases[y0:y1, x0:x1] = True
            rects.append((y0, y1, x0, x1))

    def biais(y0, y1, x0, x1, prof):
        """Gouttière droite en biais qui traverse la case de part en part : la case est coupée le long d'elle, chaque morceau est redécoupé."""
        hh, ww = y1 - y0, x1 - x0
        if hh < 60 or ww < 60:
            return False
        meilleur = None
        for vertical in (True, False):
            L, T = (ww, hh) if vertical else (hh, ww)
            ts = np.arange(0, T, 3)
            pos = np.arange(int(0.08 * L), int(0.92 * L), 3)
            for a in pos:
                for b in pos[np.abs(pos - a) <= 0.35 * T]:
                    if a == b:
                        continue
                    u = (a + (b - a) * ts / T).astype(int)
                    ys, xs = (y0 + ts, x0 + u) if vertical else (y0 + u, x0 + ts)
                    fr = sombre[ys, xs].mean()
                    if fr > 0.95 and (meilleur is None or fr > meilleur[0]):
                        meilleur = (fr, vertical, a, b)
        if meilleur is None:
            return False
        _, vertical, a, b = meilleur
        T = hh if vertical else ww
        ts = np.arange(0, T, 3)
        larg = 1
        while larg < 25:
            ok = True
            for dd in (-larg - 1, larg + 1):
                u = np.clip((a + dd + (b - a) * ts / T).astype(int), 0, (ww if vertical else hh) - 1)
                ys, xs = (y0 + ts, x0 + u) if vertical else (y0 + u, x0 + ts)
                ok &= sombre[ys, xs].mean() > 0.85
            if not ok:
                break
            larg += 1
        if vertical:
            morceaux = (np.array([[x0, y0], [x0 + a - larg, y0], [x0 + b - larg, y1], [x0, y1]], np.int32),
                        np.array([[x0 + a + larg, y0], [x1, y0], [x1, y1], [x0 + b + larg, y1]], np.int32))
        else:
            morceaux = (np.array([[x0, y0], [x1, y0], [x1, y0 + b - larg], [x0, y0 + a - larg]], np.int32),
                        np.array([[x0, y0 + a + larg], [x1, y0 + b + larg], [x1, y1], [x0, y1]], np.int32))
        for morceau in morceaux:
            m = np.zeros((h, w), np.uint8)
            cv2.fillPoly(m, [morceau], 1)
            m[:y0] = 0
            m[y1:] = 0
            m[:, :x0] = 0
            m[:, x1:] = 0
            ys_, xs_ = np.where(m > 0)
            if len(ys_):
                decouper(ys_.min(), ys_.max() + 1, xs_.min(), xs_.max() + 1, prof + 1, m > 0)
        return True

    decouper(0, h, 0, w, 0)
    # une bulle qui déborde de sa case agrandit le rectangle : au-delà du vrai trait de la case, et sur l'aplat du ton du fond qui touche le bord
    # du rectangle, le fond passe au noir
    bh = cv2.morphologyEx(cv2.medianBlur(g, 3), cv2.MORPH_BLACKHAT, np.ones((15, 15), np.uint8)) > 40
    vert = cv2.morphologyEx(bh.astype(np.uint8), cv2.MORPH_OPEN, np.ones((31, 1), np.uint8))
    hori = cv2.morphologyEx(bh.astype(np.uint8), cv2.MORPH_OPEN, np.ones((1, 31), np.uint8))
    a_noircir = np.zeros((h, w), bool)
    for y0, y1, x0, x1 in rects:
        hh, ww = y1 - y0, x1 - x0
        cvv = cv2.dilate(vert[y0:y1, x0:x1], np.ones((1, 3), np.uint8)).mean(0)
        chh = cv2.dilate(hori[y0:y1, x0:x1], np.ones((3, 1), np.uint8)).mean(1)
        for cote in ("gauche", "droite", "haut", "bas"):
            pr, n_ = (cvv, ww) if cote in ("gauche", "droite") else (chh, hh)
            z_ = int(0.3 * n_)
            idx = np.arange(5, z_) if cote in ("gauche", "haut") else np.arange(n_ - 6, n_ - z_, -1)
            ok_ = [i for i in idx if pr[i] >= 0.6]
            if not ok_:
                continue
            i = ok_[0]
            sl = {"gauche": np.s_[y0:y1, x0:x0 + i], "droite": np.s_[y0:y1, x0 + i + 1:x1],
                  "haut": np.s_[y0:y0 + i, x0:x1], "bas": np.s_[y0 + i + 1:y1, x0:x1]}[cote]
            if sombre[sl].size and sombre[sl].mean() >= 0.5:
                a_noircir[sl] = True
    noir = int(min(25, np.percentile(g, 1)))
    dehors = ~cases
    clair = (dehors & (g >= 0.7 * papier)).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(clair, connectivity=8)
    petits = [j for j in range(1, n) if 6 <= max(st[j, cv2.CC_STAT_WIDTH], st[j, cv2.CC_STAT_HEIGHT]) <= 28]
    pc = np.array([cen[j] for j in petits]) if petits else np.zeros((0, 2))
    lettre = np.zeros(n, bool)
    for i_, j in enumerate(petits):                       # une lettre a des voisines sur sa ligne (pas une poussière isolée)
        if np.sum((np.abs(pc[:, 1] - pc[i_, 1]) < 8) & (np.abs(pc[:, 0] - pc[i_, 0]) < 60)) - 1 >= 2:
            lettre[j] = True
    garde = cv2.dilate((lettre[lab] & (clair > 0)).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & dehors
    fondv = g[dehors & sombre & ~(rempli.astype(bool) if rempli is not None else np.zeros_like(sombre))]
    if fondv.size > 1000:
        ton = float(np.median(fondv))
        f32 = cv2.GaussianBlur(g, (0, 0), 1.5).astype(np.float32)
        ecart = np.sqrt(np.maximum(cv2.blur(f32 * f32, (7, 7)) - cv2.blur(f32, (7, 7)) ** 2, 0))
        aplat = (np.abs(f32 - ton) < 28) & (ecart < 9)
        for y0, y1, x0, x1 in rects:
            z = aplat[y0:y1, x0:x1].astype(np.uint8)
            n_, lab_, st_, _ = cv2.connectedComponentsWithStats(z, connectivity=4)
            for j in set(np.unique(np.concatenate([lab_[:3].ravel(), lab_[-3:].ravel(), lab_[:, :3].ravel(), lab_[:, -3:].ravel()]))) - {0}:
                if st_[j, cv2.CC_STAT_AREA] >= 0.01 * z.size:
                    a_noircir[y0:y1, x0:x1] |= lab_ == j
    sortie = g.copy()
    sortie[dehors & ~garde] = noir
    sortie[a_noircir & sombre] = noir
    return sortie, cases


def flashback(a, rempli):
    """Flash-back fini (après les retouches) : (image, masque du contenu)."""
    fc, cs = fond_cases(a, rempli=rempli)
    if cs.mean() < 0.85:
        return fc, cs
    a = fond_rempli(a, rempli=rempli)                     # demi flash-back : pas de découpe d'emblée
    a, contenu = fond_cases(a, rempli=rempli, seuil_g=0.8)
    h, w = a.shape
    _, ver = lignes_fines(a)
    cv = cv2.dilate(ver, np.ones((1, 3), np.uint8)).sum(0) / h
    noir = int(min(25, np.percentile(a, 1)))
    d = int(0.8 * w) + np.where(cv[int(0.8 * w):] >= 0.3)[0]
    if len(d):                                           # coupe droite quelques px à l'intérieur du dernier groupe de traits (la bande collée part avec)
        k = len(d) - 1
        while k > 0 and d[k] - d[k - 1] <= 6:
            k -= 1
        x = int(d[k]) - 8
        a[:, x:] = noir
        contenu[:, x:] = False
    g_ = np.where(cv[:int(0.2 * w)] >= 0.3)[0]
    if len(g_):
        k = 0
        while k < len(g_) - 1 and g_[k + 1] - g_[k] <= 6:
            k += 1
        x = int(g_[k]) + 8
        a[:, :x] = noir
        contenu[:, :x] = False
    return a, contenu


# --- Une page, un tome -----------------------------------------------------------------------------------------------------------------------

def paires(tailles):
    """[(gauche, droite)] : pages simples consécutives de même hauteur et de largeurs à 2 px près (les deux moitiés d'un même scan)."""
    res, i = [], 0
    while i + 1 < len(tailles):
        (wa, ha), (wb, hb) = tailles[i], tailles[i + 1]
        if ha == hb and abs(wa - wb) <= 2 and wa < 0.8 * ha and wb < 0.8 * hb:
            res.append((i, i + 1))
            i += 2
        else:
            i += 1
    return res


def placer(gauche, droite, est_gauche, fb, HR, WR, partenaire_y):
    """La page (moitié gauche ou droite du scan) dans sa boîte HR × WR : (image, papier ajouté hors du scan)."""
    g = gauche if est_gauche else droite
    cote_ext = "gauche" if est_gauche else "droite"
    y0, ext, sur = boite(g, cote_ext, fb, HR)
    if partenaire_y is not None and (not sur or y0 is None):
        y0 = partenaire_y                                 # le haut de l'autre moitié du même scan, plus sûr
    if y0 is None:
        y0 = (g.shape[0] - HR) // 2
    planche = np.hstack([gauche, droite])
    dx = 0 if est_gauche else gauche.shape[1]
    x0 = (ext if est_gauche else ext - WR) + dx
    H, W = planche.shape
    c = np.full((HR, WR), int(np.percentile(g, 2)) if fb else int(np.percentile(g, 95)), np.uint8)
    ya, yb, xa, xb = max(0, y0), min(H, y0 + HR), max(0, x0), min(W, x0 + WR)
    lo, hi = (0, gauche.shape[1]) if est_gauche else (gauche.shape[1], W)        # jamais l'autre page du scan
    xa, xb = max(xa, lo), min(xb, hi)
    rempli = np.ones((HR, WR), bool)
    if xb > xa and yb > ya:
        c[ya - y0:yb - y0, xa - x0:xb - x0] = planche[ya:yb, xa:xb]
        rempli[ya - y0:yb - y0, xa - x0:xb - x0] = False
    return c, rempli


def recadrer_tome(chemin, source, boites, taille, retouches, destination, progres=None) -> dict:
    """Écrit dans `destination` le tome recadré aux cases. `source` : fichier des pages d'origine ; `boites` : cadres réglés à la main {numéro: boîte}
    (mesure du redressement) ; `taille` : (W, H) des pages finales ; `retouches` : réglages ✨ à appliquer (sans redresser ni flash-back, faits ici).
    Les pages hors paires sont recopiées du tome actuel. Retour : {"pages", "flashbacks", "hauteur", "zoom"}."""
    import optimiser
    W, H = int(taille[0]), int(taille[1])
    ordre_s, ordre = archives.pages(source), archives.pages(chemin)
    if len(ordre_s) != len(ordre):
        raise RuntimeError("le tome n'a plus le même nombre de pages que ses pages d'origine")
    with zipfile.ZipFile(source) as zs:
        tailles = [Image.open(io.BytesIO(zs.read(n))).size for n in ordre_s]
    lp = paires(tailles)
    regl = optimiser.reglages_amelioration({k: v for k, v in (retouches or {}).items() if k not in ("redresser", "flashback", "recadrer")})
    tmp = Path(tempfile.mkdtemp(prefix="cases-"))
    etapes = 3 * len(lp)
    fait = [0]

    def avance():
        fait[0] += 1
        if progres:
            progres(fait[0], etapes)
    try:
        # 1. moitiés redressées, flash-backs, taille réelle
        info = {}
        with zipfile.ZipFile(source) as zs:
            for a, b in lp:
                for i in (a, b):
                    g = np.array(Image.open(io.BytesIO(zs.read(ordre_s[i]))).convert("L"))
                    g = redresse(g, boites.get(str(i)))
                    cv2.imwrite(str(tmp / f"r{i}.png"), g)
                    info[i] = est_flashback(g)
                avance()
        HR = hauteur_reelle([(cv2.imread(str(tmp / f"r{i}.png"), cv2.IMREAD_GRAYSCALE), info[i]) for i in info])
        if not HR:
            raise RuntimeError("taille réelle de la page introuvable (ni flash-back, ni traits de cases nets)")
        WR = round(HR * W / H)
        # 2. chaque page placée, coupée, retouchée ; contenu mesuré
        cadrage = {}
        for a, b in lp:
            gauche = cv2.imread(str(tmp / f"r{a}.png"), cv2.IMREAD_GRAYSCALE)
            droite = cv2.imread(str(tmp / f"r{b}.png"), cv2.IMREAD_GRAYSCALE)
            hauts = {}
            for i, est_g in ((a, True), (b, False)):
                y0, _, sur = boite(gauche if est_g else droite, "gauche" if est_g else "droite", info[i], HR)
                hauts[i] = y0 if sur else None
            for i, est_g in ((a, True), (b, False)):
                autre = b if i == a else a
                c, rempli = placer(gauche, droite, est_g, info[i], HR, WR, hauts[autre])
                if not info[i]:
                    c, _ = couper_cases(c, rempli, "droite" if est_g else "gauche")
                out = cv2.resize(c, (W, H), interpolation=cv2.INTER_CUBIC)
                rem = cv2.resize(rempli.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
                if regl:
                    out = np.array(optimiser.ameliorer(Image.fromarray(out), regl, source=H / HR).convert("L"))
                    if out.shape != (H, W):
                        out = cv2.resize(out, (W, H), interpolation=cv2.INTER_AREA)
                if info[i]:
                    out, contenu = flashback(out, rem)
                else:
                    contenu = out < 128
                rows, cols = np.where(contenu.sum(1) >= 3)[0], np.where(contenu.sum(0) >= 3)[0]
                if len(rows) < 10 or len(cols) < 10:
                    rows, cols = np.arange(H), np.arange(W)
                cadrage[i] = (int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1)
                cv2.imwrite(str(tmp / f"c{i}.png"), out)
            avance()
        # 3. mise en page : page blanche plein écran, flash-back au zoom médian des pages blanches
        zooms = {i: min(W * MARGE / (x1 - x0), H * MARGE / (y1 - y0)) for i, (y0, y1, x0, x1) in cadrage.items()}
        blanches = [z for i, z in zooms.items() if not info[i]]
        zoom = float(np.median(blanches or list(zooms.values())))
        pages = {}
        for i, (y0, y1, x0, x1) in cadrage.items():
            a_ = cv2.imread(str(tmp / f"c{i}.png"), cv2.IMREAD_GRAYSCALE)
            z = min(zoom, zooms[i]) if info[i] else zooms[i]
            fond = int(min(25, np.percentile(a_, 1))) if info[i] else 255
            crop = cv2.resize(a_[y0:y1, x0:x1], None, fx=z, fy=z, interpolation=cv2.INTER_CUBIC if z > 1 else cv2.INTER_AREA)[:H, :W]
            page = np.full((H, W), fond, np.uint8)
            oy, ox = (H - crop.shape[0]) // 2, (W - crop.shape[1]) // 2
            page[oy:oy + crop.shape[0], ox:ox + crop.shape[1]] = crop
            pages[i] = Image.fromarray(page)
            if i % 2:
                avance()
        # écriture : pages recadrées, les autres recopiées du tome actuel
        destination = Path(destination)
        part = destination.with_name(destination.name + ".part")
        with zipfile.ZipFile(chemin) as zc, zipfile.ZipFile(part, "w", zipfile.ZIP_STORED) as dst:
            rang = {n: i for i, n in enumerate(ordre)}
            for inf in zc.infolist():
                i = rang.get(inf.filename)
                data = optimiser._octets_page(pages[i], inf.filename) if i in pages else zc.read(inf.filename)
                z2 = zipfile.ZipInfo(inf.filename, date_time=inf.date_time)
                dst.writestr(z2, data)
        with zipfile.ZipFile(part) as z:
            if z.testzip() is not None or archives._names(z) != ordre:
                raise RuntimeError("archive recadrée illisible")
        part.replace(destination)
        return {"pages": len(pages), "flashbacks": sorted(i for i in pages if info[i]), "hauteur": HR, "zoom": round(zoom, 3)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- Dans l'appli (optimiser.lancer_coupes) --------------------------------------------------------------------------------------------------

def ecrire_tome(chemin, indices, sens_manga=True, destination=None, travail=None) -> dict:
    """Opération pour optimiser.lancer_coupes : tome recadré aux cases écrit à côté, relu, mis en place (l'ancien part dans « .avant »).
    `travail` : {"source", "copier_source", "boites", "W", "H", "retouches"} ; reçoit « resultat » et « empreintes »."""
    import rognage
    chemin = Path(chemin)
    source = Path(travail["source"])
    if travail.get("copier_source") and not (source.is_file() and source.stat().st_size == chemin.stat().st_size):
        source.parent.mkdir(parents=True, exist_ok=True)       # première fois : les pages d'origine sont gardées avant de toucher au tome
        part = source.with_name(source.name + ".part")
        shutil.copyfile(chemin, part)
        if part.stat().st_size != chemin.stat().st_size:
            part.unlink()
            raise RuntimeError("copie des pages d'origine incomplète")
        part.replace(source)
    tmp = Path(destination) if destination is not None else chemin.with_name("." + chemin.name + ".cases")
    try:
        travail["resultat"] = recadrer_tome(chemin, source, travail.get("boites") or {}, (travail["W"], travail["H"]), travail.get("retouches"), tmp)
        with zipfile.ZipFile(tmp) as z:
            travail["empreintes"] = {str(i): rognage.empreinte(z.read(n)) for i, n in enumerate(archives._names(z))}
    except Exception:
        if destination is None:
            tmp.unlink(missing_ok=True)
        raise
    n = len(archives.pages(chemin))
    res = {"carte": {i: i for i in range(n)}, "pages_avant": n, "pages": n}
    if destination is not None:
        return res
    avant = chemin.with_name(chemin.name + ".avant")
    chemin.rename(avant)
    tmp.rename(chemin)
    res["avant"] = avant
    return res


ecrire_tome.reglage = "travail"
ecrire_tome.libelle = lambda pages, tomes: f"{tomes} tome(s) recadré(s) aux cases"


def noter(manga_dir, fichier_reglages, serie, chemin, travail):
    """Après écriture : le rognage garde ses pages d'origine et ses cadres ; le tome écrit devient son « produit » (sinon, à la prochaine ouverture, ses
    pages passeraient pour changées par autre chose et deviendraient de nouvelles pages d'origine)."""
    import rognage
    chemin = Path(chemin)
    with rognage._VERROU:
        d = rognage._lire(fichier_reglages)
        e = (d["tomes"].setdefault(serie, {})).get(chemin.name)
        if e is None:
            e = {"boites": {}, "W": travail["W"], "H": travail["H"]}
            d["tomes"][serie][chemin.name] = e
        if travail.get("copier_source"):
            e["source"] = str(Path(travail["source"]).relative_to(manga_dir))
            e["source_octets"] = Path(travail["source"]).stat().st_size
            e["tailles"] = rognage.tailles_pages(travail["source"])
        e["produit"] = {"octets": chemin.stat().st_size, "W": travail["W"], "H": travail["H"], "boites": dict(e.get("boites") or {}),
                        "empreintes": travail.get("empreintes") or {}, "date": __import__("datetime").datetime.now().strftime("%d/%m/%Y"), "cases": True}
        e["cases"] = dict(travail.get("resultat") or {}, date=e["produit"]["date"])
        rognage._ecrire(fichier_reglages, d)
