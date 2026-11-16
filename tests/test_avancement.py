"""Avancement réel d'un travail (✨ Améliorer, alléger) : pourcentage pondéré, temps restant, dernier signe de vie, page par page."""
import io
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import optimiser  # noqa: E402


def base(**kw):
    e = {"en_cours": True, "appliquer": True, "fait": 0, "total": 2, "debut": time.time() - 100, "signe": time.time() - 5,
         "octets_total": 100, "octets_faits": 50, "tome_octets": 50, "phase": "ecriture", "page": 5, "pages": 10}
    e.update(kw)
    return e


class CompleterTest(unittest.TestCase):
    def test_pourcent_pondere_par_la_taille_et_la_page_en_cours(self):
        e = base()
        optimiser._completer(e)
        self.assertEqual(e["pourcent"], 77)                         # 50 de faits + (10 % d'analyse + 90 % × 5/10) de 50
        self.assertEqual(e["ecoule_s"], 100)
        self.assertAlmostEqual(e["reste_s"], 100 * 0.225 / 0.775, delta=2)

    def test_analyse_seule_et_phase_d_analyse(self):
        e = base(appliquer=False, phase="analyse", page=3, pages=6, octets_faits=0)
        optimiser._completer(e)
        self.assertEqual(e["pourcent"], 25)                         # la moitié du tome en cours (50 sur 100 d'octets) × la moitié des pages d'essai
        e = base(phase="analyse", page=3, pages=6, octets_faits=0)
        optimiser._completer(e)
        self.assertEqual(e["pourcent"], 2)                          # en application, l'analyse ne pèse que 10 % du tome

    def test_pas_d_estimation_trop_tot_et_jamais_100_avant_la_fin(self):
        e = base(debut=time.time() - 5)
        optimiser._completer(e)
        self.assertIsNone(e["reste_s"])
        e = base(octets_faits=100, tome_octets=0, page=10)
        optimiser._completer(e)
        self.assertLessEqual(e["pourcent"], 99)

    def test_depuis_signe_repere_un_blocage(self):
        e = base(signe=time.time() - 300)
        optimiser._completer(e)
        self.assertGreaterEqual(e["depuis_signe_s"], 299)

    def test_sans_octets_repli_sur_les_tomes_faits(self):
        e = base(octets_total=0, fait=1, total=4, page=0, pages=0)
        optimiser._completer(e)
        self.assertEqual(e["pourcent"], 25)


class AvancerTest(unittest.TestCase):
    def tearDown(self):
        optimiser._LOCAL.__dict__.pop("serie", None)
        optimiser._ETAT.pop("S", None)

    def test_reecrire_signale_chaque_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            tome = Path(tmp) / "T.cbz"
            with zipfile.ZipFile(tome, "w") as z:
                for i in range(4):
                    b = io.BytesIO()
                    Image.new("L", (100, 150), 200).save(b, "JPEG", quality=90)
                    z.writestr(f"{i:03d}.jpg", b.getvalue())
            optimiser._ETAT["S"] = {"en_cours": True}
            optimiser._LOCAL.serie = "S"
            vus = []
            reel = optimiser._avancer

            def espion(phase, k, n):
                reel(phase, k, n)
                vus.append((phase, k, n, optimiser._ETAT["S"]["page"]))
            optimiser._avancer = espion
            try:
                optimiser.reecrire(tome, 60, "1,0,0,0,0,0,0,0,0,0")
            finally:
                optimiser._avancer = reel
            self.assertEqual([v[:3] for v in vus], [("ecriture", 1, 4), ("ecriture", 2, 4), ("ecriture", 3, 4), ("ecriture", 4, 4), ("verification", 1, 1)])
            self.assertEqual(optimiser._ETAT["S"]["phase"], "verification")

    def test_hors_traitement_aucune_trace(self):
        optimiser._avancer("ecriture", 1, 2)                         # pas de série dans ce fil : rien à faire, pas d'erreur
        self.assertNotIn("S", optimiser._ETAT)

    def test_etat_d_un_travail_fini_n_a_pas_de_pourcent(self):
        optimiser._ETAT["S"] = {"en_cours": False, "message": "fini"}
        self.assertNotIn("pourcent", optimiser.etat("S"))


if __name__ == "__main__":
    unittest.main()
