#!/usr/bin/env python3
"""
Diagnostic Cloudflare : affiche en texte tout ce qu'il faut pour comprendre un blocage.
Lancer : cd /opt/mouflanga && xvfb-run -a ./venv/bin/python diag_cloudflare.py
"""
import asyncio
import re

from japscan_scraper import JapscanScraper, JAPSCAN_URL, attendre_cloudflare, async_playwright
from pathlib import Path

URL_SERIE = JAPSCAN_URL + "/manga/dandadan/"


async def empreinte(page):
    """Ce que le site voit de notre navigateur."""
    return await page.evaluate("""() => {
        let gl = '';
        try {
            const c = document.createElement('canvas').getContext('webgl');
            const e = c.getExtension('WEBGL_debug_renderer_info');
            gl = c.getParameter(e.UNMASKED_RENDERER_WEBGL);
        } catch (e) { gl = 'indisponible'; }
        return {
            userAgent: navigator.userAgent,
            webdriver: navigator.webdriver,
            langues: navigator.languages,
            plugins: navigator.plugins.length,
            ecran: screen.width + 'x' + screen.height,
            webgl: gl,
            fuseau: Intl.DateTimeFormat().resolvedOptions().timeZone,
        };
    }""")


async def etat_page(page, reponse, etiquette):
    print(f"\n--- {etiquette} ---")
    if reponse is not None:
        h = reponse.headers
        print(f"Statut HTTP : {reponse.status}")
        print(f"cf-mitigated : {h.get('cf-mitigated')}  |  server : {h.get('server')}  |  cf-ray : {h.get('cf-ray')}")
    titre = await page.title()
    print(f"Titre : {titre!r}")
    texte = await page.evaluate("() => document.body ? document.body.innerText : ''")
    print("Texte visible : " + re.sub(r"\s+", " ", texte)[:400])
    html = await page.content()
    m = re.search(r"cType['\"]?\s*:\s*['\"](\w+)", html)
    print(f"Type de défi (cType) : {m.group(1) if m else 'non trouvé'}")
    cookies = await page.context.cookies()
    print("Cookies : " + ", ".join(sorted(c["name"] for c in cookies)))


async def main():
    sc = JapscanScraper(Path("/tmp/diag_cf"))
    async with async_playwright() as p:
        browser, context = await sc._init_browser(p)
        page = await context.new_page()
        try:
            print("=== Empreinte du navigateur ===")
            await page.goto("about:blank")
            print(await empreinte(page))

            # Essai A : accueil puis fiche série directement
            r = await page.goto(JAPSCAN_URL + "/", wait_until="domcontentloaded", timeout=30000)
            await attendre_cloudflare(page, 30)
            await etat_page(page, r, "A1 : page d'accueil")

            r = await page.goto(URL_SERIE, wait_until="domcontentloaded", timeout=30000)
            titre = await attendre_cloudflare(page, 60)
            await etat_page(page, r, f"A2 : fiche série après attente (titre final : {titre!r})")
            try:
                await page.screenshot(path="/tmp/diag_cf.png")
                print("Capture : /tmp/diag_cf.png")
            except Exception:
                pass
            freres = [f.url for f in page.frames]
            print(f"Cadres : {freres}")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
