"""
Provenance des tomes : d'où vient chaque tome (équipe de scan, torrent, rangement à la main, saisie).

Rangé dans « <série>/.mouflanga-infos.json », clé « provenance » : {"10": {"equipe", "origine", "date", "manuel"}}.
- L'équipe se lit dans le nom d'origine du fichier : « (PRiNTER-PapriKa+) », « (PapriKa+) »… ;
- une note saisie à la main (« manuel ») n'est jamais écrasée par une déduction automatique.
"""
import re
import time

_MOTS_PAS_EQUIPE = re.compile(r"digital|manga|\bfr\b|\bvf\b|scan|\d{3,4}|univers|int[ée]grale|complet|[ée]dition|luxe|tomes?|oda", re.I)


def equipe_du_nom(nom: str) -> str:
    """« One Piece HS - Blue (Oda) (2005) [Digital-1920] (PRiNTER-PapriKa+).cbz » → « PRiNTER-PapriKa+ » ; "" si aucune."""
    for g in reversed(re.findall(r"\(([^()]{2,40})\)", nom or "")):
        g = g.strip()
        if re.search(r"[A-Za-z]{3,}", g) and not _MOTS_PAS_EQUIPE.search(g):
            return g
    return ""


def lire(infos: dict) -> dict:
    d = infos.get("provenance") or {}
    return d if isinstance(d, dict) else {}


def noter(infos: dict, tome, equipe: str, origine: str, manuel: bool = False, ecrase: bool = False) -> bool:
    """Garde la provenance d'un tome dans le dictionnaire des infos. Renvoie True si quelque chose a changé."""
    cle = str(int(tome))
    d = lire(infos)
    deja = d.get(cle)
    if deja and (deja.get("manuel") or not ecrase) and deja.get("origine"):
        return False                      # déjà connue (une note à la main ne se remplace pas toute seule)
    if not equipe and not origine:
        return False
    d[cle] = {"equipe": equipe or (deja or {}).get("equipe", ""), "origine": origine, "date": time.strftime("%Y-%m-%d"),
              "manuel": bool(manuel)}
    infos["provenance"] = d
    return True
