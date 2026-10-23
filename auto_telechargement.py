"""
🤖 Téléchargement automatique d'une série, à la demande (bouton de la page Télécharger → Torrents).

Choisit, parmi les résultats déjà jugés par le profil de la série (refusés écartés), les torrents qui apportent les tomes qu'on n'a pas :
français seulement, avec des sources, les mieux notés d'abord (score du profil), puis ceux qui couvrent le plus de tomes manquants, puis les
plus partagés. Un tome n'est jamais pris deux fois. Rien n'est jamais remplacé : les torrents sont envoyés en mode « ajouter seulement les manquants ».
"""
import suivi

MAX_TORRENTS = 40


def tomes_couverts(r: dict, attendus) -> set:
    """Tomes qu'un résultat apporte d'après son nom ; une intégrale sans numéros couvre tous les tomes attendus (si on les connaît)."""
    t = suivi.tomes_du_titre(r.get("titre") or "")
    if not t and "Intégrale" in (r.get("badges") or []) and attendus:
        t = set(range(1, int(attendus) + 1))
    return t


def plan(resultats: list, possedes: set, attendus=None) -> dict:
    """{torrents: [résultat + `tomes` apportés], manquants: [tomes que rien ne couvre]} ; `resultats` vient de torrents.chercher."""
    possedes = set(possedes or ())
    candidats = []
    for r in resultats:
        if r.get("rejet") or not r.get("sources") or not r.get("lien") or "🇫🇷 FR" not in (r.get("badges") or []):
            continue
        c = tomes_couverts(r, attendus) - possedes
        if c:
            candidats.append((r, c))
    voulus = set(range(1, int(attendus) + 1)) - possedes if attendus else set().union(*[c for _, c in candidats]) if candidats else set()
    restants, choisis = set(voulus), []
    while restants and len(choisis) < MAX_TORRENTS:
        dispo = [(r, c & restants) for r, c in candidats if c & restants]
        if not dispo:
            break
        r, c = max(dispo, key=lambda x: (x[0].get("score", 0), len(x[1]), x[0].get("sources", 0)))
        choisis.append({**r, "tomes": sorted(c)})
        restants -= c
    return {"torrents": choisis, "manquants": sorted(restants) if attendus else []}
