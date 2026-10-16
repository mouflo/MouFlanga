"""🔒 Toutes les adresses de l'appli, essayées une par une : un lecteur n'atteint que la liste LECTEUR_OK, une personne non
connectée n'atteint que la page de connexion et les fichiers publics. Une nouvelle route est donc refusée par défaut."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PUBLIQUES = {"/login", "/healthz", "/favicon.ico", "/skin.css"}          # + /icons/, /ui/, /api/externe/ (clé API)


def _adresses(app):
    """(méthode, chemin d'essai, règle) pour chaque route ; les paramètres sont remplis avec des valeurs factices."""
    for regle in app.url_map.iter_rules():
        if regle.endpoint == "static":
            continue
        chemin = regle.rule
        for nom, conv in regle._converters.items():
            valeur = "1" if conv.__class__.__name__ in ("IntegerConverter", "FloatConverter") else "x"
            chemin = chemin.replace(f"<{nom}>", valeur)
            for t in ("int", "float", "path", "string"):
                chemin = chemin.replace(f"<{t}:{nom}>", valeur)
        for m in sorted((regle.methods or set()) - {"HEAD", "OPTIONS"}):
            yield m, chemin, regle.rule


class SecuriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); t = Path(self.tmp.name)
        from werkzeug.security import generate_password_hash
        self._env = {k: os.environ.get(k) for k in ("APP_USER", "APP_PASSWORD_HASH")}
        import app as A, auth
        os.environ.update(APP_USER="admin", APP_PASSWORD_HASH=generate_password_hash("motdepasse-admin"))
        self.A, self.auth = A, auth
        self._users = auth.USERS_FILE; auth.USERS_FILE = t / "utilisateurs.json"
        auth.ecrire_utilisateurs({"lea": {"actif": True, "hash": generate_password_hash("lecture-lea")}})

    def tearDown(self):
        self.auth.USERS_FILE = self._users
        for k, v in self._env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.tmp.cleanup()

    def _publique(self, regle):
        return regle in PUBLIQUES or regle.startswith(("/icons/", "/ui/", "/api/externe/"))

    def test_lecteur_n_atteint_que_la_liste_permise(self):
        c = self.A.app.test_client()
        c.environ_base["REMOTE_ADDR"] = "192.168.1.50"           # pas le serveur lui-même
        self.assertEqual(c.post("/login", data={"username": "lea", "password": "lecture-lea"}).status_code, 302)
        essais = 0
        for m, chemin, regle in _adresses(self.A.app):
            if (m, regle) in self.auth.LECTEUR_OK or self._publique(regle):
                continue                                  # permis : pas appelé ici (effets réels)
            r = c.open(chemin, method=m, json={})
            essais += 1
            if regle.startswith("/api/"):
                self.assertEqual(r.status_code, 403, f"{m} {regle} accessible à un lecteur")
            else:
                self.assertIn(r.status_code, (302, 403), f"{m} {regle} accessible à un lecteur")
                if r.status_code == 302:
                    self.assertTrue(r.headers["Location"].endswith("/"), f"{m} {regle}")
        self.assertGreater(essais, 100)

    def test_personne_non_connectee(self):
        c = self.A.app.test_client()
        c.environ_base["REMOTE_ADDR"] = "192.168.1.50"
        for m, chemin, regle in _adresses(self.A.app):
            if self._publique(regle):
                continue
            r = c.open(chemin, method=m, json={})
            if regle.startswith("/api/"):
                self.assertIn(r.status_code, (401, 403), f"{m} {regle} accessible sans connexion")
            else:
                self.assertEqual(r.status_code, 302, f"{m} {regle} accessible sans connexion")
                self.assertIn("/login", r.headers["Location"], f"{m} {regle}")

    def test_api_externe_sans_cle(self):
        c = self.A.app.test_client()
        for m, chemin, regle in _adresses(self.A.app):
            if regle.startswith("/api/externe/"):
                r = c.open(chemin, method=m, headers={"X-Cle-API": "fausse"})
                self.assertIn(r.status_code, (401, 403, 429), f"{m} {regle}")

    def test_faux_localhost_refuse(self):
        """/api/occupe est réservé au serveur lui-même : un en-tête X-Forwarded-For inventé ne suffit pas."""
        c = self.A.app.test_client()
        r = c.get("/api/occupe", headers={"X-Forwarded-For": "127.0.0.1"}, environ_base={"REMOTE_ADDR": "192.168.1.50"})
        self.assertIn(r.status_code, (401, 403))
        r = c.get("/api/occupe", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(r.status_code, 200)

    def test_identifiant_reserve_refuse(self):
        c = self.A.app.test_client()
        c.environ_base["REMOTE_ADDR"] = "192.168.1.50"
        self.assertEqual(c.post("/login", data={"username": "admin", "password": "motdepasse-admin"}).status_code, 302)
        for uid in ("_admin", ".x", "_x"):
            r = c.post("/api/utilisateurs", json={"action": "ajouter", "id": uid, "mdp": "lecture-123"})
            self.assertEqual(r.status_code, 400, uid)

    def test_lecteur_ne_voit_pas_les_adresses_internes(self):
        import zipfile
        racine = Path(self.tmp.name) / "mangas"
        (racine / "Serie").mkdir(parents=True)
        with zipfile.ZipFile(racine / "Serie" / "001.cbz", "w") as z:
            z.writestr("1.jpg", b"x")
        vrai, self.A.MANGA_DIR = self.A.MANGA_DIR, racine
        avant = os.environ.get("MOUFLOSTER_URL")
        os.environ["MOUFLOSTER_URL"] = "http://192.168.1.20:8000"
        try:
            c = self.A.app.test_client()
            c.environ_base["REMOTE_ADDR"] = "192.168.1.50"
            c.post("/login", data={"username": "lea", "password": "lecture-lea"})
            r = c.get("/api/series?id=Serie")
            self.assertEqual(r.status_code, 200)
            self.assertNotIn(b"192.168.1.20", r.data)
        finally:
            self.A.MANGA_DIR = vrai
            os.environ.pop("MOUFLOSTER_URL", None) if avant is None else os.environ.__setitem__("MOUFLOSTER_URL", avant)

    def test_fichiers_caches_illisibles(self):
        """La corbeille et les dossiers cachés du dossier des mangas ne se lisent pas par le lecteur de pages."""
        racine = Path(self.tmp.name) / "mangas"
        (racine / ".corbeille" / "2026-10-16").mkdir(parents=True)
        (racine / ".corbeille" / "2026-10-16" / "T01.cbz").write_bytes(b"PK")
        (racine / "Serie").mkdir()
        (racine / "Serie" / "T01.cbz").write_bytes(b"PK")
        vrai = self.A.MANGA_DIR
        self.A.MANGA_DIR = racine
        try:
            self.assertIsNone(self.A._safe_path(".corbeille/2026-10-16/T01.cbz"))
            self.assertIsNone(self.A._safe_path("../mangas/.corbeille/2026-10-16/T01.cbz"))
            self.assertIsNone(self.A._safe_path("../../etc/passwd"))
            self.assertIsNotNone(self.A._safe_path("Serie/T01.cbz"))
        finally:
            self.A.MANGA_DIR = vrai


if __name__ == "__main__":
    unittest.main()
