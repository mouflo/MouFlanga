"""Sommaire d'un tome lu par OCR : lignes reconnues, page du sommaire trouvée, décalage des pages calculé."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sommaire  # noqa: E402

CLAYMORE = """( PANTIORE,
Volume 1
SOMMAIRE
SCÈNE 1 La tueuse aux yeux d'argent ...................5
SCÈNE 2 Les ongles du cief...........................69
SCÈNE 3 Les souvenirs d'une sorcière ..................109
SCÈNEA Le livret noir ..............................149"""


class AnalyseTest(unittest.TestCase):
    def test_lignes_de_sommaire(self):
        l = sommaire.analyser(CLAYMORE)
        self.assertEqual([(x["num"], x["page"]) for x in l], [(1, 5), (2, 69), (3, 109), (4, 149)])
        self.assertEqual(l[0]["titre"], "La tueuse aux yeux d'argent")
        self.assertTrue(sommaire._vraisemblable(l))

    def test_autres_formes(self):
        l = sommaire.analyser("Chapitre 12 : Le retour 45\n13. Un autre jour ........ 60\nUne bulle de texte 3")
        self.assertEqual([(x["num"], x["titre"], x["page"]) for x in l], [(12, "Le retour", 45), (13, "Un autre jour", 60)])

    def test_bruit_refuse(self):
        self.assertFalse(sommaire._vraisemblable(sommaire.analyser("Voici le premier volume.\nJ'espère qu'il vous plaira.")))
        self.assertFalse(sommaire._vraisemblable([{"num": 2, "page": 50}, {"num": 3, "page": 10}]))


class LectureTest(unittest.TestCase):
    def test_sommaire_et_decalage(self):
        textes = {0: "NORIHIRO YAGI", 1: "Voici le premier volume.", 5: CLAYMORE, 6: "SCENE 1 LA TUEUSE AUX YEUX D'ARGENT"}
        with mock.patch.object(sommaire, "ocr", side_effect=lambda octets: textes.get(octets, "")):
            r = sommaire.lire("essai", lambda i: i, 189)
        self.assertEqual(r["page_sommaire"], 5)
        self.assertEqual(r["decalage"], 1)
        self.assertEqual([c["image"] for c in r["chapitres"]], [6, 70, 110, 150])

    def test_rien_trouve(self):
        with mock.patch.object(sommaire, "ocr", return_value="dessin"):
            r = sommaire.lire("essai", lambda i: i, 20)
        self.assertEqual(r["chapitres"], [])


if __name__ == "__main__":
    unittest.main()


class VisionTest(unittest.TestCase):
    """Sommaire stylisé (Bakuman) : lu par Claude seulement si une clé est enregistrée."""

    def test_sans_cle_rien_n_est_envoye(self):
        with mock.patch.object(sommaire, "ocr", return_value="dessin"), mock.patch.dict("os.environ", {"CLAUDE_API_KEY": ""}), \
                mock.patch("requests.post") as p:
            r = sommaire.lire("x", lambda i: i, 20)
        self.assertEqual(r["chapitres"], [])
        p.assert_not_called()

    def test_reponse_de_claude(self):
        import io as _io
        from PIL import Image
        b = _io.BytesIO(); Image.new("RGB", (40, 60)).save(b, "JPEG")
        texte = ('Voici : {"page_sommaire": 4, "image_chapitre_1": 6, "chapitres": [{"num": 8, "titre": "La carotte et le bâton", "page": 7},'
                 ' {"num": 9, "titre": "Conditions et capitale", "page": 29}]}')
        rep = mock.Mock(status_code=200, json=mock.Mock(return_value={"content": [{"type": "text", "text": texte}]}))
        with mock.patch.object(sommaire, "ocr", return_value="dessin"), mock.patch.dict("os.environ", {"CLAUDE_API_KEY": "sk-ant-x"}), \
                mock.patch("requests.post", return_value=rep):
            r = sommaire.lire("x", lambda i: b.getvalue(), 190)
        self.assertEqual([(c["num"], c["page"], c["image"]) for c in r["chapitres"]], [(8.0, 7, 6), (9.0, 29, 28)])
        self.assertEqual(r["source"], "Claude")

    def test_titre_mal_lu_et_numero_de_fichier(self):
        # « tefrent » (OCR) reste reconnu pour « torrent » ; sans texte lisible, le numéro du fichier « 005 » donne le décalage
        self.assertTrue(sommaire._proche("torrent", ["un", "tefrent", "de"]))
        self.assertFalse(sommaire._proche("torrent", ["sortir"]))
        noms = ["000.jpg", "000a.jpg", "000b.jpg", "000c.jpg", "001.jpg", "002.jpg", "003.jpg", "004.jpg", "005.jpg", "006.jpg"]
        self.assertEqual(sommaire._decalage_par_nom(5, noms, 7), 3)                 # « 005.jpg » est la 9e image : décalage 3
        self.assertIsNone(sommaire._decalage_par_nom(5, noms[:4], 1))

    def test_decalage_par_vote_titre_en_page_2(self):
        # le titre du chapitre 1 est en page 2 de son chapitre (décalage +1), ceux des chapitres 2 et 3 en 1re page
        ch = [{"num": 1.0, "titre": "Le retour du héros", "page": 5}, {"num": 2.0, "titre": "Les marais sombres", "page": 25},
              {"num": 3.0, "titre": "La tour de cristal", "page": 45}]
        textes = {2: "sommaire", 8: "rien", 9: "Le retour du heros", 28: "Les marais sombres", 48: "La tour de cristal"}
        # chaque titre donne l'image où il est lu : 9 pour le 1er (page 2 de son chapitre), puis 28 et 48
        self.assertEqual(sommaire._images(ch, textes, 2)[0], [9, 28, 48])
        self.assertEqual(sommaire._decalage(ch, textes, 2), 4)

    def test_seconde_lecture_meme_si_la_premiere_donne_du_bruit(self):
        # la lecture normale sort une ligne parasite : le canal bleu doit quand même être essayé
        with mock.patch.object(sommaire, "ocr", side_effect=lambda o, clair=False: "Chapitre 19 : À votre place ...... 5\nChapitre 20 : Un maître ...... 41" if clair else "bruit\n3 . 12 ..... 4"):
            r = sommaire.lire("x", lambda i: b"", 1)
        self.assertEqual([c["page"] for c in r["chapitres"]], [5, 41])

    def test_numero_mal_lu_dans_la_suite(self):
        lignes = [{"num": 22.0, "titre": "a", "page": 115}, {"num": 23.0, "titre": "b", "page": 161}, {"num": 21.0, "titre": "c", "page": 207}]
        self.assertEqual([x["num"] for x in sommaire._numeros_suivis(lignes)], [22.0, 23.0, 24.0])
        self.assertTrue(sommaire._vraisemblable(sommaire._numeros_suivis(lignes)))

    def test_titre_sur_deux_lignes(self):
        texte = ("SOMMAIRE\n\nChapitre 71 @ L'homme écarlate ———— 173\n\n"
                 "Chapitre 72 @ Une spirale négative\n\net un pas vers le salut ———— 215\n")
        r = sommaire.analyser(texte)
        self.assertEqual([(c["num"], c["page"]) for c in r], [(71.0, 173), (72.0, 215)])
        self.assertEqual(r[1]["titre"], "Une spirale négative et un pas vers le salut")

    def test_image_par_nom_de_fichier(self):
        noms = ["000.jpg", "000a.jpg", "000b.jpg", "000c.jpg", "001.jpg", "002.jpg", "003.jpg", "004.jpg",
                "005.jpg", "006-007.jpg", "008.jpg", "009.jpg"]
        self.assertEqual(sommaire._image_par_nom(5, noms, 7), 8)
        self.assertEqual(sommaire._image_par_nom(7, noms, 7), 9)             # page de droite d'une double page
        self.assertEqual(sommaire._image_par_nom(8, noms, 7), 10)
        self.assertIsNone(sommaire._image_par_nom(50, noms, 7))
        ch = [{"num": 1.0, "titre": "Début", "page": 5}, {"num": 2.0, "titre": "Suite", "page": 8}]
        self.assertEqual(sommaire._images(ch, {}, 7, None, 12, noms)[0], [8, 10])

    def test_epilogue_sans_numero_et_symboles_parasites(self):
        texte = ("SOMMAIRE\nChapitre 107 € Le dernier combat ———— 141\nChapitre 108 €} La fin du voyage ———— 213\n"
                 "Épilogue @ L'autre fin du voyage ———— 329\n")
        r = sommaire.analyser(texte)
        self.assertEqual([(c["num"], c["page"]) for c in r], [(107.0, 141), (108.0, 213), (109.0, 329)])
        self.assertEqual([c["titre"] for c in r], ["Le dernier combat", "La fin du voyage", "Épilogue : L'autre fin du voyage"])


class FormesApprisesTest(unittest.TestCase):
    """Formes de sommaires rencontrées dans la bibliothèque (balayage d'octobre 2026), d'après le texte OCR réel."""

    def test_numero_avant_le_mot(self):                          # Magi
        l = sommaire.analyser("Table des matières\nLa 38 nuit Le bidonville ----- 3\nLa 39e nuit L'affaire -----. 21\n"
                              "La 41enuit L'attaque ------ 57\nLa45enuit Il s'appelle Judal ---- 129")
        self.assertEqual([(x["num"], x["titre"], x["page"]) for x in l],
                         [(38, "Le bidonville", 3), (39, "L'affaire", 21), (41, "L'attaque", 57), (45, "Il s'appelle Judal", 129)])

    def test_lignes_chapitre_mal_lues(self):                     # One Piece : 1re page absente, « uu », page qui recule
        l = sommaire._reparer_lignes("= SOMMAIRE -\nCHAPITRE 389 : RÉPONSE D\nCHAPITRE 390: PRÊTS À EN DÉCOUDRE 25\n"
                                     "CHAPITRE 391 : UNE FILLETTE ..........uu\nCHAPITRE 392: DÉRÉSHI........... 65\n"
                                     "CHAPITRE 393: OLVIA A 85\nCHAPITRE 394 : LES DÉMONS D'OHARA 104\n"
                                     "CHAPITRE 395: OHARA … 125\nCHAPITRE 396: SAURO Rs 105\nCHAPITRE 397 : POUR LES GÉNÉRATIONS 165")
        self.assertEqual([x["num"] for x in l], [389.0 + k for k in range(9)])
        self.assertEqual([x["page"] for x in l], [5, 25, 45, 65, 85, 104, 125, 145, 165])
        self.assertTrue(l[0].get("estimee") and l[7].get("estimee"))

    def test_lignes_chapitre_numero_illisible(self):             # 20th Century Boys tome 4
        l = sommaire._reparer_lignes("Chapitre 1 - L'évasion.......... 7\nChapitre 2 - L'air frais ....... 25\n"
                                     "ChapitreMSllaccostage PP 7 43\nChapitre 4 - L'exposition de rêve ....... 61\n"
                                     "Chapitre 22 =Les Noix. 59")
        self.assertEqual([(x["num"], x["page"]) for x in l], [(1, 7), (2, 25), (3, 43), (4, 61), (5, 79)])

    def test_page_au_dessus_du_titre(self):                      # YuYu Hakusho : pas de numéro de chapitre imprimé
        texte = ("SOMMAIRE\n6 Nu à\n. Le réveil du Yoko! |\n21 = $\nLe coup de Shishiwakamaru !!\n4] |\nDémasqué !!\n"
                 "67 ;\nL'appel de la mort 1!\nAN) Le boss, Onjih 1! |\nAU 107\nDS L'homme aux mille visages L!")
        l = sommaire.analyser_page_puis_titre(texte, [83.0, 84.0, 85.0, 86.0, 87.0, 88.0])
        self.assertEqual([x["num"] for x in l], [83.0, 84.0, 85.0, 86.0, 87.0, 88.0])
        self.assertEqual(l[5]["titre"], "L'homme aux mille visages")
        self.assertEqual([l[0]["page"], l[3]["page"], l[5]["page"]], [6, 67, 107])
        self.assertEqual(sommaire.analyser_page_puis_titre(texte, [1.0, 2.0]), [])      # pas le même nombre : rien

    def test_credits_lus_comme_pastilles(self):                  # Area-D : « 1, 2, 7 » n'est pas un sommaire
        self.assertFalse(sommaire._ecarts_plausibles([{"page": 1}, {"page": 2}, {"page": 7}]))
        self.assertTrue(sommaire._ecarts_plausibles([{"page": 5}, {"page": 25}, {"page": 45}]))

    def test_chapitre_sur_trois_lignes(self):                    # Dandadan
        l = sommaire.analyser_empile("Épisode 1\nSerait-ce une romance qui commence ?\n005\nÉpisode F.\n"
                                     "On dirait bien un extraterrestre !\n069\nÉpisode 3\nLe choc des vioques\n121\n"
                                     "Épisode 4\nFilons aux toilettes !\n161")
        self.assertEqual([(x["num"], x["page"]) for x in l], [(1, 5), (2, 69), (3, 121), (4, 161)])
        self.assertEqual(l[1]["titre"], "On dirait bien un extraterrestre !")

    def test_page_avant_le_numero(self):                         # Deadman Wonderland
        l = sommaire.analyser("SOMMAIRE\np003 01 Qui a tué Cock Robin?\np077 02 La règle des règles\n"
                              "p125 03 La course mortelle des Chiens heureux\np171 04 Tueur d'esclave\np212 Contenu bonus")
        self.assertEqual([(x["num"], x["page"]) for x in l], [(1, 3), (2, 77), (3, 125), (4, 171)])
        self.assertEqual(l[1]["titre"], "La règle des règles")

    def test_phrases_ne_sont_pas_un_sommaire(self):
        self.assertLess(sommaire._ecart_median([{"page": 1}, {"page": 2}, {"page": 6}, {"page": 12}]), 5)

    def test_decor_apres_la_page(self):                          # Four Knights of the Apocalypse
        l = sommaire.analyser("+ SOMMAIRE + dé)\nChapitre 1 - À l'aube du grand voyage 3 A\nChapitre 2 - Rencontre inopinée T3 Ÿ J\n"
                              "Chapitre 3 - Sur les traces de son père 113 L\nChapitre 4 - Une force inconnue 143 E ::\n"
                              "Chapitre 5 - Les Four Knights of the Apocalypse 163")
        self.assertEqual([(x["num"], x["page"]) for x in l], [(1, 3), (2, 73), (3, 113), (4, 143), (5, 163)])
        self.assertEqual(l[1]["titre"], "Rencontre inopinée")

    def test_lignes_sautees_comblees(self):                      # Magi tome 1 : « La ænuit », « LaSenuit »
        texte = ("Table des matières\nLa 1 nuit || sappelle Aladin + 3\nLa 2e nuit || sappelle Ali Baba -.. 57\n"
                 "La 3e nuit  Aladin et Ali Baba --.... 91\nLa ænuit  Lelabyrinthe --. 115\nLaSenuit  Àl'aventure 133\n"
                 "La6enuit À l'intérieur du labyrinthe -. 151\nLa 7enuit Les dangers du labyrinthe ----- 175")
        l = sommaire._combler(texte, sommaire._numeros_suivis(sommaire.analyser(texte)))
        self.assertEqual([(x["num"], x["page"]) for x in l], [(1, 3), (2, 57), (3, 91), (4, 115), (5, 133), (6, 151), (7, 175)])

    def test_trick_entre_parentheses(self):                      # Air Gear tome 6 : « (Trick:43 24) » lu « CTrick:43 24 ) »
        l = sommaire._numeros_suivis(sommaire.analyser("CTrick:43 24 )\nTrick:45 64 )\nTrick:46 86 )\nCTrick:47 1O5\n"
                                                       "CTrick:48 127)\nTrick:49 145\nCTrick:50 166 )|e"))
        self.assertEqual([(x["num"], x["page"]) for x in l], [(43, 24), (45, 64), (46, 86), (47, 105), (48, 127), (49, 145), (50, 166)])

    def test_ordinaux_en_lettres(self):                          # Gintama : « PREMIER PRÉCEPTE : … 5 »
        texte = ("PREMIER PRÉCEPTÉ : QUELQU'UN QUI À LES CHEVEUX NATURELLEMENT\nONDULÉS NE PEUT PAS ÊTRE MAUVAIS ! 5\n"
                 "DEUXIÈME PRÉCÉPTÉ : LE MAÎTRE S'OCCUPÉRA JUSQU'AU BOUT\nDE SON ANIMAL DE COMPAGNIE. 2]\n"
                 "TROISIÈME PRÉCÉPTÉ : LE MAGAZINE JUMP PARAÎT PARFOIS LE SAMEDI ;\nSOYONS DONC ATTENTIFS. 87\n"
                 "QUATRIÈME PRÉCÉPTE : CÉLUI QUI FAIT BONNE IMPRESSION\nÀ LA PREMIÈRE RENCONTRE N'EST JAMAIS FIABLE. fl\n"
                 "CINQUIÈME PRÉCEPTÉ : MÊME QUAND TU SÉRAS DÉVENU UN PAPY,\nVOUS APPELER PAR VOS SURNOMS. 131")
        l = sommaire.analyser_ordinaux(texte)
        self.assertEqual([x["num"] for x in l], [1, 2, 3, 4, 5])
        self.assertEqual([l[0]["page"], l[2]["page"], l[4]["page"]], [5, 87, 131])
        self.assertTrue(l[1].get("estimee") and l[3].get("estimee"))

    def test_numero_titre_page_sans_mot(self):                   # Green Blood (page sombre, décor autour)
        l = sommaire.analyser_nus("A 0) LEGRIMREAPER 00! ; 4\n| OZ L'AGENT DE POLICE 049 è\n< 03 LACIBLE 083 È\n"
                                  "| 04 roue 128 k\nL |  À05 |'SouRRE 139 F\n| À 06 ASSASSIN 157 1\n- | 07 LEPRIX 175 | 4")
        self.assertEqual([(x["num"], x["page"]) for x in l], [(1, 1), (2, 49), (3, 83), (4, 128), (5, 139), (6, 157), (7, 175)])

    def test_chapitres_par_noms_des_images(self):                # tomes assemblés par une équipe (« c0047.00-p001.jpg »)
        noms = ["c0047.00-p001.png", "c0047.00-p002.jpg", "c0048.00-p001.jpg", "c0048.00-p002.jpg", "c0048.5-p001.jpg"]
        l = sommaire.chapitres_par_noms(noms)
        self.assertEqual([(x["num"], x["image"]) for x in l], [(47, 0), (48, 2), (48.5, 4)])
        noms = ["001-00_3026.jpg", "002-01_5806.jpg", "003-00_6260.jpg", "004-01_1111.jpg"]
        self.assertEqual([(x["num"], x["image"]) for x in sommaire.chapitres_par_noms(noms, [68.0, 69.0])], [(68, 0), (69, 2)])
        self.assertEqual(sommaire.chapitres_par_noms(["0001.jpg", "0002.jpg"]), [])

    def test_page_aberrante_estimee(self):                       # Crows tome 2 : « 419 » pour 119, « 4f9 », « OS » pour 05
        l = sommaire._meilleure_lecture("CHAPITRE OS : LINE FUITE PLEINE DE RAGE ! ... 7\nCHAPITRE 06 : FEEL SO GOOD-...... 58\n"
                                        "CHAPITRE O7 : CROIRE AUX RUMEURS ? :-..... 419\nCHAPITRE O8 : GHOST BUSTER C PARTIE O1)-- 4f9\n"
                                        "CHAPITRE 09 : GHOST BUSTER (PARTIE 02) ...... 171")
        self.assertEqual([x["num"] for x in l], [5, 6, 7, 8, 9])
        self.assertEqual([l[0]["page"], l[1]["page"], l[4]["page"]], [7, 58, 171])
        self.assertTrue(58 < l[2]["page"] < l[3]["page"] < 171)

    def test_entete_puis_titre_et_page(self):                    # Ken Fist of the Blue Sky (moitié gauche d'une double page)
        texte = ("Chapitre 1\n\nL'homme dont la tête est mise à prix :\n\nYan-Wang, le Roi des Enfers l\n\nChapitre 2 |\n\n"
                 "Le code d'honneur !! 57\n\nChapitre 3\n\nLa menace du poing meurtrier !! 83\n\nChapitre 4 »\n\n"
                 "L'empereur fantoche !! 105 F\n\nChapitre 5 L\n\nL'insupportable humiliation !! 123 1\n")
        l = sommaire._meilleure_lecture(texte)
        self.assertEqual([x["num"] for x in l], [1, 2, 3, 4, 5])
        self.assertEqual([x["page"] for x in l][1:], [57, 83, 105, 123])
        self.assertEqual(l[1]["titre"], "Le code d'honneur")
        self.assertTrue(l[0].get("estimee"))

    def test_nuits_mal_lues(self):                               # Magi tome 2 : « La 102 nuit » pour 10e, « La gœenuit »
        texte = ("Table des matières\nLa nuit Le passé d'Aladin +. 3\nLa gœenuit  Letyran-- 21\nLa 102 nuit Le pays natal ---. 39\n"
                 "La11enuit La nécropole ---. 59\nLa 12e nuit L'endroit où l'on risque sa vie -----+ 77\n"
                 "La13nuit Le grand magicien qui crée le monde + 95\nLa 14 nuit Le propriétaire du labyrinthe ----- 113")
        l = sommaire._meilleure_lecture(texte)
        self.assertEqual([(x["num"], x["page"]) for x in l], [(8, 3), (9, 21), (10, 39), (11, 59), (12, 77), (13, 95), (14, 113)])

    def test_mot_appris_et_titre_sur_deux_lignes(self):          # Reborn : « CIBLE 1 : … / VENU D'ITALIE 5 »
        texte = ("CIBLE I : UN DROLE DE BONHOMME\nVENU D'ITALIE 5\n000000000000000\nCIBLE 2 : SANS COMPTER SUR\ne\n"
                 "LA DERNIERE VOLONTE .…..ereS Q\nCIBLE 3 : HAYATO GOKUDERA 85\nCIBLE 4 : LA CRISE : VIRE DE L'ECOLE ! 107\n"
                 "CIBLE 5 : TAKESHI YAMAMOTO 127\nCIBLE 6 : LA ROULETTE RUSSE 147")
        l = sommaire._meilleure_lecture(texte)
        self.assertEqual([x["num"] for x in l], [1, 2, 3, 4, 5, 6])
        self.assertEqual([x["page"] for x in l if not x.get("estimee")], [5, 85, 107, 127, 147])

    def test_nom_de_serie_comme_mot(self):                       # Rave : « RAVE : 5 TRAVEL — TROUBLE ?P/ p. 3 »
        l = sommaire._meilleure_lecture("RAVE : 5 TRAVEL — TROUBLE ?P/ p. 3\nRAVE : © DEAD OR ALINE P. 23\n"
                                        "RAVE : 7 VENGEANCE EN TRIO !/ p. 43\nRAVE : 8 LA MAGIE D'UN SOURIRE P. 63\n"
                                        "RAVE : O LE FORGERON LÉGENDAIRE P. 83")
        self.assertEqual([(x["num"], x["page"]) for x in l], [(5, 3), (6, 23), (7, 43), (8, 63), (9, 83)])
        self.assertEqual(l[1]["titre"], "DEAD OR ALINE")

    def test_decor_devant_chapitre(self):                        # Seven Deadly Sins tome 2 : « k Chapitre 9 », « Chapire 11 »
        l = sommaire._meilleure_lecture("SOMMATRE\nChapitre 6 - Gilthunder, le chevalier sacré 3 ù\n"
                                        "| Chapitre 7 - Le prisonnier des ténèbres\". 23 |\n| Chapitre 8 - Le rêve d'une jeune fille 43 |\n"
                                        "k Chapitre 9 - N'y touche pas 68 ï\n| Chapitre 10 - Le mal invisible 89 À\n"
                                        "| Chapire 11 - Même si tu venais à mourir 109 |\n| Chapitre 12 - Un banquet chaotique 129 |")
        self.assertEqual([(x["num"], x["page"]) for x in l], [(6, 3), (7, 23), (8, 43), (9, 68), (10, 89), (11, 109), (12, 129)])
        self.assertEqual(l[5]["titre"], "Même si tu venais à mourir")

    def test_ligne_sans_page_comblee(self):                      # Judge tome 3 : « Chapitre 14 : Aveux WI »
        l = sommaire._meilleure_lecture("A Chapitre 11 : Choix 003 |\nx apitre 12 : Deuxième jugement 039 |\n"
                                        "CP 1 | ea ! Chapitre 13 : Témoignage 075\n9 Î Chapitre 14 : Aveux WI\n"
                                        "À | | Chapitre 15 : Procès inéquitable 149")
        self.assertEqual([x["num"] for x in l], [11, 12, 13, 14, 15])
        self.assertTrue(l[3].get("estimee") and 75 < l[3]["page"] < 149)
        self.assertEqual(l[3]["titre"], "Aveux")

    def test_rangees_encadrees_lues_par_bandes(self):            # Air Gear tome 9 : bord de la rangée lu « EE »
        l = sommaire._meilleure_lecture("EE Trick:69 ss)\nEE Trick:70) 23)\nEE Trick:71 43 })\nEE Trick:72 61 })\n"
                                        "EE Trick:73 5655)\nEE Trick:74 107 })\nEE Trick:75 129 })")
        self.assertEqual([x["num"] for x in l], [69, 70, 71, 72, 73, 74, 75])
        self.assertEqual([x["page"] for x in l if not x.get("estimee")], [23, 43, 61, 107, 129])

    def test_numeros_lus_avec_un_trou(self):                     # Reborn tome 3 : « CIBLE 22 » illisible
        l = sommaire._meilleure_lecture("CIBLE 19 : PREMIER MEURTRE 51\nCIBLE 20 : GRIVELERIE 73\nCIBLE 21 : RECHERCHE BABY-SITTER\n"
                                        "CIBLE 23 : I-PIN 139\nCIBLE 24 : I-PIN CONTRE LAMBO lé!\nCIBLE 25 : KYOKO CONTRE HARU 81")
        self.assertEqual([x["num"] for x in l], [19, 20, 21, 22, 23, 24, 25])      # 22 ajouté, page estimée

    def test_numero_avec_un_chiffre_en_trop(self):               # Magi tome 4 : « La 308 nuit » pour la 30e
        l = sommaire._meilleure_lecture("Table des matières\nLa 28 nuit La tribu des combattants Fanalis +... 3\n"
                                        "La 29enuit Les esclaves ----- 21\nLa 308 nuit Le miracle -----+ 39\n"
                                        "La 31 nuit La fête des adieux ----- 57\nLa 32e nuit Le chemin vers Balbad -----. 79")
        self.assertEqual([x["num"] for x in l], [28, 29, 30, 31, 32])

    def test_page_o7(self):                                      # Crows tome 7 : « …… O7 » (zéro lu O)
        l = sommaire._meilleure_lecture("CHAPITRE 23 : LE COEUR À SES RAISONS....cvvvrrvmrovorrrnrers O7\n"
                                        "CHAPITRE 24 : PARCE QUE LA LUNE EST SI BLEUE.........,,,,87\n"
                                        "CHAPITRE 25 : LES GRENOUILLES VIENNENT DE L'OCÉAN..139")
        self.assertEqual([(x["num"], x["page"]) for x in l], [(23, 7), (24, 87), (25, 139)])

    def test_quart_temps(self):                                  # Kuroko's Basket : séparateur lu « H », points lus « LELELE »
        texte = ("62° Quart-temps H Ce qu'il me reste à faire CEELTETETEETETETTITETIITET] 005\n"
                 "63° Quart-temps H Le temps d'une vie LEALELLLLELELLELELLELLELELLE EE EL! 045 |\n"
                 "66° Quart-temps 2 Mise en garde LLLLLELELELEELELEELEELEELELLEEEE] 105\n"
                 "67° Quart-temps H J'arrête LERLRLLELELELELLEEELLELELEEELELEEEL2] 125 |\n"
                 "68° Quart-temps Hi Tout est possible LLRLELELRLELELLELLELRLELRLEL)] 145 |")
        l = sommaire._meilleure_lecture(texte)
        self.assertEqual([x["num"] for x in l], [62, 63, 64, 65, 66, 67, 68])
        self.assertEqual(l[0]["titre"], "Ce qu'il me reste à faire")

    def test_page_p_lettres(self):                               # Rave tome 9 : « P. us » (45), « P.1u7 » (147), bonus ignoré
        l = sommaire._meilleure_lecture("RAVE : 67 UNE DÉTERMINATION INFINIE p. us\nRAVE : ©B DES SENTIMENTS TOURNÉS VERS P. 65\n"
                                        "RAVE : 70 À LA RECHERCHE DE LA LUMIÈRE P. 107\nRAVE : 71 L'AVENIR EST ENTRE SES MAINS P. 127\n"
                                        "RAVE : 72 LE BUT ULTIME DE KING !/ P.1u7\nRAVE : 73 DES LIENS ÉTERNELS P. 168\n"
                                        "MANGA BONUS RAVE 0077 P. 1©7")
        self.assertEqual([x["num"] for x in l], [67, 68, 69, 70, 71, 72, 73])
        self.assertEqual([l[0]["page"], l[5]["page"]], [45, 147])

    def test_ordinaux_mal_lus(self):                             # Gintama tome 12 : « QUATRE-NINGT-QUINZIÈME »
        self.assertEqual(sommaire.nombre_fr("QUATRE-NINGT-QUINZIÈME"), 95)
        self.assertEqual(sommaire.nombre_fr("CENT UNIÈME"), 101)

    def test_quart_temps_pages_illisibles(self):                 # Kuroko's Basket tome 12 : peu de pages lues, pas régulier
        texte = ("100° Quart-temps : Comment ne pas S'enflammer 21 M\n101° Quart-temps : Quel que Soit le prix à PAYEF Mn 025\n"
                 "102° Quart-temps : Voilà pourquoi je Suis revenu 045\n103° Quart-temps : Ce match, tu vas le perdre ess\n"
                 "104° Quart-temps : C'est là qu'est le piège ee\n105° Quart-temps : CONMANCe\n"
                 "106° Quart-Lemps : JE IE SENS M nn 12 |\n107° Quart-temps : RAS 1e DOI eee 44 |\n"
                 "108° Quart-temps : Lents à en PIEUTEr eee eee n een 169")
        l = sommaire._meilleure_lecture(texte)
        self.assertEqual([x["num"] for x in l], list(range(100, 109)))
        self.assertEqual([l[1]["page"], l[2]["page"], l[8]["page"]], [25, 45, 169])
