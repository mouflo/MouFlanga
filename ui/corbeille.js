/* 🗑 Combien de temps les anciens fichiers restent à la corbeille : réglé dans ⚙️ Réglages → Corbeille (jours, mois, ou jamais effacés).
   corb() donne la phrase à mettre entre parenthèses dans les messages : « durée de conservation : 30 jours ». */
(function () {
  var PAR_DEFAUT = 'durée de conservation : 30 jours';
  window.corb = function () { return window.MF_CORBEILLE || PAR_DEFAUT; };
  function lire() {
    if (document.body && document.body.classList.contains('lecteur')) return;      // un lecteur ne supprime rien : pas de question au serveur
    try {
      fetch('/api/corbeille', {credentials: 'same-origin'}).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { if (d && d.duree_texte) window.MF_CORBEILLE = d.duree_texte; }).catch(function () {});
    } catch (e) {}
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', lire); else lire();
})();
