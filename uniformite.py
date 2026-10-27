"""🎨 Uniformité d'une série : le noir, le blanc et la teinte de chaque tome sont mesurés sur quelques pages, puis comparés
d'un tome à l'autre. Les tomes qui s'écartent des autres (noirs relevés, papier gris, léger ton violet ou jaune) sont signalés avec
un calage proposé : un point noir et un point blanc qui ramènent le tome au niveau de référence (le groupe de tomes le plus
nombreux, ou celui qu'on choisit). Rien n'est modifié ici : le calage s'applique ensuite par ✨ Améliorer (réglage « Uniformiser »).

Mesures par page (réduite, noir et blanc seulement ; une page en couleur est ignorée) :
- noir : le niveau le plus sombre de la page (0,3e centile de la luminosité), puis la médiane sur les pages du tome ;
- encre : la luminosité médiane des pixels sombres (< 70) : plus ou moins « noire » à l'écran ;
- blanc : la luminosité médiane des pixels clairs (> 200) : papier blanc ou gris ;
- teinte : l'écart moyen de chaque canal rouge/vert/bleu à la luminosité, sur l'encre et sur le papier (un noir à 35/31/32 est « un peu violet »).
"""
import colorsys
import io
import json
import logging
import threading
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

import archives

logger = logging.getLogger("mouflanga")

VERSION = 1                      # change quand les mesures changent : les anciennes ne sont plus reprises
HAUTEUR = 600                    # les pages sont mesurées réduites à cette hauteur
NB_PAGES = 14                    # pages mesurées par tome, réparties sur tout le tome
SEUIL_COULEUR = 12               # même seuil qu'optimiser.est_couleur
# Écarts à partir desquels deux tomes ne se ressemblent plus à l'écran
ECART_ENCRE = 10                 # niveaux de gris (0-255) entre deux encres
ECART_BLANC = 8                  # entre deux papiers
ECART_TEINTE = 1.5               # écart de teinte de l'encre (même unité) ; 3 pour le papier

_ETAT = {}                       # série → {"en_cours", "fait", "total", "message"}
_VERROU = threading.Lock()
_VERROU_CACHE = threading.Lock()


# ---------------- mesure ----------------
def mesurer_page(im: Image.Image) -> dict | None:
    """Noir, encre, blanc et teinte d'une page noir et blanc ; None pour une page en couleur ou sans assez de noir et de blanc à mesurer."""
    im = im.convert("RGB")
    if im.height > HAUTEUR:
        im = im.resize((max(1, round(im.width * HAUTEUR / im.height)), HAUTEUR), Image.BOX)
    a = np.asarray(im, dtype=np.float32)
    if float(np.mean(np.abs(a[..., 0] - a[..., 1]) + np.abs(a[..., 1] - a[..., 2]))) > SEUIL_COULEUR:
        return None
    lum = a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
    sombre, clair = lum < 70, lum > 200
    n = lum.size
    if sombre.sum() < n * 0.01 or clair.sum() < n * 0.05:
        return None
    ecart = a - lum[..., None]
    return {"noir": float(np.percentile(lum, 0.3)), "encre": float(np.median(lum[sombre])), "blanc": float(np.median(lum[clair])),
            "teinte_encre": ecart[sombre].mean(axis=0).tolist(), "teinte_papier": ecart[clair].mean(axis=0).tolist()}


