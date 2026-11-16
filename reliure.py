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
    if w > 1.2 * h:
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
