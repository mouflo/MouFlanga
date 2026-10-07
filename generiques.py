"""
🎵 Génériques des mangas sans anime dans Emby : pour chaque série, l'anime adapté (AniList, saison 1 de préférence)
et son premier opening (AnimeThemes, base tenue par la communauté). Le son est converti en MP3 (volume harmonisé)
et rangé dans « <série>/.theme.mp3 » (caché, suit la série si elle est renommée).
Le générique de l'anime présent dans Emby (choisi avec MouFlopening) reste toujours prioritaire.
Résultats gardés dans data/generiques.json (une série sans anime est revue au bout de 30 jours).
"""
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)
FICHIER_SON = ".theme.mp3"
REVOIR = 30 * 86400
_ETAT = {"fichier": Path("generiques.json"), "en_cours": False, "fait": 0, "total": 0, "ajoutes": 0, "message": ""}
_verrou = threading.Lock()
_session = requests.Session()
_session.headers["User-Agent"] = "MouFlanga (bibliotheque perso)"


def lire():
    try:
        return json.loads(_ETAT["fichier"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _noter(serie, **kw):
    with _verrou:
        d = lire()
        d[serie] = {"date": time.time(), **kw}
        tmp = _ETAT["fichier"].with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, _ETAT["fichier"])


def anime_du_manga(manga_id: int):
    """Anime adapté du manga : série TV la plus ancienne (saison 1), sinon film ou OVA. → (id, titre) ou None."""
    q = "query($i:Int){Media(id:$i){relations{edges{relationType node{id type format title{romaji english} startDate{year month}}}}}}"
    r = _session.post("https://graphql.anilist.co", json={"query": q, "variables": {"i": int(manga_id)}}, timeout=15)
    if r.status_code == 429:
        raise RuntimeError("AniList demande de ralentir")
    edges = (((r.json().get("data") or {}).get("Media") or {}).get("relations") or {}).get("edges") or []
    animes = [e["node"] for e in edges if e["node"]["type"] == "ANIME" and e["relationType"] in ("ADAPTATION", "ALTERNATIVE", "SOURCE")]
    if not animes:
        return None
    rang = {"TV": 0, "TV_SHORT": 1, "ONA": 2, "MOVIE": 3, "OVA": 4, "SPECIAL": 5}
    a = min(animes, key=lambda n: (rang.get(n.get("format"), 9), (n.get("startDate") or {}).get("year") or 9999,
                                   (n.get("startDate") or {}).get("month") or 13))
    return a["id"], (a["title"].get("english") or a["title"].get("romaji") or "")


def opening_1(anime_id: int):
    """Adresse du son du premier opening (OP1) de l'anime chez AnimeThemes, ou None."""
    r = _session.get("https://api.animethemes.moe/anime", params={
        "filter[has]": "resources", "filter[site]": "AniList", "filter[external_id]": int(anime_id),
        "include": "animethemes.animethemeentries.videos.audio"}, timeout=20)
    for a in r.json().get("anime", []):
        ops = [t for t in a.get("animethemes", []) if t.get("type") == "OP"]
        ops.sort(key=lambda t: (t.get("sequence") or 1, len(t.get("slug") or "")))
        for t in ops:
            for e in t.get("animethemeentries", []):
                for v in e.get("videos", []):
                    lien = (v.get("audio") or {}).get("link")
                    if lien:
                        return lien
    return None


def telecharger(lien: str, cible: Path):
    """Télécharge le son et le convertit en MP3 au volume harmonisé (ffmpeg, loudnorm)."""
    with tempfile.TemporaryDirectory() as t:
        src = Path(t) / "op.ogg"
        with _session.get(lien, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(src, "wb") as f:
                for bloc in r.iter_content(1 << 16):
                    f.write(bloc)
        mp3 = Path(t) / "op.mp3"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-vn", "-af", "loudnorm=I=-16:TP=-1.5",
                        "-ar", "44100", "-b:a", "192k", str(mp3)], check=True, timeout=300)
        tmp = cible.with_name(cible.name + ".tmp")
        with open(mp3, "rb") as a, open(tmp, "wb") as b:
            b.write(a.read())
        os.replace(tmp, cible)


def pour_serie(serie: str, dossier: Path, manga_id, forcer=False) -> str:
    """Cherche et pose le générique d'une série. Renvoie « ok », « deja », « aucun_anime », « aucun_theme » ou « inconnu »."""
    if (dossier / FICHIER_SON).exists() and not forcer:
        return "deja"
    if not manga_id:
        _noter(serie, statut="inconnu")
        return "inconnu"
    a = anime_du_manga(manga_id)
    time.sleep(1)                                  # sobre avec AniList
    if not a:
        _noter(serie, statut="aucun_anime")
        return "aucun_anime"
    lien = opening_1(a[0])
    if not lien:
        _noter(serie, statut="aucun_theme", anime=a[1])
        return "aucun_theme"
    telecharger(lien, dossier / FICHIER_SON)
    _noter(serie, statut="ok", anime=a[1], source=lien)
    logger.info("Générique de « %s » : OP1 de « %s »", serie, a[1])
    return "ok"


def tout(series, manga_dir: Path, manga_id_de, deja_dans_emby, envoyer, forcer=False):
    """Toute la bibliothèque, en arrière-plan. series : noms ; manga_id_de(nom) → identifiant AniList du manga."""
    if _ETAT["en_cours"]:
        return False
    a_faire = []
    vus = lire()
    for n in series:
        v = vus.get(n) or {}
        if deja_dans_emby(n) or ((Path(manga_dir) / n / FICHIER_SON).exists() and not forcer):
            continue
        if not forcer and v.get("statut") in ("aucun_anime", "aucun_theme", "inconnu") and time.time() - v.get("date", 0) < REVOIR:
            continue
        a_faire.append(n)
    _ETAT.update(en_cours=True, fait=0, total=len(a_faire), ajoutes=0, message=f"{len(a_faire)} série(s) à vérifier…")

    def travail():
        ajoutes, sans = [], 0
        try:
            for n in a_faire:
                _ETAT["message"] = f"{n}…"
                try:
                    r = pour_serie(n, Path(manga_dir) / n, manga_id_de(n), forcer)
                    if r == "ok":
                        ajoutes.append(n)
                    elif r in ("aucun_anime", "aucun_theme"):
                        sans += 1
                except Exception as e:
                    logger.warning("Générique de %s : %s", n, e)
                    if "ralentir" in str(e):
                        time.sleep(60)
                _ETAT["fait"] += 1
                _ETAT["ajoutes"] = len(ajoutes)
            _ETAT["message"] = f"✅ {len(ajoutes)} générique(s) ajouté(s) ; {sans} série(s) sans anime ou sans générique connu."
            if ajoutes:
                envoyer("🎵 MouFlanga : " + _ETAT["message"] + "\n" + ", ".join(ajoutes[:30]))
        finally:
            _ETAT["en_cours"] = False
    threading.Thread(target=travail, daemon=True).start()
    return True
