"""
🧲 Torrents : recherche dans Prowlarr, téléchargement par qBittorrent, puis import habituel dans la bibliothèque.

Circuit (comme Radarr/Sonarr) : catégorie qBittorrent « mouflanga » (créée toute seule) → dossier d'arrivée
« …NOK » ; une fois fini, le contenu est COPIÉ dans la bibliothèque (lien physique quand c'est possible : aucune
place en plus) et importé (tomes, nom, couverture) ; puis qBittorrent déplace le torrent dans « …OK » où il continue
à partager. MouFlanga ne touche qu'aux torrents de sa catégorie, jamais à ceux de Sonarr/Radarr.

Réglages (data/secrets.env, page Réglages → Connexions) : PROWLARR_URL, PROWLARR_API_KEY, QBIT_URL, QBIT_USER,
QBIT_PASSWORD, TORRENTS_NOK, TORRENTS_OK, et facultatif TORRENTS_CHEMINS « chemin_qbittorrent=>chemin_local ».
"""
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import requests

import regles

logger = logging.getLogger(__name__)

CATEGORIE = "mouflanga"
EXT_IMPORT = {".cbz", ".cbr", ".zip", ".rar", ".7z", ".pdf", ".nfo", ".txt", ".jpg", ".jpeg", ".png", ".webp"}
_ETAT = {"fichier": Path("torrents.json")}
_verrou = threading.Lock()


def reglages():
    g = lambda k, d="": os.getenv(k, d).strip()
    return {"prowlarr": g("PROWLARR_URL").rstrip("/"), "prowlarr_cle": g("PROWLARR_API_KEY"),
            "qbit": g("QBIT_URL").rstrip("/"), "qbit_user": g("QBIT_USER"), "qbit_mdp": _mdp(),
            "nok": g("TORRENTS_NOK"), "ok": g("TORRENTS_OK"), "chemins": g("TORRENTS_CHEMINS")}


def _mdp():
    """Mot de passe qBittorrent : rangé codé en base64 (QBIT_PASSWORD_B64) pour accepter tous les caractères."""
    import base64
    b = os.getenv("QBIT_PASSWORD_B64", "").strip()
    if b:
        try:
            return base64.b64decode(b).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            pass
    return os.getenv("QBIT_PASSWORD", "")


def configure():
    r = reglages()
    return bool(r["prowlarr"] and r["prowlarr_cle"] and r["qbit"] and r["nok"])


def chemin_local(p: str) -> Path:
    """Chemin vu par qBittorrent → chemin vu par MouFlanga (réglage facultatif « qbit=>local »)."""
    m = reglages()["chemins"]
    if "=>" in m:
        a, b = (x.strip().rstrip("/") for x in m.split("=>", 1))
        if a and p.startswith(a):
            return Path(b + p[len(a):])
    return Path(p)


# ---------------------------------------------------------------- Prowlarr

def badges(titre: str) -> list[str]:
    t = titre.lower()
    out = []
    if re.search(r"\b(french|fr|vf|truefrench|multi)\b", t):
        out.append("🇫🇷 FR")
    if re.search(r"digital|num[ée]rique|web[ -]?dl", t):
        out.append("Digital")
    elif re.search(r"\bscan", t):
        out.append("Scan")
    if re.search(r"int[ée]grale|complete|complet\b", t):
        out.append("Intégrale")
    m = re.search(r"\bt(?:omes?)?\.?\s?(\d{1,3})\s?(?:-|à|a|to)\s?t?(\d{1,3})\b", t)
    if m:
        out.append(f"T{int(m.group(1))}–{int(m.group(2))}")
    elif re.search(r"(\d{1,3})\s*tomes", t):
        out.append(re.search(r"(\d{1,3})\s*tomes", t).group(1) + " tomes")
    return out


