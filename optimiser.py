"""🪶 Alléger les tomes sans perte visible, et 🧼 éclaircir le papier des scans gris.

Alléger : pour chaque tome, quelques pages d'essai sont recompressées en JPEG à plusieurs qualités ; on garde la plus
basse dont l'écart avec l'original reste invisible (PSNR ≥ 42 dB sur chaque page d'essai) et qui fait gagner au moins
10 %. Une page qui ne gagne rien garde ses octets d'origine. Les noms et l'ordre des pages, chapitres.json et
ComicInfo.xml sont recopiés tels quels : le tome reste lisible et rangé pareil.
✨ Améliorer (vieux scans, seulement si on le demande) : réglages de 0 à 3 pour débruiter, adoucir les trames, blanchir
le papier (fond gris ou jauni, même inégal), renforcer les noirs, effacer les petites taches isolées, lisser les traits
en escalier et rendre plus net. Jamais sur une
page en couleur. Voir ameliorer().
L'original part à la corbeille (30 jours) seulement quand le nouveau fichier est écrit et relu ; un fichier encore
partagé par qBittorrent (lien physique) n'est jamais touché.
"""
import io
import logging
import threading
import time
import zipfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

COMICINFO = "ComicInfo.xml"
logger = logging.getLogger("mouflanga")

QUALITES = (80, 85, 88, 92)
PSNR_MIN = 39.0            # en dessous, des différences peuvent se voir en zoomant ; au-dessus, invisibles à l'écran
GAIN_MIN = 0.10
_IMAGES = (".jpg", ".jpeg")                 # seulement les JPEG : un PNG ou un WebP garde son format et ses octets
_ETAT = {}                      # série → {"en_cours", "fait", "total", "message", "rapport"}
_VERROU = threading.Lock()


def _psnr(a: Image.Image, b: Image.Image) -> float:
    x = np.asarray(a.convert("L"), dtype=np.float32)
    y = np.asarray(b.convert("L"), dtype=np.float32)
    mse = float(np.mean((x - y) ** 2))
    return 99.0 if mse == 0 else 10 * np.log10(255 ** 2 / mse)


def _jpeg(im: Image.Image, q: int) -> bytes:
    out = io.BytesIO()
    im.convert("RGB" if im.mode not in ("L", "RGB") else im.mode).save(out, "JPEG", quality=q, optimize=True, progressive=True)
    return out.getvalue()


_QUANT_Q50 = np.sort(np.array([16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
                               18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112,
                               100, 103, 99], dtype=np.float64))     # table de luminosité standard à la qualité 50 (libjpeg)


def qualite_jpeg(im: Image.Image):
    """Qualité (de 1 à 100) avec laquelle un JPEG a été enregistré, retrouvée dans sa table de quantification ; None si ce n'est pas un JPEG."""
    tables = getattr(im, "quantization", None)
    if not tables or 0 not in tables or len(tables[0]) < 64:
        return None
    echelle = float(np.median(np.sort(np.array(tables[0][:64], dtype=np.float64)) / _QUANT_Q50)) * 100
    q = (200 - echelle) / 2 if echelle <= 100 else 5000 / echelle
    return int(max(1, min(100, round(q))))


QUALITE_ORIGINE = "origine"       # qualite_forcee : réenregistrer chaque tome à la qualité qu'il avait déjà (sans l'alléger)


def _pages(z: zipfile.ZipFile):
    return [n for n in z.namelist() if Path(n).suffix.lower() in _IMAGES]


