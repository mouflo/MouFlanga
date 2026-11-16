"""
Chapitres automatiques : à quel point peut-on se fier à un sommaire lu tout seul, et où commence vraiment chaque chapitre.

Trois outils, sans rien écrire nulle part (l'appli décide quoi en faire) :

1. `confiance(lu)` : le niveau d'un sommaire, pour ne montrer à la personne que ce qui mérite son œil.
   - « valide »     : elle l'a validé, saisi ou corrigé à la main. On n'y touche JAMAIS.
   - « sur »        : les chapitres viennent des noms des images (« 077.jpg » = page 77) : exact par construction.
   - « probable »   : sommaire imprimé lu en entier ; « confirmé » quand les numéros de page imprimés disent la même chose.
   - « a_verifier » : pages estimées, chapitres devinés d'après les pages d'ouverture, numéros qui ne se suivent pas…
   - « aucun »      : pas de chapitres.

2. `relever(...)` puis `confirmer(...)` : la place de chaque chapitre vérifiée par les numéros imprimés en bas des pages.
   Le sommaire dit « chapitre 12, page 77 ». On lit les numéros imprimés des pages du tome ; chaque page numérotée
   « vote » pour l'image où doit tomber la page 77, en comptant une double page pour deux pages. Mesuré sur 224 chapitres
   de tomes validés à la main : quand le lecteur de sommaire et les votes disent la même image, c'est juste 93 fois sur
   100 ; quand ils diffèrent et que les votes sont nets, ce sont les votes qui ont raison 14 fois sur 15.
   ATTENTION (dit par l'utilisatrice le 16/11/2026) : ses validations à la main ne sont PAS une vérité, elle a pu se tromper
   (souvent la page qui porte le titre, qui n'est pas toujours la première du chapitre). Ces chiffres ne valent donc pas
   grand-chose. La règle : le sommaire donne la page, les numéros imprimés disent quelle image porte cette page, c'est tout.
   Une place posée d'après des votes nets est donc « confirmée », pas « à vérifier ».

3. `nommer(...)` : les titres vides reçoivent le titre officiel (fiche de la série) ou le nom régulier de la série
   (« Trick 12 ») appris sur ses autres tomes. Un vrai titre déjà lu n'est jamais remplacé.
"""
import io
import re
from collections import Counter

import titres_chapitres

VERSION = 1                     # version de la confirmation (gardée avec le sommaire : on ne refait pas le relevé pour rien)
SEUIL_DOUBLE = 1.1              # largeur / hauteur au-delà de laquelle une image est une double page (2 pages imprimées)
RAYON = 40                      # un numéro imprimé ne vote que pour les chapitres à moins de 40 pages de lui
VOTES_MINI = 2                  # il faut au moins deux pages d'accord pour retenir une place
ECART_SUR = 5                   # une place déplacée de plus de 5 images par les numéros de page reste « à vérifier »
ANCRES_MINI = 4                 # pages d'accord qu'il faut pour le calage d'ensemble du tome

SOURCES_DEVINEES = ("pages d'ouverture", "pages d'équipe")     # chapitres devinés sans sommaire : toujours à vérifier
SOURCE_SURE = "noms des images"

LIBELLES = {"valide": "validé par toi", "sur": "sûr", "probable": "probable", "a_verifier": "à vérifier", "aucun": "pas de chapitres"}
PASTILLES = {"valide": "✅", "sur": "✅", "probable": "🟡", "a_verifier": "🟠", "aucun": "⚪"}


def verrouille(lu) -> bool:
    """Vrai si la personne a validé, saisi ou corrigé ce sommaire : plus rien d'automatique n'y touche."""
    return bool(lu and (lu.get("valide_le") or lu.get("saisie") or lu.get("manuel")))


def imprime(lu) -> bool:
    """Vrai si les chapitres viennent d'un sommaire imprimé (la « page » de chaque chapitre est alors une page imprimée)."""
    return bool(lu and lu.get("chapitres") and not lu.get("source") and not lu.get("fichier"))


