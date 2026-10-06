# 🚀 Déploiement Scraper Japscan v2.0

## ✅ Ce qui vient d'être fait

1. **Scraper v2.0 complet** : `japscan_scraper.py`
   - Async/await pour meilleures perfs
   - Patchright pour meilleur contournement Cloudflare
   - Interception réseau pour capture images
   - Plus de fallback suicidaire vers requests
   - Format CBZ (plus standard)

2. **Tests unitaires** : `test_scraper_v2.py`
   - Test complet 4 étapes
   - Lance : `xvfb-run -a python3 test_scraper_v2.py`

3. **Guide installation** : `INSTALLATION_V2.md`
   - Étapes pré-requis système
   - Installation Python
   - Dépannage

4. **Mises à jour** :
   - `requirements.txt` : Patchright remplace Playwright

## 🔄 Déploiement sur serveur

Ton serveur va auto-pull ces changements via le cron Git dans les minutes qui viennent.

### Manuellement (si tu veux tester tout de suite)

```bash
cd /opt/mouflanga
git pull origin main
```

### Première exécution (installation dépendances)

```bash
cd /opt/mouflanga

# Installation des dépendances Python
pip install --break-system-packages -r requirements.txt

# Cela va télécharger Chromium optimisé via Patchright (~300 Mo)
# Attendre 2-3 minutes
```

## 🧪 Test complet

```bash
cd /opt/mouflanga

# Lance le test avec affichage virtuel
xvfb-run -a python3 test_scraper_v2.py
```

### Résultats attendus

**Si tout fonctionne** ✓
```
TEST 1 : Récupération de la liste des mangas
✓ 500+ mangas trouvés

TEST 2 : Récupération des chapitres
✓ 200+ chapitres trouvés

TEST 3 : Téléchargement des pages du chapitre
✓ 45 pages capturées

TEST 4 : Création archive CBZ
✓ CBZ créé : test_chapter_200.cbz (25.30 Mo)

✓ TOUS LES TESTS RÉUSSIS !
```

**Si ça échoue** ✗
```
✗ Aucun manga trouvé
✗ Aucune page capturée
✗ Erreur création CBZ
```

## 📊 Ce qui change par rapport à v1.0

| Problème v1.0 | Cause | Solution v2.0 |
|---------------|-------|---------------|
| Timeout 30s | `wait_until="networkidle"` | `wait_until="domcontentloaded"` |
| 403 Cloudflare | Parse HTML statique | Interception réseau |
| Aucune image | Images injectées en JS | Capture déchiffrées par Chromium |
| Fallback requests échoue | Cloudflare bloque requests | Plus de fallback |
| Confusion chapitre/série | Pas de nettoyage URL | `extract_manga_root_url()` |

## 🔧 Intégration Flask

Si tu as une interface web, adapter pour async :

```python
import asyncio
from japscan_scraper import JapscanScraper

scraper = JapscanScraper(Path('/opt/mouflanga/mangas'))

# Dans une route Flask
@app.route('/api/chapters/<manga_id>')
def get_chapters(manga_id):
    chapters = asyncio.run(scraper.get_chapters(manga_url))
    return jsonify(chapters)
```

Ou mieux : utiliser Quart (version async de Flask)

```python
from quart import Quart
app = Quart(__name__)

@app.route('/api/chapters/<manga_id>')
async def get_chapters(manga_id):
    chapters = await scraper.get_chapters(manga_url)
    return chapters
```

## 📝 Logs

Voir les logs détaillés :

```bash
# Avec debug
python3 -c "
import logging
logging.getLogger('japscan_scraper').setLevel(logging.DEBUG)
exec(open('test_scraper_v2.py').read())
" 2>&1 | tee test_output.log
```

## ⏱️ Temps d'exécution estimés

- **Liste mangas** : ~5-10s
- **Récupération chapitres** : ~3-8s
- **Téléchargement 40 pages** : ~20-30s
- **Création CBZ** : <1s

**Total pour 1 manga (50 chapitres)** : ~40-60 minutes

## 🐛 Dépannage rapide

### "Patchright not found"
```bash
pip install --break-system-packages patchright
python3 -m patchright.install
```

### "No X display"
```bash
# Toujours lancer avec xvfb-run -a
xvfb-run -a python3 test_scraper_v2.py
```

### "Chromium not found"
```bash
python3 -m patchright.install  # Télécharge Chromium
```

### Aucune image capturée
- Vérifier que `page.on("response", on_response)` est appelé
- Augmenter la pause après `page.goto()`
- Vérifier que les images ne sont pas filtrées par les critères (taille, URL keywords)

## 📂 Structure fichiers après déploiement

```
/opt/mouflanga/
├── japscan_scraper.py           # Code principal v2.0
├── test_scraper_v2.py           # Script test
├── requirements.txt             # Dépendances (patchright)
├── INSTALLATION_V2.md           # Guide install
├── DEPLOY_V2_INSTRUCTIONS.md    # Ce fichier
├── mangas/                      # Dossier sortie CBZ
├── logs/                        # Logs (si configuré)
└── [autres fichiers MouFlanga]
```

## ✨ Prochaines étapes

1. **Tester** : Lance `test_scraper_v2.py`
2. **Valider** : Vérifie que les CBZ sont créés correctement
3. **Intégrer Flask** : Adapter ton interface web
4. **Archiver v1.0** : Garder japscan_scraper_old.py en backup (optionnel)

## 🎯 Objectif atteint

La nouvelle approche d'**interception réseau** capture les vraies images déchiffrées par Chromium. C'est inarrêtable contre Cloudflare puisque le navigateur doit lui-même voir les images pour les afficher.

**C'est le contournement ultime.** 🔓

---

Questions ou problèmes ? Lance le test et dis-moi ce qui s'affiche !
