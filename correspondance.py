"""
Ce titre est-il celui de cette série ? Les règles de reconnaissance d'un nom, au même endroit pour toutes les sources
(Wikipédia, BnF, Google Books, AniList, MangaDex…), avec les écarts qu'on rencontre vraiment :
- écritures différentes d'un même nom : « Golden Kamuy » / « Golden Kamui », « Kenichi » / « Ken-Ichi », « Ghost » / « Ghosts » ;
- titre français plus long que le nom du dossier : « Red eyes sword : Akame ga Kill ! » pour « Akame ga Kill ! » ;
- autre série de la même famille : « Akame ga Kill ! Zero », « Ken-Ichi, saison 2 », « 21st Century Boys » ne sont PAS
  « Akame ga Kill ! », « Kenichi : le disciple ultime », « 20th Century Boys ».
"""
import re
import unicodedata

import noms_editions

# Mots qui font d'un titre un autre livre que la série elle-même (sauf s'ils sont dans le nom de la série)
MARQUEURS_DERIVES = {"zero", "gaiden", "spin", "off", "spinoff", "prequel", "prequelle", "sequel", "suite", "side", "story", "extra",
                     "artbook", "fanbook", "databook", "guide", "anthologie", "novel", "roman", "light", "memories", "origins",
                     "saison", "season", "party", "episode", "special", "bangai", "coffret", "doors", "returns", "shin", "new", "next",
                     "neo", "hs", "omake", "kai"}
# Mots d'un titre qui ne distinguent rien (article, langue, mot « tome »…)
MOTS_VIDES = {"le", "la", "les", "un", "une", "de", "du", "des", "et", "the", "a", "an", "of", "no", "to", "ga", "wa", "ni",
              "tome", "t", "vol", "volume", "manga", "edition", "originale", "texte", "imprime"}


_TRANSLITTERATION = str.maketrans({"Ø": "O", "ø": "o", "Æ": "AE", "æ": "ae", "Œ": "OE", "œ": "oe", "ß": "ss", "Đ": "D", "đ": "d",
                                   "Ł": "L", "ł": "l", "Þ": "Th", "þ": "th", "Ð": "D", "ð": "d", "ı": "i"})


def simple(texte: str) -> str:
    """Minuscules, sans accents, rien que des lettres et des chiffres séparés par une espace. « L'Attaque » → « attaque »
    (élision), « Kuroko's » → « kurokos » (possessif)."""
    texte = unicodedata.normalize("NFKD", (texte or "").translate(_TRANSLITTERATION)).encode("ascii", "ignore").decode().lower()
    texte = re.sub(r"\b[ldjmnst]['’]", "", texte)
    texte = re.sub(r"(\w)['’]s\b", r"\1s", texte)
    return re.sub(r"[^a-z0-9]+", " ", texte).strip()


def mots_bruts(texte: str) -> list:
    """Les mots tels qu'un moteur de recherche les découpe : « Cat's Eye » → cat, s, eye (sans coller le possessif ni retirer les
    élisions comme le fait simple())."""
    t = unicodedata.normalize("NFKD", (texte or "").translate(_TRANSLITTERATION)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).split()


def jetons(texte: str) -> list:
    return simple(texte).split()


def _distance_max_un(a: str, b: str) -> bool:
    """a et b diffèrent d'une seule lettre (ajoutée, retirée, changée) ou de deux lettres voisines échangées."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        ecarts = [i for i in range(len(a)) if a[i] != b[i]]
        if len(ecarts) == 1:
            return True
        return len(ecarts) == 2 and ecarts[1] == ecarts[0] + 1 and a[ecarts[0]] == b[ecarts[1]] and a[ecarts[1]] == b[ecarts[0]]
    court, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(court) and court[i] == long_[i]:
        i += 1
    return court[i:] == long_[i + 1:]


_ABREVIATIONS = [{"dr", "docteur", "doctor"}, {"st", "saint"}, {"ste", "sainte"}, {"mr", "monsieur", "mister"}, {"mme", "madame"},
                 {"vs", "versus", "contre"}]


def jetons_equivalents(a: str, b: str) -> bool:
    """Deux mots sont-ils le même mot écrit un peu autrement ? Les nombres doivent être identiques ; un mot de 5 lettres ou
    plus peut différer d'une lettre (« kamuy »/« kamui », « ghost »/« ghosts »), à condition de commencer pareil ; une
    abréviation vaut son mot (« Dr Slump » = « Docteur Slump »)."""
    if a == b:
        return True
    if any(a in g and b in g for g in _ABREVIATIONS):
        return True
    if any(c.isdigit() for c in a + b):
        return False
    return len(a) >= 5 and len(b) >= 5 and a[0] == b[0] and _distance_max_un(a, b)


def _vocabulaire(titre: str) -> set:
    """Les mots du titre, plus ceux qu'on obtient en collant deux mots voisins (« ken » + « ichi » → « kenichi »)."""
    j = jetons(titre)
    return set(j) | {a + b for a, b in zip(j, j[1:])}


def contient_nom(titre: str, nom: str, souple: bool = True) -> bool:
    """Tous les mots distinctifs de « nom » sont dans « titre ». Le nom « Ghost » n'est pas dans « Ghost in the Shell »?
    Si : c'est à l'appelant de refuser les autres séries (voir titre_de_la_serie). Ici on ne répond qu'à « les mots y sont »."""
    mots_nom = jetons(nom)
    utiles = [m for m in mots_nom if m not in MOTS_VIDES]           # « The Seven Deadly Sins » / « Seven Deadly Sins »
    mots_nom = utiles or mots_nom
    if not mots_nom:
        return False
    vocab = _vocabulaire(titre)
    reste = [m for m in mots_nom if m not in vocab]
    if not reste:
        return True
    if not souple:
        return False
    return all(any(jetons_equivalents(m, v) for v in vocab) for m in reste)


