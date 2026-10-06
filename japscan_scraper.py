#!/usr/bin/env python3
"""
Scraper Japscan v2.0 - MouFlanga
Capture les flux réseau déchiffrés par Chromium sous Xvfb et génère des archives CBZ.
Utilise Patchright (fork de Playwright) pour meilleur contournement Cloudflare.
"""
import asyncio
import hashlib
import logging
import os
import re
import shutil
import socket
import threading
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin
from datetime import datetime

from bs4 import BeautifulSoup


def async_playwright():
    """Import paresseux : l'appli démarre même si Patchright n'est pas installé."""
    from patchright.async_api import async_playwright as _ap
    return _ap()


def nom_sur(texte: str, defaut: str = "sans-titre") -> str:
    """Rend un texte utilisable comme nom de fichier/dossier (pas de / ni de ..)."""
    texte = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", texte or "")
    texte = re.sub(r"\s+", " ", texte).strip(" .")
    return texte[:120] or defaut


CHALLENGE_TITRES = ("just a moment", "un instant", "attention required")


def _installer_xdotool():
    """Retrouve xdotool ; s'il manque, tente de l'installer (une tentative par heure au maximum)."""
    import shutil
    import subprocess
    exe = shutil.which("xdotool")
    if exe:
        return exe
    marque = PROFIL.parent / "xdotool-install-tente"
    try:
        if marque.exists() and time.time() - marque.stat().st_mtime < 3600:
            return None
        marque.parent.mkdir(parents=True, exist_ok=True)
        marque.write_text(datetime.now().isoformat())
        logger.info("Installation de xdotool (vrai clic de souris pour la vérification Cloudflare)...")
        r = subprocess.run(["apt-get", "install", "-y", "-q", "xdotool"], capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            marque.unlink(missing_ok=True)
            logger.info("✓ xdotool installé")
            return shutil.which("xdotool")
        logger.warning("Installation de xdotool échouée : " + (r.stderr or r.stdout)[-200:])
    except Exception as e:
        logger.warning(f"Installation de xdotool impossible : {e}")
    return None


def coord_ecran(geo: dict, x: float, y: float) -> tuple[int, int]:
    """Position à l'écran (écran virtuel) d'un point de la page, à partir de la géométrie de la fenêtre."""
    gauche = geo.get("sx", 0) + max(0, geo.get("dw", 0)) // 2
    haut = geo.get("sy", 0) + max(0, geo.get("dh", 0))      # barre d'outils de Chrome au-dessus de la page
    return int(gauche + x), int(haut + y)


async def _clic_reel(page, x: float, y: float) -> bool:
    """Clique comme une vraie souris, par l'écran virtuel (xdotool) : les coordonnées d'écran du clic sont alors
    cohérentes, ce que le clic « d'automatisation » ne permet pas. Renvoie False si ce n'est pas possible."""
    if not os.environ.get("DISPLAY"):
        return False
    exe = await asyncio.to_thread(_installer_xdotool)
    if not exe:
        return False
    try:
        geo = await page.evaluate("""() => ({sx: window.screenX, sy: window.screenY,
            dw: window.outerWidth - window.innerWidth, dh: window.outerHeight - window.innerHeight})""")
        cx, cy = coord_ecran(geo, x, y)

        async def xdo(*args):
            proc = await asyncio.create_subprocess_exec(exe, *args, stdout=asyncio.subprocess.DEVNULL,
                                                        stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(proc.wait(), 10)
            return proc.returncode

        # trajet de souris en plusieurs étapes, arrivée un peu lente, puis clic
        for fx, fy in ((-90, -50), (-45, -22), (-14, -7), (-3, -1), (0, 0)):
            if await xdo("mousemove", str(max(0, cx + fx)), str(max(0, cy + fy))) != 0:
                return False
            await asyncio.sleep(0.07)
        await asyncio.sleep(0.15)
        return await xdo("click", "1") == 0
    except Exception as e:
        logger.debug(f"Clic réel impossible : {e}")
        return False


async def _glisser_reel(page, points: list) -> bool:
    """Glisser-déposer comme une vraie souris (xdotool) le long d'un trajet de points de la page."""
    if not os.environ.get("DISPLAY"):
        return False
    exe = await asyncio.to_thread(_installer_xdotool)
    if not exe:
        return False
    try:
        geo = await page.evaluate("""() => ({sx: window.screenX, sy: window.screenY,
            dw: window.outerWidth - window.innerWidth, dh: window.outerHeight - window.innerHeight})""")

        async def xdo(*args):
            proc = await asyncio.create_subprocess_exec(exe, *args, stdout=asyncio.subprocess.DEVNULL,
                                                        stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(proc.wait(), 10)
            return proc.returncode

        ecran = [coord_ecran(geo, x, y) for x, y in points]
        # Tout le geste dans UNE commande xdotool : appui, déplacements, relâchement (rapide et régulier)
        cmd = ["mousemove", str(max(0, ecran[0][0])), str(max(0, ecran[0][1])), "sleep", "0.08", "mousedown", "1", "sleep", "0.08"]
        for cx, cy in ecran[1:]:
            cmd += ["mousemove", str(max(0, cx)), str(max(0, cy)), "sleep", "0.012"]
        cmd += ["sleep", "0.08", "mouseup", "1"]
        proc = await asyncio.create_subprocess_exec(exe, *cmd, stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(proc.wait(), 30)
        return proc.returncode == 0
    except Exception as e:
        logger.debug(f"Glisser réel impossible : {e}")
        return False


async def _cliquer_case_cloudflare(page) -> bool:
    """Tente de cocher la case « Vérifiez que vous êtes humain » (Turnstile)."""
    try:
        cadre = await page.query_selector("iframe[src*='challenges.cloudflare.com']")
        if not cadre:
            return False
        boite = await cadre.bounding_box()
        if not boite:
            return False
        cible_x, cible_y = boite["x"] + 28, boite["y"] + boite["height"] / 2
        if await _clic_reel(page, cible_x, cible_y):
            logger.info("Clic sur la case Cloudflare (souris de l'écran virtuel)")
            return True
        await page.mouse.move(boite["x"] + 20, cible_y, steps=8)
        await asyncio.sleep(0.4)
        await page.mouse.click(cible_x, cible_y)
        logger.info("Clic sur la case Cloudflare (automatisation)")
        return True
    except Exception as e:
        logger.debug(f"Clic Cloudflare impossible : {e}")
        return False


# ----------------------------------------------------------------------
# Vérification Cloudflare faite à la main (page « Vérification » de l'appli)
# ----------------------------------------------------------------------
_VERIF = {"actif": False, "loop": None, "page": None, "depuis": 0.0, "url": "", "alertes": {}}
_VERIF_VERROU = threading.Lock()
PATIENCE_HUMAIN = 600          # secondes laissées à l'utilisateur pour intervenir
RAPPEL_ALERTE = 900            # pas deux alertes Telegram à moins de 15 minutes pour la même page


# Lit, dans la page, uniquement les éléments VISIBLES de chaque ligne de chapitre
_JS_ZONES_VISIBLES = r"""() => [...document.querySelectorAll('.list_chapters')].map(z => {
  const visible = e => {
    for (let n = e; n && n !== z.parentElement; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
      if (cs.clipPath && cs.clipPath !== 'none') return false;
    }
    const r = e.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  const items = [...z.querySelectorAll('*')].filter(visible).map(e => ({
    tag: e.tagName.toLowerCase(),
    text: ((e.innerText || e.textContent) || '').trim().slice(0, 80),
    href: e.getAttribute('href'),
    attrs: Object.fromEntries([...e.attributes].filter(a => !['class', 'style', 'href'].includes(a.name)).map(a => [a.name, a.value.slice(0, 60)])),
  }));
  return {items};
})"""


# Le lecteur demande-t-il un captcha ? Oui si le script de la page le dit et qu'aucune page n'est encore affichée
_JS_CAPTCHA_PRESENT = r"""() => {
  const demande = [...document.querySelectorAll('script:not([src])')].some(s => /__captcha\s*=\s*\{\s*needed\s*:\s*true/.test(s.textContent || ''));
  if (!demande) return false;
  const pageVisible = [...document.querySelectorAll('canvas')].some(c => c.getBoundingClientRect().height > 100)
    || [...document.querySelectorAll('img')].some(i => i.naturalWidth >= 300 && i.naturalHeight >= 300);
  return !pageVisible;
}"""

# Zone du captcha d'images (fenêtre « Vérification humaine ») : sert à zoomer la capture sur le téléphone
_JS_ZONE_CAPTCHA = r"""() => {
  const imgs = [...document.querySelectorAll('img')].filter(i => (i.currentSrc || i.src || '').startsWith('data:image/jpeg') && i.getBoundingClientRect().width > 100);
  if (imgs.length < 2) return null;
  let n = imgs[0], r = null;
  for (let k = 0; k < 8 && n.parentElement; k++) {
    n = n.parentElement;
    const b = n.getBoundingClientRect();
    if (/Vérification humaine|Valider/i.test(n.innerText || '') && b.height > 150 && b.width < innerWidth - 20) { r = b; break; }
  }
  if (!r) {
    const bs = imgs.map(i => i.getBoundingClientRect());
    const x1 = Math.min(...bs.map(b => b.left)) - 20, y1 = Math.min(...bs.map(b => b.top)) - 80;
    const x2 = Math.max(...bs.map(b => b.right)) + 20, y2 = Math.max(...bs.map(b => b.bottom)) + 90;
    r = {x: x1, y: y1, width: x2 - x1, height: y2 - y1};
  }
  const x = Math.max(0, Math.floor(r.x)), y = Math.max(0, Math.floor(r.y));
  const w = Math.min(innerWidth - x, Math.ceil(r.width)), h = Math.min(innerHeight - y, Math.ceil(r.height));
  return (w > 80 && h > 80) ? {x, y, width: w, height: h} : null;
}"""

# Décrit ce que contient la page du lecteur (pour le rapport)
_JS_INFO_LECTEUR = r"""() => {
  const court = u => (u || '').split('?')[0].replace(/^https?:\/\//, '').slice(0, 80);
  const imgs = [...document.querySelectorAll('img')];
  const cans = [...document.querySelectorAll('canvas')];
  const gros = imgs.filter(i => i.naturalWidth >= 300 && i.naturalHeight >= 300);
  return {
    titre: document.title, url: location.pathname,
    nImg: imgs.length, nImgGrandes: gros.length, nCanvas: cans.length,
    grandes: gros.slice(0, 4).map(i => ({src: court(i.currentSrc || i.src), w: i.naturalWidth, h: i.naturalHeight, cls: (i.className || '').toString().slice(0, 30), parent: (i.parentElement && (i.parentElement.id || i.parentElement.className) || '').toString().slice(0, 30)})),
    canvas: cans.slice(0, 4).map(c => ({w: c.width, h: c.height, cls: (c.className || '').toString().slice(0, 30), id: c.id})),
    gl: (() => { try { const c = document.createElement('canvas'); const g = c.getContext('webgl') || c.getContext('experimental-webgl'); if (!g) return 'indisponible'; const e = g.getExtension('WEBGL_debug_renderer_info'); return String(e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : g.getParameter(g.RENDERER)).slice(0, 80); } catch (x) { return 'erreur'; } })(),
    nPages: (document.querySelector('select#pages') || {options: []}).options.length,
    stockage: Object.keys(localStorage).slice(0, 8).map(k => k + '=' + String(localStorage.getItem(k) || '').slice(0, 50)),
    cookies: document.cookie.split(';').map(c => c.split('=')[0].trim()).filter(Boolean).slice(0, 12),
    texte: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 300),
  };
}"""


# Structure du lecteur (pour le rapport) : où sont les pages, comment passer à la suivante
_JS_STRUCTURE_LECTEUR = r"""() => {
  const nom = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + ((e.className && e.className.toString().trim()) ? '.' + e.className.toString().trim().split(/\s+/).slice(0, 3).join('.') : '');
  const court = u => (u || '').split('?')[0].replace(/^https?:\/\//, '').slice(0, 70);
  const res = {};
  res.selects = [...document.querySelectorAll('select')].slice(0, 4).map(s => ({nom: nom(s), n: s.options.length, debut: [...s.options].slice(0, 3).map(o => (o.text + '=' + o.value).slice(0, 40))}));
  res.nav = [...document.querySelectorAll('a, button')].filter(e => /suiv|préc|prec|next|prev|page|»|«|›|‹/i.test((e.innerText || e.title || e.getAttribute('aria-label') || '').trim()) && (e.innerText || '').length < 30).slice(0, 8).map(e => nom(e) + ' « ' + (e.innerText || e.title || '').trim().slice(0, 20) + ' » ' + court(e.getAttribute('href')));
  res.scripts = [...document.querySelectorAll('script[src]')].map(s => court(s.src)).slice(0, 10);
  res.inline = [...document.querySelectorAll('script:not([src])')].map(s => s.textContent).filter(t => /page|image|canvas|chap|scan/i.test(t)).slice(0, 3).map(t => t.replace(/\s+/g, ' ').slice(0, 260));
  const cible = [...document.querySelectorAll('body *')].filter(e => e.children.length < 12 && /^\s*Page\s*1\s*$/.test(e.innerText || '')).slice(-1)[0];
  if (cible) {
    const chaine = []; for (let n = cible, i = 0; n && n !== document.body && i < 6; n = n.parentElement, i++) chaine.push(nom(n));
    res.chaine = chaine;
    const conteneur = cible.parentElement && cible.parentElement.parentElement || cible.parentElement;
    res.autour = [...conteneur.children].slice(0, 12).map(e => nom(e) + ' ' + Math.round(e.getBoundingClientRect().width) + 'x' + Math.round(e.getBoundingClientRect().height) + ' [' + (e.innerText || '').replace(/\s+/g, ' ').slice(0, 25) + ']');
  }
  res.imgs = [...document.querySelectorAll('img')].slice(0, 8).map(i => court(i.currentSrc || i.src) + ' ' + i.naturalWidth + 'x' + i.naturalHeight + ' ' + nom(i));
  res.canvas = [...document.querySelectorAll('canvas')].slice(0, 8).map(c => nom(c) + ' ' + c.width + 'x' + c.height + ' css:' + Math.round(c.getBoundingClientRect().width) + 'x' + Math.round(c.getBoundingClientRect().height) + (c.parentElement ? ' dans ' + nom(c.parentElement) : ''));
  return res;
}"""

# Extrait les pages telles qu'on les voit : canvas (images remises en ordre par le site) ou grandes images
_JS_EXTRAIRE_PAGES = r"""async () => {
  const out = [];
  const els = [...document.querySelectorAll('canvas, img')].filter(e => {
    const w = e.naturalWidth || e.width, h = e.naturalHeight || e.height;
    return w >= 300 && h >= 300;
  });
  for (const e of els) {
    try {
      if (e.tagName === 'CANVAS') {
        out.push({type: 'canvas', data: e.toDataURL('image/png')});
      } else {
        const r = await fetch(e.currentSrc || e.src, {credentials: 'include'});
        const b = await r.blob();
        const data = await new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(b); });
        out.push({type: 'img', data});
      }
    } catch (err) { out.push({type: 'erreur', data: String(err).slice(0, 80)}); }
  }
  return out;
}"""

_HISTORIQUE = []     # derniers événements de vérification (pour le rapport de l'appli)


def _noter(texte: str) -> None:
    ligne = f"{datetime.now().strftime('%H:%M:%S')} {texte}"
    _HISTORIQUE.append(ligne)
    del _HISTORIQUE[:-60]
    logger.info("Vérification : " + texte)


def _surveiller(page) -> None:
    """Note dans l'historique les échecs réseau et erreurs de la page (15 au plus), pour comprendre un blocage Cloudflare."""
    n = {"v": 0}

    def court(u):
        return re.sub(r"\?.*", "", u)[:110]

    def note(t):
        if n["v"] < 15:
            n["v"] += 1
            _noter(t)
    page.on("requestfailed", lambda r: note(f"réseau en échec : {court(r.url)} ({(r.failure or '')[:50]})"))
    page.on("response", lambda r: note(f"réponse {r.status} : {court(r.url)}") if r.status >= 400 else None)
    page.on("console", lambda m: note(f"console : {m.text[:110]}") if m.type == "error" else None)


def verif_historique() -> list:
    return list(_HISTORIQUE)


def verif_etat() -> dict:
    """État lu par l'appli : une vérification attend-elle l'utilisateur ?"""
    with _VERIF_VERROU:
        return {"actif": _VERIF["actif"], "depuis": _VERIF["depuis"], "url": _VERIF["url"]}


def _sur_la_boucle(coro_fn, timeout: float = 20):
    """Exécute une action sur la page depuis un autre thread (celui de Flask)."""
    with _VERIF_VERROU:
        boucle, page, actif = _VERIF["loop"], _VERIF["page"], _VERIF["actif"]
    if not actif or boucle is None or page is None:
        raise RuntimeError("Aucune vérification en attente")
    return asyncio.run_coroutine_threadsafe(coro_fn(page), boucle).result(timeout)


def verif_capture() -> bytes:
    """Capture d'écran (JPEG léger, pour aller vite) du navigateur du serveur."""
    async def f(page):
        return await page.screenshot(type="jpeg", quality=55)
    return _sur_la_boucle(f)


def verif_defiler(dy: float) -> None:
    """Fait défiler la page du navigateur du serveur (pour atteindre un captcha placé plus bas)."""
    async def f(page):
        await page.mouse.move(640, 400)
        await page.mouse.wheel(0, dy)
    _sur_la_boucle(f)


def verif_glisser(points: list) -> dict:
    """Glisse le doigt de l'utilisateur dans le navigateur du serveur (captcha à remettre en ordre)."""
    async def f(page):
        reel = await _glisser_reel(page, points)
        if not reel:
            await page.mouse.move(points[0][0], points[0][1])
            await page.mouse.down()
            for x, y in points[1:]:
                await page.mouse.move(x, y, steps=2)
                await asyncio.sleep(0.02)
            await page.mouse.up()
        await asyncio.sleep(0.7)
        return {"mode": "souris écran" if reel else "automatisation", "captcha": await _captcha_present(page)}
    info = _sur_la_boucle(f, timeout=40)
    _noter(f"glissement ({len(points)} points) → mode {info['mode']}, captcha encore présent : {'oui' if info['captcha'] else 'non'}")
    return info


def verif_capture_zoom():
    """Capture du navigateur du serveur ; si un captcha d'images est affiché, la capture est recadrée dessus
    (beaucoup plus lisible sur un téléphone). Renvoie (image JPEG, zone recadrée ou None)."""
    async def f(page):
        zone = None
        try:
            zone = await page.evaluate(_JS_ZONE_CAPTCHA)
        except Exception:
            zone = None
        options = {"type": "jpeg", "quality": 60}
        if zone:
            options["clip"] = zone
        try:
            return await page.screenshot(**options), zone
        except Exception:
            return await page.screenshot(type="jpeg", quality=60), None
    return _sur_la_boucle(f)


def verif_clic(x: float, y: float) -> dict:
    """Clique à cet endroit de la page (coordonnées de la capture) et renvoie ce que le site répond ensuite."""
    async def f(page):
        reel = await _clic_reel(page, x, y)
        if not reel:
            await page.mouse.move(x - 14, y - 8, steps=5)
            await asyncio.sleep(0.2)
            await page.mouse.move(x, y, steps=3)
            await asyncio.sleep(0.12)
            await page.mouse.click(x, y, delay=80)
        # Laisse Cloudflare réagir : jusqu'à 25 s, on s'arrête dès que le titre n'est plus celui du défi
        debut = time.time()
        await asyncio.sleep(2.5)
        while time.time() - debut < 25:
            try:
                if not _titre_defi((await page.title()) or ""):
                    break
            except Exception:
                break
            await asyncio.sleep(1)
        info = {"titre": "", "cookie": False, "texte": "", "cadres": 0, "mode": "souris écran" if reel else "automatisation",
                "attente": round(time.time() - debut), "empreinte": ""}
        try:
            info["empreinte"] = await page.evaluate("""() => JSON.stringify({
                webdriver: navigator.webdriver, langues: navigator.languages, fuseau: Intl.DateTimeFormat().resolvedOptions().timeZone,
                plateforme: navigator.platform, ua: navigator.userAgent.slice(0, 90), focus: document.hasFocus(),
                ecran: [screen.width, screen.height, devicePixelRatio]})""")
            info["titre"] = (await page.title()) or ""
            info["cookie"] = any(c["name"] == "cf_clearance" for c in await page.context.cookies())
            info["cadres"] = len(page.frames)
            texte = await page.evaluate("() => document.body ? document.body.innerText : ''")
            info["texte"] = re.sub(r"\s+", " ", texte)[:140]
        except Exception as e:
            info["texte"] = f"(lecture impossible : {e.__class__.__name__})"
        return info
    info = _sur_la_boucle(f, timeout=40)
    _noter(f"clic {info['mode']} ({x:.0f},{y:.0f}) → titre « {info['titre']} », cf_clearance {'présent' if info['cookie'] else 'absent'}, "
           f"{info['cadres']} cadre(s), après {info['attente']} s, texte : {info['texte']}")
    _noter("empreinte du navigateur : " + info["empreinte"])
    return info


def _alerter_telegram(url_page: str, raison: str = "cloudflare"):
    """Prévient sur Telegram à chaque nouvelle demande (nouvelle page ou autre raison) ;
    pour la même page et la même raison, au plus une fois par RAPPEL_ALERTE."""
    cle = (raison, url_page)
    with _VERIF_VERROU:
        if time.time() - _VERIF["alertes"].get(cle, 0.0) < RAPPEL_ALERTE:
            return
        _VERIF["alertes"][cle] = time.time()
    try:
        import notifier
        base = os.getenv("APP_URL", "").strip().rstrip("/")
        lien = f"\n\n👉 {base}/verification" if base else "\n\nOuvre MouFlanga → Télécharger : la vérification t'attend."
        if raison == "captcha":
            texte = ("🛡️ MouFlanga : le site demande un captcha avant d'afficher les pages du chapitre. "
                     "Le téléchargement est en pause en attendant ta réponse.")
        else:
            texte = ("🛡️ MouFlanga : Cloudflare demande une vérification humaine. "
                     "Le téléchargement est en pause en attendant ton clic.")
        ok, msg = notifier.envoyer(texte + lien)
        logger.info("Alerte Telegram : %s", msg if not ok else "envoyée")
    except Exception as e:
        logger.warning(f"Alerte Telegram impossible : {e}")


def _titre_defi(titre: str) -> bool:
    return (not titre) or any(k in titre.lower() for k in CHALLENGE_TITRES)


async def attendre_cloudflare(page, secondes: int = 25, humain: bool = False) -> str:
    """Attend la fin du défi Cloudflare ; renvoie le titre final.

    1) quelques secondes pour la vérification automatique (avec un clic de tentative sur la case) ;
    2) si humain=True et que le défi est toujours là : alerte Telegram puis attente de l'utilisateur
       (il passe la vérification depuis la page « Vérification » de l'appli).
    """
    titre = ""
    for i in range(secondes):
        try:
            titre = (await page.title()) or ""
        except Exception:
            titre = ""  # page en cours de navigation
        if not _titre_defi(titre):
            return titre
        if i >= 4 and i % 6 == 4:
            await _cliquer_case_cloudflare(page)
        await asyncio.sleep(1)

    if not humain:
        logger.warning(f"Défi Cloudflare non résolu (titre : {titre!r})")
        return titre

    # --- vérification humaine ---
    logger.warning("Cloudflare demande une vérification humaine : en attente de l'utilisateur")
    _noter(f"vérification demandée sur {page.url}")
    with _VERIF_VERROU:
        _VERIF.update(actif=True, loop=asyncio.get_running_loop(), page=page, depuis=time.time(), url=page.url)
    try:
        await asyncio.to_thread(_alerter_telegram, page.url)
        fin = time.time() + PATIENCE_HUMAIN
        while time.time() < fin:
            await asyncio.sleep(2)
            try:
                titre = (await page.title()) or ""
            except Exception:
                continue
            if not _titre_defi(titre):
                _noter(f"✓ vérification passée (titre « {titre} »)")
                await asyncio.sleep(1)
                return titre
        _noter("✗ vérification non faite dans le temps imparti")
        return titre
    finally:
        with _VERIF_VERROU:
            _VERIF.update(actif=False, loop=None, page=None)


async def _pages_annoncees(page) -> int:
    """Nombre de pages que le lecteur annonce (liste déroulante des pages), 0 si inconnu."""
    try:
        return int(await page.evaluate("() => (document.querySelector('select#pages') || {options: []}).options.length") or 0)
    except Exception:
        return 0


async def _captcha_present(page) -> bool:
    """Le lecteur du site réclame-t-il un captcha avant d'afficher les pages ?"""
    try:
        # On lit le DOM (et non window.__captcha) : Camoufox exécute les scripts dans un monde isolé
        # où les variables de la page sont invisibles
        return bool(await page.evaluate(_JS_CAPTCHA_PRESENT))
    except Exception:
        return False   # page en cours de rechargement


async def attendre_captcha(page) -> bool:
    """Si le lecteur affiche un captcha, prévient l'utilisateur et attend qu'il le résolve
    (depuis la page « Vérification » de l'appli). Renvoie True si la page est utilisable."""
    if not await _captcha_present(page):
        return True
    logger.warning("Le lecteur demande un captcha : en attente de l'utilisateur")
    _noter(f"captcha demandé sur {page.url}")
    with _VERIF_VERROU:
        _VERIF.update(actif=True, loop=asyncio.get_running_loop(), page=page, depuis=time.time(), url=page.url)
    try:
        await asyncio.to_thread(_alerter_telegram, page.url, "captcha")
        fin = time.time() + PATIENCE_HUMAIN
        while time.time() < fin:
            await asyncio.sleep(2)
            if not await _captcha_present(page):
                _noter("✓ captcha résolu")
                await asyncio.sleep(3)
                return True
        _noter("✗ captcha non résolu dans le temps imparti")
        return False
    finally:
        with _VERIF_VERROU:
            _VERIF.update(actif=False, loop=None, page=None)


logger = logging.getLogger("japscan_scraper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

JAPSCAN_URL = "https://www.japscan.foo"

PROFIL = Path(os.environ.get("JAPSCAN_PROFIL", Path(__file__).resolve().parent / "data" / "navigateur"))
_VERROU = threading.Lock()


def _installer_chrome() -> bool:
    """Installe Google Chrome via Patchright (une tentative par heure au maximum). Renvoie True si c'est fait."""
    import subprocess
    import sys
    marque = PROFIL.parent / "chrome-install-tente"
    try:
        if marque.exists() and time.time() - marque.stat().st_mtime < 3600:
            return False
        marque.parent.mkdir(parents=True, exist_ok=True)
        marque.write_text(datetime.now().isoformat())
        logger.info("Installation de Google Chrome (2 à 5 minutes, une seule fois)...")
        r = subprocess.run([sys.executable, "-m", "patchright", "install", "chrome"],
                           capture_output=True, text=True, timeout=900)
        if r.returncode == 0:
            marque.unlink(missing_ok=True)
            logger.info("✓ Google Chrome installé")
            return True
        logger.warning("Installation de Chrome échouée : " + (r.stderr or r.stdout)[-300:])
    except Exception as e:
        logger.warning(f"Installation de Chrome impossible : {e}")
    return False


MARQUE_CAMOUFOX = PROFIL.parent / "camoufox-installe"
PROFIL_FIREFOX = Path(os.environ.get("JAPSCAN_PROFIL_FIREFOX", PROFIL.parent / "navigateur-firefox"))
_INSTALL_CAMOUFOX = {"etat": "", "en_cours": False}


def moteur() -> str:
    """Navigateur choisi dans ⚙ Réglages : « chrome » (par défaut) ou « camoufox » (Firefox anti-détection)."""
    return "camoufox" if os.environ.get("JAPSCAN_MOTEUR", "").strip().lower() == "camoufox" else "chrome"


def camoufox_etat() -> dict:
    """État pour la page Réglages : module Python présent ? navigateur téléchargé ? installation en cours ?"""
    try:
        import importlib.util
        module = importlib.util.find_spec("camoufox") is not None
    except Exception:
        module = False
    return {"moteur": moteur(), "module": module, "navigateur": MARQUE_CAMOUFOX.exists(),
            "en_cours": _INSTALL_CAMOUFOX["en_cours"], "message": _INSTALL_CAMOUFOX["etat"]}


def _installer_camoufox() -> bool:
    """Télécharge le navigateur de Camoufox (gros fichier, une seule fois). Renvoie True si c'est fait."""
    import subprocess
    import sys
    if _INSTALL_CAMOUFOX["en_cours"]:
        return False
    _INSTALL_CAMOUFOX.update(en_cours=True, etat="Installation de Camoufox en cours (quelques minutes)…")
    try:
        logger.info("Installation de Camoufox (téléchargement du navigateur, une seule fois)...")
        r = subprocess.run([sys.executable, "-m", "camoufox", "fetch"], capture_output=True, text=True, timeout=1500)
        if r.returncode == 0:
            MARQUE_CAMOUFOX.parent.mkdir(parents=True, exist_ok=True)
            MARQUE_CAMOUFOX.write_text(datetime.now().isoformat())
            _INSTALL_CAMOUFOX["etat"] = "✅ Camoufox installé."
            logger.info("✓ Camoufox installé")
            return True
        _INSTALL_CAMOUFOX["etat"] = "❌ Installation échouée : " + (r.stderr or r.stdout or "").strip()[-200:]
        logger.warning(_INSTALL_CAMOUFOX["etat"])
    except Exception as e:
        _INSTALL_CAMOUFOX["etat"] = f"❌ Installation impossible : {e.__class__.__name__} {e}"[:250]
        logger.warning(_INSTALL_CAMOUFOX["etat"])
    finally:
        _INSTALL_CAMOUFOX["en_cours"] = False
    return False


def installer_camoufox_en_fond() -> None:
    threading.Thread(target=_installer_camoufox, daemon=True).start()


def _hosts_brunhild() -> None:
    """Firefox n'a pas l'équivalent de la redirection de Chrome : on note brunhild.challenges.cloudflare.com
    (qui n'existe qu'en IPv6) avec une adresse IPv4 de Cloudflare dans /etc/hosts, si le serveur y a droit."""
    try:
        ip4 = socket.getaddrinfo("challenges.cloudflare.com", 443, socket.AF_INET)[0][4][0]
        marque = "# MouFlanga-cloudflare"
        chemin = Path("/etc/hosts")
        lignes = [l for l in chemin.read_text(encoding="utf-8").splitlines() if marque not in l]
        lignes.append(f"{ip4} brunhild.challenges.cloudflare.com {marque}")
        chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    except Exception as e:
        logger.info(f"Redirection IPv4 de brunhild impossible ({e.__class__.__name__}) : on continue sans")


_XVFB = {"proc": None}


def _assurer_ecran() -> None:
    """Sans écran (service lancé sans xvfb-run), démarre un écran virtuel Xvfb pour le navigateur."""
    if os.environ.get("DISPLAY"):
        return
    import shutil
    import subprocess
    exe = shutil.which("Xvfb")
    if not exe:
        raise RuntimeError("Aucun écran disponible et Xvfb n'est pas installé (apt-get install xvfb)")
    lecture, ecriture = os.pipe()
    try:
        proc = subprocess.Popen([exe, "-displayfd", str(ecriture), "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
                                pass_fds=(ecriture,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(ecriture)
        ecriture = -1
        numero = os.read(lecture, 16).decode().strip()   # Xvfb écrit son numéro d'écran quand il est prêt
        if not numero.isdigit():
            raise RuntimeError("Xvfb n'a pas démarré")
        _XVFB["proc"] = proc
        os.environ["DISPLAY"] = f":{numero}"
        logger.info(f"Écran virtuel démarré (:{numero})")
    finally:
        os.close(lecture)
        if ecriture != -1:
            os.close(ecriture)


class _Session:
    """Ferme le navigateur puis libère le verrou (appelé comme browser.close())."""

    def __init__(self, context, gestionnaire=None):
        self._context = context
        self._gestionnaire = gestionnaire     # contexte Camoufox à refermer après le navigateur
        self._ferme = False

    async def close(self):
        if self._ferme:
            return
        self._ferme = True
        try:
            await self._context.close()
        except Exception:
            pass
        try:
            if self._gestionnaire is not None:
                await self._gestionnaire.__aexit__(None, None, None)
        except Exception:
            pass
        finally:
            _VERROU.release()


# État global des téléchargements (pour Flask)
download_jobs = {}


class JapscanScraper:
    """Scraper Japscan v2.0 avec interception réseau pour contourner Cloudflare."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def _init_browser(self, p):
        """Lance le navigateur sous Xvfb avec un profil persistant (les cookies Cloudflare sont gardés).

        Patchright recommande : vrai Chrome si possible, pas de faux user-agent ni de taille imposée.
        Un seul navigateur à la fois (le profil ne peut pas être partagé) : un verrou protège l'accès.
        """
        _VERROU.acquire()
        try:
            _assurer_ecran()
            PROFIL.mkdir(parents=True, exist_ok=True)
            if moteur() == "camoufox":
                ctx = await self._lancer_camoufox()
                if ctx is not None:
                    return ctx
                logger.warning("Camoufox indisponible : retour à Google Chrome")
            args_cf = []
            try:
                # brunhild.challenges.cloudflare.com n'existe qu'en IPv6 : sans IPv6 sur le serveur, le défi ne peut pas
                # s'achever. On le redirige vers une adresse IPv4 de Cloudflare (le nom reste le même pour le chiffrement).
                ip4 = socket.getaddrinfo("challenges.cloudflare.com", 443, socket.AF_INET)[0][4][0]
                args_cf = [f"--host-resolver-rules=MAP *.challenges.cloudflare.com {ip4}"]
            except OSError:
                pass
            options = dict(
                user_data_dir=str(PROFIL),
                headless=False,  # Lancé via xvfb-run sur serveur
                no_viewport=True,
                locale="fr-FR",
                timezone_id="Europe/Paris",
                args=[
                    "--no-sandbox", "--disable-setuid-sandbox",
                    "--window-size=1280,960",  # doit tenir dans l'écran virtuel (1280x1024 par défaut)
                    # Pas de carte graphique sur le serveur : on active le rendu WebGL logiciel,
                    # sinon le navigateur annonce « WebGL indisponible », typique d'un robot
                    "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                    "--ignore-gpu-blocklist", "--enable-webgl",
                    *args_cf,
                ],
            )
            try:
                context = await p.chromium.launch_persistent_context(channel="chrome", **options)
                logger.info("Navigateur : Google Chrome")
            except Exception as e:
                logger.info(f"Chrome indisponible ({str(e).splitlines()[0][:80]})")
                context = None
                if _installer_chrome():
                    try:
                        context = await p.chromium.launch_persistent_context(channel="chrome", **options)
                        logger.info("Navigateur : Google Chrome (tout juste installé)")
                    except Exception as e2:
                        logger.warning(f"Chrome installé mais inutilisable : {str(e2).splitlines()[0][:100]}")
                if context is None:
                    logger.info("Navigateur : Chromium (moins bien accepté par Cloudflare)")
                    context = await p.chromium.launch_persistent_context(**options)
            return _Session(context), context
        except Exception:
            _VERROU.release()
            raise

    async def _lancer_camoufox(self):
        """Lance Camoufox (Firefox anti-détection) avec un profil persistant. Renvoie (_Session, context) ou None."""
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError:
            logger.warning("Le module Python « camoufox » n'est pas installé (il arrive avec le prochain déploiement)")
            return None
        _hosts_brunhild()
        PROFIL_FIREFOX.mkdir(parents=True, exist_ok=True)
        base = dict(headless=False, persistent_context=True, user_data_dir=str(PROFIL_FIREFOX),
                    locale="fr-FR", os="linux", humanize=False, geoip=False)
        for tentative in range(2):
            for extra in ({"window": (1280, 960)}, {}):      # « window » n'existe que dans les versions récentes
                gestionnaire = AsyncCamoufox(**base, **extra)
                try:
                    context = await gestionnaire.__aenter__()
                    logger.info("Navigateur : Camoufox (Firefox)")
                    return _Session(context, gestionnaire), context
                except TypeError:
                    continue
                except Exception as e:
                    logger.warning(f"Camoufox ne démarre pas : {e.__class__.__name__} {str(e).splitlines()[0][:120] if str(e) else ''}")
                    break
            if tentative == 0 and not MARQUE_CAMOUFOX.exists() and _installer_camoufox():
                continue
            break
        return None      # le verrou reste tenu : _init_browser enchaîne sur Chrome

    async def _chauffer(self, page):
        """Passe d'abord par la page d'accueil (comme un vrai visiteur) pour obtenir le cookie Cloudflare."""
        try:
            await page.goto(JAPSCAN_URL + "/", wait_until="domcontentloaded", timeout=30000)
            await attendre_cloudflare(page, humain=True)
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"Page d'accueil non chargée : {e}")

    def extract_manga_root_url(self, url: str) -> str:
        """Nettoie une URL de chapitre pour obtenir l'URL racine de la série."""
        match = re.match(r"^(https?://[^/]+/(?:manga|manhua|manhwa)/[^/]+/).*", url)
        if match:
            return match.group(1)
        return url

    async def list_manga(self) -> list[dict]:
        """Liste les mangas disponibles."""
        logger.info("Récupération de la liste des mangas...")
        mangas = []

        async with async_playwright() as p:
            browser, context = await self._init_browser(p)
            page = await context.new_page()

            try:
                # Essaie plusieurs endpoints - / fonctionne le mieux
                endpoints = ["/", "/mangas/", "/listing", "/series"]
                html = None

                for endpoint in endpoints:
                    url = f"{JAPSCAN_URL}{endpoint}"
                    logger.info(f"Essai endpoint : {url}")
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        await attendre_cloudflare(page, humain=True)
                        await asyncio.sleep(2)
                        html = await page.content()
                        if html and len(html) > 1000:
                            logger.info(f"✓ Endpoint {endpoint} chargé ({len(html)} caractères)")
                            break
                    except Exception as e:
                        logger.warning(f"Erreur endpoint {endpoint}: {e}")
                        continue

                if not html:
                    logger.error("Impossible de charger la liste des mangas")
                    await browser.close()
                    return []

                soup = BeautifulSoup(html, "html.parser")
                seen_urls = set()

                # Sélecteurs pour trouver les mangas
                selectors = [
                    "a[href*='/manga/']",
                    "a[href*='/manhua/']",
                    "a[href*='/manhwa/']",
                    "a.image-box",
                ]

                for selector in selectors:
                    try:
                        matches = soup.select(selector)
                        logger.info(f"Sélecteur '{selector}' : {len(matches)} matches")

                        for item in matches:
                            try:
                                title = item.get_text(strip=True)
                                href = item.get("href", "")

                                if not title or not href:
                                    continue

                                if not any(x in href.lower() for x in ["manga", "manhua", "manhwa"]):
                                    continue

                                url = urljoin(JAPSCAN_URL, href)
                                if url in seen_urls or url == JAPSCAN_URL:
                                    continue

                                seen_urls.add(url)
                                mangas.append({
                                    "title": title,
                                    "url": url,
                                    "id": hashlib.md5(url.encode()).hexdigest()[:12]
                                })
                            except Exception as e:
                                logger.debug(f"Erreur parsing item: {e}")
                                continue
                    except Exception as e:
                        logger.debug(f"Erreur sélecteur '{selector}': {e}")
                        continue

                await browser.close()
                logger.info(f"✓ {len(mangas)} mangas trouvés au total")
                return mangas

            except Exception as e:
                logger.error(f"Erreur liste mangas: {e}")
                await browser.close()
                return []

    async def get_chapters(self, manga_url: str) -> list[dict]:
        """Récupère la liste des chapitres d'un manga."""
        manga_url = self.extract_manga_root_url(manga_url)
        logger.info(f"Chargement de la fiche série : {manga_url}")

        async with async_playwright() as p:
            browser, context = await self._init_browser(p)
            page = await context.new_page()
            _surveiller(page)

            # Requêtes de données (XHR/fetch) faites par la page : la liste complète des chapitres
            # est peut-être chargée à part
            xhr = []

            def _noter_xhr(r):
                try:
                    if r.request.resource_type in ("xhr", "fetch") and "cloudflare" not in r.url and len(xhr) < 40:
                        xhr.append((r.status, r.url.split("?")[0]))
                except Exception:
                    pass
            page.on("response", _noter_xhr)

            try:
                # domcontentloaded au lieu de networkidle pour éviter les timeouts
                await self._chauffer(page)
                await page.goto(manga_url, wait_until="domcontentloaded", timeout=30000)

                title = await attendre_cloudflare(page, humain=True)

                # Juste après la vérification, le site affiche « Loading … » puis recharge la vraie page :
                # on attend (40 s au plus) que le titre change et que des liens de chapitres apparaissent
                debut = time.time()
                while time.time() - debut < 40:
                    try:
                        title = (await page.title()) or ""
                        n_liens = await page.evaluate(
                            "() => [...document.querySelectorAll('a[href]')].filter(a => /\\/(manga|manhua|manhwa)\\/[^/]+\\/[^/]*\\d[^/]*\\/?$/.test(a.getAttribute('href'))).length")
                    except Exception:
                        n_liens = 0   # la page est en train de se recharger
                    if n_liens and not title.lower().startswith("loading") and not _titre_defi(title):
                        break
                    await asyncio.sleep(2)
                await asyncio.sleep(1)
                # Défilement progressif : certaines listes ne se remplissent qu'au passage de l'écran
                try:
                    for _ in range(10):
                        await page.mouse.wheel(0, 1500)
                        await asyncio.sleep(0.5)
                    await asyncio.sleep(2)
                except Exception:
                    pass
                html = await page.content()
                logger.info(f"Fiche série chargée : titre={title!r}, {len(html)} caractères")

                # Dump de debug pour analyse hors-ligne
                try:
                    Path("/tmp/japscan_series_debug.html").write_text(html, encoding="utf-8")
                except Exception:
                    pass

                soup = BeautifulSoup(html, "html.parser")
                slug_match = re.search(r"/(?:manga|manhua|manhwa)/([^/]+)/?", manga_url)
                slug = slug_match.group(1) if slug_match else None
                chapters = []
                seen_urls = set()

                # Tous les liens pointant vers /<type>/<slug>/<numéro>/ de CETTE série
                pattern = re.compile(
                    r"/(?:manga|manhua|manhwa|lecture-en-ligne|chapitre)/" + (re.escape(slug) if slug else r"[^/]+") + r"/([\w.\-]+)/?$"
                )
                # Pour le rapport : à quoi ressemblent les liens de cette série (aucune donnée personnelle)
                try:
                    liens = [(a["href"], a.get_text(strip=True)[:30]) for a in soup.find_all("a", href=True)
                             if slug and f"/{slug}/" in a["href"]]
                    _noter(f"fiche série : {len(liens)} lien(s) contenant « {slug} »")
                    for h, t in (liens[:6] + liens[-4:] if len(liens) > 10 else liens):
                        _noter(f"  lien {re.sub(r'^https?://[^/]+', '', h)[:70]} → « {t} »")
                    zones = [(e.name, " ".join(e.get("class", []))[:40], len(e.find_all("a")))
                             for e in soup.find_all(True, class_=re.compile("chapter|chapitre|episode", re.I))][:6]
                    _noter(f"  zones « chapitres » : {zones}")
                    # Regroupe les liens par forme (les chiffres deviennent N) pour voir les familles de liens
                    formes = {}
                    for h, t in liens:
                        f = re.sub(r"\d+", "N", re.sub(r"^https?://[^/]+", "", h))[:60]
                        formes.setdefault(f, []).append((h, t))
                    for f, lst in sorted(formes.items(), key=lambda kv: -len(kv[1]))[:8]:
                        avec = [x for x in lst if x[1]]
                        ex = (avec or lst)[-1]
                        _noter(f"  forme {f} : {len(lst)} lien(s), {len(avec)} avec texte ; ex. {re.sub(r'^https?://[^/]+', '', ex[0])[:50]} → « {ex[1]} »")
                    zone = soup.find(True, class_="list_chapters")
                    if zone is not None:
                        parent = zone.parent
                        brut = re.sub(r"\s+", " ", str(zone))[:350]
                        p_classe = " ".join(parent.get("class", []))[:60]
                        p_id = parent.get("id", "")
                        p_n = len(parent.find_all(True, class_="list_chapters"))
                        _noter(f"  1re zone : {brut}")
                        zones_html = soup.find_all(True, class_="list_chapters")
                        for k in (1, 2, 40):
                            if len(zones_html) > k:
                                _noter(f"  zone n°{k + 1} : " + re.sub(r"\s+", " ", str(zones_html[k]))[:900])
                        attrs = sorted({n for z in zones_html for a in z.find_all("a") for n in a.attrs})
                        _noter(f"  attributs des liens des zones : {attrs}")
                        _noter(f"  nombre de zones « list_chapters » : {len(zones_html)}")
                    nums = [e for e in soup.find_all(True) if re.fullmatch(r"Chapitre 0+\d+", e.get_text(strip=True) or "") and not e.find(True)]
                    _noter(f"  éléments « Chapitre 0000N » : {len(nums)}")
                    for e in nums[:2] + nums[-1:]:
                        _noter("    " + re.sub(r"\s+", " ", str(e))[:300] + " ← parent : " + re.sub(r"\s+", " ", str(e.parent))[:300])
                        _noter(f"  parent : <{parent.name} class={p_classe!r} id={p_id!r}> : {p_n} zone(s) « list_chapters »")
                    boutons = [e.get_text(' ', strip=True)[:25] for e in soup.find_all(["button", "a"])
                               if re.search(r"chapitre|voir|plus|tous|afficher", e.get_text(' ', strip=True), re.I)
                               and len(e.get_text(strip=True)) < 40][:8]
                    _noter(f"  boutons/liens « voir plus » : {boutons}")
                    for st, u in xhr[:10]:
                        _noter(f"  requête de données {st} : {u[:90]}")
                except Exception as e:
                    _noter(f"  diagnostic des liens impossible : {e.__class__.__name__}")
                # Le site noie la vraie liste sous des leurres : liens cachés (d-none) aux numéros en « 222 »,
                # éléments « Chapitre 000001… » rendus invisibles (clip-path, position absolue).
                # On ne garde donc que ce qu'un humain voit réellement à l'écran.
                try:
                    zones_vues = await page.evaluate(_JS_ZONES_VISIBLES)
                except Exception as e:
                    zones_vues = []
                    _noter(f"  lecture des zones visibles impossible : {e.__class__.__name__}")
                try:
                    _noter(f"  zones visibles : {len(zones_vues)}")
                    for k in (0, 1, 40):
                        if len(zones_vues) > k:
                            _noter(f"  zone visible n°{k + 1} : {str(zones_vues[k])[:500]}")
                except Exception:
                    pass
                type_m = re.search(r"/(manga|manhua|manhwa)/", manga_url)
                type_url = type_m.group(1) if type_m else "manga"
                for z in zones_vues:
                    for el in z.get("items", []):
                        txt = (el.get("text") or "").strip()
                        mm = re.search(r"chapitre\s+(\d+(?:\.\d+)?)", txt, re.I)
                        if not mm:
                            continue
                        cid = mm.group(1)
                        full_url = urljoin(JAPSCAN_URL, f"/{type_url}/{slug}/{cid}/") if slug else ""
                        if not full_url or full_url in seen_urls:
                            continue
                        seen_urls.add(full_url)
                        chapters.append({"title": txt.split("\n")[0][:120], "url": full_url, "chapter_id": cid})
                        break
                if chapters:
                    logger.info(f"Chapitres lus depuis les zones visibles : {len(chapters)}")
                for item in ([] if chapters else soup.find_all("a", href=True)):
                    href = item["href"]
                    m = pattern.search(href)
                    if not m or not re.search(r"\d", m.group(1)):
                        continue
                    full_url = urljoin(JAPSCAN_URL, href)
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)
                    chapters.append({
                        "title": item.get_text(strip=True) or f"Chapitre {m.group(1)}",
                        "url": full_url,
                        "chapter_id": m.group(1),
                    })

                # Ordre chronologique (le site liste du plus récent au plus ancien)
                def _key(c):
                    try:
                        return float(c["chapter_id"])
                    except ValueError:
                        return float("inf")
                chapters.sort(key=_key)
                for i, c in enumerate(chapters, 1):
                    c["num"] = i

                await browser.close()
                logger.info(f"✓ {len(chapters)} chapitres trouvés.")
                return chapters

            except Exception as e:
                logger.error(f"Erreur lors de la récupération des chapitres : {e}")
                await browser.close()
                return []

    async def download_chapter_pages(self, chapter_url: str, session=None) -> list[bytes]:
        """Récupère les pages d'un chapitre. Sans « session », ouvre puis ferme son propre navigateur ;
        avec une session (navigateur, contexte) déjà ouverte, la réutilise : plus rapide pour plusieurs chapitres."""
        if session is not None:
            return await self._lire_chapitre(session[1], chapter_url, chauffer=False)
        async with async_playwright() as p:
            browser, context = await self._init_browser(p)
            try:
                return await self._lire_chapitre(context, chapter_url, chauffer=True)
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _ouvrir_session(self, p):
        """Ouvre le navigateur une seule fois pour tout le téléchargement (et passe par l'accueil)."""
        browser, context = await self._init_browser(p)
        try:
            page = await context.new_page()
            _surveiller(page)
            await self._chauffer(page)
            await page.close()
        except Exception as e:
            logger.warning(f"Échauffement du navigateur impossible : {e}")
        return browser, context

    async def _fermer_session(self, session):
        try:
            await session[0].close()
        except Exception:
            pass

    async def _lire_chapitre(self, context, chapter_url: str, chauffer: bool = False) -> list[bytes]:
        """Lit les pages d'un chapitre : d'abord telles qu'affichées (canvas / grandes images),
        sinon en interceptant les images qui passent sur le réseau, dans l'ordre où le lecteur les demande."""
        logger.info(f"Début de l'aspiration du chapitre : {chapter_url}")
        captured_images = {}
        vues = []          # images vues passer sur le réseau (pour le rapport)
        ordre = {}         # adresse -> rang de la demande (le lecteur demande les pages dans l'ordre)
        arrivee = []       # adresses dans l'ordre d'arrivée des réponses
        pages_dom = []
        attendues = None

        page = await context.new_page()
        _surveiller(page)

        def on_request(req):
            if len(ordre) < 5000 and req.url not in ordre:
                ordre[req.url] = len(ordre)

        # Listener d'interception des requêtes d'images
        async def on_response(response):
            try:
                content_type = response.headers.get("content-type", "")
                if "image" in content_type and response.status == 200:
                    url = response.url
                    chemin = url.split("?")[0].lower()
                    body = await response.body()
                    if len(vues) < 12:
                        vues.append(f"{len(body) // 1024} Ko {content_type.split(';')[0]} {re.sub(r'^https?://', '', chemin)[:70]}")
                    # Exclure les éléments d'interface (logos, pubs, avatars, favicons)
                    if not any(k in chemin for k in ["logo", "avatar", "banner", "/ads/", "/ad/", "favicon", "/icons/"]):
                        if len(body) > 15000:  # Exclure les petites images/icônes (< 15 Ko)
                            if url not in captured_images:
                                arrivee.append(url)
                            captured_images[url] = body
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", on_response)

        try:
            if chauffer:
                await self._chauffer(page)
            captured_images.clear()  # ignore les images de la page d'accueil
            vues.clear()
            arrivee.clear()
            ordre.clear()
            await page.goto(chapter_url, wait_until="domcontentloaded", timeout=30000)
            title = await attendre_cloudflare(page, humain=True)

            # Après une vérification, le site affiche « Loading… » avant la vraie page
            debut = time.time()
            while time.time() - debut < 40:
                try:
                    title = (await page.title()) or ""
                except Exception:
                    title = "loading"   # la page se recharge
                if title and not title.lower().startswith("loading") and not _titre_defi(title):
                    break
                await asyncio.sleep(2)
            await asyncio.sleep(4)  # Laisser charger le lecteur JS

            # Le lecteur peut exiger un captcha : l'utilisateur le résout depuis la page « Vérification »
            if not await attendre_captcha(page):
                return []

            # Juste après un captcha, le lecteur reste parfois vide (aucune page annoncée) : on recharge
            # le chapitre une fois, le site se souvient alors du captcha résolu
            if not await _pages_annoncees(page):
                await asyncio.sleep(4)
                if not await _pages_annoncees(page):
                    _noter("  lecteur vide (aucune page annoncée) : rechargement du chapitre")
                    captured_images.clear()
                    arrivee.clear()
                    ordre.clear()
                    await page.goto(chapter_url, wait_until="domcontentloaded", timeout=30000)
                    await attendre_cloudflare(page, humain=True)
                    await asyncio.sleep(6)
                    if not await attendre_captcha(page):
                        return []

            # Défilement progressif vers le bas pour forcer le chargement de toutes les pages
            logger.info("Défilement de la page pour forcer le lazy-loading...")
            for _ in range(15):
                await page.mouse.wheel(0, 1200)
                await asyncio.sleep(0.6)

            # On attend que TOUTES les pages annoncées soient arrivées (le site les charge à son rythme).
            # Sans mouvement pendant 6 s, on « tourne la page » comme un lecteur (touche →) pour relancer le chargement.
            debut = time.time()
            dernier, derniere_variation, attendues = len(captured_images), time.time(), 0
            while time.time() - debut < 150:
                attendues = await _pages_annoncees(page) or attendues
                n = len(captured_images)
                if n != dernier:
                    dernier, derniere_variation = n, time.time()
                if attendues and n >= attendues:
                    break
                calme = time.time() - derniere_variation
                if calme > 25 and (n > 0 or not attendues):
                    break            # plus rien n'arrive (ou lecteur vide) : on prend ce qu'on a
                if calme > 6:
                    try:
                        await page.keyboard.press("ArrowRight")
                    except Exception:
                        pass
                await asyncio.sleep(1)
            _noter(f"  attente des pages : {len(captured_images)} reçues sur {attendues or '?'} annoncées en {round(time.time() - debut)} s")

            # Ce que contient la page (pour le rapport)
            info = {}
            try:
                info = await page.evaluate(_JS_INFO_LECTEUR)
                attendues = info.get("nPages")
                _noter(f"lecteur : {info.get('titre')!r} {info.get('url')} · {info.get('nImg')} img "
                       f"({info.get('nImgGrandes')} grandes), {info.get('nCanvas')} canvas · pages annoncées : {attendues}")
                _noter(f"  mémoire du site (localStorage) : {info.get('stockage')} · cookies : {info.get('cookies')}")
                _noter(f"  rendu graphique annoncé par le navigateur (WebGL) : {info.get('gl')}")
            except Exception as e:
                _noter(f"lecteur : lecture de la page impossible ({e.__class__.__name__})")
            for v in vues[:3]:
                _noter(f"  image réseau : {v}")

            # Pages telles qu'affichées (si le lecteur dessine de vraies pages dans des canvas / grandes images)
            try:
                pages_dom = await page.evaluate(_JS_EXTRAIRE_PAGES)
            except Exception as e:
                _noter(f"  extraction de la page impossible : {e.__class__.__name__}")

        except Exception as e:
            logger.error(f"Erreur lors du chargement du chapitre {chapter_url} : {e}")
        finally:
            try:
                await page.close()
            except Exception:
                pass

        import base64
        from_dom, vus_hash = [], set()
        for b in pages_dom:
            if b.get("type") not in ("canvas", "img") or "," not in b.get("data", ""):
                continue
            try:
                octets = base64.b64decode(b["data"].split(",", 1)[1])
            except Exception:
                continue
            h = hashlib.md5(octets).hexdigest()
            if len(octets) > 15000 and h not in vus_hash:
                vus_hash.add(h)
                from_dom.append(octets)
        a_canvas = any(b.get("type") == "canvas" for b in pages_dom)
        if from_dom and (a_canvas or not captured_images):
            logger.info(f"✓ {len(from_dom)} pages lues dans la page ({'canvas' if a_canvas else 'images'}).")
            return from_dom

        # Sinon : images interceptées sur le réseau, dans l'ordre où le lecteur les a demandées
        # (les noms de fichiers sont des suites de lettres sans ordre : on ne peut pas s'y fier)
        urls = sorted(captured_images.keys(), key=lambda u: (ordre.get(u, 10 ** 9), arrivee.index(u) if u in arrivee else 0))
        decalees = sum(1 for k, u in enumerate(urls) if k < len(arrivee) and arrivee[k] != u)
        _noter(f"  pages : {len(urls)} capturées"
               f"{f' sur {attendues} annoncées' if attendues else ''} · triées par ordre de demande"
               f" · {decalees} arrivée(s) dans un autre ordre que la demande")
        images_bytes = [captured_images[u] for u in urls]
        logger.info(f"✓ {len(images_bytes)} pages capturées sur le réseau.")
        return images_bytes

    def create_cbz(self, pages: list[bytes], output_path: Path) -> bool:
        """Combine les pages capturées dans un fichier .cbz (Archive Zip)."""
        if not pages:
            return False

        logger.info(f"Création de l'archive CBZ : {output_path}")
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for idx, page_data in enumerate(pages, 1):
                    # Déduction de l'extension selon le magic byte
                    ext = "jpg"
                    if page_data.startswith(b"\x89PNG"):
                        ext = "png"
                    elif page_data.startswith(b"RIFF") and page_data[8:12] == b"WEBP":
                        ext = "webp"

                    filename = f"page_{idx:03d}.{ext}"
                    zf.writestr(filename, page_data)

            logger.info(f"✓ CBZ créé avec succès ({len(pages)} pages) -> {output_path}")
            return True
        except Exception as e:
            logger.error(f"Erreur création CBZ : {e}")
            return False

    # ------------------------------------------------------------------
    # Versions synchrones (Flask n'est pas asynchrone)
    # ------------------------------------------------------------------
    def list_manga_sync(self) -> list[dict]:
        return asyncio.run(self.list_manga())

    def get_chapters_sync(self, manga_url: str) -> list[dict]:
        return asyncio.run(self.get_chapters(manga_url))

    async def _telecharger_chapitres(self, job: dict, chapters: list[dict], progress_callback=None):
        """Télécharge les chapitres un par un avec UN SEUL navigateur (plus rapide, moins de vérifications)."""
        job_id = job["id"]
        async with async_playwright() as p:
            session = await self._ouvrir_session(p)
            try:
                echecs_de_suite = 0
                for idx, chapter in enumerate(chapters):
                    if job.get("annule"):
                        job["status"] = "annule"
                        logger.info(f"Téléchargement annulé : {job_id}")
                        break
                    titre = chapter.get("title") or f"Chapitre {idx + 1}"
                    job["en_cours"] = titre
                    try:
                        pages = await self.download_chapter_pages(chapter["url"], session=session)
                        if not pages:
                            logger.warning(f"Aucune page pour {titre}")
                            job["failed"].append(titre)
                            echecs_de_suite += 1
                        else:
                            echecs_de_suite = 0
                            num = int(chapter.get("num") or idx + 1)
                            fichier = self.output_dir / f"{num:03d} - {nom_sur(titre)}.cbz"
                            if self.create_cbz(pages, fichier):
                                job["downloaded"].append(str(fichier))
                            else:
                                job["failed"].append(titre)
                    except Exception as e:
                        logger.error(f"Erreur chapitre {titre} : {e}")
                        job["failed"].append(titre)
                        job["error"] = str(e)

                    job["progress"] = idx + 1
                    if progress_callback:
                        progress_callback(job)

                    # Pause entre deux chapitres, comme un lecteur qui lit (réglable avec JAPSCAN_PAUSE, en secondes ; 0 = aucune)
                    if idx < len(chapters) - 1 and not job.get("annule"):
                        try:
                            base = float(os.environ.get("JAPSCAN_PAUSE", "20"))
                        except ValueError:
                            base = 20.0
                        if base > 0:
                            import random
                            job["en_cours"] = "(pause avant le chapitre suivant)"
                            await asyncio.sleep(random.uniform(base * 0.75, base * 1.5))

                    if echecs_de_suite >= 3:
                        job["status"] = "error"
                        job["error"] = ("3 chapitres de suite sans aucune page : arrêt du téléchargement "
                                        "(Cloudflare ou lecteur du site). Envoie le rapport pour qu'on cherche pourquoi.")
                        logger.error(job["error"])
                        break

                if job["status"] == "running":
                    job["status"] = "completed"
                    logger.info(f"Téléchargement terminé : {job_id}")
            finally:
                await self._fermer_session(session)

    def download_manga_sync(self, job_id: str, manga_title: str, chapters: list[dict],
                            progress_callback=None):
        """Télécharge les chapitres un par un et crée un .cbz par chapitre."""
        job = {
            "id": job_id,
            "title": manga_title,
            "status": "running",
            "progress": 0,
            "total": len(chapters),
            "downloaded": [],
            "failed": [],
            "error": None,
            "started": datetime.now().isoformat(),
        }
        download_jobs[job_id] = job

        try:
            asyncio.run(self._telecharger_chapitres(job, chapters, progress_callback))
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            logger.error(f"Erreur téléchargement : {e}")

        job["ended"] = datetime.now().isoformat()


def download_manga_background(job_id: str, manga_title: str, chapters: list[dict], output_dir: Path):
    """Point d'entrée utilisé par l'appli (dans un thread)."""
    JapscanScraper(output_dir).download_manga_sync(job_id, manga_title, chapters)