# ───────────────────────────── Numéros de page imprimés ─────────────────────────────

def cumul(ratios) -> list:
    """Pour chaque image, le nombre de pages imprimées qui la précèdent (une double page en compte deux)."""
    out, n = [], 0
    for r in ratios:
        out.append(n)
        n += 2 if (r or 0) > SEUIL_DOUBLE else 1
    return out


def _image_de(page, depart, ratios, cum):
    """Image qui porte la page imprimée `page`, si l'image 0 porte la page `depart` (peut être négatif), sinon None."""
    for j, c in enumerate(cum):
        p0 = depart + c
        if p0 == page or ((ratios[j] or 0) > SEUIL_DOUBLE and p0 + 1 == page):
            return j
        if p0 > page:
            break
    return None


def place_par_numeros(ratios, folios, page, rayon=RAYON, mini=VOTES_MINI):
    """Image où tombe la page imprimée `page`, d'après les pages numérotées voisines.
    Renvoie (image ou None, nombre de pages d'accord, nombre de pages qui ont voté)."""
    cum = cumul(ratios)
    votes = Counter()
    for i, f in folios.items():
        i = int(i)
        if i >= len(cum) or abs(page - f) > rayon:
            continue
        cible = _image_de(page, f - cum[i], ratios, cum)
        if cible is not None:
            votes[cible] += 1
    if not votes:
        return None, 0, 0
    image, n = votes.most_common(1)[0]
    return (image if n >= mini else None), n, sum(votes.values())


def place_globale(ratios, folios, page):
    """Même question, avec un seul calage pour tout le tome (celui que le plus de pages numérotées confirment)."""
    cum = cumul(ratios)
    calages = Counter(f - cum[int(i)] for i, f in folios.items() if int(i) < len(cum))
    if not calages:
        return None
    depart, n = calages.most_common(1)[0]
    if n < ANCRES_MINI:
        return None
    return _image_de(page, depart, ratios, cum)


def relever(lire_page, nb_pages, numero_imprime, arret=None, avance=None) -> dict:
    """Forme (largeur / hauteur) de chaque image et numéro imprimé des pages simples. Lent (une lecture par page) : à lancer
    en fond. `lire_page(i)` renvoie les octets de l'image i ; `numero_imprime(octets)` le numéro lu, ou None.
    Renvoie {"ratios": [...], "folios": {image: numéro}} ; None si `arret()` devient vrai."""
    from PIL import Image
    ratios, folios = [], {}
    for i in range(nb_pages):
        if arret and arret():
            return None
        try:
            octets = lire_page(i)
            w, h = Image.open(io.BytesIO(octets)).size
        except Exception:
            ratios.append(0)                               # image illisible : comptée comme une page simple, sans numéro
            continue
        ratios.append(round(w / h, 3) if h else 0)
        if w <= h * 1.05:                                  # les doubles pages n'ont pas de numéro fiable
            try:
                n = numero_imprime(octets)
            except Exception:
                n = None
            if n is not None:
                folios[i] = n
        if avance:
            avance(i + 1, nb_pages)
    return {"ratios": ratios, "folios": folios}


