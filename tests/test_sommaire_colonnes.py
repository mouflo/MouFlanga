"""Sommaire en colonnes (Kapitel·1 … Kapitel·5), numéros à segments, résumé MangaDex trop court, chapitres « <br /> »."""
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sommaire  # noqa: E402
import tomes  # noqa: E402

SEGMENTS = {"5": "acdfg", "9": "abcdfg", "3": "abcdg", "6": "acdefg", "2": "abdeg", "0": "abcdef"}


def _chiffre(dessin, x, y, c, h=28, l=24, e=5):
    """Chiffre à segments de 24 × 28 pixels."""
    zones = {"a": (x, y, x + l, y + e), "d": (x, y + h - e, x + l, y + h), "g": (x, y + h // 2 - e // 2, x + l, y + h // 2 + e // 2 + 1),
             "f": (x, y, x + e, y + h // 2), "b": (x + l - e, y, x + l, y + h // 2),
             "e": (x, y + h // 2, x + e, y + h), "c": (x + l - e, y + h // 2, x + l, y + h)}
    for s in SEGMENTS[c]:
        dessin.rectangle(zones[s], fill=(235, 225, 40))


def _image(texte):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (400, 200), (60, 70, 150))
    d = ImageDraw.Draw(im)
    for k, c in enumerate(texte):
        _chiffre(d, 100 + k * 34, 80, c)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class LireNumero(unittest.TestCase):
    def test_chiffres_a_segments(self):
        for t in ("5", "63", "209"):
            self.assertEqual(sommaire.lire_numero(_image(t), (95, 75, 34 * len(t), 38)), int(t))

    def test_un_trop_fin_pour_etre_un_autre_chiffre(self):
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (400, 200), (60, 70, 150))
        d = ImageDraw.Draw(im)
        _chiffre(d, 100, 80, "9")
        d.rectangle((140, 80, 146, 108), fill=(235, 225, 40))          # un « 1 » : trait fin
        buf = io.BytesIO()
        im.save(buf, "PNG")
        self.assertEqual(sommaire.lire_numero(buf.getvalue(), (95, 75, 60, 38)), 91)


class ColonnesAvecMots(unittest.TestCase):
    def _mots(self):
        def m(t, x, y, w=120, c=90):
            return {"t": t, "x": x, "y": y, "w": w, "h": 30, "c": c}
        return [m("Kapitel:1", 130, 224), m("Kapitel:2", 500, 224), m("Kapitel-5", 1600, 224),
                m("La", 190, 275, 55), m("fuite", 160, 326), m("Le", 520, 275, 50), m("district", 500, 326),
                m("Corrosion", 1590, 275, 235)]

    def test_entetes_et_titres_sous_chaque_colonne(self):
        with mock.patch.object(sommaire, "lire_numero", side_effect=[5, 51, 163]):
            r = sommaire.analyser_colonnes(b"", self._mots() + [
                {"t": "x", "x": 200, "y": 380, "w": 30, "h": 28, "c": 40}, {"t": "x", "x": 560, "y": 380, "w": 30, "h": 28, "c": 40},
                {"t": "x", "x": 1650, "y": 330, "w": 30, "h": 28, "c": 40}])
        # numéros 1, 2 puis 5 : il manque des chapitres, la lecture est refusée plutôt que devinée
        self.assertEqual(r, [])


class Resume(unittest.TestCase):
    def test_lien_wikipedia_nest_pas_un_resume(self):
        reponse = mock.Mock()
        reponse.json.return_value = {"data": [{"attributes": {"links": {"al": "31349"},
                                                              "description": {"fr": "[Wikipedia](https://fr.wikipedia.org/wiki/07-Ghost)"}}}]}
        with mock.patch.object(tomes._SESSION, "get", return_value=reponse), \
                mock.patch.object(tomes, "_wikipedia_fr", return_value="Teito Klein est un adolescent."):
            texte, langue = tomes._resume({"id": 31349, "title": {"romaji": "07-Ghost"}, "description": ""}, "07-ghost")
        self.assertEqual((texte, langue), ("Teito Klein est un adolescent.", "fr"))

    def test_resume_dun_mot_est_refait(self):
        import time
        self.assertFalse(tomes.statut_a_jour({"resume": "Wikipedia", "statut": "FINISHED", "date": time.time() - 2 * 86400}))
        self.assertTrue(tomes.statut_a_jour({"resume": "x" * 120, "statut": "FINISHED", "date": time.time() - 2 * 86400}))

    def test_nombre_ordinal_dans_un_titre(self):
        self.assertEqual(tomes._wiki_propre("Le {{7e|district}}"), "Le 7e district")


if __name__ == "__main__":
    unittest.main()
