// Bandeau « le site attend ta vérification » sur toutes les pages, pastille sur « Télécharger »,
// et mémoire de la page d'origine pour y revenir toute seule une fois la vérification passée.
(function () {
  if (document.body.classList.contains('lecteur') || location.pathname === '/verification') return;
  var CLE = 'mfRetourVerif';
  // Dernière page vue (fiche d'une série comprise) : sert au retour quand la vérification est ouverte depuis l'alerte Telegram
  function noterPage() {
    try { localStorage.setItem('mfDernierePage', JSON.stringify({url: location.pathname + location.search + location.hash, t: Date.now()})); } catch (e) { /* stockage bloqué */ }
  }
  noterPage();
  window.addEventListener('hashchange', noterPage);
  window.addEventListener('popstate', noterPage);
  var pousser = history.pushState;
  history.pushState = function () { var r = pousser.apply(this, arguments); noterPage(); return r; };
  function memoriser() {
    try { localStorage.setItem(CLE, JSON.stringify({url: location.pathname + location.search + location.hash, t: Date.now()})); } catch (e) { /* stockage bloqué */ }
  }
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href="/verification"]');
    if (a) memoriser();
  }, true);

  var st = document.createElement('style');
  st.textContent = '.verif-bandeau{position:sticky;top:0;z-index:900;display:block;margin:0 0 12px;padding:12px 16px;border-radius:10px;' +
    'background:#3a2e12;border:1px solid #b58a1b;color:#ffd978;text-decoration:none;font-weight:600}.verif-bandeau[hidden]{display:none}' +
    '.pastille-verif{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:10px;background:#d33;color:#fff;font-size:.75rem;font-weight:700}';
  document.head.appendChild(st);

  var bandeau = null, conteneur = document.querySelector('.container');
  if (conteneur && !document.getElementById('verif-banner')) {          // la page Télécharger a déjà son propre bandeau
    bandeau = document.createElement('a');
    bandeau.className = 'verif-bandeau'; bandeau.href = '/verification'; bandeau.hidden = true;
    bandeau.textContent = '⚠️ Le site attend ta vérification : appuie ici →';
    conteneur.insertBefore(bandeau, conteneur.firstChild);
  }

  async function verifier() {
    try {
      var r = await fetch('/api/japscan/verif/etat', {cache: 'no-store'});
      if (!r.ok) return;
      var d = await r.json();
      if (bandeau) bandeau.hidden = !d.actif;
      document.querySelectorAll('a[href="/telecharger"]').forEach(function (a) {
        var p = a.querySelector('.pastille-verif');
        if (d.actif && !p) { p = document.createElement('span'); p.className = 'pastille-verif'; p.textContent = '⚠️ 1'; a.appendChild(p); }
        else if (!d.actif && p) p.remove();
      });
    } catch (e) { /* réseau coupé un instant */ }
  }
  verifier();
  setInterval(verifier, 4000);
})();
