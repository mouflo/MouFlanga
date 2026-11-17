"""
📖 Défauts d'un tome relié scanné à plat (écrit le 16/11/2026, mesuré sur le tome 1 de Nori Taka) :

- l'ombre du dos : le papier s'assombrit vers la reliure (jusqu'à 26 % sur la page 21, 20 % sur la 61, 8 % sur la 35) ;
- l'inclinaison : les bords de cases penchent de 0,3 à 0,9° ;
- les bords noirs ou gris du scanner : une bande étroite le long du bord de la page, parfois des bouts de la page voisine.

Tout travaille sur une page en niveaux de gris (uint8) et rend une page de même taille ; une page qui n'a pas le défaut est rendue telle quelle.
La déformation géométrique près du dos (lignes courbes, texte comprimé) n'est PAS corrigée : sur ces scans les bords de cases restent droits à moins
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


def bords_page(g: np.ndarray):
    """Les bords du papier d'une page scannée : (x0, y0, x1, y1) à garder, en pixels. Chaque bord est repéré sur le profil des colonnes (ou des lignes) au 80e centile : le papier
    est clair, la bande d'ombre de la page voisine, la bande du scanner ou le reste de la couverture sont plus sombres (moins de 82 % du papier). On coupe jusqu'à cette bande, au
    plus 8 % par côté ; un côté sans bande franche reste tel quel. Une page presque toute sombre n'est pas touchée."""
    h, w = g.shape
    papier = float(np.percentile(g, 90))
    if papier < 150:
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
    p = g[y0:y1, x0:x1]
    W, H = (p.shape[1] if double else cadre["w"]), cadre["h"]
    sortie = np.full((H, W), papier, g.dtype)
    dx, dy = (W - p.shape[1]) // 2, (H - p.shape[0]) // 2                        # > 0 : de la marge à ajouter, < 0 : du papier en trop à couper
    sx, sy = max(0, -dx), max(0, -dy)
    cw, ch = min(p.shape[1] - sx, W - max(0, dx)), min(p.shape[0] - sy, H - max(0, dy))
    if cw > 0 and ch > 0:
        sortie[max(0, dy):max(0, dy) + ch, max(0, dx):max(0, dx) + cw] = p[sy:sy + ch, sx:sx + cw]
    return sortie
