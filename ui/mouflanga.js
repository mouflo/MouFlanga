/* MouFlanga · liste des séries et page d'une série */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); };
  async function api(url, opts) {
    var res = await fetch(url, opts), data = {};
    if (res.status === 401) { location.href = '/login'; throw new Error('Session expirée'); }
    try { data = await res.json(); } catch (e) {}
    if (!res.ok && !data.error) data.error = 'Erreur ' + res.status;
    return data;
  }
  function post(url, body) { return api(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})}); }
  function note(id, text, kind) { $(id).innerHTML = text ? '<div class="mou-note ' + (kind || 'err') + '">' + esc(text) + '</div>' : ''; }
  function pref(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }
  function setPref(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  // Marque de la couverture : statut officiel (AniList) comparé à ce qu'il y a sur le NAS
  var ETATS = {fini: ['✅ Fini', 'Série terminée, tout est là'], incomplet: ['⚠ Incomplet', 'Série terminée, mais il manque des tomes ou chapitres'],
    en_cours: ['🔄 En cours', 'Encore en parution'], pause: ['⏸ En pause', 'Parution en pause']};
  // 1234,5 Mo → « 1,2 Go » ; sinon des Mo arrondis
  function taille(mo) {
    mo = +mo || 0;
    return mo >= 1000 ? (mo / 1024).toFixed(1).replace('.', ',') + ' Go' : Math.round(mo) + ' Mo';
  }
  var series = [], current = null, suiviRangement = null, tomesOuverts = {};

  function sorted(list) {
    var q = $('search').value.trim().toLowerCase(), how = $('sort').value;
    list = list.filter(function (s) { return !q || s.title.toLowerCase().indexOf(q) >= 0; });
    var by = {
      title: function (a, b) { return a.title.localeCompare(b.title, 'fr', {numeric: true}); },
      recent: function (a, b) { return (b.last_read || '').localeCompare(a.last_read || '') || by.title(a, b); },
      added: function (a, b) { return b.added - a.added || by.title(a, b); },
      unread: function (a, b) { return (b.chapters - b.read) - (a.chapters - a.read) || by.title(a, b); }
    };
    return list.sort(by[how] || by.title);
  }

  function drawGrid() {
    var list = sorted(series.slice());
    if (!series.length) { $('grid').innerHTML = ''; return; }
    if (!list.length) { $('grid').innerHTML = '<div class="empty">Aucune série ne correspond à « ' + esc($('search').value) + ' ».</div>'; return; }
    $('grid').innerHTML = list.map(function (s) {
      var left = s.chapters - s.read, pct = s.chapters ? Math.round(100 * s.read / s.chapters) : 0;
      return '<div class="card" tabindex="0" data-id="' + esc(s.id) + '">' +
        '<img class="cv" loading="lazy" alt="" src="' + esc(s.cover) + '">' +
        (ETATS[s.etat] ? '<span class="etat ' + s.etat + '" title="' + ETATS[s.etat][1] + '">' + ETATS[s.etat][0] + '</span>' : '') +
        '<div class="nm">' + esc(s.title) + '</div>' +
        '<div class="st">' + esc(s.compte || (s.chapters + ' chapitre(s)')) + ' · ' + taille(s.size_mb) + '</div>' +
        '<div class="bar"><i style="width:' + pct + '%"></i></div></div>';
    }).join('');
  }

  async function loadList() {
    var r = await api('/api/library');
    series = r.series || [];
    // Archives déposées à la racine du dossier des mangas : lien vers la page d'import
    var bi = $('bandeauImport');
    bi.hidden = !(r.a_importer || r.import_en_cours);
    bi.textContent = r.import_en_cours ? '⏳ Import en cours : ' + r.import_en_cours + ' — voir l\'avancement'
      : '📦 ' + r.a_importer + ' archive' + (r.a_importer > 1 ? 's' : '') + ' à importer dans la bibliothèque — ouvrir';
    note('listMsg', r.error, 'warn');
    if (!r.error && !series.length) {
      $('grid').innerHTML = '<div class="empty">Aucun manga trouvé dans le dossier configuré.<br>Range des fichiers <b>.cbz</b> ou <b>.cbr</b> dans un sous-dossier par série, ou change le dossier dans ⚙️ Réglages.</div>';
    } else drawGrid();
  }

  async function rafraichirSerie(id) {
    var r = await api('/api/series?id=' + encodeURIComponent(id));
    if (r.error || $('seriesView').style.display === 'none' || !current || current.id !== id) return;
    current = r; drawSeries();
  }

  async function openSeries(id, push) {
    var r = await api('/api/series?id=' + encodeURIComponent(id));
    if (r.error) { note('listMsg', r.error); return; }
    current = r;
    $('listView').style.display = 'none'; $('seriesView').style.display = '';
    if (push !== false) history.pushState({s: id}, '', '#' + encodeURIComponent(id));
    drawSeries();
    window.scrollTo(0, 0);
  }

  function drawSeries() {
    var s = current, read = s.chapters.filter(function (c) { return c.read; }).length;
    $('sTitle').textContent = s.title;
    $('sCover').src = '/api/cover?id=' + encodeURIComponent(s.id) + '&v=' + (s.cover_v || 0);
    var perso = s.id !== '(Sans série)';
    $('sCoverPick').hidden = !perso;
    $('sCoverAuto').hidden = !s.cover_perso;
    // MouFloster s'ouvre avec la recherche déjà faite ; une fois le poster envoyé, il propose de revenir ici
    var mfs = adresseMoufloster(s);
    $('sCoverMfs').hidden = !(perso && mfs);
    if (mfs) $('sCoverMfs').href = mfs.replace(/\/$/, '') + '/?mouflanga=' + encodeURIComponent(s.id) +
      '&q=' + encodeURIComponent(s.id) + '&retour=' + encodeURIComponent(location.origin + location.pathname + '#' + encodeURIComponent(s.id));
    // Chapitres manquants : une ligne discrète, seulement s'il en manque
    var nbLus = s.chapters.filter(function (c) { return c.read; }).length;
    $('sMeta').textContent = (s.compte || '') + ' · ' + nbLus + ' lu' + (nbLus > 1 ? 's' : '');
    $('sPitchTexte').textContent = s.resume || 'Aucun résumé trouvé sur Internet. Appuie sur « ✏️ Modifier » pour en écrire un.';
    $('sPitchTexte').classList.toggle('vide', !s.resume);
    $('sPitchLangue').textContent = s.resume_langue === 'en' ? ' (en anglais, aucun résumé français trouvé)' : s.resume_langue === 'perso' ? ' (écrit à la main)' : '';
    $('sPitch').classList.remove('ouvert');
    $('sPitchEdit').hidden = true; $('sPitchTexte').hidden = false; $('sPitchModif').hidden = false;
    $('sPitchAuto').hidden = s.resume_langue !== 'perso';
    $('sPitchZone').value = s.resume || '';
    $('sEtat').hidden = !s.etat_texte;
    $('sEtat').className = 'etat-ligne ' + (s.etat || '');
    $('sEtat').textContent = s.etat_texte ? s.etat_texte + (s.etat_source ? ' (d\'après AniList : ' + s.etat_source + ')' : '') : '';
    $('sMissingLine').hidden = !(s.manquants && s.manquants.length);
    if (s.manquants && s.manquants.length) $('sMissingLine').textContent = '⚠ ' + (s.type_manquants === 'tomes' ? 'Tomes manquants' : 'Manquants') + ' : ' + s.manquants.join(', ');
    fermerMenus();
    // Série ajoutée à la main : proposition de rangement (nom propre, un dossier par tome)
    var o = s.organiser;
    $('sOrga').hidden = !o || !!(s.rangement && s.rangement.en_cours);
    if (o) {
      var quoi = [];
      if (o.tomes) quoi.push(o.tomes + ' tome' + (o.tomes > 1 ? 's' : '') + ' complet' + (o.tomes > 1 ? 's' : '') + (o.premier_tome != null && o.tomes > 1 ? ' (' + o.premier_tome + ' à ' + o.dernier_tome + ')' : '') + ' rangé' + (o.tomes > 1 ? 's' : '') + ' chacun dans son dossier « Tome NN »');
      if (o.archives) quoi.push(o.archives + ' archive' + (o.archives > 1 ? 's' : '') + ' (' + String(o.taille_go).replace('.', ',') + ' Go) extraite' + (o.archives > 1 ? 's' : '') + ' : un fichier par tome, avec les chapitres quand ils sont séparés (plusieurs minutes, en arrière-plan)');
      if (o.pdf) quoi.push(o.pdf + ' PDF converti' + (o.pdf > 1 ? 's' : '') + ' en fichier de tome');
      if (o.chapitres) quoi.push(o.chapitres + ' chapitre' + (o.chapitres > 1 ? 's' : '') + ' regroupé' + (o.chapitres > 1 ? 's' : '') + ' en tomes (répartition cherchée sur Internet)');
      $('sOrgaTexte').innerHTML = '<b>Série ajoutée à la main.</b> « Organiser » la renomme' + (quoi.length ? ', puis : ' + esc(quoi.join(' ; ')) : '') + '. Ta progression et ta couverture sont gardées.';
      if (document.activeElement !== $('sOrgaNom')) $('sOrgaNom').value = o.nom;
    }
    var rg = s.rangement || {};
    $('sTomes').hidden = !(s.a_ranger || rg.en_cours);
    $('sTomes').disabled = !!rg.en_cours;
    $('sTomes').textContent = rg.en_cours ? '⏳ Rangement en tomes… ' + (rg.total ? rg.fait + ' / ' + rg.total : '') : '📚 Ranger en tomes';
    if (rg.message && !rg.en_cours) note('sMsg', rg.message, 'ok');
    // Import ou rangement en cours : ce qui se passe, depuis combien de temps, combien de tomes sont faits
    $('sProgres').hidden = !rg.en_cours;
    if (rg.en_cours) {
      var duree = rg.etape_depuis ? Math.round(Date.now() / 1000 - rg.etape_depuis) : 0;
      var fmt = duree >= 60 ? Math.floor(duree / 60) + ' min ' + (duree % 60) + ' s' : duree + ' s';
      var archives = rg.total ? 'Archive ' + Math.min(rg.fait + 1, rg.total) + ' sur ' + rg.total + ' · ' : '';
      var tomesTxt = rg.sous_total ? rg.sous_fait + ' tome(s) sur ' + rg.sous_total + ' écrit(s)' : '';
      var pct = rg.sous_total ? Math.round(100 * rg.sous_fait / rg.sous_total) : null;
      $('sProgres').innerHTML = '<div class="pg-titre">⏳ ' + esc(rg.message || 'Travail en cours…') + '</div>' +
        '<div class="pg-detail">' + esc(archives + (tomesTxt || ('depuis ' + fmt))) + '</div>' +
        (pct !== null ? '<div class="pg-barre"><i style="width:' + pct + '%"></i></div>' : '<div class="pg-barre indet"><i></i></div>');
      if ($('sMsg').textContent.indexOf('Rangement des fichiers') >= 0) note('sMsg', '');
    }
    clearTimeout(suiviRangement);
    if (rg.en_cours) suiviRangement = setTimeout(function () {
      if ($('seriesView').style.display === 'none' || !current || current.id !== s.id) return;   // tu es allé ailleurs
      rafraichirSerie(s.id);
    }, 2500);
    var next = s.current || (s.chapters.find(function (c) { return !c.read; }) || s.chapters[0] || {}).key;
    $('sResume').textContent = (s.current ? '▶ Reprendre' : read ? '▶ Continuer' : '▶ Commencer');
    $('sResume').dataset.path = next || '';
    // Chapitres groupés par tome (« Tome 02 », « Hors tome ») : un appui sur le titre ouvre ou ferme le tome.
    // Au départ, seul le tome en cours de lecture (ou le premier avec des chapitres à lire) est ouvert.
    function ligne(c) {
      return '<div class="chap' + (c.read ? ' read' : '') + (c.key === s.current ? ' cur' : '') + '" data-path="' + esc(c.key) + '">' +
        '<span class="dot"></span><span class="ct">' + esc(c.title) + (c.sous ? '<small class="ct2">' + esc(c.sous) + '</small>' : '') + '</span><span class="cs">' + taille(c.size_mb) + '</span>' +
        '<button class="tog" data-tog="' + esc(c.key) + '" title="Marquer ' + (c.read ? 'non lu' : 'lu') + '">' + (c.read ? '↺' : '✔') + '</button>' +
        '<button class="tog del" data-del="' + esc(c.key) + '" title="Supprimer ce chapitre">🗑</button></div>';
    }
    var groupes = [];
    s.chapters.forEach(function (c) {
      var g = groupes[groupes.length - 1];
      if (!g || g.nom !== (c.groupe || '')) groupes.push(g = {nom: c.groupe || '', chapitres: []});
      g.chapitres.push(c);
    });
    if (!tomesOuverts[s.id] && groupes.some(function (g) { return g.nom; })) {
      var actuel = s.chapters.find(function (c) { return c.key === s.current; }) || s.chapters.find(function (c) { return !c.read; }) || {};
      tomesOuverts[s.id] = {}; tomesOuverts[s.id][actuel.groupe || ''] = true;
    }
    $('chapters').innerHTML = groupes.map(function (g) {
      if (!g.nom) return g.chapitres.map(ligne).join('');
      var lus = g.chapitres.filter(function (c) { return c.read; }).length, ouvert = !!tomesOuverts[s.id][g.nom];
      var cur = g.chapitres.some(function (c) { return c.key === s.current; });
      return '<div class="tome' + (ouvert ? ' ouvert' : '') + '">' +
        '<button class="tome-titre" data-tome="' + esc(g.nom) + '" aria-expanded="' + ouvert + '">' +
        '<span class="fleche">▸</span><span class="tn">📚 ' + esc(g.nom) + (cur ? ' <small>· en cours</small>' : '') + '</span>' +
        '<span class="tc">' + g.chapitres.length + ' ch. · ' + (lus === g.chapitres.length ? 'lu ✔' : lus + ' lu' + (lus > 1 ? 's' : '')) + '</span></button>' +
        '<div class="tome-chaps">' + g.chapitres.map(ligne).join('') + '</div></div>';
    }).join('');
    if (!(s.rangement && s.rangement.message)) note('sMsg', (!s.rar && s.chapters.some(function (c) { return /\.(cbr|rar)$/i.test(c.path); })) ? 'Les vrais fichiers RAR (.cbr) ne s\'ouvrent que si le serveur a « rarfile » et un outil de décompression : voir le Journal si une page refuse de s\'ouvrir.' : '', 'warn');
  }

  // Adresse de MouFloster : celle du réseau local si on est connecté à MouFlanga en local (192.168…),
  // sinon l'adresse perso (proxy) ; à défaut, celle qui existe
  function adresseMoufloster(s) {
    var h = location.hostname;
    var local = /^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h) || /\.(local|lan|home)$/.test(h);
    return local ? (s.moufloster || s.moufloster_externe) : (s.moufloster_externe || s.moufloster);
  }

  function readChapter(path) {
    location.href = '/lire?s=' + encodeURIComponent(current.id) + '&c=' + encodeURIComponent(path) +
      (path === current.current ? '&p=' + (current.page || 0) : '');
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('search').addEventListener('input', drawGrid);
    $('sort').value = pref('mfSort', 'recent');
    $('sort').addEventListener('change', function () { setPref('mfSort', $('sort').value); drawGrid(); });
    $('grid').addEventListener('click', function (e) { var c = e.target.closest('.card'); if (c) openSeries(c.dataset.id); });
    $('grid').addEventListener('keydown', function (e) { if (e.key === 'Enter') { var c = e.target.closest('.card'); if (c) openSeries(c.dataset.id); } });
    $('backList').addEventListener('click', function (e) { e.preventDefault(); history.pushState({}, '', location.pathname); showList(); });
    $('sResume').addEventListener('click', function () { if ($('sResume').dataset.path) readChapter($('sResume').dataset.path); });
    $('chapters').addEventListener('click', async function (e) {
      var tt = e.target.closest('[data-tome]');
      if (tt) {
        var bloc = tt.parentElement, ouvert = !bloc.classList.contains('ouvert');
        bloc.classList.toggle('ouvert', ouvert); tt.setAttribute('aria-expanded', ouvert);
        tomesOuverts[current.id][tt.dataset.tome] = ouvert;
        return;
      }
      var t = e.target.closest('[data-tog]');
      if (t) {
        e.stopPropagation();
        var c = current.chapters.find(function (x) { return x.key === t.dataset.tog; });
        await post('/api/mark', {series: current.id, path: c.key, read: !c.read});
        c.read = !c.read; drawSeries(); return;
      }
      var d = e.target.closest('[data-del]');
      if (d) {
        e.stopPropagation();
        var ch = current.chapters.find(function (x) { return x.key === d.dataset.del; });
        if (!confirm('Supprimer « ' + ch.title + ' » ?\n\nLe fichier va dans la corbeille du dossier des mangas (effacé pour de bon après 30 jours).')) return;
        var r = await post('/api/delete', {series: current.id, path: ch.key});
        if (!r.ok) { note('sMsg', r.error); return; }
        if (current.chapters.length <= 1) { history.pushState({}, '', location.pathname); showList(); }
        else await openSeries(current.id, false);
        return;
      }
      var row = e.target.closest('.chap');
      if (row && current.chapters.some(function (c) { return c.key === row.dataset.path && c.a_importer; })) {
        note('sMsg', 'Ce fichier doit d\'abord être converti : appuie sur « 🧹 Organiser » en haut de la page.', 'warn'); return;
      }
      if (row) readChapter(row.dataset.path);
    });
    async function markAll(v) { await post('/api/mark', {series: current.id, all: true, read: v}); await openSeries(current.id, false); }
    $('sAllRead').addEventListener('click', function () { markAll(true); });
    $('sCoverPick').addEventListener('click', function () { $('sCoverFile').value = ''; $('sCoverFile').click(); });
    $('sCoverFile').addEventListener('change', async function () {
      var f = $('sCoverFile').files[0]; if (!f) return;
      note('sMsg', 'Envoi de la couverture…', 'warn');
      var fd = new FormData(); fd.append('id', current.id); fd.append('image', f);
      var r = await api('/api/cover/choisir', {method: 'POST', body: fd});
      if (!r.ok) { note('sMsg', r.error); return; }
      note('sMsg', 'Couverture changée.', 'ok');
      await openSeries(current.id, false);
    });
    $('sCoverAuto').addEventListener('click', async function () {
      if (!confirm('Revenir à la couverture automatique (1re page du 1er chapitre) ?\n\nTa couverture va dans la corbeille.')) return;
      var r = await post('/api/cover/automatique', {id: current.id});
      if (!r.ok) { note('sMsg', r.error); return; }
      await openSeries(current.id, false);
    });
    $('sRenommer').addEventListener('click', async function () {
      var nom = prompt('Nouveau nom de la série :', current.title);
      if (!nom || nom.trim() === current.title) return;
      var r = await post('/api/renommer', {series: current.id, nom: nom.trim()});
      if (!r.ok && r.existe) {
        if (!confirm(r.error + '\n\nFusionner les deux ? Les tomes et chapitres de « ' + current.title + ' » rejoignent « ' + nom.trim() + ' », ta progression de lecture est gardée ; les fichiers déjà présents des deux côtés vont à la corbeille (30 jours).')) return;
        r = await post('/api/renommer', {series: current.id, nom: nom.trim(), fusionner: true});
      }
      if (!r.ok) { note('sMsg', r.error); return; }
      history.replaceState({s: r.id}, '', '#' + encodeURIComponent(r.id));
      await openSeries(r.id, false);
      note('sMsg', r.message || 'Série renommée.', 'ok');
    });
    $('sPitchTexte').addEventListener('click', function () { $('sPitch').classList.toggle('ouvert'); });
    // Modifier le résumé : ton texte remplace celui d'Internet (et n'est jamais écrasé par une mise à jour)
    function editionResume(ouvrir) {
      $('sPitchEdit').hidden = !ouvrir; $('sPitchTexte').hidden = ouvrir; $('sPitchModif').hidden = ouvrir;
      if (ouvrir) { $('sPitchZone').value = $('sPitchTexte').classList.contains('vide') ? '' : $('sPitchTexte').textContent; $('sPitchZone').focus(); }
    }
    async function enregistrerResume(texte) {
      var r = await post('/api/resume', {series: current.id, texte: texte});
      if (!r.ok) { note('sMsg', r.error); return; }
      await openSeries(current.id, false);
      note('sMsg', r.message, 'ok');
    }
    $('sPitchModif').addEventListener('click', function () { editionResume(true); });
    $('sPitchAnnuler').addEventListener('click', function () { editionResume(false); });
    $('sPitchOk').addEventListener('click', function () { enregistrerResume($('sPitchZone').value); });
    $('sPitchAuto').addEventListener('click', function () {
      if (confirm('Effacer ton résumé et reprendre celui trouvé sur Internet ?')) enregistrerResume('');
    });
    $('sTomes').addEventListener('click', async function () {
      if (!confirm('Ranger « ' + current.title + ' » en tomes ?\n\nL\'appli cherche sur Internet (Wikipédia, MangaDex) quels chapitres vont dans quel tome, puis regroupe les chapitres : un fichier par tome, les chapitres pas encore sortis en tome dans « Hors tome ». Ta progression de lecture est gardée ; les anciens fichiers vont dans la corbeille.')) return;
      var r = await post('/api/tomes/ranger', {series: current.id});
      if (!r.ok) { note('sMsg', r.error); return; }
      await openSeries(current.id, false);
    });
    $('sOrgaGo').addEventListener('click', async function () {
      var nom = $('sOrgaNom').value.trim(); if (!nom) return;
      $('sOrgaGo').disabled = true; note('sMsg', 'Rangement des fichiers…', 'warn');
      var r = await post('/api/organiser', {series: current.id, nom: nom});
      $('sOrgaGo').disabled = false;
      if (!r.ok) { note('sMsg', r.error); return; }
      tomesOuverts[r.id] = null;
      history.replaceState({s: r.id}, '', '#' + encodeURIComponent(r.id));
      await openSeries(r.id, false);
    });
    // Menus : appui sur la couverture (couverture) et sur « ⋯ » (actions moins courantes)
    function basculer(menu, e) {
      e.stopPropagation();
      var ouvrir = $(menu).hidden;
      fermerMenus();
      $(menu).hidden = !ouvrir;
    }
    $('sCoverBtn').addEventListener('click', function (e) { if (current.id !== '(Sans série)') basculer('menuCover', e); });
    $('sMore').addEventListener('click', function (e) { basculer('menuMore', e); });
    document.addEventListener('click', function (e) { if (!e.target.closest('.menu')) fermerMenus(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') fermerMenus(); });
    ['menuCover', 'menuMore'].forEach(function (m) { $(m).addEventListener('click', function () { setTimeout(fermerMenus, 0); }); });
    $('sDelete').addEventListener('click', async function () {
      var n = current.chapters.length;
      if (!confirm('Supprimer toute la série « ' + current.title + ' » (' + n + ' chapitre' + (n > 1 ? 's' : '') + ') ?\n\nLes fichiers vont dans la corbeille du dossier des mangas (effacés pour de bon après 30 jours).')) return;
      var r = await post('/api/delete', {series: current.id, all: true});
      if (!r.ok) { note('sMsg', r.error); return; }
      history.pushState({}, '', location.pathname); showList();
    });
    $('sAllUnread').addEventListener('click', function () { if (confirm('Tout marquer comme non lu pour cette série ?')) markAll(false); });
    window.addEventListener('popstate', route);
    route();
  });

  function fermerMenus() { $('menuCover').hidden = true; $('menuMore').hidden = true; }

  function showList() { $('seriesView').style.display = 'none'; $('listView').style.display = ''; loadList(); }
  function route() {
    var h = decodeURIComponent((location.hash || '').slice(1));
    if (h) openSeries(h, false); else showList();
  }
})();