def chercher(q: str, toutes_categories=False) -> list[dict]:
    r = reglages()
    params = [("query", q), ("type", "search"), ("limit", "100")]
    if not toutes_categories:
        params += [("categories", "7000"), ("categories", "7030"), ("categories", "8000")]
    rep = requests.get(r["prowlarr"] + "/api/v1/search", params=params, headers={"X-Api-Key": r["prowlarr_cle"]}, timeout=90)
    if rep.status_code == 401:
        raise RuntimeError("Prowlarr refuse la clé API (Réglages → Connexions).")
    rep.raise_for_status()
    out = []
    for x in rep.json():
        if x.get("protocol", "torrent") != "torrent" or not (x.get("downloadUrl") or x.get("magnetUrl")):
            continue
        titre = x.get("title") or "?"
        out.append({"titre": titre, "taille": x.get("size") or 0, "sources": x.get("seeders") or 0,
                    "indexeur": x.get("indexer") or "", "date": (x.get("publishDate") or "")[:10],
                    "page": x.get("infoUrl") or "", "lien": x.get("downloadUrl") or x.get("magnetUrl"),
                    "badges": badges(titre)})
    # Règles de recherche (profils) : on écarte ce qu'elles refusent, puis le score des formats personnalisés
    out = regles.filtrer(out, q)
    # score des formats d'abord, puis VF, intégrale/digital, et nombre de sources
    out.sort(key=lambda x: (-x.get("score", 0), "🇫🇷 FR" not in x["badges"], "Intégrale" not in x["badges"], "Digital" not in x["badges"], -x["sources"]))
    return out


# ---------------------------------------------------------------- qBittorrent

class Qbit:
    def __init__(self):
        r = reglages()
        self.url, self.s = r["qbit"], requests.Session()
        self.s.headers["Referer"] = self.url
        rep = self.s.post(self.url + "/api/v2/auth/login", data={"username": r["qbit_user"], "password": r["qbit_mdp"]}, timeout=15)
        if rep.status_code != 200 or rep.text.strip() != "Ok.":
            raise RuntimeError("qBittorrent refuse l'identifiant ou le mot de passe (Réglages → Connexions).")

    def appel(self, chemin, **data):
        rep = self.s.post(self.url + "/api/v2/" + chemin, data=data, timeout=30)
        if rep.status_code >= 400 and not (chemin == "torrents/createCategory" and rep.status_code == 409):
            raise RuntimeError(f"qBittorrent : {chemin} → erreur {rep.status_code} {rep.text[:100]}")
        return rep

    def info(self, **params):
        return self.s.get(self.url + "/api/v2/torrents/info", params=params, timeout=30).json()

    def preparer_categorie(self):
        r = reglages()
        cats = self.s.get(self.url + "/api/v2/torrents/categories", timeout=15).json()
        if CATEGORIE not in cats:
            self.appel("torrents/createCategory", category=CATEGORIE, savePath=r["nok"])
        elif (cats[CATEGORIE].get("savePath") or "").rstrip("/") != r["nok"].rstrip("/"):
            self.appel("torrents/editCategory", category=CATEGORIE, savePath=r["nok"])


def tester() -> list[str]:
    """Vérifie Prowlarr, qBittorrent (et la catégorie), et les dossiers. Renvoie des lignes lisibles."""
    r, lignes = reglages(), []
    try:
        rep = requests.get(r["prowlarr"] + "/api/v1/indexer", headers={"X-Api-Key": r["prowlarr_cle"]}, timeout=15)
        rep.raise_for_status()
        actifs = [i for i in rep.json() if i.get("enable")]
        lignes.append(f"✅ Prowlarr : {len(actifs)} indexeur(s) actif(s)")
    except Exception as e:
        lignes.append(f"❌ Prowlarr : {e}")
    try:
        q = Qbit()
        version = q.s.get(q.url + "/api/v2/app/version", timeout=15).text
        q.preparer_categorie()
        lignes.append(f"✅ qBittorrent {version} : catégorie « {CATEGORIE} » prête")
    except Exception as e:
        lignes.append(f"❌ qBittorrent : {e}")
    for nom, d in (("arrivée (NOK)", r["nok"]), ("partage (OK)", r["ok"])):
        if not d:
            lignes.append(f"⚠ Dossier {nom} : pas réglé")
            continue
        p = chemin_local(d)
        try:
            p.mkdir(parents=True, exist_ok=True)
            lignes.append(f"✅ Dossier {nom} : {p}" if os.access(p, os.W_OK) else f"❌ Dossier {nom} : {p} en lecture seule")
        except OSError as e:
            lignes.append(f"❌ Dossier {nom} : {e}")
    return lignes


