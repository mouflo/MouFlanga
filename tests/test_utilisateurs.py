"""Comptes lecteur : lecture seule, progression séparée, gestion par l'admin."""
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class UtilisateursTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); t = Path(self.tmp.name)
        self.root = t / "mangas"; (self.root / "Serie").mkdir(parents=True)
        with zipfile.ZipFile(self.root / "Serie" / "001 - Chapitre 1.cbz", "w") as z:
            z.writestr("1.jpg", b"x")
        self._env = {k: os.environ.get(k) for k in ("APP_USER", "APP_PASSWORD_HASH")}
        from werkzeug.security import generate_password_hash
        import app as A, auth                         # (l'appli lit data/secrets.env à l'import : on remplace ensuite)
        os.environ.update(APP_USER="admin", APP_PASSWORD_HASH=generate_password_hash("motdepasse-admin"))
        self.A, self.auth = A, auth
        A.MANGA_DIR = self.root; A.PROGRESS_FILE = t / "progress.json"
        self._users = auth.USERS_FILE; auth.USERS_FILE = t / "utilisateurs.json"
        A._ANIMES["date"] = 0

    def tearDown(self):
        self.auth.USERS_FILE = self._users
        for k, v in self._env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.tmp.cleanup()

    def connecter(self, u, m):
        c = self.A.app.test_client()
        r = c.post("/login", data={"username": u, "password": m})
        self.assertEqual(r.status_code, 302, r.data[:200])
        return c

    def test_lecteur(self):
        admin = self.connecter("admin", "motdepasse-admin")
        r = admin.post("/api/utilisateurs", json={"action": "ajouter", "id": "lea", "mdp": "court"})
        self.assertEqual(r.status_code, 400)
        self.assertTrue(admin.post("/api/utilisateurs", json={"action": "ajouter", "id": "lea", "mdp": "lecture-lea"}).json["ok"])
        self.assertEqual(admin.post("/api/utilisateurs", json={"action": "ajouter", "id": "admin", "mdp": "xxxxxxxxx"}).status_code, 409)
        lea = self.connecter("lea", "lecture-lea")
        # lire : oui
        self.assertEqual(lea.get("/api/library").status_code, 200)
        r = lea.post("/api/progress", json={"series": "Serie", "path": "Serie/001 - Chapitre 1.cbz", "page": 3, "finished": True})
        self.assertTrue(r.json.get("ok"), (r.status_code, r.json))
        # tout le reste : non (serveur)
        for meth, url in (("post", "/api/delete"), ("post", "/api/renommer"), ("get", "/api/utilisateurs"), ("get", "/api/diagnostic"),
                          ("post", "/api/japscan/download"), ("post", "/api/resume")):
            self.assertEqual(getattr(lea, meth)(url, json={}).status_code, 403, url)
        self.assertEqual(lea.get("/reglages").status_code, 302)
        # progressions séparées
        self.assertEqual(lea.get("/api/library").json["series"][0]["read"], 1)
        self.assertEqual(admin.get("/api/library").json["series"][0]["read"], 0)
        self.assertNotIn("Serie", json.loads(self.A.PROGRESS_FILE.read_text()) if self.A.PROGRESS_FILE.exists() else {})
        # désactivé ou nouveau mot de passe : déconnecté
        admin.post("/api/utilisateurs", json={"action": "activer", "id": "lea", "actif": False})
        self.assertEqual(lea.get("/api/library").status_code, 401)
        r = self.A.app.test_client().post("/login", data={"username": "lea", "password": "lecture-lea"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(admin.get("/api/utilisateurs").json["utilisateurs"][0]["actif"], False)


if __name__ == "__main__":
    unittest.main()