def confirmer(chapitres, ratios, folios) -> dict:
    """Compare la place de chaque chapitre (son « image ») à ce que disent les numéros de page imprimés, et marque
    les chapitres EN PLACE :
      - même image des deux côtés                         → `confirme: True` (et plus de marque « estimee ») ;
      - votes nets et unanimes pour une AUTRE image        → l'image des numéros de page est prise (ils font foi : le sommaire dit
        « page 77 », le chapitre commence sur l'image qui porte la page 77, même si le titre est écrit sur une autre), l'ancienne
        est gardée dans `image_lue`, `corrige: True` et `confirme: True` : ce n'est plus « à vérifier » ;
      - sinon rien ne change.
    Renvoie le bilan {"confirmes", "corriges", "sans_avis", "total"}."""
    bilan = {"confirmes": 0, "corriges": 0, "sans_avis": 0, "total": 0}
    for c in chapitres or []:
        page = c.get("page")
        if not isinstance(page, int) or isinstance(page, bool) or c.get("special"):
            continue
        bilan["total"] += 1
        c.pop("confirme", None)
        image, n, total = place_par_numeros(ratios, folios, page)
        if image is None:
            bilan["sans_avis"] += 1
            continue
        lue = c.get("image")
        if image == lue:
            c["confirme"] = True
            c.pop("estimee", None)
            bilan["confirmes"] += 1
            continue
        net = n >= 3 and n >= 0.6 * total
        if net and place_globale(ratios, folios, page) == image:
            if lue is not None:
                c["image_lue"] = lue
            c["image"] = image
            c["corrige"] = True                             # pour information : la place vient des numéros de page, qui font foi
            if lue is None or abs(image - lue) <= ECART_SUR:
                c["confirme"] = True
            # écart plus grand : c'est peut-être la page du sommaire qui a été mal lue (« 107 » pour 151) : reste « à vérifier »
            c.pop("estimee", None)
            bilan["corriges"] += 1
        else:
            bilan["sans_avis"] += 1
    return bilan


# ───────────────────────────── Confiance d'un sommaire ─────────────────────────────

def _defauts(chapitres) -> list:
    """Ce qui cloche dans une liste de chapitres, en clair (liste vide = rien à signaler)."""
    raisons = []
    sans_image = [c for c in chapitres if c.get("image") is None]
    estimes = [c for c in chapitres if c.get("estimee") and c.get("image") is not None]
    corriges = [c for c in chapitres if c.get("corrige") and not c.get("confirme")
                and (c.get("image_lue") is None or c.get("image") is None or abs(c["image"] - c["image_lue"]) > ECART_SUR)]
    if sans_image:
        raisons.append(f"{len(sans_image)} chapitre{'s' if len(sans_image) > 1 else ''} sans page")
    if estimes:
        raisons.append(f"{len(estimes)} page{'s' if len(estimes) > 1 else ''} estimée{'s' if len(estimes) > 1 else ''}")
    if corriges:
        raisons.append(f"{len(corriges)} place{'s' if len(corriges) > 1 else ''} corrigée{'s' if len(corriges) > 1 else ''} "
                       "d'après les numéros de page")
    images = [c["image"] for c in chapitres if c.get("image") is not None]
    if any(b <= a for a, b in zip(images, images[1:])):
        raisons.append("des chapitres ne sont pas dans l'ordre des pages")
    nums = []
    for c in chapitres:
        if c.get("special"):
            continue
        try:
            nums.append(float(c.get("num")))
        except (TypeError, ValueError):
            pass
    entiers = [n for n in nums if n.is_integer()]
    if len(entiers) >= 2 and any(b - a != 1 for a, b in zip(entiers, entiers[1:])):
        raisons.append("les numéros de chapitre ne se suivent pas")
    return raisons


def douteux(lu) -> list:
    """Numéros (ou rangs) des chapitres qu'il vaut mieux regarder : sans page, page estimée, place corrigée."""
    out = []
    for i, c in enumerate((lu or {}).get("chapitres") or []):
        if c.get("image") is None or c.get("estimee") or (c.get("corrige") and not c.get("confirme") and c.get("image_lue") is not None
                                                          and abs(c["image"] - c["image_lue"]) > ECART_SUR):
            out.append(c.get("num") if c.get("num") is not None else i + 1)
    return out


