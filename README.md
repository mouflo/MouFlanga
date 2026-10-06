# 📚 MouFlanga - Lecteur et gestionnaire de mangas

[![Licence : MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

**Application web pour gérer, organiser et lire vos mangas téléchargés en fichiers CBR** - une interface élégante pour parcourir vos chapitres, accéder aux informations des mangas, et les intégrer à votre médiathèque Emby.

## 📸 Aperçu

*Captures avec des données de démonstration.*

**La liste des mangas téléchargés avec progression de lecture**

![Liste des mangas](docs/screenshots/liste.png)

**Lecteur de manga en plein écran avec navigation chapitres**

![Lecteur](docs/screenshots/lecteur.png)

**Gestion des mangas : supprimer, organiser, re-scraper**

![Gestion](docs/screenshots/gestion.png)

**La page ⚙️ Réglages : dossiers, Emby, intégration scraper**

![Réglages](docs/screenshots/reglages.png)

**Sur téléphone**

![Mobile](docs/screenshots/mobile.png)

## ✨ Fonctionnalités

- 📖 **Lecteur CBR intégré** : navigation fluide entre les pages, zoom, mode plein écran
- 📚 **Gestion des mangas** : liste avec miniatures, tri par titre/date/progression
- 🔍 **Recherche et filtres** : trouve rapidement un manga par titre, auteur ou genre
- 📊 **Suivi de lecture** : progression sauvegardée par manga
- 🎨 **Informations détaillées** : couverture, synopsis, nombre de chapitres, taille
- 🔄 **Intégration Scraper** : relance le téléchargement pour ajouter de nouveaux chapitres
- 🌙 **Thème clair/sombre** : interface cohérente avec le reste de la suite MouFl
- 📱 **Responsive** : fonctionne sur téléphone, tablette et desktop
- ⚙️ **Page Réglages** : même page que MouFlopening et MouFloster pour cohérence
- 📦 **Import CBR** : détecte automatiquement les fichiers CBR dans le dossier manga

## 🚀 Installation

### Prérequis
- Python 3.9+
- Git
- Accès à la liste des mangas (fichiers CBR)

### Installation rapide

```bash
cd /opt
git clone https://github.com/mouflo/MouFlanga.git mouflanga
cd mouflanga
pip install -r requirements.txt
bash install.sh
```

Ouvre ensuite `http://<adresse-du-serveur>:5002` et configure les dossiers dans ⚙️ Réglages.

## 📖 Utilisation

1. **Ajoute tes mangas** : télécharge-les avec le scraper ou copie les fichiers CBR manuellement
2. **Regarde la liste** : clique sur un manga pour voir ses chapitres
3. **Lis** : clique sur un chapitre pour l'ouvrir en lecteur
4. **Suivi** : ta progression est sauvegardée automatiquement
5. **Gestion** : supprime, déplace, ou re-scrape un manga depuis le panneau de gestion

## ⚙️ Configuration

Tout se règle dans la page **⚙️ Réglages** :

- **Dossier des mangas** : où sont tes fichiers CBR (défaut `/mnt/data/manga`)
- **Dossier Emby** : si tu veux synchroniser avec ta médiathèque (optionnel)
- **Import automatique** : redémare automatiquement après un scraper (optionnel)

## 📁 Structure attendue

```
/mnt/data/manga/
├── One Piece/
│   ├── Tome_01/
│   │   ├── Chapitre_1.cbr
│   │   ├── Chapitre_2.cbr
│   │   └── Chapitre_3.cbr
│   └── Tome_02/
│       └── ...
├── Naruto/
└── Bleach/
```

## 🔧 Développement

```bash
# Cloner et activer l'environnement
git clone https://github.com/mouflo/MouFlanga.git
cd MouFlanga
python3 -m venv venv
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt

# Lancer l'app
python3 app.py
```

Ouvre `http://localhost:5002` 🎉

## 🎨 Interface

- **Dark mode** par défaut, toggle clair/sombre dans l'en-tête
- **Design MouFl** cohérent avec MouFlanimeXer, MouFloster et MouFlopening
- **Responsive** : s'adapte à tous les écrans
- **Optimisée pour téléphone** : navigation tactile fluide

## 🤝 Dans la même famille

[MouFlanimeXer](https://github.com/mouflo/MouFlanimeXer) (remux d'animes) · [MouFloster](https://github.com/mouflo/MouFloster) (posters) · [MouFlopening](https://github.com/mouflo/MouFlopening) (thèmes) : même style, même page Réglages.

## 📝 Licence

MIT - voir [LICENSE](LICENSE)

## 📞 Aide

Un problème ? Ouvre une [issue sur GitHub](https://github.com/mouflo/MouFlanga/issues).

---

Créé avec ❤️ pour les amateurs de manga • Intégré à MouFl

*Dernière mise à jour: 2026-10-06*
