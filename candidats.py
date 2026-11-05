"""
« Quelle série est-ce ? » : les séries qui peuvent correspondre à un dossier, tirées de plusieurs sources, rangées de la plus probable
à la moins probable. Sert à l'écran de choix (fiche d'une série, après un renommage ou une identification douteuse).

Sources : AniList (mangas japonais, coréens, chinois…), Vega Livres et Ankama (catalogues d'éditeurs français, pour les séries que
les bases ne connaissent pas). Une source qui ne répond pas est dite dans `pannes` : ce n'est jamais « rien trouvé ».
Chaque proposition : {source, id, titre, anglais, natif, annee, statut, tomes, chapitres, couverture, lien, editeur, score, raison, ok}.
`ok` = rien ne contredit les fichiers de la série ; `score` sert à ranger.
"""
import ankama
import reseau
import tomes
import vega

LIBELLES = {"anilist": "AniList", "vega": "Vega Livres", "ankama": "Ankama"}
MAX_PROPOSITIONS = 10


def _simple(t):
    return tomes._simple(t or "")


def juger(c: dict, serie: str, tome_max, texte=None) -> dict:
    """Ajoute `score`, `raison` et `ok` à une proposition d'après ce qu'on a (nombre de tomes locaux, nom de la série)."""
    cles = {_simple(serie), _simple(tomes.sans_edition(serie)), _simple(texte)} - {""}
    titres = [_simple(x) for x in (c.get("titre"), c.get("anglais"), c.get("natif"), *(c.get("synonymes") or [])) if x]
    score, raisons, ok = 0, [], True
    if any(k in titres for k in cles):
        score += 50
        raisons.append("même titre")
    elif any(k and k in t for k in cles for t in titres):
        score += 10
        raisons.append("titre voisin")
    tomes_c, chap = c.get("tomes"), c.get("chapitres")
    if tome_max and tomes_c:
        if tomes_c >= tome_max:
            score += 30
            raisons.append(f"{tomes_c} tomes (tu en as {tome_max})")
        else:
            score -= 40
            ok = False
            raisons.append(f"seulement {tomes_c} tome(s) alors que tu en as {tome_max}")
    elif tome_max and chap and chap < tome_max:
        score -= 60
        ok = False
        raisons.append(f"seulement {chap} chapitre(s) pour {tome_max} tomes")
    if c["source"] in ("vega", "ankama"):
        score += 15
        raisons.append("catalogue de l'éditeur français")
    c["score"], c["raison"], c["ok"] = score, " · ".join(raisons), ok
    return c


def proposer(serie: str, tome_max=None, texte=None) -> dict:
    """{"propositions": [...], "pannes": ["AniList", ...]} pour la série (ou pour les mots tapés dans `texte`)."""
    noms = list(dict.fromkeys(n for n in ([texte] if texte else tomes._variantes(serie)) if n))[:3]
    out, pannes = [], []
    vus = set()
    for nom in noms:
        try:
            for m in tomes.chercher_anilist(nom):
                if m["id"] not in vus:
                    vus.add(m["id"])
                    out.append({"source": "anilist", "id": m["id"], "titre": m["titre"], "anglais": m["anglais"], "natif": m["natif"],
                                "annee": m["annee"], "statut": m["statut"], "tomes": m["tomes"], "chapitres": m["chapitres"],
                                "couverture": m["couverture"], "lien": m["lien"], "editeur": "", "format": m.get("format")})
        except reseau.Panne:
            pannes.append("AniList")
            break
    for source, module in (("vega", vega), ("ankama", ankama)):
        for nom in noms:
            try:
                liste = module.tomes_de_la_serie(nom)
            except reseau.Panne:
                pannes.append(LIBELLES[source])
                break
            if liste:
                out.append({"source": source, "id": nom, "titre": nom, "anglais": "", "natif": "", "annee": None, "statut": None,
                            "tomes": max(t["tome"] for t in liste), "chapitres": None, "couverture": "", "lien": liste[0]["url"],
                            "editeur": LIBELLES[source]})
                break
    out = [juger(c, serie, tome_max, texte) for c in out if c.get("format") != "NOVEL"]
    out.sort(key=lambda c: (-c["score"], not c["ok"]))
    return {"propositions": out[:MAX_PROPOSITIONS], "pannes": sorted(set(pannes))}


def y_a_doute(serie: str, st: dict, infos: dict, brut: dict, tome_max=None) -> bool:
    """Faut-il demander à la personne ? Non si elle a déjà choisi, ou si l'identité est sûre : fiche AniList au titre identique et
    compatible avec les tomes, ou série retrouvée telle quelle dans le catalogue d'un éditeur."""
    if infos.get("anilist_choisi") or infos.get("editeur_choisi") or infos.get("aucune_fiche_anilist"):
        return False
    rech = brut.get("recherches") or {}
    if any((rech.get(s) or {}).get("tomes") for s in ("vega", "ankama")):
        return False
    if st.get("anilist") and not st.get("choisi"):
        titres = [_simple(x) for x in (st.get("titre"), st.get("titre_en"), *(st.get("synonymes") or [])) if x]
        cles = {_simple(serie), _simple(tomes.sans_edition(serie))} - {""}
        return not (any(k in titres for k in cles) and not tomes._douteuse(st, serie, tome_max))
    return not st.get("anilist")