def confiance(lu) -> dict:
    """Niveau de confiance d'un sommaire : {"niveau", "libelle", "pastille", "raisons", "chapitres", "confirmes"}."""
    chapitres = (lu or {}).get("chapitres") or []
    confirmes = sum(1 for c in chapitres if c.get("confirme"))

    def rendu(niveau, raisons=()):
        return {"niveau": niveau, "libelle": LIBELLES[niveau], "pastille": PASTILLES[niveau], "raisons": list(raisons),
                "chapitres": len(chapitres), "confirmes": confirmes}

    if verrouille(lu):
        return rendu("valide")
    if not chapitres:
        return rendu("aucun")
    defauts = _defauts(chapitres)
    source = (lu or {}).get("source") or ""
    if source == SOURCE_SURE:
        return rendu("a_verifier", defauts) if defauts else rendu("sur", ["chapitres donnés par les noms des images"])
    if source in SOURCES_DEVINEES:
        return rendu("a_verifier", [f"chapitres devinés d'après les {source} (pas de sommaire lu)"] + defauts)
    if defauts:
        return rendu("a_verifier", defauts)
    if lu.get("fichier"):
        return rendu("probable", ["chapitres repris du fichier"])
    avec_page = [c for c in chapitres if isinstance(c.get("page"), int) and not c.get("special")]
    if avec_page and all(c.get("confirme") for c in avec_page):
        return rendu("probable", ["places confirmées par les numéros de page imprimés"])
    if confirmes:
        return rendu("probable", [f"{confirmes} place{'s' if confirmes > 1 else ''} sur {len(chapitres)} "
                                  "confirmée" + ("s" if confirmes > 1 else "") + " par les numéros de page"])
    return rendu("probable", ["sommaire imprimé lu en entier"])


def bilan_serie(sommaires, tomes) -> dict:
    """Résumé pour une série : combien de tomes par niveau, et lesquels attendent un coup d'œil.
    `tomes` = numéros des tomes présents. Renvoie {"total", "comptes": {niveau: n}, "a_verifier": [tomes], "aucun": [tomes],
    "par_tome": {tome: confiance}}."""
    comptes = Counter()
    par_tome, a_verifier, aucun = {}, [], []
    for t in sorted(tomes, key=_ordre):
        c = confiance((sommaires or {}).get(_cle(t)))
        par_tome[_cle(t)] = c
        comptes[c["niveau"]] += 1
        if c["niveau"] == "a_verifier":
            a_verifier.append(t)
        elif c["niveau"] == "aucun":
            aucun.append(t)
    for t, raison in _doublons_entre_tomes(sommaires, sorted(tomes, key=_ordre)):
        c = par_tome[_cle(t)]
        if c["niveau"] == "valide":
            continue                                    # validé à la main : on n'y touche pas, même pour le signaler
        if c["niveau"] != "a_verifier":
            comptes[c["niveau"]] -= 1
            comptes["a_verifier"] += 1
            c.update(niveau="a_verifier", libelle=LIBELLES["a_verifier"], pastille=PASTILLES["a_verifier"])
            a_verifier.append(t)
        c["raisons"] = [raison] + [r for r in c["raisons"] if r != raison]
    a_verifier.sort(key=_ordre)
    return {"total": len(par_tome), "comptes": {k: v for k, v in comptes.items() if v}, "a_verifier": a_verifier, "aucun": aucun,
            "par_tome": par_tome}


def _numeros(lu) -> list:
    """[(numéro entier, chapitre)] des chapitres numérotés d'un sommaire, dans l'ordre."""
    out = []
    for c in (lu or {}).get("chapitres") or []:
        if c.get("special"):
            continue
        try:
            n = float(c.get("num"))
        except (TypeError, ValueError):
            continue
        if n.is_integer():
            out.append((int(n), c))
    return out


