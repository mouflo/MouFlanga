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

import reseau

logger = logging.getLogger(__name__)
FICHIER_SON = ".theme.mp3"
REVOIR = 30 * 86400
_ETAT = {"fichier": Path("generiques.json"), "en_cours": False, "fait": 0, "total": 0, "ajoutes": 0, "message": ""}
_verrou = threading.Lock()
_session = reseau.SESSION             # une seule session pour tout Internet (voir reseau.py)


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
    edges = (((reseau.anilist(q, {"i": int(manga_id)}) or {}).get("Media") or {}).get("relations") or {}).get("edges") or []
    animes = [e["node"] for e in edges if e["node"]["type"] == "ANIME" and e["relationType"] in ("ADAPTATION", "ALTERNATIVE", "SOURCE")]
    if not animes:
        return None
    rang = {"TV": 0, "TV_SHORT": 1, "ONA": 2, "MOVIE": 3, "OVA": 4, "SPECIAL": 5}
    a = min(animes, key=lambda n: (rang.get(n.get("format"), 9), (n.get("startDate") or {}).get("year") or 9999,
                                   (n.get("startDate") or {}).get("month") or 13))
    return a["id"], (a["title"].get("english") or a["title"].get("romaji") or "")


def opening_1(anime_id: int):
    """Adresse du son du premier opening (OP1) de l'anime chez AnimeThemes, ou None."""
    r = reseau.get("https://api.animethemes.moe/anime", params={
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


def themes_de_l_anime(anime_id: int) -> list[dict]:
    """Tous les génériques connus de l'anime chez AnimeThemes (openings puis endings, dans l'ordre), pour les écouter
    et en choisir un : [{"slug": "OP5", "type": "OP", "titre": "Truth", "episodes": "124-142", "lien": …}]."""
    r = reseau.get("https://api.animethemes.moe/anime", params={
        "filter[has]": "resources", "filter[site]": "AniList", "filter[external_id]": int(anime_id),
        "include": "animethemes.song,animethemes.animethemeentries.videos.audio"}, timeout=30)
    sortie = []
    for a in r.json().get("anime", []):
        for t in a.get("animethemes", []):
            if t.get("type") not in ("OP", "ED"):
                continue
            for e in t.get("animethemeentries", []):
                lien = next(((v.get("audio") or {}).get("link") for v in e.get("videos", []) if (v.get("audio") or {}).get("link")), None)
                if lien:
                    sortie.append({"slug": t.get("slug") or t["type"], "type": t["type"], "sequence": t.get("sequence") or 1,
                                   "titre": (t.get("song") or {}).get("title") or "", "episodes": e.get("episodes") or "",
                                   "lien": lien})
                    break
    sortie.sort(key=lambda x: (x["type"] != "OP", x["sequence"], x["slug"]))
    return sortie


def _audio_mouflopening():
    """Module de conversion de MouFlopening (même serveur) et son niveau cible, pour que les génériques des mangas
    aient exactement le même volume que ceux d'Emby ; (None, None) si MouFlopening n'est pas installé ici."""
    base = Path(os.getenv("MOUFLOPENING_DIR", "/opt/mouflopening"))
    f = base / "src" / "audio.py"
    if not f.is_file():
        return None, None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("mouflopening_audio", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        try:
            cible = float(((json.loads((base / "config.json").read_text(encoding="utf-8")).get("audio") or {})
                           .get("target_db")) or mod.REFERENCE_DB)
        except (OSError, ValueError, TypeError):
            cible = mod.REFERENCE_DB
        return mod, cible
    except Exception as e:
        logger.warning("Conversion de MouFlopening inutilisable : %s", e)
        return None, None


def _convertir(src: Path, mp3: Path):
    """MP3 au volume harmonisé : réglage de MouFlopening s'il est là, sinon loudnorm."""
    mod, cible = _audio_mouflopening()
    if mod and mod.convert_to_mp3(src, mp3, cible):
        return
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-vn", "-af", "loudnorm=I=-16:TP=-1.5",
                    "-ar", "44100", "-b:a", "192k", str(mp3)], check=True, timeout=300)


def _poser(mp3: Path, cible: Path):
    tmp = cible.with_name(cible.name + ".tmp")
    with open(mp3, "rb") as a, open(tmp, "wb") as b:
        b.write(a.read())
    os.replace(tmp, cible)


def telecharger(lien: str, cible: Path):
    """Télécharge le son et le convertit en MP3 au volume harmonisé."""
    with tempfile.TemporaryDirectory() as t:
        src = Path(t) / "op.ogg"
        with _session.get(lien, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(src, "wb") as f:
                for bloc in r.iter_content(1 << 16):
                    f.write(bloc)
        mp3 = Path(t) / "op.mp3"
        _convertir(src, mp3)
        _poser(mp3, cible)


def choisir(serie: str, dossier: Path, theme: dict | None, anime: str = "", anime_id=None):
    """Générique choisi à la main (theme = un élément de themes_de_l_anime) ou aucun (None) : la recherche
    automatique n'y touche plus."""
    cible = dossier / FICHIER_SON
    if theme is None:
        cible.unlink(missing_ok=True)
        _noter(serie, statut="muet", manuel=True, anime=anime, anime_id=anime_id)
        logger.info("Générique de « %s » : aucun (choisi à la main)", serie)
        return
    telecharger(theme["lien"], cible)
    _noter(serie, statut="ok", manuel=True, anime=anime, anime_id=anime_id, source=theme["lien"], choix=theme.get("slug"))
    logger.info("Générique de « %s » : %s choisi à la main", serie, theme.get("slug"))


_NORMAL = {"en_cours": False, "fait": 0, "total": 0, "message": ""}


def renormaliser(fichiers):
    """Ramène les génériques déjà posés au niveau de MouFlopening (une fois, en arrière-plan). Ceux qui y sont déjà
    (à 0,5 dB près) ne sont pas réencodés."""
    if _NORMAL["en_cours"]:
        return False
    fichiers = [Path(f) for f in fichiers]
    _NORMAL.update(en_cours=True, fait=0, total=len(fichiers), message=f"{len(fichiers)} générique(s) à vérifier…")

    def travail():
        changes = 0
        try:
            mod, cible = _audio_mouflopening()
            if not mod:
                _NORMAL["message"] = "MouFlopening n'est pas installé sur ce serveur : rien à harmoniser."
                return
            for f in fichiers:
                try:
                    m = mod.measure_gain(f)
                    if m is not None and abs((mod.REFERENCE_DB - m[0]) - cible) >= 0.5:
                        with tempfile.TemporaryDirectory() as t:
                            mp3 = Path(t) / "op.mp3"
                            if mod.convert_to_mp3(f, mp3, cible):
                                _poser(mp3, f)
                                changes += 1
                except Exception as e:
                    logger.warning("Harmonisation de %s : %s", f, e)
                _NORMAL["fait"] += 1
            _NORMAL["message"] = f"✅ {changes} générique(s) ramené(s) à {cible:g} dB ; les autres y étaient déjà."
            logger.info("Génériques des mangas : %s", _NORMAL["message"])
        finally:
            _NORMAL["en_cours"] = False
    threading.Thread(target=travail, daemon=True).start()
    return True


def pour_serie(serie: str, dossier: Path, manga_id, forcer=False) -> str:
    """Cherche et pose le générique d'une série. Renvoie « ok », « deja », « aucun_anime », « aucun_theme » ou « inconnu »."""
    if (lire().get(serie) or {}).get("manuel"):
        return "deja"
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
        _noter(serie, statut="aucun_theme", anime=a[1], anime_id=a[0])
        return "aucun_theme"
    telecharger(lien, dossier / FICHIER_SON)
    _noter(serie, statut="ok", anime=a[1], anime_id=a[0], source=lien)
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
        if v.get("manuel"):                        # générique (ou silence) choisi à la main : jamais remplacé
            continue
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
