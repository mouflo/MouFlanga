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


_GENERIQUES = {"fr", "vf", "cbz", "cbr", "manga", "digital", "scan", "team", "the"}


def equipe_torrent(titre: str) -> str:
    """Équipe d'un nom de torrent : « … (PRiNTER-PapriKa+) » ou « One.Piece.T101.FR.[CBZ]-TONER-Paprika » → « TONER-Paprika »."""
    e = equipe_du_nom(titre)
    if e:
        return e
    m = re.search(r"\]\s*-\s*([A-Za-z][\w+-]{2,40})\s*$|-([A-Za-z][A-Za-z0-9+]{2,20}(?:-[A-Za-z0-9+]{2,20})?)\s*$", (titre or "").strip())
    g = (m.group(1) or m.group(2)) if m else ""
    return g if g and not _MOTS_PAS_EQUIPE.search(g) else ""


def analyser_saisie(texte: str, origine: str = ""):
    """Ce qu'on a tapé à la main -> (équipe, origine). Un nom de torrent ou de fichier collé à la place de l'équipe
    (« Video Girl - Ai (01-15) (Katsura) (2008) [Digital-1482] (PapriKa+) [CBZ] ») donne l'équipe qu'il contient
    (« PapriKa+ ») et le nom complet comme origine, au lieu d'être coupé et rangé comme équipe."""
    texte, origine = (texte or "").strip(), (origine or "").strip()
    if len(texte) > 30 or re.search(r"[()\[\]]|\.cbz|\.cbr|\.zip", texte, re.I):
        return equipe_torrent(texte)[:60], origine or ("Torrent : " + texte)[:200]
    return texte[:60], origine[:200]


def mots_equipe(equipe: str) -> set:
    """« PRiNTER-PapriKa+ » → {"printer", "paprika"} (sans casse, sans « + », mots génériques retirés)."""
    return {m for m in re.split(r"[^a-z0-9]+", (equipe or "").lower()) if len(m) >= 4 and m not in _GENERIQUES}


def meme_equipe(a: str, b: str) -> bool:
    """« PRiNTER-PapriKa+ » ≈ « TONER-Paprika » (un mot en commun : « paprika »)."""
    return bool(mots_equipe(a) & mots_equipe(b))


def lire(infos: dict) -> dict:
    d = infos.get("provenance") or {}
    return d if isinstance(d, dict) else {}


def noter(infos: dict, tome, equipe: str, origine: str, manuel: bool = False, ecrase: bool = False) -> bool:
    """Garde la provenance d'un tome dans le dictionnaire des infos. Renvoie True si quelque chose a changé."""
    cle = str(int(tome))
    d = lire(infos)
    deja = d.get(cle)
    if deja and deja.get("origine") and not (manuel and ecrase) and (deja.get("manuel") or not ecrase):
        return False                      # déjà connue (une note à la main ne se remplace pas toute seule, mais une nouvelle saisie à la main la remplace)
    if not equipe and not origine:
        return False
    d[cle] = {"equipe": equipe or (deja or {}).get("equipe", ""), "origine": origine, "date": time.strftime("%Y-%m-%d"),
              "manuel": bool(manuel)}
    infos["provenance"] = d
    return True
