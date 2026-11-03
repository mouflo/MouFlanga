"""Un torrent qui apporte une série neuve ET son spin-off : relier l'univers ne doit pas planter faute de dossier pour la mère."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: E402


class RelierUniversTest(unittest.TestCase):
    def test_serie_mere_sans_dossier(self):
        with tempfile.TemporaryDirectory() as t:
            manga = Path(t)
            (manga / "Mere - Spin").mkdir()
            with mock.patch.object(app, "MANGA_DIR", manga), mock.patch.object(app, "_scan_invalider"):
                app._relier_univers("Mere", "Mere - Spin")
            self.assertTrue((manga / "Mere" / ".mouflanga-infos.json").exists())
            self.assertTrue((manga / "Mere - Spin" / ".mouflanga-infos.json").exists())


if __name__ == "__main__":
    unittest.main()
