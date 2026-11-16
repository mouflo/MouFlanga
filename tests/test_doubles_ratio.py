"""📖 Repérage des doubles pages : les scans à 1,18 – 1,20 de ratio (Nori Taka : 1275 × 1068) sont bien proposés, une page seule jamais."""
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import optimiser  # noqa: E402


class RatioDoublesTest(unittest.TestCase):
    def test_doubles_juste_sous_1_2_reperees_pages_seules_jamais(self):
        with tempfile.TemporaryDirectory() as tmp:
            tome = Path(tmp) / "T.cbz"
            tailles = {"0001.jpg": (600, 1000), "0002.jpg": (1275, 1068), "0003.jpg": (1272, 1033), "0004.jpg": (640, 1050), "0005.jpg": (1100, 1000)}
            with zipfile.ZipFile(tome, "w") as z:
                for nom, t in tailles.items():
                    b = io.BytesIO()
                    Image.new("L", t, 200).save(b, "JPEG")
                    z.writestr(nom, b.getvalue())
            self.assertEqual([d["nom"] for d in optimiser.reperer_doubles(tome)], ["0002.jpg", "0003.jpg", "0005.jpg"])   # 1,19 · 1,23 · 1,10 ; pas 0,6


if __name__ == "__main__":
    unittest.main()