def qualite_origine(chemin: Path, nb_essai=5) -> int:
    """Qualité d'enregistrement habituelle des pages d'un tome (médiane sur quelques pages) ; 90 si on ne peut pas la lire."""
    with zipfile.ZipFile(chemin) as z:
        noms = _pages(z)
        pas = max(1, len(noms) // nb_essai)
        trouvees = []
        for n in noms[::pas][:nb_essai]:
            q = qualite_jpeg(Image.open(io.BytesIO(z.read(n))))
            if q:
                trouvees.append(q)
    return max(60, min(98, int(np.median(trouvees)))) if trouvees else 90


def est_couleur(im: Image.Image) -> bool:
    """Page en couleur (pas un scan noir et blanc, même légèrement teinté). Deux signes : un écart moyen entre canaux, ou une petite zone franchement
    colorée (un titre, un dessin, une illustration sur le quart de la page…). Sur 1 060 pages réelles, aucune page noir et blanc n'a plus de 0,05 %
    de pixels très colorés (écart > 40) et toutes les pages en couleur en ont plus de 0,5 % : le seuil est à 0,15 %. L'ancien test (écart moyen seul)
    prenait pour du noir et blanc des pages dont 2 à 10 % étaient en couleur, qui auraient été passées en gris."""
    if im.mode in ("L", "1"):
        return False
    petit = np.asarray(im.convert("RGB").resize((400, 600), Image.BOX), dtype=np.int16)
    if float(np.mean(np.abs(petit[..., 0] - petit[..., 1]) + np.abs(petit[..., 1] - petit[..., 2]))) > 12:
        return True
    return float(((petit.max(axis=2) - petit.min(axis=2)) > 40).mean()) > 0.0015


# ✨ Amélioration des vieux scans : chaque réglage va de 0 (non) à 3 (fort), appliqué dans cet ordre. « uniformiser » (0 ou 1) cale les
# noirs, les blancs et la teinte du tome sur ceux des autres tomes de la série (voir uniformite.py) : il lui faut le calage du tome.
AMELIORATIONS = ("debruit", "trames", "papier", "noirs", "taches", "lisser", "nettete", "agrandir", "uniformiser")


def reglages_amelioration(x) -> dict | None:
    """Réglages d'amélioration lus depuis la page : « 2,2,2,1,1,2,0 » (ordre d'AMELIORATIONS), un dict, ou True (ancien
    « 🧼 éclaircir » = papier moyen + noirs légers). None si rien n'est demandé."""
    if x is True:
        x = {"papier": 2, "noirs": 1}
    if isinstance(x, str):
        x = dict(zip(AMELIORATIONS, x.split(",")))
    if not isinstance(x, dict):
        return None
    r = {}
    for k in AMELIORATIONS:
        try:
            r[k] = max(0, min(1 if k == "uniformiser" else 3, int(x.get(k) or 0)))
        except (TypeError, ValueError):
            r[k] = 0
    return r if any(r.values()) else None


def _traits(g, seuil=25.0):
    """0 à 1 selon la présence d'un vrai trait (bord long et net), mesurée sur une version floue où les trames
    (petits points réguliers) ont disparu : ce masque protège les traits pendant que le reste est lissé."""
    f = cv2.GaussianBlur(g, (0, 0), 1.6)
    gx, gy = cv2.Sobel(f, cv2.CV_32F, 1, 0), cv2.Sobel(f, cv2.CV_32F, 0, 1)
    m = np.clip((np.sqrt(gx * gx + gy * gy) - seuil) / (2 * seuil), 0, 1)
    return cv2.GaussianBlur(m, (0, 0), 1.2)


def _caler(g, calage):
    """Niveaux de gris recalés : le noir le plus sombre (b), le noir habituel (e) et le blanc (w) du tome deviennent ceux de la référence (indices 1),
    en ligne droite entre ces repères (sans repère « e », une seule droite du noir au blanc)."""
    x0 = [0.0, float(calage["b0"]), float(calage["w0"]), 255.0]
    x1 = [0.0, float(calage["b1"]), float(calage["w1"]), 255.0]
    if "e0" in calage and "e1" in calage:
        x0.insert(2, float(calage["e0"]))
        x1.insert(2, float(calage["e1"]))
    for i in range(1, len(x0)):                           # des repères toujours croissants, sinon la courbe ne serait pas une courbe
        x0[i] = max(x0[i], x0[i - 1] + 0.5)
        x1[i] = max(x1[i], x1[i - 1] + 0.5)
    lut = np.interp(np.arange(256, dtype=np.float32), x0, x1)
    return cv2.LUT(g, np.clip(np.round(lut), 0, 255).astype(np.uint8))


def ameliorer(im: Image.Image, reglages, calage=None) -> Image.Image:
    """Page noir et blanc d'un vieux scan, rendue plus propre (renvoyée en gris). Une page en couleur n'est pas touchée.
    « lisser » travaille sur la page doublée (il faut de la place pour arrondir) puis la ramène à sa taille : les bords
    restent lisses (anticrénelage) sans alourdir le fichier. « agrandir » garde la page doublée (petits scans de moins
    de 1700 px de haut seulement) : plus fin en zoomant, mais fichier bien plus lourd."""
    r = reglages_amelioration(reglages)
    if not r or est_couleur(im):
        return im
    g = np.asarray(im.convert("L"))                       # une teinte (page un peu violette ou jaune) disparaît ici : tout est rendu en gris
    h, w = g.shape
    echelle = max(1.0, (w * h) / 1.2e6)                   # les tailles suivent la résolution de la page
    if r["uniformiser"] and calage:                       # d'abord : les niveaux d'origine sont ceux qui ont été mesurés
        g = _caler(g, calage)
    if r["debruit"]:                                      # grain et petits carrés de la compression JPEG
        g = cv2.fastNlMeansDenoising(g, None, h=(0, 4, 7, 10)[r["debruit"]], templateWindowSize=7, searchWindowSize=21)
    if r["trames"]:                                       # aplats gris pointillés (trames) → gris uni, traits gardés
        flou = cv2.GaussianBlur(g, (0, 0), (0, 1.1, 1.6, 2.2)[r["trames"]] * echelle ** 0.5).astype(np.float32)
        m = _traits(g)
        g = (g * m + flou * (1 - m)).astype(np.uint8)
    if r["papier"]:
        # Fond de la page à grande échelle (l'encre retirée par une fermeture sur une version réduite), puis division :
        # le papier gris, jauni ou inégal devient blanc, un aplat gris reste gris. Le fond ne descend jamais sous 85 %
        # du papier de la page : une grande zone noire (cheveux) reste noire.
        pw, ph = max(1, w // 4), max(1, h // 4)
        k = max(7, (min(h, w) // 40) | 1)
        petit = cv2.resize(g, (pw, ph), interpolation=cv2.INTER_AREA)
        fond = cv2.morphologyEx(petit, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        fond = cv2.resize(cv2.GaussianBlur(fond, (0, 0), k / 2), (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
        encre = min(float(np.percentile(g, 0.5)), 90.0)      # le noir le plus sombre de la page reste le noir
        p90 = float(np.percentile(g, 90))
        fond = np.clip(fond, max(encre + 40, p90 * 0.85), 255)
        # Page presque toute noire (peu de papier visible) : le « fond » trouvé serait un gris foncé et tout serait éclairci à tort.
        # Plus le papier visible est sombre (90e centile < 170), plus on retient le blanchiment ; sous 100, la page n'est pas touchée.
        force = min(1.0, max(0.0, (p90 - 100) / 70))
        fond = fond * force + 255 * (1 - force)
        blanc = (1, 0.975, 0.95, 0.91)[r["papier"]]          # fort : les gris les plus pâles deviennent blancs aussi
        g = np.clip((g.astype(np.float32) - encre) / ((fond - encre) * blanc) * 255, 0, 255).astype(np.uint8)
    if r["noirs"]:                                        # encre délavée : point noir relevé + légère courbe
        noir = (0, 25, 45, 65)[r["noirs"]]
        x = np.clip((np.arange(256, dtype=np.float32) - noir) / (255 - noir), 0, 1)
        g = cv2.LUT(g, (255 * x ** (1, 1.08, 1.15, 1.25)[r["noirs"]]).astype(np.uint8))
    if r["taches"]:
        # Poussières : petits points sombres SEULS au milieu du papier (aucune autre encre autour), bouchés avec le
        # fond voisin. Les points de suspension et les accents, collés à d'autres traits, restent.
        sombre = (g < 200).astype(np.uint8)
        nb, lab, st, _ = cv2.connectedComponentsWithStats(sombre, connectivity=8)
        rayon = int(4 + 2 * echelle)
        voisins = cv2.boxFilter(sombre.astype(np.float32), -1, (2 * rayon + 1,) * 2, normalize=False)
        maxi = np.zeros(nb, np.float32)
        np.maximum.at(maxi, lab.ravel(), voisins.ravel())
        aire = st[:, cv2.CC_STAT_AREA]
        isole = (aire <= (0, 3, 7, 14)[r["taches"]] * echelle) & (maxi <= aire + 0.5)
        isole[0] = False
        masque = isole[lab].astype(np.uint8) * 255
        if masque.any():
            g = cv2.inpaint(g, masque, 3, cv2.INPAINT_TELEA)
    if r["lisser"]:
        # Traits en escalier : page doublée si elle est petite, puis, sur les traits seulement, flou + courbe en S :
        # le bord redevient franc mais suit une courbe lisse. Les aplats et les gris ne sont pas touchés.
        g = cv2.resize(g, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        m = _traits(g, 30.0)
        b = cv2.GaussianBlur(g, (0, 0), (0, 0.8, 1.2, 1.6)[r["lisser"]]).astype(np.float32) / 255
        pente = (0, 7, 9, 11)[r["lisser"]]
        bas, haut = 1 / (1 + np.exp(pente / 2)), 1 / (1 + np.exp(-pente / 2))
        s = (1 / (1 + np.exp(-(b - 0.5) * pente)) - bas) / (haut - bas) * 255
        g = np.clip(g * (1 - m) + s * m, 0, 255).astype(np.uint8)
        if not (r["agrandir"] and h < 1700):
            g = cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA)
    elif r["agrandir"] and h < 1700:
        g = cv2.resize(g, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    if r["nettete"]:                                      # masque flou : traits plus francs
        a = (0, 0.5, 0.9, 1.4)[r["nettete"]]
        g = cv2.addWeighted(g, 1 + a, cv2.GaussianBlur(g, (0, 0), 1.0), -a, 0)
    return Image.fromarray(g, "L")


def reduire(im: Image.Image, largeur_max) -> Image.Image:
    """Page plus large que l'écran qui l'affichera (largeur_max px) : réduite, proportions gardées. Double page : sa moitié."""
    if not largeur_max:
        return im
    limite = largeur_max * (2 if im.width > im.height else 1)
    if im.width <= limite:
        return im
    return im.resize((limite, round(im.height * limite / im.width)), Image.LANCZOS)


def analyser(chemin: Path, nb_essai=8, eclairer=False, largeur_max=None, qualite_forcee=None, calage=None) -> dict:
    """Choisit la qualité d'un tome : {"qualite", "gain_estime" (0-1), "psnr_min", "taille"} (qualite None : rien à gagner).
    qualite_forcee : réglage manuel, seule cette qualité est essayée (sans seuil d'écart : c'est ton choix) ; None si elle ne gagne rien."""
    taille = chemin.stat().st_size
    with zipfile.ZipFile(chemin) as z:
        noms = _pages(z)
        if not noms:
            return {"qualite": None, "gain_estime": 0, "psnr_min": None, "taille": taille}
        pas = max(1, len(noms) // nb_essai)
        essai = noms[::pas][:nb_essai]
        originaux = {n: z.read(n) for n in essai}
    images = {n: Image.open(io.BytesIO(b)) for n, b in originaux.items()}
    for im in images.values():
        im.load()
    fidele = qualite_forcee == QUALITE_ORIGINE           # « même qualité que l'original » : chaque page garde SA qualité, et une page que rien ne touche garde ses octets
    qpage = {}
    if fidele:
        qpage = {n: qualite_jpeg(im) for n, im in images.items()}
        trouvees = [q for q in qpage.values() if q]
        qualite_forcee = max(60, min(98, int(np.median(trouvees)))) if trouvees else 90      # pour une page dont la qualité n'est pas lisible
        qpage = {n: (q or qualite_forcee) for n, q in qpage.items()}
    eclairer = reglages_amelioration(eclairer)
    inchangees = set(images)
    if eclairer:
        traitees = {n: ameliorer(im, eclairer, calage) for n, im in images.items()}
        inchangees = {n for n in images if traitees[n] is images[n]}
        images = traitees
    reduites = {n: reduire(im, largeur_max) for n, im in images.items()}
    inchangees = {n for n in inchangees if reduites[n] is images[n]} if fidele else set()
    images = reduites
    total = sum(len(b) for b in originaux.values())
    meilleur = {"qualite": None, "gain_estime": 0.0, "psnr_min": None, "taille": taille}
    if qualite_forcee:
        nouveaux, psnrs = 0, []
        for n, im in images.items():
            if n in inchangees:                           # page en couleur ou non concernée : ses octets d'origine, rien de recompressé
                nouveaux += len(originaux[n])
                continue
            b = _jpeg(im, qpage.get(n, qualite_forcee))
            psnrs.append(_psnr(im, Image.open(io.BytesIO(b))))
            nouveaux += min(len(b), len(originaux[n])) if not (eclairer or largeur_max) else len(b)
        gain = 1 - nouveaux / total
        if gain > 0 or eclairer:
            meilleur = {"qualite": int(qualite_forcee), "gain_estime": round(float(gain), 3), "psnr_min": round(float(min(psnrs or [99.0])), 1), "taille": taille}
        return meilleur
    for q in sorted(QUALITES, reverse=True):          # de la plus fidèle à la plus légère : on garde la dernière acceptable
        nouveaux, psnrs = 0, []
        for n, im in images.items():
            b = _jpeg(im, q)
            psnrs.append(_psnr(im, Image.open(io.BytesIO(b))))
            nouveaux += min(len(b), len(originaux[n])) if not (eclairer or largeur_max) else len(b)
        gain = 1 - nouveaux / total
        if min(psnrs) >= PSNR_MIN and (gain >= GAIN_MIN or eclairer):
            meilleur = {"qualite": q, "gain_estime": round(float(gain), 3), "psnr_min": round(float(min(psnrs)), 1), "taille": taille}
    return meilleur


def reecrire(chemin: Path, qualite: int, eclairer=False, largeur_max=None, destination: Path | None = None, comicinfo=None, calage=None,
             fidele=False) -> int:
    """Écrit la version allégée (ou éclaircie) à côté, la relit, puis remplace. Renvoie le nombre d'octets gagnés.
    L'ancien fichier est renvoyé à l'appelant via un nom « .avant » (à mettre à la corbeille).
    Avec « destination » (fichier partagé par qBittorrent : le NAS refuse de le renommer), la version allégée est seulement
    écrite là, relue, et l'original n'est pas touché : l'appelant échange les dossiers.
    « comicinfo » : fonction (ancien ComicInfo.xml ou None) -> nouveau ComicInfo.xml, pour écrire les infos du tome dans la
    même passe ; le fichier est alors remplacé même sans gain. « qualite » vide : les images sont recopiées telles quelles.
    « fidele » (mode « même qualité que l'original ») : chaque page est réenregistrée à SA qualité d'origine (une double page assemblée est en 95, les
    autres pages d'un tome en 70 : « qualite » ne sert que pour une page dont la qualité n'est pas lisible), et une page que les filtres n'ont pas touchée
    (une page en couleur) et qui n'est pas réduite garde ses octets d'origine, sans nouvelle compression."""
    eclairer = reglages_amelioration(eclairer)
    tmp = destination if destination is not None else chemin.with_name("." + chemin.name + ".allege")
    vu_comicinfo = False
    with zipfile.ZipFile(chemin) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            compression = zipfile.ZIP_STORED
            if qualite and Path(info.filename).suffix.lower() in _IMAGES:
                im = Image.open(io.BytesIO(data))
                im.load()
                traitee = ameliorer(im, eclairer, calage) if eclairer else im
                im2 = reduire(traitee, largeur_max)
                if not (fidele and im2 is im):
                    nouveau = _jpeg(im2, (qualite_jpeg(im) or qualite) if fidele else qualite)
                    if im2 is not im or len(nouveau) < len(data):
                        data = nouveau
            elif comicinfo is not None and info.filename == COMICINFO:
                data, vu_comicinfo, compression = comicinfo(data), True, zipfile.ZIP_DEFLATED
            info2 = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            info2.compress_type = compression
            dst.writestr(info2, data)
        if comicinfo is not None and not vu_comicinfo:
            c = zipfile.ZipInfo(COMICINFO, date_time=time.localtime()[:6])
            c.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(c, comicinfo(None))
    with zipfile.ZipFile(tmp) as z:                       # relecture : mêmes pages (et le ComicInfo), archive saine
        if z.testzip() is not None:
            tmp.unlink()
            raise RuntimeError("archive allégée illisible")
        with zipfile.ZipFile(chemin) as o:
            attendu = o.namelist() + ([COMICINFO] if comicinfo is not None and not vu_comicinfo else [])
            if z.namelist() != attendu:
                tmp.unlink()
                raise RuntimeError("pages différentes après allègement")
    avant = chemin.stat().st_size
    gagne = avant - tmp.stat().st_size
    if gagne <= 0 and not eclairer and comicinfo is None:
        tmp.unlink()
        return 0
    if destination is not None:
        return gagne
    chemin.rename(chemin.with_name(chemin.name + ".avant"))
    tmp.rename(chemin)
    return gagne


def echanger_dossier(chemin: Path, ecrire, vers_corbeille) -> bool:
    """Fichier partagé par qBittorrent (lien physique) : le NAS refuse de le renommer ou de l'effacer, mais accepte de
    renommer un DOSSIER. « ecrire(destination) » écrit la nouvelle version du fichier dans un dossier voisin caché
    (True si quelque chose est à remplacer), le reste du contenu y est copié, puis les deux dossiers sont échangés :
    l'ancien, avec le fichier du torrent, va à la corbeille (le torrent n'est pas touché). Mêmes noms de fichiers,
    donc lecture, progression et infos suivent."""
    import shutil
    dossier = chemin.parent
    nouveau = dossier.with_name("." + dossier.name + ".allege")
    ancien = dossier.with_name("." + dossier.name + ".avant")
    for d in (nouveau, ancien):
        if d.exists():
            raise RuntimeError(f"reste d'un traitement interrompu : {d.name} (à vérifier)")
    nouveau.mkdir()
    try:
        if not ecrire(nouveau / chemin.name):
            shutil.rmtree(nouveau, ignore_errors=True)
            return False
        for x in dossier.iterdir():                       # le reste du dossier (couverture, infos) suit
            if x != chemin and not x.name.startswith("."):
                shutil.copy2(x, nouveau / x.name) if x.is_file() else shutil.copytree(x, nouveau / x.name)
        dossier.rename(ancien)
        try:
            nouveau.rename(dossier)
        except OSError:
            ancien.rename(dossier)                         # échec : l'ancien dossier reprend sa place
            raise
    except Exception:
        shutil.rmtree(nouveau, ignore_errors=True)
        raise
    vers_corbeille(ancien)
    return True


def reecrire_partage(chemin: Path, qualite: int, vers_corbeille, eclairer=False, largeur_max=None, comicinfo=None, calage=None, fidele=False) -> int:
    """Tome partagé : version allégée écrite à part puis dossiers échangés (voir echanger_dossier). Renvoie les octets gagnés."""
    gagne = [0]
    eclairer = reglages_amelioration(eclairer)

    def ecrire(dest):
        gagne[0] = reecrire(chemin, qualite, eclairer, largeur_max, destination=dest, comicinfo=comicinfo, calage=calage, fidele=fidele)
        return gagne[0] > 0 or bool(eclairer) or comicinfo is not None
    return gagne[0] if echanger_dossier(chemin, ecrire, vers_corbeille) else 0


def _dossier_a_lui(f: Path, serie: str) -> bool:
    """Le fichier est seul de son genre dans un dossier de tome (« Tome 01/ »), pas à la racine de la série."""
    d = f.parent
    if d.name == serie:
        return False
    try:
        return [x for x in d.iterdir() if x.suffix.lower() in (".cbz", ".cbr", ".zip")] == [f]
    except OSError:
        return False


def etat(serie):
    with _VERROU:
        return dict(_ETAT.get(serie) or {})


def lancer(serie, fichiers, appliquer, vers_corbeille, eclairer=False, fini=None, largeur_max=None, qualite_forcee=None, infos_de=None, calages=None):
    """En arrière-plan : analyse (appliquer=False) ou allègement de chaque fichier de la liste.
    « infos_de(fichier) » : fonction de ComicInfo (voir reecrire) ou None ; les infos du tome sont alors écrites dans la même passe.
    « calages » : {nom du fichier: calage} des noirs et blancs de chaque tome (réglage « uniformiser », voir uniformite.py)."""
    eclairer = reglages_amelioration(eclairer)
    with _VERROU:
        if (_ETAT.get(serie) or {}).get("en_cours"):
            return False
        _ETAT[serie] = {"en_cours": True, "fait": 0, "total": len(fichiers), "message": "Analyse…" if not appliquer else "Traitement…",
                        "rapport": [], "appliquer": appliquer, "eclairer": eclairer, "largeur": largeur_max, "qualite_manuelle": qualite_forcee}

    def travail():
        gagne, avant_total, rapport = 0, 0, []
        try:
            for f in fichiers:
                f = Path(f)
                try:
                    if f.suffix.lower() not in (".cbz", ".zip") or not zipfile.is_zipfile(f):
                        rapport.append({"fichier": f.name, "note": "pas une archive ZIP : ignoré"})
                        continue
                    partage = f.stat().st_nlink > 1
                    if partage and not _dossier_a_lui(f, serie):
                        rapport.append({"fichier": f.name, "note": "partagé par qBittorrent et posé hors d'un dossier de tome : jamais modifié"})
                        continue
                    calage = (calages or {}).get(f.name)
                    fidele = qualite_forcee == QUALITE_ORIGINE
                    a = analyser(f, eclairer=eclairer, largeur_max=largeur_max, qualite_forcee=qualite_forcee, calage=calage)
                    avant_total += a["taille"]
                    ligne = {"fichier": f.name, "taille_mo": round(a["taille"] / 1048576, 1), "qualite": a["qualite"], "fidele": fidele,
                             "gain": a["gain_estime"], "psnr": a["psnr_min"]}
                    if eclairer and eclairer.get("uniformiser") and not calage:
                        ligne["alerte"] = "uniformisation ignorée : ce tome n'est pas encore mesuré"
                    comicinfo = infos_de(f) if (appliquer and infos_de) else None
                    if appliquer and (a["qualite"] or comicinfo):
                        if partage:
                            g = reecrire_partage(f, a["qualite"], vers_corbeille, eclairer, largeur_max, comicinfo, calage, fidele)
                            ligne["note"] = "partagé par qBittorrent : version allégée à part, le torrent n'est pas touché"
                        else:
                            g = reecrire(f, a["qualite"], eclairer, largeur_max, comicinfo=comicinfo, calage=calage, fidele=fidele)
                            ancien = f.with_name(f.name + ".avant")
                            if ancien.exists():
                                vers_corbeille(ancien)
                        ligne["gagne_mo"] = round(g / 1048576, 1)
                        if comicinfo:
                            ligne["infos"] = True
                        gagne += g
                    elif a["qualite"]:
                        gagne += int(a["taille"] * a["gain_estime"])
                    if not a["qualite"]:
                        ligne["note"] = "rien à changer sur ce tome (images laissées telles quelles)" + (", infos écrites" if ligne.get("infos") else "")
                    rapport.append(ligne)
                except Exception as e:
                    logger.warning("Allègement de %s : %s", f, e)
                    rapport.append({"fichier": f.name, "note": f"erreur : {e}"})
                with _VERROU:
                    _ETAT[serie]["fait"] += 1
                    _ETAT[serie]["rapport"] = list(rapport)
            go = lambda n: f"{n / 1048576:.0f} Mo" if abs(n) < 1073741824 else f"{n / 1073741824:.2f}".replace(".", ",") + " Go"
            traites = sum(1 for x in rapport if x.get("taille_mo") is not None)
            apres = avant_total - gagne
            if appliquer:
                msg = f"{traites} tome(s) traité(s) : {go(avant_total)} → {go(apres)}" + ("" if gagne == 0 else f" ({'−' if gagne > 0 else '+'}{go(abs(gagne))})")
            else:
                msg = (f"Analyse de {traites} tome(s) : {go(avant_total)} → environ {go(apres)}" + ("" if gagne == 0 else f" ({'−' if gagne > 0 else '+'}{go(abs(gagne))})") +
                       ". Rien n'a encore été modifié.")
        except Exception as e:
            msg = f"Erreur : {e}"
        with _VERROU:
            _ETAT[serie].update(en_cours=False, message=msg, rapport=rapport, gain=gagne)
        logger.info("Allègement de « %s » (%s) : %s", serie, "appliqué" if appliquer else "analyse", msg)
        if fini:
            fini()
    threading.Thread(target=travail, daemon=True).start()
    return True


_CACHE_COMPARAISON = {}


def comparer(chemin: Path, index: int, qualite, eclairer=False, largeur_max=None, zoom=None, calage=None, fidele=False) -> dict:
    """Une page du tome AVANT / APRÈS, avec exactement ce que « Appliquer » écrirait (même qualité, même largeur, même éclaircissement).
    zoom = (fx, fy) entre 0 et 1 : un détail de 640 px à l'échelle réelle plutôt que la page entière.
    Renvoie {"avant", "apres" (JPEG), "avant_ko", "apres_ko", "page", "pages", "inchange", "dimensions": [avant, après]}."""
    eclairer = reglages_amelioration(eclairer)
    cle = (str(chemin), chemin.stat().st_mtime_ns, index, qualite, tuple((eclairer or {}).values()), largeur_max, zoom, tuple(sorted((calage or {}).items())), fidele)
    with _VERROU_COMPARAISON:            # la page demande avant, après et infos en même temps : un seul calcul, les autres attendent
        if cle not in _CACHE_COMPARAISON:
            res = _comparer(chemin, index, qualite, eclairer, largeur_max, zoom, calage, fidele)
            if len(_CACHE_COMPARAISON) >= 8:
                _CACHE_COMPARAISON.pop(next(iter(_CACHE_COMPARAISON)))
            _CACHE_COMPARAISON[cle] = res
        return _CACHE_COMPARAISON[cle]


_VERROU_COMPARAISON = threading.Lock()


def _comparer(chemin, index, qualite, eclairer, largeur_max, zoom, calage=None, fidele=False):
    with zipfile.ZipFile(chemin) as z:
        noms = _pages(z)
        if not noms:
            raise RuntimeError("aucune page JPEG dans ce tome")
        index = max(0, min(index, len(noms) - 1))
        data = z.read(noms[index])
    im = Image.open(io.BytesIO(data))
    im.load()
    couleur = bool(eclairer) and est_couleur(im)
    traitee = ameliorer(im, eclairer, calage) if eclairer else im
    im2 = reduire(traitee, largeur_max)
    q_page = (qualite_jpeg(im) or qualite) if fidele else qualite                  # mode « même qualité » : celle de CETTE page
    nouveau = _jpeg(im2, q_page) if qualite and not (fidele and im2 is im) else data
    if qualite and not (im2 is not im or len(nouveau) < len(data)):
        nouveau = data                                   # une page qui ne gagne rien garde ses octets d'origine
    apres = Image.open(io.BytesIO(nouveau))
    apres.load()
    avant = im if im.size == apres.size else im.resize(apres.size, Image.LANCZOS)   # même géométrie pour comparer
    if zoom:
        c = 640
        x0 = int(max(0, min(apres.width - c, zoom[0] * apres.width - c / 2)))
        y0 = int(max(0, min(apres.height - c, zoom[1] * apres.height - c / 2)))
        boite = (x0, y0, min(apres.width, x0 + c), min(apres.height, y0 + c))
        sortie = [_jpeg(x.crop(boite), 100) for x in (avant, apres)]
    else:
        # Vue entière : la page « Après » est exactement ce que « Appliquer » écrirait (pas de recompression en plus)
        sortie = [_jpeg(avant, 100), nouveau]
    res = {"avant": sortie[0], "apres": sortie[1], "avant_ko": round(len(data) / 1024), "apres_ko": round(len(nouveau) / 1024),
           "page": index, "pages": len(noms), "inchange": nouveau is data, "dimensions": [list(im.size), list(apres.size)],
           "ameliore": traitee is not im, "couleur": couleur, "qualite_page": q_page if qualite else None}
    return res


# ---------------- 📖 Pages doubles : une image large contient souvent deux pages collées ----------------
import archives                         # ordre et numérotation des pages tels que le lecteur les voit
import xml.etree.ElementTree as ET

_RATIO_DOUBLE = 1.2                     # largeur / hauteur à partir de laquelle une image est une double page
_DOUBLES_CACHE = {}                     # (fichier, date, taille) → liste repérée
_COUPES_ETAT = {}                       # série → {"en_cours", "fait", "total", "message", "rapport"}
_COUPE_FORMATS = (".jpg", ".jpeg", ".png", ".webp")


def reperer_doubles(chemin: Path) -> list[dict]:
    """Doubles pages d'un tome (image plus large que haute) : [{"index", "nom"}], index = numéro de page du lecteur.
    Le repérage automatique ne sait pas distinguer une double normale d'une vraie double (une illustration) : c'est
    toi qui gardes les secondes entières dans la planche de vignettes."""
    chemin = Path(chemin)
    st = chemin.stat()
    cle = (str(chemin), st.st_mtime_ns, st.st_size)
    if cle in _DOUBLES_CACHE:
        return _DOUBLES_CACHE[cle]
    res = []
    with zipfile.ZipFile(chemin) as z:
        for i, nom in enumerate(archives.pages(chemin)):
            if Path(nom).suffix.lower() not in _COUPE_FORMATS:
                continue
            try:
                with Image.open(io.BytesIO(z.read(nom))) as im:
                    if im.width >= im.height * _RATIO_DOUBLE:
                        res.append({"index": i, "nom": nom})
            except Exception as e:
                logger.info("Page %s de %s ignorée pour les doubles : %s", nom, chemin.name, e)
    if len(_DOUBLES_CACHE) > 256:
        _DOUBLES_CACHE.clear()
    _DOUBLES_CACHE[cle] = res
    return res


def apercu_page(chemin: Path, index: int, largeur=300) -> bytes:
    """Une page du tome en JPEG réduit (vignette pour choisir les doubles pages)."""
    data, _ = archives.read_page(Path(chemin), index)
    im = Image.open(io.BytesIO(data))
    im.load()
    im = im.convert("RGB")
    im.thumbnail((largeur, largeur * 2))
    return _jpeg(im, 85)


def apercu_paire(chemin: Path, index: int, sens_manga=True, largeur=900, ajust=0, info=None) -> bytes:
    """La double page que donnerait l'assemblage des pages `index` et `index + 1`, calculée comme à l'assemblage (marges rognées,
    recalage), en JPEG réduit : c'est ce que montre la prévisualisation."""
    pages = []
    for n in (index, index + 1):
        data, _ = archives.read_page(Path(chemin), n)
        im = Image.open(io.BytesIO(data))
        im.load()
        pages.append(im)
    im = _coller(pages[0], pages[1], sens_manga, ajust, info)
    im.thumbnail((largeur, largeur))
    return _jpeg(im, 85)


# ---------------- 🔍 Repérer les paires de pages à assembler ----------------
_HAUTEUR_PAIRES = 1400                  # hauteur des pages pour le repérage : plus bas, les raies de scan et les traits fins se perdent
_PAIRES_CACHE = {}                      # (fichier, date, taille, sens) → paires repérées
SEUIL_PAIRE_POSSIBLE = 0.5              # accord des deux bords : à vérifier (≈ 1 fausse alerte sur 100 paires de pages voisines)
SEUIL_PAIRE_PROBABLE = 0.7              # ≈ 1 fausse alerte sur 200, un tiers des vraies paires


def _bandes_de_bord(im, k=6):
    """Les `k` colonnes de chaque bord d'une page (liserés de scan retirés), page réduite à _HAUTEUR_PAIRES : (bord gauche, bord droit)."""
    im = im.convert("L")
    if im.height > _HAUTEUR_PAIRES:
        im = im.resize((max(1, round(im.width * _HAUTEUR_PAIRES / im.height)), _HAUTEUR_PAIRES), Image.BOX)
    gauche, droite = _rogner_bord(im, "gauche"), _rogner_bord(im, "droite")
    return np.asarray(gauche)[:, :k].astype(np.float32), np.asarray(droite)[:, -k:].astype(np.float32)


def score_paire(cote_gauche, cote_droit, k=3):
    """À quel point le dessin continue d'une page à l'autre : accord (de -1 à 1) entre les `k` colonnes qui se touchent (`cote_gauche` : bord droit de la page
    de gauche, `cote_droit` : bord gauche de la page de droite), au meilleur décalage vertical de quelques pixels. Renvoie (accord, présence d'encre à la
    jointure, contraste) : une jointure blanche ou unie n'est jamais retenue."""
    a, b = cote_gauche[:, -k:].mean(axis=1), cote_droit[:, :k].mean(axis=1)
    h = min(len(a), len(b))
    a, b = a[:h], b[:h]
    accord = float(_courbe_profils(a, b, max(10, round(0.03 * h))).max())
    encre = min(float((cote_gauche[:, -k:] < 200).mean()), float((cote_droit[:, :k] < 200).mean()))
    return accord, encre, float(min(a.std(), b.std()))


def reperer_paires(chemin: Path, sens_manga=True, progres=None) -> list[dict]:
    """Pages simples qui sont probablement les deux moitiés d'une double page coupée : [{"index", "accord", "niveau": "probable" | "possible"}], `index` = numéro
    de la première page de la paire (celle qu'on touche dans la planche), sans paire qui se chevauche. Une double page a le dessin qui traverse la jointure :
    c'est ce que mesure score_paire. Sur de vrais tomes (banc d'essai) : un tiers des vraies paires en « probable » pour une fausse alerte sur 200 paires de pages
    voisines, la moitié en « possible » pour une sur 100. À toi de confirmer sur l'aperçu : rien n'est assemblé sans ton accord."""
    chemin = Path(chemin)
    st = chemin.stat()
    cle = (str(chemin), st.st_mtime_ns, st.st_size, bool(sens_manga))
    if cle in _PAIRES_CACHE:
        return _PAIRES_CACHE[cle]
    ordre = archives.pages(chemin)
    bandes = []
    with zipfile.ZipFile(chemin) as z:
        for i, nom in enumerate(ordre):
            b = None
            if Path(nom).suffix.lower() in _COUPE_FORMATS:
                try:
                    im = Image.open(io.BytesIO(z.read(nom)))
                    if im.width <= im.height * 1.1:                    # une page large est déjà une double
                        if im.format == "JPEG" and im.height > 2 * _HAUTEUR_PAIRES:
                            im.draft("L", (im.width // 2, im.height // 2))
                        im.load()
                        b = _bandes_de_bord(im)
                except Exception as e:
                    logger.info("Page %s de %s ignorée pour les paires : %s", nom, chemin.name, e)
            bandes.append(b)
            if progres:
                progres(i + 1, len(ordre))
    candidats = []
    for i in range(len(ordre) - 1):
        premiere, seconde = bandes[i], bandes[i + 1]
        if premiere is None or seconde is None:
            continue
        # manga : la page i est à droite (son bord gauche touche), la page i+1 à gauche ; occidental : l'inverse
        gauche, droite = (seconde, premiere) if sens_manga else (premiere, seconde)
        accord, encre, contraste = score_paire(gauche[1], droite[0])
        if accord >= SEUIL_PAIRE_POSSIBLE and encre >= 0.15 and contraste >= 12:
            candidats.append((accord, i))
    choisies, pris = [], set()
    for accord, i in sorted(candidats, reverse=True):                  # les plus sûres d'abord, jamais deux paires qui se touchent
        if i in pris or i + 1 in pris:
            continue
        pris.update((i, i + 1))
        choisies.append({"index": i, "accord": round(accord, 2), "niveau": "probable" if accord >= SEUIL_PAIRE_PROBABLE else "possible"})
    choisies.sort(key=lambda p: p["index"])
    if len(_PAIRES_CACHE) > 64:
        _PAIRES_CACHE.clear()
    _PAIRES_CACHE[cle] = choisies
    return choisies


def _moities(im, sens_manga):
    """Les deux moitiés d'une double page. Manga : la moitié droite se lit d'abord."""
    w, h = im.size
    m = w // 2
    gauche, droite = im.crop((0, 0, m, h)), im.crop((m, 0, w, h))
    return (droite, gauche) if sens_manga else (gauche, droite)


def _octets_page(im, nom):
    out = io.BytesIO()
    ext = Path(nom).suffix.lower()
    if ext == ".png":
        im.save(out, "PNG", optimize=True)
    elif ext == ".webp":
        im.save(out, "WEBP", quality=95)
    else:
        im.convert("RGB" if im.mode not in ("L", "RGB") else im.mode).save(out, "JPEG", quality=95, optimize=True, progressive=True)
    return out.getvalue()


def _comicinfo_maj(donnees: bytes, carte: dict, nb: int) -> bytes:
    """Numéros de page des signets (ComicInfo) suivis, et nombre total de pages mis à jour."""
    try:
        racine = ET.fromstring(donnees)
    except ET.ParseError:
        return donnees
    for p in racine.iter("Page"):
        try:
            ancien = int(p.get("Image", ""))
        except ValueError:
            continue
        if ancien in carte:
            p.set("Image", str(carte[ancien]))
    pc = racine.find("PageCount")
    if pc is not None:
        pc.text = str(nb)
    return ET.tostring(racine, encoding="utf-8", xml_declaration=True)


def couper(chemin: Path, indices, sens_manga=True, destination=None) -> dict:
    """Écrit le tome avec les pages « indices » (numéros du lecteur) coupées en deux. Même principe que reecrire : version
    à côté (ou « destination » pour un fichier partagé), relue, puis remplacée ; l'ancien part dans « avant » (corbeille).
    Renvoie {"carte": {ancien numéro: nouveau}, "pages_avant", "pages", "avant"}. Les noms des pages de chapitre
    (c0012.00-p003.jpg) sont renumérotés dans les chapitres touchés ; les autres moitiés s'appellent « 0008b.jpg »."""
    import tomes_cbz
    chemin = Path(chemin)
    ordre = archives.pages(chemin)
    coupees = {ordre[i] for i in indices if 0 <= i < len(ordre) and Path(ordre[i]).suffix.lower() in _COUPE_FORMATS}
    if not coupees:
        raise RuntimeError("aucune page double à couper")
    entrees = []                                  # [nom, octets, numéro ancien ou None, numéro de chapitre ou None, date]
    with zipfile.ZipFile(chemin) as z:
        for info in z.infolist():
            nom, data = info.filename, z.read(info.filename)
            num = tomes_cbz.num_page(nom)
            if nom not in coupees:
                entrees.append([nom, data, ordre.index(nom) if nom in ordre else None, num, info.date_time])
                continue
            a, b = _moities(Image.open(io.BytesIO(data)), sens_manga)
            a.load()
            stem, suf = Path(nom).stem, Path(nom).suffix
            entrees.append([nom, _octets_page(a, nom), ordre.index(nom), num, info.date_time])
            entrees.append([nom if num is not None else f"{stem}b{suf}", _octets_page(b, nom), None, num, info.date_time])
    touches = {tomes_cbz.num_page(n) for n in coupees} - {None}          # chapitres où une page a été coupée
    compte = {}
    for e in entrees:
        if e[3] is None or e[3] not in touches:
            continue
        compte[e[3]] = compte.get(e[3], 0) + 1
        e[0] = tomes_cbz.nom_page(e[3], compte[e[3]], ext=Path(e[0]).suffix.lstrip(".") or "jpg")
    nouvel_ordre = sorted((e[0] for e in entrees if e[0].lower().endswith(archives.IMAGE_EXT)
                           and "__MACOSX" not in e[0] and not Path(e[0]).name.startswith(".")), key=archives.natural_key)
    position = {nom: i for i, nom in enumerate(nouvel_ordre)}
    carte = {e[2]: position[e[0]] for e in entrees if e[2] is not None and e[0] in position}
    nb = len(nouvel_ordre)
    tmp = Path(destination) if destination is not None else chemin.with_name("." + chemin.name + ".coupe")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
        for nom, data, _, _, date in entrees:
            if Path(nom).name == "ComicInfo.xml":
                data = _comicinfo_maj(data, carte, nb)
            info2 = zipfile.ZipInfo(nom, date_time=date)
            info2.compress_type = zipfile.ZIP_STORED
            dst.writestr(info2, data)
    with zipfile.ZipFile(tmp) as z:                   # relecture : archive saine, mêmes pages dans le même ordre
        if z.testzip() is not None:
            tmp.unlink()
            raise RuntimeError("archive coupée illisible")
        if archives._names(z) != nouvel_ordre:
            tmp.unlink()
            raise RuntimeError("pages différentes après coupe")
    res = {"carte": carte, "pages_avant": len(ordre), "pages": nb}
    if destination is not None:
        return res
    avant = chemin.with_name(chemin.name + ".avant")
    chemin.rename(avant)
    tmp.rename(chemin)
    res["avant"] = avant
    return res


def _coller(premiere, seconde, sens_manga, ajust=0, info=None):
    """Deux pages simples côte à côte en une double page. Manga : la première page à lire est à droite. Hauteurs différentes :
    la plus petite est agrandie à la hauteur de l'autre (proportions gardées). `info` (dict, facultatif) reçoit l'estimation
    de l'alignement : {"dy", "niveau", "score"} (voir estimer_decalage), sans la retouche à la main `ajust`."""
    for im in (premiere, seconde):
        im.load()
    h = max(premiere.height, seconde.height)
    p, q = [im.convert("RGB").resize((max(1, round(im.width * h / im.height)), h), Image.LANCZOS) if im.height != h else im.convert("RGB")
            for im in (premiere, seconde)]
    gauche, droite = (q, p) if sens_manga else (p, q)
    gauche, droite = _rogner_bord(gauche, "droite"), _rogner_bord(droite, "gauche")
    estimation = estimer_decalage(gauche, droite)
    if info is not None:
        info.update(estimation)
    decalage = estimation["dy"] + int(ajust or 0)                            # `ajust` : retouche à la main, en pixels
    if decalage:                                  # la page descend ou monte : la bande libérée prolonge le bord de la page (pas de bande blanche)
        a = np.asarray(droite)
        d = max(-h + 1, min(h - 1, decalage))
        a = np.concatenate([np.repeat(a[:1], d, axis=0), a[:h - d]]) if d > 0 else np.concatenate([a[-d:], np.repeat(a[-1:], -d, axis=0)])
        droite = Image.fromarray(a)
    out = Image.new("RGB", (gauche.width + droite.width, h), (255, 255, 255))
    out.paste(gauche, (0, 0))
    out.paste(droite, (gauche.width, 0))
    return out


def _rogner_bord(im, cote, maxi=0.04):
    """Enlève, du côté qui touche l'autre page, les colonnes de bord du scan (liseré blanc ou noir, même dégradé) qui tranchent sur le dessin
    juste à côté : c'est ce qui fait la raie au milieu. Jamais plus de 4 % de la largeur pour le liseré, 8 % pour la marge blanche vide ; le dessin, lui, n'est pas touché."""
    moyennes = np.asarray(im.convert("L"), dtype=np.float32).mean(axis=0)
    ordre = moyennes[::-1] if cote == "droite" else moyennes
    limite = int(im.width * maxi)
    ref = float(np.median(ordre[8:40])) if len(ordre) > 40 else float(np.median(ordre))     # le dessin juste derrière le liseré
    stable = float(np.median(ordre[30:70])) if len(ordre) > 70 else ref
    zone = [j for j in range(min(24, len(ordre))) if abs(ordre[j] - stable) > 20]            # ombre ou halo de la reliure : tout ce qui dévie
    proche = float(np.median(ordre[8:16])) if len(ordre) > 16 else ref
    fins = [j for j in range(min(8, len(ordre))) if abs(ordre[j] - proche) > 7]                # raie fine : même peu marquée, elle court sur toute la hauteur
    base = max(zone[-1] + 1 if zone else 0, fins[-1] + 1 if fins else 0)
    franches = [j for j in range(min(8, len(ordre) - 3)) if abs(ordre[j] - ref) > 40 and abs(ordre[j + 3] - ref) <= 25]    # trait étroit
    n = max(base, franches[-1] + 1 if franches else 0)         # un liseré peut avoir un trou : blanc, trait noir, blanc
    while n < limite and n < len(ordre) and abs(ordre[n] - ref) > 12 and (ordre[n] > 170 or ordre[n] < 40 or (n < 8 and abs(ordre[n] - ref) > 40)):
        n += 1                                   # liseré clair ou sombre ; sur les 8 premières colonnes, tout ce qui tranche franchement
    encre = (np.asarray(im.convert("L")) < 215).sum(axis=0)                  # traits par colonne
    encre = encre[::-1] if cote == "droite" else encre
    blanc_max = int(im.width * 0.08)
    avant_marge = n
    while n < blanc_max and n < len(encre) and encre[n] <= max(2, im.height // 120) and (ordre[n] > 200 or ordre[n] < 40):   # marge blanche coupée par le scan
        n += 1
    if n > avant_marge:                                                      # marge blanche retirée : son dégradé (halo clair) reste devant le dessin
        ref2 = float(np.median(ordre[n + 12:n + 45])) if len(ordre) > n + 45 else float(np.median(ordre[n:]))
        fin = n + 12
        while n < fin and n < len(ordre) and ordre[n] - ref2 > 20:
            n += 1
    gris = np.asarray(im.convert("L"), dtype=np.int16)
    gris = gris[:, ::-1] if cote == "droite" else gris
    n += _raie_dans_le_noir_ou_le_blanc(gris[:, n:])
    if not n:
        return im
    return im.crop((0, 0, im.width - n, im.height)) if cote == "droite" else im.crop((n, 0, im.width, im.height))


def _raie_dans_le_noir_ou_le_blanc(gris, largeur=12):
    """Raie fine du bord que les moyennes de colonnes ne voient pas : un fil clair dans une zone noire, ou un fil sombre dans une zone
    blanche (le dessin voisin décide). Rend le nombre de colonnes à retirer (0 s'il n'y en a pas)."""
    if gris.shape[1] < largeur + 12:
        return 0
    voisin = np.median(gris[:, largeur:largeur + 8], axis=1)                  # ce que devrait être la ligne, d'après le dessin d'à côté
    noir, blanc = voisin < 70, voisin > 205
    dernier = -1
    for j in range(largeur):
        ecart = gris[:, j] - voisin
        if noir.sum() > gris.shape[0] // 20 and ecart[noir].mean() > 45:        # fil clair dans le noir
            dernier = j
        elif blanc.sum() > gris.shape[0] // 20 and ecart[blanc].mean() < -45:   # fil sombre dans le blanc
            dernier = j
    return dernier + 1


def _intersections(im, cote, ecart, profondeur=100):
    """Où les traits proches de la jointure la croiseraient s'ils continuaient tout droit : histogramme par ligne, pondéré par la netteté
    du trait. `ecart` : largeur perdue au milieu par le scan (les traits se prolongent au-dessus de ce vide)."""
    a = np.asarray(im.convert("L"), dtype=np.float32)
    h, w = a.shape
    p = min(profondeur, w)
    bande = cv2.GaussianBlur(a[:, -p:] if cote == "g" else a[:, :p], (0, 0), 1.2)
    gx, gy = cv2.Sobel(bande, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(bande, cv2.CV_32F, 0, 1, ksize=3)
    nettete = np.sqrt(gx * gx + gy * gy)
    with np.errstate(divide="ignore", invalid="ignore"):
        pente = np.where(np.abs(gy) > 1e-3, -gx / gy, np.inf)                      # pente du trait (perpendiculaire au dégradé)
    garde = (nettete > np.percentile(nettete, 90)) & (np.abs(pente) < 2.5) & (np.abs(gy) > 0.3 * nettete)    # traits nets, pas verticaux
    ys, xs = np.nonzero(garde)
    jointure = (p + ecart / 2.0) if cote == "g" else (-ecart / 2.0)
    cible = np.round(ys + pente[ys, xs] * (jointure - xs)).astype(int) + 200
    hist = np.zeros(h + 400, dtype=np.float32)
    ok = (cible >= 0) & (cible < len(hist))
    np.add.at(hist, cible[ok], np.minimum(nettete[ys, xs][ok], 200))
    return cv2.GaussianBlur(hist.reshape(-1, 1), (1, 0), 1.5).ravel()


def _courbe_profils(L, R, maxi):
    """Corrélation de deux profils (une valeur par rangée) pour chaque décalage de -maxi à +maxi pixels : R est le profil de la page
    de droite telle qu'elle est, descendue de `dy` par rapport à celle de gauche quand le décalage de la courbe vaut -dy."""
    n = len(L)
    sortie = np.full(2 * maxi + 1, -1.0)
    for k, dy in enumerate(range(-maxi, maxi + 1)):
        lo, hi = max(0, dy), min(n, n + dy)
        if hi - lo < max(50, n // 5):
            continue
        x, y = L[lo:hi], R[lo - dy:hi - dy]
        x, y = x - x.mean(), y - y.mean()
        sortie[k] = float((x * y).sum() / (np.sqrt((x * x).sum() * (y * y).sum()) + 1e-9))
    return sortie


def _bords(g, d, k, sigma=0.0, derive=False):
    """Les `k` colonnes qui touchent la jointure, moyennées par rangée (flou vertical `sigma`, dérivée si `derive`)."""
    h = min(g.shape[0], d.shape[0])
    gauche, droite = g[:h, -k:].astype(np.float32).mean(axis=1), d[:h, :k].astype(np.float32).mean(axis=1)
    if sigma:
        gauche = cv2.GaussianBlur(gauche.reshape(-1, 1), (0, 0), sigma).ravel()
        droite = cv2.GaussianBlur(droite.reshape(-1, 1), (0, 0), sigma).ravel()
    return (np.gradient(gauche), np.gradient(droite)) if derive else (gauche, droite)


def _courbe_lignes(g, d, maxi, ecarts):
    """Pour chaque décalage, le meilleur accord (sur plusieurs largeurs perdues au milieu) des traits prolongés jusqu'à la jointure."""
    gi, di = Image.fromarray(g), Image.fromarray(d)
    meilleur = np.full(2 * maxi + 1, -1.0)
    for ecart in ecarts:
        hg, hd = _intersections(gi, "g", ecart), _intersections(di, "d", ecart)
        n = min(len(hg), len(hd))
        x = hg[200:n - 200]
        x = x - x.mean()
        for k, dy in enumerate(range(-maxi, maxi + 1)):
            y = np.roll(hd, dy)[200:n - 200]
            y = y - y.mean()
            meilleur[k] = max(meilleur[k], float((x * y).sum() / (np.sqrt((x * x).sum() * (y * y).sum()) + 1e-9)))
    return meilleur


def _pic(courbe, garde=3):
    """(indice du maximum, valeur, avance sur le meilleur autre pic situé à plus de `garde` pixels)."""
    k = int(np.argmax(courbe))
    reste = np.ones(len(courbe), bool)
    reste[max(0, k - garde):k + garde + 1] = False
    return k, float(courbe[k]), float(courbe[k]) - (float(courbe[reste].max()) if reste.any() else -1.0)


SEUIL_FIN = 0.8                 # accord des deux colonnes qui touchent la jointure : assez net pour décider seul
SEUIL_GROSSIER = 0.8            # accord des traits prolongés + profils : en dessous, le décalage reste à 0 et on le dit


def estimer_decalage(gauche, droite) -> dict:
    """De combien de pixels descendre (+) ou monter (-) la page de droite pour que le dessin continue de part et d'autre de la jointure,
    avec la confiance qu'on peut avoir : {"dy", "niveau": "sur" | "probable" | "incertain", "score"}. Deux étapes : une recherche
    d'ensemble sur la page réduite (traits prolongés + profils de la jointure à trois largeurs : robuste à la trame, à la largeur perdue au milieu
    et à la résolution), puis un affinage au pixel près sur les deux colonnes qui touchent la jointure, retenu quand elles se répondent
    nettement (≥ 0,8) ET que la recherche d'ensemble tombe au même endroit. Quand rien ne se superpose assez (marges blanches, pas de dessin qui traverse), le décalage est 0 et le niveau « incertain » :
    mieux vaut ne rien décaler que décaler à tort. Banc d'essai : outils/banc_alignement.py (vraies doubles pages coupées et décalées exprès)."""
    g, d = np.asarray(gauche.convert("L")), np.asarray(droite.convert("L"))
    h = min(g.shape[0], d.shape[0])
    maxi = max(30, min(100, round(0.03 * h)))
    f = max(1.0, h / 1400)
    if f > 1:                                                       # recherche d'ensemble sur une page de 1400 px de haut
        g1 = cv2.resize(g, (max(1, int(g.shape[1] / f)), int(g.shape[0] / f)), interpolation=cv2.INTER_AREA)
        d1 = cv2.resize(d, (max(1, int(d.shape[1] / f)), int(d.shape[0] / f)), interpolation=cv2.INTER_AREA)
    else:
        g1, d1 = g, d
    m1 = int(np.ceil(maxi / f))
    courbe = _courbe_lignes(g1, d1, m1, (0, 4, 8, 14))
    for k in (4, 12, 30):
        courbe = courbe + _courbe_profils(*_bords(g1, d1, k, 1.5, True), m1) / 3
    k, v, avance = _pic(courbe)
    grossier, score = int(round((k - m1) * f)), v + avance
    fin = (_courbe_profils(*_bords(g, d, 2), maxi) + _courbe_profils(*_bords(g, d, 1), maxi)) / 2
    kf = int(np.argmax(fin))
    r = int(np.ceil(f)) + 3
    if fin[kf] >= SEUIL_FIN and 0 < kf < 2 * maxi and abs((kf - maxi) - grossier) <= 2 * r:     # les deux estimations se répondent
        return {"dy": kf - maxi, "niveau": "sur", "score": round(float(fin[kf]), 2)}
    if score >= SEUIL_GROSSIER and 0 < k < 2 * m1:
        centre = grossier + maxi                                     # affinage autour de l'estimation d'ensemble
        fenetre = fin[max(0, centre - r):centre + r + 1]
        dy = max(0, centre - r) + int(np.argmax(fenetre)) - maxi if fenetre.size and fenetre.max() > 0.4 else grossier
        return {"dy": int(dy), "niveau": "sur" if score >= 1.1 else "probable", "score": round(score, 2)}
    return {"dy": 0, "niveau": "incertain", "score": round(score, 2)}


def _decalage_vertical(gauche, droite):
    """Le décalage à appliquer (0 quand l'estimation est incertaine). Voir estimer_decalage."""
    return estimer_decalage(gauche, droite)["dy"]


def carte_assemblage(avant: Path, apres: Path) -> dict:
    """Retrouve, en comparant l'archive d'origine et l'archive assemblée, où est passée chaque page : {ancien numéro: nouveau}.
    Les pages non collées sont reprises telles quelles (même somme de contrôle) ; une page qui ne retrouve pas la sienne est une double
    page née de deux pages d'origine. Sert à recaler après coup ce qui a été enregistré avant l'assemblage. Lève RuntimeError si les deux
    archives ne se correspondent pas."""
    def sommes(chemin):
        chemin = Path(chemin)
        with zipfile.ZipFile(chemin) as z:
            return [z.getinfo(n).CRC for n in archives.pages(chemin)]
    anciennes, nouvelles = sommes(avant), sommes(apres)
    carte, i = {}, 0
    for j, crc in enumerate(nouvelles):
        if i < len(anciennes) and anciennes[i] == crc:
            carte[i] = j
            i += 1
        elif i + 1 < len(anciennes):
            carte[i] = carte[i + 1] = j
            i += 2
        else:
            raise RuntimeError("les pages ne se correspondent pas")
    if i != len(anciennes):
        raise RuntimeError("les pages ne se correspondent pas")
    return carte


def assembler(chemin: Path, indices, sens_manga=True, destination=None, ajust=None) -> dict:
    """Inverse de `couper` : chaque page « i » des `indices` (numéros du lecteur) est collée à la page suivante pour faire une vraie
    double page. Même principe que `couper` (version à côté, relue, puis remplacée ; l'ancien part dans « avant »).
    Renvoie {"carte": {ancien numéro: nouveau}, "pages_avant", "pages", "avant"}."""
    import tomes_cbz
    chemin = Path(chemin)
    ordre = archives.pages(chemin)
    debuts = sorted({i for i in indices if 0 <= i < len(ordre) - 1 and Path(ordre[i]).suffix.lower() in _COUPE_FORMATS
                     and Path(ordre[i + 1]).suffix.lower() in _COUPE_FORMATS})
    if not debuts or any(b - a < 2 for a, b in zip(debuts, debuts[1:])):
        raise RuntimeError("aucune paire de pages à assembler (une page ne peut être dans deux paires)")
    suivantes = {ordre[i + 1]: ordre[i] for i in debuts}                 # page absorbée → page qui la reçoit
    premieres = {ordre[i] for i in debuts}
    entrees = []                                  # [nom, octets, numéro ancien ou None, numéro de chapitre ou None, date]
    with zipfile.ZipFile(chemin) as z:
        pages_lues = {}
        for nom in list(premieres) + list(suivantes):
            im = Image.open(io.BytesIO(z.read(nom)))
            im.load()
            pages_lues[nom] = im
        for info in z.infolist():
            nom = info.filename
            if nom in suivantes:
                continue
            data = z.read(nom)
            num = tomes_cbz.num_page(nom)
            if nom in premieres:
                seconde = ordre[ordre.index(nom) + 1]
                data = _octets_page(_coller(pages_lues[nom], pages_lues[seconde], sens_manga, (ajust or {}).get(ordre.index(nom), 0)), nom)
            entrees.append([nom, data, ordre.index(nom) if nom in ordre else None, num, info.date_time])
    touches = {tomes_cbz.num_page(n) for n in premieres} - {None}        # chapitres où des pages ont été collées : renumérotés
    compte = {}
    for e in entrees:
        if e[3] is None or e[3] not in touches:
            continue
        compte[e[3]] = compte.get(e[3], 0) + 1
        e[0] = tomes_cbz.nom_page(e[3], compte[e[3]], ext=Path(e[0]).suffix.lstrip(".") or "jpg")
    nouvel_ordre = sorted((e[0] for e in entrees if e[0].lower().endswith(archives.IMAGE_EXT)
                           and "__MACOSX" not in e[0] and not Path(e[0]).name.startswith(".")), key=archives.natural_key)
    position = {nom: i for i, nom in enumerate(nouvel_ordre)}
    carte = {e[2]: position[e[0]] for e in entrees if e[2] is not None and e[0] in position}
    for i in debuts:                                                      # la page absorbée suit la double page qui la remplace
        carte[i + 1] = carte.get(i, 0)
    nb = len(nouvel_ordre)
    tmp = Path(destination) if destination is not None else chemin.with_name("." + chemin.name + ".assemble")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
        for nom, data, _, _, date in entrees:
            if Path(nom).name == "ComicInfo.xml":
                data = _comicinfo_maj(data, carte, nb)
            info2 = zipfile.ZipInfo(nom, date_time=date)
            info2.compress_type = zipfile.ZIP_STORED
            dst.writestr(info2, data)
    with zipfile.ZipFile(tmp) as z:                   # relecture : archive saine, une page de moins par paire
        if z.testzip() is not None:
            tmp.unlink()
            raise RuntimeError("archive assemblée illisible")
        if archives._names(z) != nouvel_ordre or len(nouvel_ordre) != len(ordre) - len(debuts):
            tmp.unlink()
            raise RuntimeError("pages différentes après assemblage")
    res = {"carte": carte, "pages_avant": len(ordre), "pages": nb}
    if destination is not None:
        return res
    avant = chemin.with_name(chemin.name + ".avant")
    chemin.rename(avant)
    tmp.rename(chemin)
    res["avant"] = avant
    return res


def lancer_coupes(serie, travaux, sens_manga, vers_corbeille, apres=None, operation=None) -> bool:
    """En arrière-plan : coupe les pages doubles de chaque tome (ou, avec operation=assembler, colle des paires de pages). travaux = [(chemin, {numéros de page})].
    apres(chemin, carte) est appelé après chaque tome (pour recaler la position de lecture). Un fichier partagé par
    qBittorrent suit la même règle que l'allègement : version à part, le torrent n'est pas touché."""
    with _VERROU:
        if (_COUPES_ETAT.get(serie) or {}).get("en_cours"):
            return False
        _COUPES_ETAT[serie] = {"en_cours": True, "fait": 0, "total": len(travaux), "message": "En cours…", "rapport": []}

    def travail():
        rapport, pages_coupees = [], 0
        try:
            for chemin, indices, *reste in travaux:
                reglage = {"ajust": reste[0]} if reste and operation else {}
                chemin = Path(chemin)
                ligne = {"fichier": chemin.name}
                try:
                    if chemin.stat().st_nlink > 1 and not _dossier_a_lui(chemin, serie):
                        ligne["note"] = "partagé par qBittorrent hors d'un dossier de tome : jamais modifié"
                    elif chemin.stat().st_nlink > 1:
                        res = {}

                        def ecrire(dest):
                            res.update((operation or couper)(chemin, indices, sens_manga, destination=dest, **reglage))
                            return True
                        echanger_dossier(chemin, ecrire, vers_corbeille)
                        ligne["note"] = "partagé par qBittorrent : nouvelle version à part, le torrent n'est pas touché"
                    else:
                        res = (operation or couper)(chemin, indices, sens_manga, **reglage)
                        vers_corbeille(res.pop("avant"))
                    if res:
                        ligne.update(pages_avant=res["pages_avant"], pages=res["pages"])
                        pages_coupees += len(indices)
                        if apres:
                            apres(chemin, res["carte"])
                except Exception as e:
                    logger.warning("Coupe de %s : %s", chemin, e)
                    ligne["note"] = f"erreur : {e}"
                rapport.append(ligne)
                with _VERROU:
                    _COUPES_ETAT[serie]["fait"] += 1
                    _COUPES_ETAT[serie]["rapport"] = list(rapport)
            msg = (f"{pages_coupees} double(s) page(s) créée(s) dans {len(travaux)} tome(s)" if operation else
                   f"{pages_coupees} page(s) coupée(s) dans {len(travaux)} tome(s)")
        except Exception as e:
            msg = f"Erreur : {e}"
        with _VERROU:
            _COUPES_ETAT[serie].update(en_cours=False, message=msg, rapport=rapport)
        logger.info("Pages doubles de « %s » : %s", serie, msg)
    threading.Thread(target=travail, daemon=True).start()
    return True


def coupes_etat(serie):
    with _VERROU:
        return dict(_COUPES_ETAT.get(serie) or {})