def _doublons_entre_tomes(sommaires, tomes) -> list:
    """Un même numéro de chapitre à la fin d'un tome et au début du suivant (« chapitre 31 » à la fin du tome 2, estimé, et au début du
    tome 3) : l'un des deux est faux. Renvoie [(tome à regarder, raison)] : le tome dont le chapitre en double est le moins sûr
    (page estimée, corrigée, sans page, non confirmée), sinon le second. On signale seulement : rien n'est modifié."""
    out = []
    for a, b in zip(tomes, tomes[1:]):
        na, nb = _numeros((sommaires or {}).get(_cle(a))), _numeros((sommaires or {}).get(_cle(b)))
        if not na or not nb or nb[0][0] > na[-1][0]:
            continue
        if nb[0][0] <= 1 or len({n for n, _ in nb} & {n for n, _ in na}) > max(2, len(nb) // 2):
            continue                                    # numérotation qui repart à 1 à chaque tome, ou même sommaire relu : pas un doublon
        num = nb[0][0]
        en_a = next((c for n, c in na if n == num), na[-1][1])
        fragile = lambda c: c.get("image") is None or c.get("estimee") or c.get("corrige")
        if verrouille((sommaires or {}).get(_cle(b))) or (fragile(en_a) and not fragile(nb[0][1])):
            out.append((a, f"le chapitre {num} est aussi au début du tome {_cle(b)}"))
        else:
            out.append((b, f"le chapitre {num} est déjà dans le tome {_cle(a)}"))
    return out


def _cle(tome) -> str:
    """Clé d'un tome dans le dictionnaire des sommaires (« 3 », « 3.5 »)."""
    try:
        f = float(tome)
        return str(int(f)) if f.is_integer() else str(f)
    except (TypeError, ValueError):
        return str(tome)


def _ordre(tome):
    try:
        return (0, float(tome))
    except (TypeError, ValueError):
        return (1, 0.0)


def phrase(bilan) -> str:
    """« 📑 Chapitres : 30 sûrs · 5 probables · 2 à vérifier (T4, T7) » : la ligne courte de la fiche."""
    c = bilan.get("comptes") or {}
    surs = c.get("valide", 0) + c.get("sur", 0)
    parts = []
    if surs:
        parts.append(f"{surs} sûr{'s' if surs > 1 else ''}")
    if c.get("probable"):
        parts.append(f"{c['probable']} probable{'s' if c['probable'] > 1 else ''}")
    if c.get("a_verifier"):
        parts.append(f"{c['a_verifier']} à vérifier ({plages(bilan.get('a_verifier') or [])})")
    if c.get("aucun"):
        parts.append(f"{c['aucun']} sans chapitres")
    return "📑 Chapitres : " + " · ".join(parts) if parts else ""


def plages(tomes) -> str:
    """[1, 2, 3, 7] → « T1-3, T7 »."""
    nums = []
    for t in tomes:
        try:
            f = float(t)
        except (TypeError, ValueError):
            continue
        nums.append(int(f) if f.is_integer() else f)
    nums.sort()
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and isinstance(nums[j], int) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(f"T{nums[i]}-{nums[j]}" if j > i else f"T{nums[i]}")
        i = j + 1
    return ", ".join(out)


# ───────────────────────────── Titres ─────────────────────────────

def nommer(sommaires, tomes, officiels=None) -> list:
    """Titres à poser tout seuls sur les tomes `tomes` (jamais un tome validé, saisi ou corrigé à la main) :
    un titre vide ou qui n'est qu'un numéro reçoit le nom régulier de la série (« Trick 12 », appris sur au moins trois
    chapitres bien nommés), sinon le titre officiel de la fiche. Un vrai titre n'est jamais remplacé.
    Renvoie la liste des changements [{"tome", "num", "avant", "apres"}] (à passer à `titres_chapitres.appliquer`)."""
    officiels = officiels or {}
    voulus = {_cle(t) for t in tomes}
    libres = {t: s for t, s in (sommaires or {}).items() if isinstance(s, dict) and not verrouille(s)}
    mot, nb = titres_chapitres.apprendre({str(t): (s or {}).get("chapitres") or []
                                          for t, s in (sommaires or {}).items() if isinstance(s, dict)})
    changements = []
    for tome in sorted(voulus & set(libres), key=_ordre):
        for c in libres[tome].get("chapitres") or []:
            n = titres_chapitres._entier(c.get("num"))
            if n is None or c.get("special"):
                continue
            actuel = (c.get("titre") or "").strip()
            if actuel and not re.fullmatch(r"\d+", actuel):
                continue                                   # un vrai titre : on n'y touche pas
            cible = titres_chapitres._titre(mot, n) if nb and mot else (officiels.get(n) or "").strip()
            if cible and cible != actuel:
                changements.append({"tome": tome, "num": n, "avant": actuel, "apres": cible})
    return changements