def mesurer_tome(chemin: Path, nb_pages: int = NB_PAGES) -> dict:
    """Mesures d'un tome : médiane sur `nb_pages` pages réparties dans le tome (sans les toutes premières ni dernières).
    {"noir", "encre", "blanc", "teinte_encre": [r, g, b], "teinte_papier": [r, g, b], "pages": mesurées, "couleur": en couleur ou ignorées}."""
    chemin = Path(chemin)
    noms = [n for n in archives.pages(chemin) if n.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
    if not noms:
        return {"pages": 0, "couleur": 0}
    debut, fin = min(3, len(noms) // 6), max(len(noms) - min(3, len(noms) // 6), 1)
    choix = sorted({int(x) for x in np.linspace(debut, fin - 1, min(nb_pages, fin - debut))})
    mesures, ignorees = [], 0
    with zipfile.ZipFile(chemin) as z:
        for i in choix:
            try:
                im = Image.open(io.BytesIO(z.read(noms[i])))
                if im.format == "JPEG" and im.height > 2 * HAUTEUR:
                    im.draft("RGB", (im.width // 2, im.height // 2))            # décodage deux fois plus rapide, mesure inchangée
                im.load()
                if im.width > im.height * 1.2:                                  # une double page : même mesure, mais ne compte pas deux fois
                    pass
                m = mesurer_page(im)
            except Exception as e:
                logger.info("Uniformité : page %s de %s ignorée : %s", noms[i], chemin.name, e)
                m = None
            if m:
                mesures.append(m)
            else:
                ignorees += 1
    if not mesures:
        return {"pages": 0, "couleur": ignorees}
    med = lambda cle: float(np.median([m[cle] for m in mesures]))
    vec = lambda cle: [round(float(x), 2) for x in np.median([m[cle] for m in mesures], axis=0)]
    return {"noir": round(med("noir"), 1), "encre": round(med("encre"), 1), "blanc": round(med("blanc"), 1),
            "teinte_encre": vec("teinte_encre"), "teinte_papier": vec("teinte_papier"), "pages": len(mesures), "couleur": ignorees}


def chroma(t) -> float:
    return float(np.sqrt(sum(float(x) ** 2 for x in t))) if t else 0.0


def _hex(niveau, teinte) -> str:
    """Couleur réelle (#rrggbb) d'un niveau de gris et de son écart de teinte, pour la montrer à l'écran."""
    return "#" + "".join(f"{int(min(255, max(0, round(float(niveau) + float(x))))):02x}" for x in (teinte or [0, 0, 0]))


def nom_teinte(t) -> str:
    """Teinte d'un écart rouge/vert/bleu : « neutre », « violacée », « jaunâtre »… (l'oeil en voit à partir de 1,5 environ)."""
    if chroma(t) < 0.8:
        return "neutre"
    r, g, b = (min(255, max(0, 128 + 40 * float(x))) / 255 for x in t)
    teinte = colorsys.rgb_to_hsv(r, g, b)[0] * 360
    for borne, nom in ((15, "rougeâtre"), (45, "orangée"), (70, "jaunâtre"), (170, "verdâtre"), (200, "cyan"), (255, "bleutée"),
                       (345, "violacée"), (361, "rougeâtre")):
        if teinte < borne:
            return nom
    return "neutre"


# ---------------- mémoire des mesures ----------------
def _cle(chemin: Path):
    st = Path(chemin).stat()
    return [st.st_mtime_ns, st.st_size, VERSION]


def _lire_cache(cache: Path) -> dict:
    try:
        d = json.loads(Path(cache).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _ecrire_cache(cache: Path, d: dict):
    tmp = Path(str(cache) + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cache)


def stats_en_memoire(cache: Path, fichiers) -> dict:
    """{nom du fichier: mesures} de ce qui est déjà mesuré (fichier inchangé depuis la mesure)."""
    d = _lire_cache(cache).get("tomes", {})
    sortie = {}
    for f in fichiers:
        try:
            e = d.get(str(f))
            if e and e.get("cle") == _cle(f):
                sortie[Path(f).name] = e["stats"]
        except OSError:
            continue
    return sortie


def reference_choisie(cache: Path, serie: str):
    return (_lire_cache(cache).get("references") or {}).get(serie)


def choisir_reference(cache: Path, serie: str, ref):
    """ref : None (le groupe le plus nombreux), « groupe:B » ou « tome:Tome 07.cbz »."""
    with _VERROU_CACHE:
        d = _lire_cache(cache)
        refs = d.setdefault("references", {})
        if ref:
            refs[serie] = ref
        else:
            refs.pop(serie, None)
        _ecrire_cache(cache, d)


# ---------------- comparaison des tomes ----------------
def _vecteur(s: dict):
    """Position d'un tome dans l'espace (encre, blanc, teinte), chaque axe divisé par l'écart qui se voit : 1 = différence visible."""
    return np.array([s["encre"] / ECART_ENCRE, s["blanc"] / ECART_BLANC, chroma(s["teinte_encre"]) / ECART_TEINTE,
                     chroma(s["teinte_papier"]) / (2 * ECART_TEINTE)])


def _distance(a: dict, b: dict) -> float:
    return float(np.max(np.abs(_vecteur(a) - _vecteur(b))))


def grouper(stats: dict) -> list[list[str]]:
    """Regroupe les tomes qui se ressemblent (différence invisible à l'écran), par proximité d'encre d'abord. Le plus gros groupe en premier."""
    ordre = sorted(stats, key=lambda n: (stats[n]["encre"], stats[n]["blanc"]))
    groupes = []
    for nom in ordre:
        for g in groupes:
            if all(_distance(stats[nom], stats[m]) < 1 for m in g):
                g.append(nom)
                break
        else:
            groupes.append([nom])
    groupes.sort(key=lambda g: (-len(g), float(np.mean([stats[n]["encre"] for n in g]))))
    return groupes


def calage(tome: dict, reference: dict) -> dict:
    """Trois repères qui ramènent le tome au niveau de la référence : son noir le plus sombre (b), son noir habituel (e) et son blanc (w) deviennent
    ceux de la référence (b1, e1, w1), le reste suit en ligne droite entre ces repères (optimiser._caler). Ainsi le plancher ET le noir médian
    tombent là où ils tombent dans les autres tomes, pas seulement l'un des deux."""
    return {"b0": round(float(tome["noir"]), 1), "e0": round(float(tome["encre"]), 1), "w0": round(float(tome["blanc"]), 1),
            "b1": round(float(reference["noir"]), 1), "e1": round(float(reference["encre"]), 1), "w1": round(float(reference["blanc"]), 1)}


def ecarts(tome: dict, reference: dict) -> list[str]:
    """Ce qui distingue le tome de la référence (vide : il lui ressemble)."""
    r = []
    if abs(tome["encre"] - reference["encre"]) >= ECART_ENCRE:
        r.append("noirs plus clairs" if tome["encre"] > reference["encre"] else "noirs plus profonds")
    if abs(tome["blanc"] - reference["blanc"]) >= ECART_BLANC:
        r.append("papier plus gris" if tome["blanc"] < reference["blanc"] else "papier plus blanc")
    if chroma(tome["teinte_encre"]) - chroma(reference["teinte_encre"]) >= ECART_TEINTE or \
            chroma(tome["teinte_papier"]) - chroma(reference["teinte_papier"]) >= 2 * ECART_TEINTE:
        t = tome["teinte_encre"] if chroma(tome["teinte_encre"]) >= ECART_TEINTE else tome["teinte_papier"]
        r.append("teinte " + nom_teinte(t))
    return r


def _moyenne(stats, noms) -> dict:
    return {"noir": float(np.median([stats[n]["noir"] for n in noms])), "encre": float(np.median([stats[n]["encre"] for n in noms])),
            "blanc": float(np.median([stats[n]["blanc"] for n in noms])),
            "teinte_encre": np.median([stats[n]["teinte_encre"] for n in noms], axis=0).tolist(),
            "teinte_papier": np.median([stats[n]["teinte_papier"] for n in noms], axis=0).tolist()}


def resumer(stats: dict, libelles: dict, reference=None) -> dict:
    """Analyse d'une série à partir des mesures {nom de fichier: mesures}.
    -> {"groupes": [{"id", "tomes", "resume"}], "reference": {"ref", "libelle", "mesures"}, "tomes": [{"fichier", "libelle", "groupe", "ecarts",
    "a_uniformiser", "calage", ...mesures}], "a_uniformiser": [fichiers], "proposition": texte}.
    `reference` : « groupe:B », « tome:<fichier> » ou None (le groupe le plus nombreux)."""
    utiles = {n: s for n, s in stats.items() if s.get("pages")}
    if not utiles:
        return {"groupes": [], "tomes": [], "a_uniformiser": [], "reference": None, "proposition": ""}
    groupes = grouper(utiles)
    ids = {}
    for i, g in enumerate(groupes):
        for n in g:
            ids[n] = chr(65 + i) if i < 26 else str(i)
    ref_nom, ref_mesures, ref_libelle = None, None, ""
    if reference and str(reference).startswith("tome:") and str(reference)[5:] in utiles:
        ref_nom = str(reference)[5:]
        ref_mesures, ref_libelle = utiles[ref_nom], libelles.get(ref_nom, ref_nom)
    elif reference and str(reference).startswith("groupe:") and any(ids[g[0]] == str(reference)[7:] for g in groupes):
        g = next(g for g in groupes if ids[g[0]] == str(reference)[7:])
        ref_mesures, ref_libelle = _moyenne(utiles, g), f"groupe {ids[g[0]]}"
    else:
        reference = None
    if ref_mesures is None:
        ref_mesures, ref_libelle = _moyenne(utiles, groupes[0]), f"groupe {ids[groupes[0][0]]}"
        reference = f"groupe:{ids[groupes[0][0]]}"
    tomes, a_faire = [], []
    for nom in sorted(utiles, key=lambda n: libelles.get(n, n)):
        s = utiles[nom]
        e = ecarts(s, ref_mesures)
        t = {"fichier": nom, "libelle": libelles.get(nom, nom), "groupe": ids[nom], "ecarts": e, "a_uniformiser": bool(e),
             "noir": s["noir"], "encre": s["encre"], "blanc": s["blanc"], "teinte": nom_teinte(s["teinte_encre"]),
             "chroma": round(chroma(s["teinte_encre"]), 1), "calage": calage(s, ref_mesures),
             "couleur_encre": _hex(s["encre"], s["teinte_encre"]), "couleur_papier": _hex(s["blanc"], s["teinte_papier"])}
        tomes.append(t)
        if e:
            a_faire.append(nom)
    resume_groupes = []
    for g in groupes:
        m = _moyenne(utiles, g)
        decrit = [f"noir {round(m['encre'])}", f"blanc {round(m['blanc'])}", "teinte " + nom_teinte(m["teinte_encre"])]
        resume_groupes.append({"id": ids[g[0]], "tomes": sorted(g, key=lambda n: libelles.get(n, n)), "resume": " · ".join(decrit)})
    texte = ""
    if a_faire:
        causes = sorted({c for t in tomes if t["a_uniformiser"] for c in t["ecarts"]})
        texte = (f"{len(a_faire)} tome{'s' if len(a_faire) > 1 else ''} sur {len(tomes)} ne ressemble{'nt' if len(a_faire) > 1 else ''} pas à {ref_libelle} "
                 f"({', '.join(causes)}) : ✨ Uniformiser les ramène au même noir, au même blanc et sans teinte.")
    return {"groupes": resume_groupes, "tomes": tomes, "a_uniformiser": a_faire, "proposition": texte,
            "reference": {"ref": reference, "libelle": ref_libelle, "mesures": {k: (round(v, 1) if isinstance(v, float) else v)
                                                                               for k, v in ref_mesures.items() if k in ("noir", "encre", "blanc")}}}


def calage_du_tome(stats: dict, fichier: str, reference=None):
    """Le calage d'un tome d'après les mesures de la série et la référence retenue ; None si le tome ou la série n'est pas mesuré."""
    utiles = {n: s for n, s in stats.items() if s.get("pages")}
    if fichier not in utiles:
        return None
    groupes = grouper(utiles)
    ids = {n: chr(65 + i) for i, g in enumerate(groupes) for n in g}
    if reference and str(reference).startswith("tome:") and str(reference)[5:] in utiles:
        ref = utiles[str(reference)[5:]]
    elif reference and str(reference).startswith("groupe:") and any(ids[g[0]] == str(reference)[7:] for g in groupes):
        ref = _moyenne(utiles, next(g for g in groupes if ids[g[0]] == str(reference)[7:]))
    else:
        ref = _moyenne(utiles, groupes[0])
    return calage(utiles[fichier], ref)


# ---------------- analyse d'une série en arrière-plan ----------------
def etat(serie):
    with _VERROU:
        return dict(_ETAT.get(serie) or {})


def lancer(serie, fichiers, cache: Path, fini=None) -> bool:
    """Mesure chaque tome qui ne l'est pas encore (ou a changé) en arrière-plan ; les mesures vont dans `cache` (data/uniformite.json)."""
    fichiers = [Path(f) for f in fichiers]
    with _VERROU:
        if (_ETAT.get(serie) or {}).get("en_cours"):
            return False
        _ETAT[serie] = {"en_cours": True, "fait": 0, "total": len(fichiers), "message": "Mesure des tomes…"}

    def travail():
        msg, erreurs = "", 0
        try:
            for f in fichiers:
                try:
                    en_memoire = stats_en_memoire(cache, [f])
                    if f.name not in en_memoire:
                        s = mesurer_tome(f)
                        with _VERROU_CACHE:
                            d = _lire_cache(cache)
                            d.setdefault("tomes", {})[str(f)] = {"cle": _cle(f), "stats": s}
                            _ecrire_cache(cache, d)
                except Exception as e:
                    erreurs += 1
                    logger.warning("Uniformité de %s : %s", f, e)
                with _VERROU:
                    _ETAT[serie]["fait"] += 1
            msg = f"{len(fichiers)} tome(s) mesuré(s)" + (f", {erreurs} illisible(s)" if erreurs else "")
        except Exception as e:
            msg = f"Erreur : {e}"
        with _VERROU:
            _ETAT[serie].update(en_cours=False, message=msg)
        logger.info("Uniformité de « %s » : %s", serie, msg)
        if fini:
            fini()
    threading.Thread(target=travail, daemon=True).start()
    return True
