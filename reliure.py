"""
📖 Défauts d'un tome relié scanné à plat (écrit le 16/11/2026, mesuré sur le tome 1 de Nori Taka) :

- l'ombre du dos : le papier s'assombrit vers la reliure (jusqu'à 26 % sur la page 21, 20 % sur la 61, 8 % sur la 35) ;
- l'inclinaison : les bords de cases penchent de 0,3 à 0,9° ;
- les bords noirs ou gris du scanner : une bande étroite le long du bord de la page, parfois des bouts de la page voisine.

Tout travaille sur une page en niveaux de gris (uint8) et rend une page de même taille ; une page qui n'a pas le défaut est rendue telle quelle.
L'inclinaison et le cisaillement de la page sont corrigés par redressement() ; la courbure près du dos (lignes courbes, texte comprimé) n'est PAS corrigée : sur ces scans les bords de cases restent droits à moins
d'un degré, et la deviner sur une page sans cadre serait pire que le mal.
"""
import cv2
import numpy as np


def _papier(g: np.ndarray) -> float:
    return float(np.percentile(g, 90))


def bords_noirs(g: np.ndarray) -> np.ndarray:
    """Efface les bandes sombres et étroites collées aux quatre bords (au plus 4 % de la page). Une bande n'est effacée que si elle est franchement plus sombre que
    le papier ET presque uniformément sombre sur toute la longueur ET suivie de papier : une grande zone noire qui touche le bord (page en pleine image) reste."""
    h, w = g.shape
    papier = _papier(g)
    if papier < 150:                                           # page presque toute sombre : rien à nettoyer sans risque
        return g
    sortie = g.copy()
    for cote in ("haut", "bas", "gauche", "droite"):
        long_, prof = (w, max(2, int(0.04 * h))) if cote in ("haut", "bas") else (h, max(2, int(0.04 * w)))
        bande = {"haut": g[:prof], "bas": g[h - prof:][::-1], "gauche": g[:, :prof].T, "droite": g[:, w - prof:][::-1].T}[cote]    # ligne 0 = le bord de la page
        n = 0
        while n < prof and float(np.mean(bande[n] < 0.55 * papier)) > 0.85:                  # ligne presque toute sombre
            n += 1
        if n == 0:
            continue
        suivante = bande[n:n + 6]
        if suivante.size == 0 or float(np.median(suivante)) < 0.8 * papier:                    # derrière la bande, il faut du papier
            continue
        marge = n + 1                                                                           # une ligne de plus : le flou du bord de la bande
        if cote == "haut":
            sortie[:marge] = papier
        elif cote == "bas":
            sortie[h - marge:] = papier
        elif cote == "gauche":
            sortie[:, :marge] = papier
        else:
            sortie[:, w - marge:] = papier
    return sortie


