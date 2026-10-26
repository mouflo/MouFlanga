"""
🤖 Téléchargement automatique d'une série, à la demande (bouton de la page Télécharger → Torrents).

Choisit, parmi les résultats déjà jugés par le profil de la série (refusés écartés), les torrents qui apportent les tomes qu'on n'a pas :
français seulement, avec des sources, les mieux notés d'abord (score du profil), puis ceux qui ont assez de sources pour ne pas rester
bloqués, puis ceux qui couvrent le plus de tomes manquants (et le moins de tomes en trop), puis les plus partagés. Un tome n'est jamais pris deux fois. Rien n'est jamais remplacé : les torrents sont envoyés en mode « ajouter seulement les manquants ».
"""
import suivi

MAX_TORRENTS = 40


def tomes_couverts(r: dict, attendus) -> set:
    """Tomes qu'un résultat apporte d'après son nom ; une intégrale sans numéros couvre tous les tomes attendus (si on les connaît)."""
    t = suivi.tomes_du_titre(r.get("titre") or "")
    if not t and "Intégrale" in (r.get("badges") or []) and attendus:
        t = set(range(1, int(attendus) + 1))
    return t


def plan(resultats: list, possedes: set, attendus=None, info=None) -> dict:
    """{torrents: [résultat + `tomes` + `type`], manquants: [tomes que rien ne couvre]} ; `resultats` vient de torrents.chercher.
    type « nouveau » : tomes manquants, rien n'est remplacé ; type « meilleur » : le torrent remplace des tomes en scan par de l'officiel
    (ou mieux notés d'après le profil), et seulement si TOUS les tomes déjà là qu'il apporte méritent d'être remplacés. `info` : voir
    app._infos_suivi (sources par tome, scores, score d'arrêt)."""
    possedes = set(possedes or ())
    candidats = []
    for r in resultats:
        if r.get("rejet") or not r.get("sources") or not r.get("lien"):
            continue
        if "🇫🇷 FR" not in (r.get("badges") or []) and not r.get("profil"):
            continue                                   # ni marqué français, ni jugé acceptable par un profil
        couverts = tomes_couverts(r, attendus)
        neufs = couverts - possedes
        deja = (couverts & possedes) - set((info or {}).get("tomes_en_cours") or ())     # un tome en téléchargement n'est pas à remplacer
        mieux = suivi.tomes_ameliorables(r, deja, info or {}) if deja else set()
        mieux = mieux if mieux and deja <= mieux else set()          # jamais remplacer un tome qui n'a pas besoin de l'être
        if neufs or mieux:
            candidats.append((r, neufs | mieux, bool(mieux)))
    voulus = set(range(1, int(attendus) + 1)) - possedes if attendus else set()
    voulus |= set().union(*[c for _, c, _ in candidats]) if candidats else set()
    restants, choisis = set(voulus), []
    while restants and len(choisis) < MAX_TORRENTS:
        dispo = [(r, c & restants, m, c) for r, c, m in candidats if c & restants]
        if not dispo:
            break
        # même ordre que la surveillance : score, assez de sources, le plus de tomes utiles, le moins de tomes en trop, sources
        r, c, m, _ = max(dispo, key=lambda x: suivi.cle_torrent(x[0], x[1], tomes_couverts(x[0], attendus)))
        choisis.append({**r, "tomes": sorted(c), "type": "meilleur" if m else "nouveau"})
        restants -= c
    return {"torrents": choisis, "manquants": sorted(restants) if attendus else []}
