# Installation Scraper Japscan v2.0

## Prérequis

- Serveur Linux (Proxmox/Debian)
- Xvfb installé : `apt-get install xvfb`
- Python 3.11+

## Étapes d'installation

### 1. Installation des dépendances système

```bash
# Xvfb (serveur d'affichage virtuel)
apt-get update
apt-get install -y xvfb

# Dépendances pour Chromium sous Linux
apt-get install -y libnspr4 libnss3 libgbm1 libatk-bridge2.0-0 libatk1.0-0 \
  libxkbcommon0 libpango-1.0-0 libpangoxft-1.0-0 libgtk-3-0 libx11-6
```

### 2. Installation Python

```bash
cd /opt/mouflanga

# Installer les dépendances Python
pip install --break-system-packages -r requirements.txt

# Patchright va télécharger automatiquement Chromium optimisé
# Cela peut prendre quelques minutes la première fois
python3 -c "from patchright.async_api import async_playwright; print('✓ Patchright OK')"
```

### 3. Créer le dossier de sortie

```bash
mkdir -p /opt/mouflanga/mangas
chmod 755 /opt/mouflanga/mangas
```

## Test rapide

```bash
cd /opt/mouflanga

# Test avec affichage virtuel
xvfb-run -a python3 test_scraper_v2.py
```

## Résultats attendus

### Test RÉUSSIT ✓
```
======================================================================
TEST 1 : Récupération de la liste des mangas
======================================================================
✓ 500+ mangas trouvés

TEST 2 : Récupération des chapitres
======================================================================
✓ 200+ chapitres trouvés

TEST 3 : Téléchargement des pages du chapitre
======================================================================
✓ 45 pages capturées

TEST 4 : Création archive CBZ
======================================================================
✓ CBZ créé : test_chapter_200.cbz (25.30 Mo)

======================================================================
✓ TOUS LES TESTS RÉUSSIS !
======================================================================
```

### Test ÉCHOUE ✗
```
✗ Cloudflare toujours présent
✗ Aucune page capturée
✗ Erreur création CBZ
```

## Points clés de la v2.0

| Aspect | v1.0 | v2.0 |
|--------|------|------|
| Library | Playwright | Patchright |
| Sync/Async | Sync | Async |
| Stratégie images | Parse HTML | Interception réseau |
| wait_until | networkidle ⚠️ | domcontentloaded ✓ |
| Fallback requests | Oui ❌ | Non ✓ |
| Format sortie | CBR | CBZ |
| Lazy-loading | Non | Scroll ✓ |
| Cloudflare | 403 ❌ | Contourné ✓ |

## Architecture

```
1. Liste mangas (/)
   ↓ [domcontentloaded] → parse HTML
   ↓
2. Détails série (/manga/xxx/)
   ↓ [domcontentloaded] → parse chapitres
   ↓
3. Lecteur chapitre (/manga/xxx/yyy/)
   ↓ [domcontentloaded]
   ↓ [Interception réseau] → capture images déchiffrées
   ↓ [Scroll progressif] → lazy-loading
   ↓
4. Création CBZ
   ↓
5. Fichier sortie (/opt/mouflanga/mangas/Titre_000.cbz)
```

## Dépannage

### Erreur : "Cannot find chromium"
```bash
# Patchright n'a pas pu télécharger Chromium
python3 -m patchright.install
```

### Erreur : "No X display"
```bash
# Xvfb n'est pas lancé correctement
# S'assurer que tu lances avec xvfb-run -a
xvfb-run -a python3 test_scraper_v2.py
```

### Erreur : "Cloudflare challenge"
- Attendre : Patchright peut avoir besoin de temps pour contourner CF
- Vérifier : JapScan n'a pas changé son infrastructure
- Déboguer : Voir les logs détaillés avec `logging.DEBUG`

### Aucune image capturée
- Les sélecteurs CSS ont peut-être changé
- Vérifier avec : `page.on("request", ...)` dans le debug
- Augmenter la pause d'attente après `page.goto()`

## Configuration pour Flask

Dans `app.py`, utiliser `asyncio.run()` pour wrapper les appels :

```python
import asyncio
from japscan_scraper import JapscanScraper

@app.route('/api/chapters/<manga_id>')
def get_chapters(manga_id):
    scraper = JapscanScraper(Path('/opt/mouflanga/mangas'))
    chapters = asyncio.run(scraper.get_chapters(manga_url))
    return jsonify(chapters)
```

## Performance

- **Liste mangas** : ~5-10 secondes
- **Chapitres d'une série** : ~3-8 secondes
- **Téléchargement chapitre** : ~15-45 secondes (dépend du nombre de pages)
- **Création CBZ** : <1 seconde

Total pour 1 manga : ~2-5 minutes (selon nombre de chapitres)

## Fichiers

- `japscan_scraper.py` - Code principal v2.0
- `test_scraper_v2.py` - Script de test
- `requirements.txt` - Dépendances Python
- `setup-xvfb.sh` - Installation système (optionnel)