def _moitie_sans_ombre(g: np.ndarray, niveau: int) -> np.ndarray:
    """Une page seule (ou une moitié de double page) : les colonnes de chaque bord, plus sombres que le centre, sont éclaircies progressivement."""
    h, w = g.shape
    f = g.astype(np.float32)
    n = 24
    colonnes = np.linspace(0, w, n + 1).astype(int)
    niveaux_col = np.array([np.percentile(f[:, a:b], 85) for a, b in zip(colonnes[:-1], colonnes[1:])])        # le papier de chaque tranche
    x = (colonnes[:-1] + colonnes[1:]) / 2
    centre = float(np.median(niveaux_col[n // 4: 3 * n // 4]))
    if centre < 120:
        return g
    profil = np.interp(np.arange(w), x, niveaux_col)
    profil = cv2.GaussianBlur(profil.astype(np.float32).reshape(1, -1), (0, 0), max(2.0, w / 60)).ravel()
    force, gain_max, bande = {1: (0.6, 1.15, 0.22), 2: (1.0, 1.30, 0.25), 3: (1.0, 1.50, 0.30)}[max(1, min(3, int(niveau)))]
    gain = np.clip(centre / np.maximum(profil, 1.0), 1.0, gain_max)
    gain = 1.0 + (gain - 1.0) * force
    dist = np.minimum(np.arange(w), w - 1 - np.arange(w)) / w                                                      # 0 au bord, 0,5 au milieu
    fondu = np.clip((bande - dist) / (0.35 * bande), 0, 1)                                                        # seulement dans la bande extérieure, en douceur
    gain = 1.0 + (gain - 1.0) * fondu
    if float(gain.max()) < 1.02:                                                                                    # moins de 2 % : pas de défaut
        return g
    return np.clip(f * gain.reshape(1, -1), 0, 255).astype(np.uint8)


def ombre_dos(g: np.ndarray, niveau: int = 2) -> np.ndarray:
    """Éclaircit le papier assombri vers le dos (et vers les bords) : gain par colonne mesuré sur le papier de chaque tranche, jamais sous 1 (on n'assombrit pas),
    plafonné selon le niveau (1 : 15 %, 2 : 30 %, 3 : 50 %). Une double page (plus large que haute) : chaque moitié séparément, le dos est au milieu."""
    h, w = g.shape
    if w > 1.1 * h:                                    # même seuil que le repérage des doubles pages (optimiser._RATIO_DOUBLE)
        m = w // 2
        return np.hstack([_moitie_sans_ombre(g[:, :m], niveau), _moitie_sans_ombre(g[:, m:], niveau)])
    return _moitie_sans_ombre(g, niveau)


def angle_page(g: np.ndarray):
    """Inclinaison de la page en degrés (positif = tournée dans le sens des aiguilles d'une montre), mesurée sur les bords de cases et de bulles (longs segments
    presque horizontaux ou verticaux), ou None : pas assez de segments, ou ils ne sont pas d'accord entre eux, ou l'angle est trop petit (moins de 0,2°) ou trop
    grand (plus de 3°) pour être sûr que c'est la page qui penche et pas le dessin."""
    h, w = g.shape
    if min(h, w) < 200:
        return None
    echelle = 1.0 if max(h, w) <= 1400 else 1400.0 / max(h, w)
    p = cv2.resize(g, None, fx=echelle, fy=echelle, interpolation=cv2.INTER_AREA) if echelle != 1.0 else g
    ph, pw = p.shape
    marge = int(0.02 * min(ph, pw))
    seg = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(p[marge:ph - marge, marge:pw - marge])[0]
    if seg is None:
        return None
    mini = 0.15 * min(ph, pw)
    angles, poids = [], []
    for x1, y1, x2, y2 in seg.reshape(-1, 4):
        longueur = float(np.hypot(x2 - x1, y2 - y1))
        if longueur < mini:
            continue
        phi = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        phi = (phi + 90.0) % 180.0 - 90.0                       # [-90, 90)
        a = phi - 90.0 if phi > 45 else phi + 90.0 if phi < -45 else phi
        if abs(a) < 3.5:
            angles.append(a)
            poids.append(longueur)
    if len(angles) < 4:
        return None
    angles, poids = np.array(angles), np.array(poids)
    ordre = np.argsort(angles)
    cumul = np.cumsum(poids[ordre])
    mediane = float(angles[ordre][np.searchsorted(cumul, cumul[-1] / 2)])
    ecart = float(np.median(np.abs(angles - mediane)))
    if ecart > 0.35 or abs(mediane) < 0.2 or abs(mediane) > 3.0:
        return None
    return mediane


def pivoter(g: np.ndarray, angle: float) -> np.ndarray:
    """Remet la page droite : tourne de -angle (voir angle_page), les coins ouverts se remplissent du ton du papier."""
    h, w = g.shape
    papier = int(min(255, max(200, _papier(g))))
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)         # OpenCV : angle positif = sens inverse des aiguilles ; une page tournée de +a (horaire) se remet avec +a
    return cv2.warpAffine(g, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=papier)


# --- Redressement : rotation et cisaillement (18/11/2026) ---------------------------------------------------------------------------------------------------------
# Mesuré sur Nori Taka tome 3 (bords de cases, 154 pages simples) : 1,1° d'inclinaison médiane ; après redressement 0,15°. Une page de livre scannée à plat n'est pas
# seulement tournée : ses traits horizontaux et verticaux ne penchent souvent pas du même angle (cisaillement), et une simple rotation laisse alors un côté de travers.
# Modèles essayés du plus simple au plus riche (rotation, + cisaillement, + perspective) ; un modèle plus riche n'est gardé que s'il redresse nettement mieux. Garde-fous :
# seuls les longs traits proches de l'inclinaison la plus partagée de leur famille (horizontaux, verticaux) comptent (les traits dessinés, de vitesse ou de décor, sont écartés) ; il faut des traits horizontaux ET
# verticaux ; la correction refaite sur deux moitiés des traits tirées au hasard doit déplacer les coins pareil (à 0,3 % près) ; sinon la page n'est pas touchée.
# Sur les tomes 1 et 2 (déjà droits) : 4 et 18 pages corrigées sur ~170.

REDRESSE_MAX = 3.0               # degrés : au-delà, c'est le dessin qui penche, pas la page


def _traits_droits(g):
    """Longs segments presque horizontaux (H) et presque verticaux (V), en coordonnées centrées réduites (demi-largeur et demi-hauteur = 1)."""
    h, w = g.shape
    k = 1.0 if max(h, w) <= 1400 else 1400.0 / max(h, w)
    p = cv2.resize(g, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k != 1.0 else g
    ph, pw = p.shape
    m = int(0.02 * min(ph, pw))
    s = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(p[m:ph - m, m:pw - m])[0]
    H, V = [], []
    if s is not None:
        mini = 0.12 * min(ph, pw)
        for xa, ya, xb, yb in s.reshape(-1, 4):
            if np.hypot(xb - xa, yb - ya) < mini:
                continue
            a = np.degrees(np.arctan2(yb - ya, xb - xa)) % 180
            seg = [(xa + m - pw / 2) / (pw / 2), (ya + m - ph / 2) / (ph / 2), (xb + m - pw / 2) / (pw / 2), (yb + m - ph / 2) / (ph / 2)]
            if a < REDRESSE_MAX + 1 or a > 179 - REDRESSE_MAX:
                H.append(seg)
            elif abs(a - 90) < REDRESSE_MAX + 1:
                V.append(seg)
    return np.array(H).reshape(-1, 4), np.array(V).reshape(-1, 4)


def _matrice_redresse(p, rapport):
    """p = (angle, cisaillement, perspective x, perspective y) → matrice 3×3 en coordonnées centrées réduites ; rapport = largeur / hauteur."""
    q = list(p) + [0.0] * (4 - len(p))
    t = np.radians(q[0])
    A, Ai = np.diag([rapport, 1.0, 1.0]), np.diag([1 / rapport, 1.0, 1.0])
    R = np.array([[np.cos(t), -np.sin(t), 0], [np.sin(t), np.cos(t), 0], [0, 0, 1]])
    return Ai @ R @ A @ np.array([[1, q[1], 0], [0, 1, 0], [q[2], q[3], 1]])


def _ecarts_redresse(p, H, V, rapport):
    """Angle (degrés) de chaque trait après correction, par rapport à l'horizontale ou à la verticale (pixels carrés)."""
    M = _matrice_redresse(p, rapport)
    out = []
    for S, vertical in ((H, False), (V, True)):
        if len(S):
            a, b = np.c_[S[:, :2], np.ones(len(S))] @ M.T, np.c_[S[:, 2:], np.ones(len(S))] @ M.T
            a, b = a[:, :2] / a[:, 2:], b[:, :2] / b[:, 2:]
            dx, dy = (b[:, 0] - a[:, 0]) * rapport, b[:, 1] - a[:, 1]
            out.append(np.degrees(np.arctan(dx / dy)) if vertical else np.degrees(np.arctan(dy / dx)))
    return np.concatenate(out) if out else np.zeros(0)


def _ajuster_redresse(H, V, rapport, n):
    """Moindres carrés robustes (Gauss-Newton amorti, poids de Huber) sur n paramètres."""
    x, lam = np.zeros(n), 1e-3
    f = lambda q: _ecarts_redresse(q, H, V, rapport)
    for _ in range(50):
        r = f(x)
        wgt = np.sqrt(np.minimum(1, 0.4 / np.maximum(np.abs(r), 1e-9)))
        J = np.empty((len(r), n))
        for k in range(n):
            d = np.zeros(n)
            d[k] = 1e-4 if k == 0 else 1e-6
            J[:, k] = (f(x + d) - r) / d[k]
        Jw, rw = J * wgt[:, None], r * wgt
        A = Jw.T @ Jw
        pas = np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-12), -Jw.T @ rw)
        rn = f(x + pas)
        if np.sum(np.minimum(1, 0.4 / np.maximum(np.abs(rn), 1e-9)) * rn ** 2) < np.sum(wgt ** 2 * r ** 2):
            x, lam = x + pas, lam / 3
        else:
            lam *= 5
        if np.abs(pas).max() < 1e-8:
            break
    return x


def _coins_redresse(p, rapport):
    c = np.array([[-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1.]]) @ _matrice_redresse(p, rapport).T
    return c[:, :2] / c[:, 2:]


def redressement(g: np.ndarray):
    """Correction de la page {"genre": « rotation », « cisaillement » ou « perspective », "p": paramètres}, ou None si rien de sûr (voir plus haut).
    La correction est en coordonnées réduites : elle s'applique aussi à la page agrandie ou réduite (redresser)."""
    h, w = g.shape
    if min(h, w) < 200:
        return None
    rapport = w / h
    H, V = _traits_droits(g)
    if len(H) + len(V) < 8:
        return None

    def penche(S, vertical):
        dx, dy = (S[:, 2] - S[:, 0]) * rapport, S[:, 3] - S[:, 1]
        return -np.degrees(np.arctan(dx / dy)) if vertical else np.degrees(np.arctan(dy / dx))
    grille = np.arange(-REDRESSE_MAX - 1, REDRESSE_MAX + 1, 0.05)

    def pic(S, vertical):                                 # l'inclinaison la plus partagée de cette famille (histogramme pondéré par la longueur)
        poids = np.hypot((S[:, 2] - S[:, 0]) * rapport, S[:, 3] - S[:, 1])
        return float(grille[np.argmax((poids[None, :] * np.exp(-0.5 * ((grille[:, None] - penche(S, vertical)[None, :]) / 0.25) ** 2)).sum(1))])
    if len(H) < 2 or len(V) < 2:
        return None
    pH, pV = pic(H, False), pic(V, True)
    if abs(pH - pV) > 1.5:                                # horizontales et verticales trop en désaccord : pas un défaut de scan
        return None
    H, V = H[np.abs(penche(H, False) - pH) <= 0.7], V[np.abs(penche(V, True) - pV) <= 0.7]
    if len(H) < 2 or len(V) < 2:                          # horizontaux ET verticaux doivent confirmer : un dessin aux traits parallèles ne suffit pas
        return None
    avant = float(np.median(np.abs(_ecarts_redresse([0], H, V, rapport))))
    tout_autour = (len(V) >= 4 and len(H) >= 4 and (V[:, 0] < -0.2).any() and (V[:, 0] > 0.2).any() and (H[:, 1] < -0.2).any() and (H[:, 1] > 0.2).any())
    hasard = np.random.default_rng(0)
    bons = []
    for genre, n in (("rotation", 1), ("cisaillement", 2), ("perspective", 4)):
        if (n == 2 and min(len(H), len(V)) < 3) or (n == 4 and not tout_autour):
            continue
        p = _ajuster_redresse(H, V, rapport, n)
        apres = float(np.median(np.abs(_ecarts_redresse(p, H, V, rapport))))
        instable = 0.0
        for _ in range(3):
            iH, iV = hasard.permutation(len(H)), hasard.permutation(len(V))
            a = _ajuster_redresse(H[iH[::2]], V[iV[::2]], rapport, n)
            b = _ajuster_redresse(H[iH[1::2]], V[iV[1::2]], rapport, n)
            instable = max(instable, float(np.abs(_coins_redresse(a, rapport) - _coins_redresse(b, rapport)).max()))
        deplacement = float(np.abs(_coins_redresse(p, rapport) - _coins_redresse([0], rapport)).max())
        if abs(p[0]) <= REDRESSE_MAX and deplacement <= 0.06 and instable <= 0.006 and avant - apres >= 0.15 and apres <= 0.6 * avant:
            if not bons or bons[-1][2] - apres >= 0.08:     # un modèle plus riche seulement s'il redresse nettement mieux
                bons.append((genre, p, apres))
    if not bons:
        return None
    genre, p, _ = bons[-1]
    return {"genre": genre, "p": [round(float(v), 5) for v in p]}


def matrice_redressement(correction, w, h) -> np.ndarray:
    """Matrice 3×3 en pixels (page de w × h) de la correction : un point (x, y, 1) de la page va en M @ (x, y, 1)."""
    N = np.array([[2 / w, 0, -1], [0, 2 / h, -1], [0, 0, 1.]])
    return np.linalg.inv(N) @ _matrice_redresse(correction["p"], w / h) @ N


def redresser(a: np.ndarray, correction, papier=None) -> np.ndarray:
    """La page (gris ou couleur, n'importe quelle taille) redressée selon `correction` (voir redressement) ; les coins ouverts prennent le ton du papier."""
    if not correction:
        return a
    h, w = a.shape[:2]
    M = matrice_redressement(correction, w, h)
    if papier is None:
        gris = a if a.ndim == 2 else cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
        papier = int(min(255, max(200, _papier(gris))))
        papier = papier if a.ndim == 2 else (papier,) * 3
    return cv2.warpPerspective(a, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=papier)


TROP_COUPE = 0.08                # on ne coupe jamais plus de 8 % de la largeur ou de la hauteur d'un côté : au-delà, ce n'est plus une bande de scanner mais le dessin


def _debut_papier(profil: np.ndarray, seuil: float, maxi: int) -> int:
    """Nombre de lignes (ou colonnes) à couper au début du profil (« niveau du papier » de chaque ligne) : une bande sombre (sous le seuil) qui TOUCHE le bord (elle commence dans les 3
    premières positions : un trait de cadre à 70 px du bord n'est pas une bande), suivie jusqu'à son bout (un trou clair d'une seule position ne l'interrompt pas), à condition que du papier
    la suive (médiane des `maxi // 2` positions suivantes au niveau du papier). Un dégradé d'ombre dont le tout dernier pixel est clair est donc coupé quand même ; une zone sombre qui va
    jusqu'au bout des `maxi` positions (ce n'est plus une bande mais le dessin ou un dos de livre) n'est pas coupée : on ne devine pas."""
    debut = np.where(profil[:3] < seuil)[0]
    if debut.size == 0:
        return 0
    i = int(debut.max())
    while i + 1 < maxi and (profil[i + 1] < seuil or (i + 2 < maxi and profil[i + 2] < seuil)):
        i += 1
    if i + 1 >= maxi:
        return 0
    tenue = max(2, maxi // 2)
    return i + 1 if float(np.median(profil[i + 1:i + 1 + tenue])) >= seuil else 0


def fond_noir(g: np.ndarray) -> bool:
    """Page sur fond noir (flash-back) : les gouttières entre les rangées de cases sont noires (ou gris foncé, scan délavé) au lieu d'être blanches. On compte les fines
    bandes sombres qui traversent toute la page (80 % du milieu de la largeur), uniformes, avec des cases claires juste au-dessus et juste en dessous ; deux ou plus :
    fond noir. Mesuré le 18/11/2026 sur Nori Taka tomes 1 à 3 : les flash-backs du tome 3 (pages 4 à 6) trouvés, 2 autres pages sombres sur ~530 (sans gravité :
    elles gardent seulement leurs bords)."""
    h, w = g.shape
    papier = float(np.percentile(g, 95))
    if papier < 120:
        return False
    bande = g[:, int(0.1 * w):int(0.9 * w)]
    sombre = (bande < 0.6 * papier).mean(1) > 0.85
    clair = (bande > 0.8 * papier).mean(1)
    n, i, fin, m = 0, int(0.05 * h), int(0.95 * h), int(0.03 * h)
    while i < fin:
        if not sombre[i]:
            i += 1
            continue
        j = i
        while j < fin and sombre[j]:
            j += 1
        if 0.006 * h <= j - i <= 0.045 * h and clair[max(0, i - m):i].max(initial=0) > 0.3 and clair[j:j + m].max(initial=0) > 0.3:
            n += 1
        i = j
    return n >= 2


def noir_uni(g: np.ndarray) -> np.ndarray:
    """Flash-back sur fond noir (fond_noir) : le fond délavé (gris, inégal) redevient un noir uni ; les cases ne sont pas touchées. Les cases sont les grandes zones
    claires (dessins bouchés par une fermeture, puis contour convexe de chacune, trait de cadre compris) ; hors des cases, ce qui est sombre ou gris devient noir, ce
    qui est clair (texte blanc sur le fond) reste. Une autre page est rendue telle quelle."""
    if not fond_noir(g):
        return g
    h, w = g.shape
    papier = float(np.percentile(g, 95))
    clair = (g > 0.6 * papier).astype(np.uint8)
    k = max(5, int(0.015 * min(h, w)) | 1)
    ferme = cv2.morphologyEx(clair, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(ferme, connectivity=8)
    cases = np.zeros_like(clair)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= 0.004 * h * w:
            cv2.fillConvexPoly(cases, cv2.convexHull(cv2.findNonZero((lab == i).astype(np.uint8))), 1)
    cases = cv2.dilate(cases, np.ones((5, 5), np.uint8))
    sortie = g.copy()
    sortie[(cases == 0) & (g < 0.75 * papier)] = int(min(30, np.percentile(g, 1)))
    return sortie


def bords_page(g: np.ndarray):
    """Les bords du papier d'une page scannée : (x0, y0, x1, y1) à garder, en pixels. Chaque bord est repéré sur le profil des colonnes (ou des lignes) au 80e centile : le papier
    est clair, la bande d'ombre de la page voisine, la bande du scanner ou le reste de la couverture sont plus sombres (moins de 82 % du papier). On coupe jusqu'à cette bande, au
    plus 8 % par côté ; un côté sans bande franche reste tel quel. Une page presque toute sombre n'est pas touchée."""
    h, w = g.shape
    papier = float(np.percentile(g, 90))
    if papier < 150 or fond_noir(g):                         # flash-back sur fond noir : le noir du bord est le fond de la page, pas une bande
        return (0, 0, w, h)
    seuil = 0.82 * papier
    colonnes = np.percentile(g, 80, axis=0)
    lignes = np.percentile(g, 80, axis=1)
    mx, my = int(TROP_COUPE * w), int(TROP_COUPE * h)
    x0 = _debut_papier(colonnes, seuil, mx)
    x1 = w - _debut_papier(colonnes[::-1], seuil, mx)
    y0 = _debut_papier(lignes, seuil, my)
    y1 = h - _debut_papier(lignes[::-1], seuil, my)
    return (x0, y0, x1, y1)


def cadre_tome(pages):
    """Taille commune d'un tome, mesurée sur des pages d'échantillon (liste de tableaux gris) : {"w", "h" (taille du papier de chaque page, médiane), "pw", "ph" (taille d'une page de
    départ)} ou None quand il y a moins de six pages de la taille habituelle. Les pages d'une autre taille (couverture, double page : à plus de 10 % de la médiane) ne comptent pas."""
    if not pages:
        return None
    ph, pw = int(np.median([g.shape[0] for g in pages])), int(np.median([g.shape[1] for g in pages]))
    tailles = []
    for g in pages:
        if abs(g.shape[1] - pw) > 0.1 * pw or abs(g.shape[0] - ph) > 0.1 * ph:
            continue
        x0, y0, x1, y1 = bords_page(g)
        tailles.append((x1 - x0, y1 - y0))
    if len(tailles) < 6:
        return None
    a = np.array(tailles)
    return {"w": int(np.median(a[:, 0])), "h": int(np.median(a[:, 1])), "pw": pw, "ph": ph}


def recadrer(g: np.ndarray, cadre: dict) -> np.ndarray:
    """Page recadrée à la taille commune du tome (cadre["w"] × cadre["h"]) : d'abord coupée aux bords de son papier (bords_page : ombres et bandes du bord enlevées), puis centrée
    dans la taille commune (un peu de papier en moins ou en plus de chaque côté ; ce qui manque est rempli du ton du papier). Jamais de zoom ni de déformation. Une page d'une autre
    taille que celles du tome (à plus de 10 %) : rendue telle quelle."""
    h, w = g.shape
    if abs(h - cadre["ph"]) > 0.1 * cadre["ph"]:
        return g
    double = w > 1.1 * h and 1.5 * cadre["pw"] <= w <= 2.3 * cadre["pw"]        # vraie double page gardée : même hauteur que les pages simples, sa propre largeur
    if not double and abs(w - cadre["pw"]) > 0.1 * cadre["pw"]:
        return g
    x0, y0, x1, y1 = bords_page(g)
    papier = int(min(255, max(200, _papier(g))))
    if fond_noir(g):                                         # ce qui manque continue le fond noir
        papier = int(np.median(np.concatenate([g[:4].ravel(), g[-4:].ravel(), g[:, :4].ravel(), g[:, -4:].ravel()])))
    p = g[y0:y1, x0:x1]
    W, H = (p.shape[1] if double else cadre["w"]), cadre["h"]
    sortie = np.full((H, W), papier, g.dtype)
    dx, dy = (W - p.shape[1]) // 2, (H - p.shape[0]) // 2                        # > 0 : de la marge à ajouter, < 0 : du papier en trop à couper
    sx, sy = max(0, -dx), max(0, -dy)
    cw, ch = min(p.shape[1] - sx, W - max(0, dx)), min(p.shape[0] - sy, H - max(0, dy))
    if cw > 0 and ch > 0:
        sortie[max(0, dy):max(0, dy) + ch, max(0, dx):max(0, dx) + cw] = p[sy:sy + ch, sx:sx + cw]
    return sortie
