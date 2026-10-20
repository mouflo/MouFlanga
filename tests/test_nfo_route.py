import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_nfo import NFO


class RouteNfoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MANGA_DIR"] = self.tmp.name
        (Path(self.tmp.name) / "Kenichi").mkdir()
        sys.modules.pop("app", None)
        import app
        self.A = app

    def tearDown(self):
        self.tmp.cleanup()

    def _appel(self, corps):
        with mock.patch.object(self.A, "_scan", return_value={"Kenichi": []}):
            with self.A.app.test_request_context("/api/serie/nfo", method="POST", json=corps):
                rep = self.A.api_serie_nfo()
        return rep if isinstance(rep, tuple) else (rep, 200)

    def test_nfo_colle_note_les_isbn(self):
        rep, code = self._appel({"series": "Kenichi", "texte": NFO})
        self.assertEqual(code, 200)
        self.assertIn("2 ISBN ajouté(s)", rep.get_json()["message"])

    def test_texte_sans_rien_d_utile_refuse(self):
        rep, code = self._appel({"series": "Kenichi", "texte": "bonjour"})
        self.assertEqual(code, 400)

    def test_serie_inconnue(self):
        rep, code = self._appel({"series": "Absente", "texte": NFO})
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
