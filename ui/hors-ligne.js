/* MouFlanga · sur ce téléphone : service worker, tomes gardés pour la lecture hors ligne, notifications.
   Chargé par la bibliothèque et par le lecteur. Liste des tomes gardés : localStorage « mfHorsLigne » (propre à
   l'appareil) ; leurs pages : cache « mf-hors-ligne » (voir ui/sw.js). */
(function () {
  'use strict';
  var PAGES = 'mf-hors-ligne', CLE = 'mfHorsLigne', FILE = 'mfFileProgression';
  var swPret = null;
  if ('serviceWorker' in navigator) {
    swPret = navigator.serviceWorker.register('/sw.js').then(function () { return navigator.serviceWorker.ready; })
      .catch(function () { return null; });
  }
  function lire(cle, d) { try { return JSON.parse(localStorage.getItem(cle)) || d; } catch (e) { return d; } }
  function ecrire(cle, v) { try { localStorage.setItem(cle, JSON.stringify(v)); } catch (e) {} }
  function urlPage(path, n) { return '/api/page?path=' + encodeURIComponent(path) + '&n=' + n; }
  function urlPages(path) { return '/api/pages?path=' + encodeURIComponent(path); }
  function urlSerie(serie) { return '/api/series?id=' + encodeURIComponent(serie); }

  function liste() { return lire(CLE, []); }
  function estGarde(serie, path) { return liste().some(function (x) { return x.serie === serie && x.path === path; }); }

  async function place() {
    try { var e = await navigator.storage.estimate(); return {libre: (e.quota || 0) - (e.usage || 0), utilise: e.usage || 0}; }
    catch (x) { return null; }
  }

  // Garde un fichier (tome) sur le téléphone : toutes ses pages, ses infos, la série et la page du lecteur
  async function garder(item, avancement) {
    if (!('caches' in window)) throw new Error('Ce navigateur ne permet pas la lecture hors ligne.');
    try { if (navigator.storage && navigator.storage.persist) await navigator.storage.persist(); } catch (e) {}
    var c = await caches.open(PAGES);
    var rp = await fetch(urlPages(item.path));
    if (!rp.ok) throw new Error('Tome introuvable sur le serveur');
    var info = await rp.clone().json();
    await c.put(urlPages(item.path), rp);
    var rs = await fetch(urlSerie(item.serie)); if (rs.ok) await c.put(urlSerie(item.serie), rs);
    var rl = await fetch('/lire'); if (rl.ok && !rl.redirected) await (await caches.open('mf-appli-v2')).put('/lire', rl);
    var octets = 0;
    for (var n = 0; n < info.count; n++) {
      var u = urlPage(item.path, n);
      if (!(await c.match(u))) {
        var r = await fetch(u);
        if (!r.ok) throw new Error('Page ' + (n + 1) + ' non téléchargée');
        var b = await r.clone().blob(); octets += b.size;
        await c.put(u, r);
      }
      if (avancement) avancement(n + 1, info.count);
    }
    var l = liste().filter(function (x) { return !(x.serie === item.serie && x.path === item.path); });
    l.push({serie: item.serie, path: item.path, cle: item.cle, titre: item.titre, pages: info.count,
            octets: octets || Math.round((item.tailleMo || 0) * 1048576), date: new Date().toISOString().slice(0, 10)});
    ecrire(CLE, l);
  }

  async function retirer(serie, path) {
    var x = liste().find(function (y) { return y.serie === serie && y.path === path; });
    if ('caches' in window) {
      var c = await caches.open(PAGES);
      var n = x ? x.pages : 0;
      for (var i = 0; i < n; i++) await c.delete(urlPage(path, i));
      await c.delete(urlPages(path));
      if (!liste().some(function (y) { return y.serie === serie && y.path !== path; })) await c.delete(urlSerie(serie));
    }
    ecrire(CLE, liste().filter(function (y) { return !(y.serie === serie && y.path === path); }));
  }

  // Progression notée sans réseau : gardée puis envoyée au retour du réseau
  function noterProgression(corps) { var f = lire(FILE, []); f.push(corps); ecrire(FILE, f.slice(-200)); }
  async function envoyerFile() {
    var f = lire(FILE, []); if (!f.length || !navigator.onLine) return;
    var reste = [];
    for (var i = 0; i < f.length; i++) {
      try {
        var r = await fetch('/api/progress', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: f[i]});
        if (!r.ok && r.status >= 500) reste.push(f[i]);
      } catch (e) { reste.push(f[i]); }
    }
    ecrire(FILE, reste);
  }
  window.addEventListener('online', envoyerFile);
  setTimeout(envoyerFile, 2000);

  // Notifications (Web Push) : abonnement de ce téléphone, sujets choisis par la personne
  function cleBinaire(b64) {
    var p = '='.repeat((4 - b64.length % 4) % 4), s = atob((b64 + p).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from(s, function (c) { return c.charCodeAt(0); });
  }
  async function etatNotifications() {
    var reg = swPret && await swPret;
    var abo = reg && reg.pushManager ? await reg.pushManager.getSubscription() : null;
    var r = await (await fetch('/api/push' + (abo ? '?endpoint=' + encodeURIComponent(abo.endpoint) : ''))).json();
    r.possible = !!(reg && reg.pushManager && window.Notification);
    r.permission = window.Notification ? Notification.permission : 'non';
    r.abonnement = abo;
    return r;
  }
  async function activerNotifications(sujets) {
    var reg = swPret && await swPret;
    if (!reg || !reg.pushManager) throw new Error('Ce navigateur ne gère pas les notifications (sur iPhone : ajoute d\'abord l\'appli à l\'écran d\'accueil).');
    if ((await Notification.requestPermission()) !== 'granted') throw new Error('Notifications refusées dans le navigateur.');
    var etat = await (await fetch('/api/push')).json();
    var abo = await reg.pushManager.getSubscription() || await reg.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: cleBinaire(etat.cle)});
    var r = await (await fetch('/api/push', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'abonner', abonnement: abo.toJSON(), sujets: sujets})})).json();
    if (!r.ok) throw new Error(r.error || 'Abonnement refusé');
    return r;
  }
  async function couperNotifications() {
    var reg = swPret && await swPret;
    var abo = reg && reg.pushManager ? await reg.pushManager.getSubscription() : null;
    if (abo) {
      await fetch('/api/push', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'desabonner', endpoint: abo.endpoint})});
      await abo.unsubscribe();
    }
  }
  async function essaiNotification() {
    return (await fetch('/api/push', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'essai'})})).json();
  }

  window.MFHorsLigne = {liste: liste, estGarde: estGarde, garder: garder, retirer: retirer, place: place,
    noterProgression: noterProgression, envoyerFile: envoyerFile,
    effacerSiLu: function () { return localStorage.getItem('mfEffacerLu') === '1'; },
    etatNotifications: etatNotifications, activerNotifications: activerNotifications,
    couperNotifications: couperNotifications, essaiNotification: essaiNotification};
})();