def mots_en_plus(titre: str, noms) -> list:
    """Mots du titre qui ne viennent d'aucun des noms connus de la série et ne sont pas des mots vides : « red eyes sword zero »
    pour la série « Akame ga Kill ! » (« red eyes sword » est un autre nom connu, « zero » reste). Deux mots voisins qui forment
    un mot connu (« ken » « ichi » pour « kenichi ») comptent pour celui-ci."""
    connus = set()
    for n in noms:
        connus |= set(jetons(n))
    mots = jetons(titre)
    out, i = [], 0
    while i < len(mots):
        m = mots[i]
        if i + 1 < len(mots) and (m + mots[i + 1]) in connus:
            i += 2
            continue
        i += 1
        if m in MOTS_VIDES or m.isdigit() or re.fullmatch(r"t\d+", m):
            continue
        if m in connus or any(jetons_equivalents(m, c) for c in connus):
            continue
        out.append(m)
    return out


def est_derive(titre: str, noms) -> bool:
    """Le titre porte un mot de série dérivée (zero, gaiden, saison…) que ni la série ni ses autres noms n'ont."""
    connus = set()
    for n in noms:
        connus |= set(jetons(n))
    return any(m in MARQUEURS_DERIVES and m not in connus for m in jetons(titre))


def _edition_du_titre(titre: str) -> str:
    """Mention d'édition spéciale d'un titre (Perfect, Deluxe, Intégrale…) ; « Édition originale » n'en est pas une (c'est
    l'édition ordinaire de certains éditeurs : « One Piece - Édition originale - Tome 47 »)."""
    for m in noms_editions.MENTION.finditer(titre or ""):
        if simple(m.group(0)) not in ("edition originale", "originale"):
            return m.group(0)
    return ""


def _parties(titre: str) -> list:
    """Parties d'un titre (« Red eyes sword : Akame ga Kill ! Zero » → deux parties), chacune en mots."""
    return [j for j in (jetons(p) for p in re.split(r"\s*(?::|/|–|—|\s-\s|,)\s*", titre or "")) if j]


def _meme_mots(a: list, b: list) -> bool:
    """Mêmes mots : collés ou non (« ken ichi » = « kenichi »), ou mot à mot à une lettre près (« golden kamuy » = « golden
    kamui »). Un mot de plus (« school rumble z » / « school rumble ») fait deux séries."""
    if not a or not b:
        return False
    if "".join(a) == "".join(b):
        return True
    return len(a) == len(b) and all(jetons_equivalents(x, y) for x, y in zip(a, b))


def _tolerance(noms) -> int:
    """Mots inconnus permis en plus du nom : aucun pour un nom court (« The Breaker » n'est pas « Wind Breaker »)."""
    distinctifs = min((len([m for m in jetons(n) if m not in MOTS_VIDES]) for n in noms), default=0)
    return 0 if distinctifs <= 2 else 1 if distinctifs <= 4 else 2


def titre_de_la_serie(titre: str, noms, autres_series=(), edition: str = "", faibles=()) -> bool:
    """Ce titre de livre / de page / de fiche est-il celui de la série, d'après ses noms (le dossier, AniList, les synonymes) ?
    - un des noms est tout un morceau du titre (« Red eyes sword : Akame ga Kill ! »), ou est dans le titre avec peu de mots
      inconnus en plus (aucun pour un nom court) ;
    - aucun mot de série dérivée en plus (« Zero », « saison 2 », « Shin »…) ;
    - pas le titre d'une autre série de la bibliothèque, plus précise (« Gantz » et le livre « Gantz : Osaka ») ;
    - une édition spéciale (Perfect, Deluxe…) doit être celle de la série, pas une autre.
    « faibles » : morceaux du nom du dossier (« Kuroko's Basket » dans « Kuroko's Basket : Extra Game ») ; ils ne comptent que
    si le titre est exactement l'un d'eux."""
    noms = [n for n in noms if n and jetons(n)]
    if not noms or not jetons(titre):
        return False
    edition_titre = _edition_du_titre(titre)
    edition_serie = edition or next((m.group(0) for n in noms for m in [noms_editions.MENTION.search(n)] if m), "")
    if bool(edition_titre) != bool(edition_serie) or (edition_titre and simple(edition_serie) not in simple(titre)):
        return False
    base = [noms_editions.FIN.sub("", n).strip(" -–:,") or n for n in noms]
    tous = base + [f for f in faibles if f]
    if est_derive(titre, noms):
        return False
    parties = _parties(titre)
    entier = jetons(titre)
    exact = any(_meme_mots(jetons(n), p) for n in base for p in parties + [entier])
    if not exact:
        if not any(contient_nom(titre, n) for n in base):
            return any(_meme_mots(jetons(f), p) for f in faibles if f for p in parties + [entier])
        if len(mots_en_plus(titre, tous)) > _tolerance(base):
            return False
    jt = set(jetons(titre))
    for autre in autres_series or ():                          # « Gantz » ne prend pas le livre « Gantz : Osaka »
        ja = jetons(autre)
        if ja and set(ja) > set(jetons(noms[0])) and all(m in jt for m in ja):
            return False
    return True


def meilleur_nom(titre: str, noms):
    """Le plus long des noms contenus dans le titre (le plus précis), ou None."""
    ok = [n for n in noms if n and contient_nom(titre, n)]
    return max(ok, key=lambda n: len(jetons(n))) if ok else None
