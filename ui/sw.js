/* MouFlanga · service worker : appli installée, tomes gardés sur le téléphone (lecture hors ligne), notifications.
   Servi depuis /sw.js (portée : tout le site). Les pages d'un tome gardé sont dans le cache « mf-hors-ligne »
   (rangées par ui/hors-ligne.js) ; le reste de l'appli dans « mf-appli ». */
const APPLI = 'mf-appli-v1', PAGES = 'mf-hors-ligne';
const COQUILLE = ['/ui/mou-ui.css', '/ui/mou-ui.js', '/ui/mouflanga.css', '/ui/mouflanga.js', '/ui/lecteur.js', '/ui/hors-ligne.js',
                  '/icons/icon-192.png', '/icons/mouflanga.svg'];

self.addEventListener('install', e => {
    e.waitUntil(caches.open(APPLI).then(c => Promise.all(COQUILLE.map(u => c.add(u).catch(() => null)))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
    e.waitUntil(caches.keys().then(noms => Promise.all(noms.filter(n => n.startsWith('mf-appli') && n !== APPLI).map(n => caches.delete(n))))
        .then(() => self.clients.claim()));
});

async function depuisPages(req) {
    const c = await caches.open(PAGES);
    return c.match(req);
}

self.addEventListener('fetch', e => {
    const req = e.request, url = new URL(req.url);
    if (req.method !== 'GET' || url.origin !== location.origin) return;
    const p = url.pathname;
    if (p === '/api/page' || p === '/api/pages') {
        // page d'un tome gardé : depuis le téléphone (rapide, et marche sans réseau)
        e.respondWith(depuisPages(req).then(r => r || fetch(req)));
        return;
    }
    if (p === '/api/series') {
        // infos de la série : le réseau d'abord ; hors ligne, la copie gardée avec le tome
        e.respondWith(fetch(req).then(async r => {
            if (r.ok && await depuisPages(req)) (await caches.open(PAGES)).put(req, r.clone());
            return r;
        }).catch(() => depuisPages(req).then(r => r || new Response(JSON.stringify({error: 'Hors ligne', chapters: []}),
            {headers: {'Content-Type': 'application/json'}}))));
        return;
    }
    if (req.mode === 'navigate') {
        // pages de l'appli : le réseau d'abord, sinon la dernière version gardée (/lire sert pour tous les tomes)
        const cle = p === '/lire' ? '/lire' : (p === '/' ? '/' : null);
        e.respondWith(fetch(req).then(r => {
            if (cle && r.ok && !r.redirected) caches.open(APPLI).then(c => c.put(cle, r.clone()));
            return r;
        }).catch(async () => (cle && await caches.match(cle)) || (await caches.match('/lire')) ||
            new Response('<meta charset="utf-8"><p style="font-family:sans-serif;padding:20px">Pas de réseau. Les tomes gardés sur le téléphone restent lisibles depuis 📱.</p>',
                {headers: {'Content-Type': 'text/html; charset=utf-8'}})));
        return;
    }
    if (p.startsWith('/ui/') || p.startsWith('/icons/')) {
        // styles, scripts et icônes : la copie tout de suite, mise à jour en fond
        e.respondWith(caches.open(APPLI).then(async c => {
            const garde = await c.match(req, {ignoreSearch: true});
            const frais = fetch(req).then(r => { if (r.ok) c.put(p, r.clone()); return r; }).catch(() => garde);
            return garde || frais;
        }));
    }
});

self.addEventListener('push', e => {
    let d = {};
    try { d = e.data.json(); } catch (x) { d = {titre: 'MouFlanga', texte: e.data ? e.data.text() : ''}; }
    e.waitUntil(self.registration.showNotification(d.titre || 'MouFlanga', {
        body: d.texte || '', icon: '/icons/icon-192.png', badge: '/icons/icon-192.png', data: {url: d.url || '/'}}));
});
self.addEventListener('notificationclick', e => {
    e.notification.close();
    const url = (e.notification.data || {}).url || '/';
    e.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(fen => {
        for (const f of fen) { if ('focus' in f) { f.navigate(url).catch(() => null); return f.focus(); } }
        return self.clients.openWindow(url);
    }));
});