# ---------------------------------------------------------------- suivi des téléchargements

def _lire():
    try:
        d = json.loads(_ETAT["fichier"].read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _ecrire(d):
    f = _ETAT["fichier"]
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d[-200:], ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def _maj(jid, **kw):
    with _verrou:
        d = _lire()
        for j in d:
            if j["id"] == jid:
                j.update(kw)
        _ecrire(d)


def demander_choix(jid, tomes) -> str:
    """Message d'une tâche « à valider » : les tomes qui existent déjà, et la question posée."""
    liste = ", ".join(f"{t:02d}" for t in sorted(tomes))
    return f"Tomes déjà présents : {liste}. À toi de choisir."


def decider_torrent(jid, remplacer: bool):
    _maj(jid, remplacer=remplacer, etat="telechargement",
         message="Choix enregistré : remplacer les tomes" if remplacer else "Choix enregistré : ajouter les manquants")


def rappeler_a_valider(envoyer):
    """Une tâche en attente de choix est rappelée une fois par jour (Telegram), jusqu'à la décision."""
    fmt = "%Y-%m-%d %H:%M"
    maintenant = datetime.now()
    for j in _lire():
        if j.get("etat") != "a_valider":
            continue
        if maintenant - datetime.strptime(j.get("rappel_le") or j["debut"], fmt) < timedelta(hours=24):
            continue
        envoyer(f"🧲 MouFlanga : « {j['serie']} » attend ton choix (remplacer tout ou ajouter les manquants) dans Télécharger.")
        _maj(j["id"], rappel_le=maintenant.strftime(fmt))


def lancer(lien: str, titre: str, serie: str, remplacer: bool | None = None) -> dict:
    r = reglages()
    q = Qbit()
    q.preparer_categorie()
    jid = uuid.uuid4().hex[:10]
    q.appel("torrents/add", urls=lien, category=CATEGORIE, tags=f"mouflanga,mf-{jid}", savepath=r["nok"], autoTMM="false")
    j = {"id": jid, "titre": titre, "serie": serie, "remplacer": remplacer, "etat": "telechargement", "progression": 0, "debut": datetime.now().strftime("%Y-%m-%d %H:%M"),
         "message": "Envoyé à qBittorrent"}
    with _verrou:
        d = _lire()
        d.append(j)
        _ecrire(d)
    logger.info("Torrent envoyé à qBittorrent : %s → série « %s »", titre, serie)
    return j


def liste():
    return list(reversed(_lire()))


def fichiers_du_torrent(source: Path) -> list[Path]:
    fichiers = [source] if source.is_file() else [f for f in sorted(source.rglob("*")) if f.is_file()]
    return [f for f in fichiers if f.suffix.lower() in EXT_IMPORT]


def lier(f: Path, cible: Path):
    """Place un fichier du torrent DIRECTEMENT sous son nom définitif : lien physique (aucune place en plus), sinon copie.
    Le NAS refuse ensuite de renommer ou d'effacer ces fichiers tant que qBittorrent les partage : on ne les déplace jamais."""
    cible.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(f, cible)
    except OSError:
        shutil.copy2(f, cible)


def surveiller(importer_serie, envoyer, manga_dir):
    """Boucle (toutes les minutes) : téléchargement fini → copie, import, puis déplacement vers « OK »."""
    with _verrou:                                 # import coupé par un redémarrage : on le reprend
        d = _lire()
        for j in d:
            if j.get("etat") == "import":
                j.update(etat="telechargement", message="Reprise après redémarrage")
        _ecrire(d)
    while True:
        time.sleep(60)
        if not configure():
            continue
        try:
            q = Qbit()
            adopter(q)
        except Exception as e:
            logger.warning("Suivi des torrents : %s", e)
            continue
        en_cours = [j for j in _lire() if j["etat"] in ("telechargement", "import")]
        if en_cours:
            traiter(q, en_cours, importer_serie, envoyer, manga_dir)
        rappeler_a_valider(envoyer)


def adopter(q):
    """Torrents ajoutés à la main dans qBittorrent avec la catégorie « mouflanga » : suivis et importés comme les autres.
    Le nom de la série est déduit du nom du torrent (même nettoyage que l'import des archives, série existante reconnue)."""
    for t in q.info(category=CATEGORIE):
        etiquettes = [x.strip() for x in (t.get("tags") or "").split(",")]
        if any(x.startswith("mf-") for x in etiquettes):
            continue
        jid = uuid.uuid4().hex[:10]
        nom = _ETAT["nom_serie"](t.get("name") or "") if _ETAT.get("nom_serie") else (t.get("name") or "manga")
        q.appel("torrents/addTags", hashes=t["hash"], tags=f"mouflanga,mf-{jid}")
        with _verrou:
            d = _lire()
            remplacer = True if _ETAT.get("remplacer_auto") and _ETAT["remplacer_auto"](nom, t.get("name") or "") else None
            d.append({"id": jid, "titre": t.get("name") or "?", "serie": nom, "remplacer": remplacer, "etat": "telechargement",
                      "progression": round((t.get("progress") or 0) * 100), "debut": datetime.now().strftime("%Y-%m-%d %H:%M"),
                      "message": "Ajouté à la main dans qBittorrent"})
            _ecrire(d)
        logger.info("Torrent ajouté à la main repris : %s → série « %s »", t.get("name"), nom)


def traiter(q, en_cours, importer_serie, envoyer, manga_dir):
    """Un passage du suivi : progression, ou copie + import + déplacement vers « OK » quand c'est fini."""
    if True:
        for j in en_cours:
            if j["etat"] != "telechargement":
                continue
            try:
                infos = q.info(tag=f"mf-{j['id']}")
                if not infos:
                    _maj(j["id"], etat="erreur", message="Torrent introuvable dans qBittorrent (supprimé ?)")
                    continue
                t = infos[0]
                if t.get("progress", 0) < 1:
                    _maj(j["id"], progression=round(t.get("progress", 0) * 100), message=t.get("state", ""))
                    continue
                source = chemin_local(t.get("content_path") or str(Path(t["save_path"]) / t["name"]))
                if j.get("remplacer") is None and _ETAT.get("doublons"):
                    deja = _ETAT["doublons"](j["serie"], source)
                    if deja:
                        msg = demander_choix(j["id"], deja)
                        _maj(j["id"], etat="a_valider", progression=100, message=msg)
                        envoyer(f"🧲 MouFlanga : « {j['serie']} » contient déjà des tomes ({msg}). "
                                "Choisis dans Télécharger : remplacer tout ou ajouter les manquants.")
                        continue
                _maj(j["id"], etat="import", progression=100, message="Rangement dans la bibliothèque…")
                fin = importer_serie(j["serie"], source, bool(j.get("remplacer")))
                if reglages()["ok"]:
                    q.appel("torrents/setLocation", hashes=t["hash"], location=reglages()["ok"])
                _maj(j["id"], etat="fini", message=(fin or "Importé").split("\n")[0][:200])
                if _ETAT.get("volumes"):
                    _ETAT["volumes"](j["serie"], j["titre"])
                rapport = None
                if _ETAT.get("rapport"):
                    try:
                        rapport = _ETAT["rapport"](j["serie"], j["titre"])      # compte rendu complet (app.py)
                    except Exception as e:
                        logger.warning("Compte rendu de %s : %s", j["serie"], e)
                envoyer(rapport or f"🧲 MouFlanga : « {j['serie']} » importé depuis le torrent {j['titre'][:80]}\n{fin or ''}".strip())
            except Exception as e:
                logger.warning("Torrent %s : %s", j["titre"], e)
                _maj(j["id"], etat="erreur", message=str(e)[:200])
                envoyer(f"⚠️ MouFlanga : import du torrent {j['titre'][:80]} impossible : {e}")
