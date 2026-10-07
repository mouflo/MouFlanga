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

  function lue(s) { return s.chapters > 0 && s.read >= s.chapters; }
  function enParution(s) { return s.etat === 'en_cours' || s.etat === 'pause'; }
  // Trois menus cumulables : Ma lecture · Parution · Tri (+ recherche et lettres)
  var FILTRES = {
    lecture: {titre: '📖 Ma lecture', choix: [['', 'Toutes'], ['lecture', 'En cours de lecture', 'En cours'], ['nonlu', 'Pas commencées'], ['lu', 'Déjà lues']],
      garde: {lecture: function (s) { return s.read > 0 && s.read < s.chapters; }, nonlu: function (s) { return !s.read; }, lu: lue}},
    parution: {titre: '🗞 Parution', choix: [['', 'Toutes'], ['fini', 'Complètes'], ['manque', 'Il en manque'], ['parution', 'En cours de parution', 'En parution']],
      garde: {fini: function (s) { return s.etat === 'fini'; }, manque: function (s) { return !!s.manque; }, parution: enParution}},
    tri: {titre: '↕ Tri', choix: [['az', 'A → Z'], ['za', 'Z → A'], ['added', 'Ajoutées récemment', 'Ajoutées'], ['recent', 'Lues récemment', 'Lues réc.'], ['progression', 'Progression']]}
  };
  var choixFiltre = {lecture: pref('mfLecture', ''), parution: pref('mfParution', ''), tri: pref('mfTri2', 'az')};
  Object.keys(FILTRES).forEach(function (k) {     // ancien choix qui n'existe plus : valeur par défaut
    if (!FILTRES[k].choix.some(function (c) { return c[0] === choixFiltre[k]; })) choixFiltre[k] = FILTRES[k].choix[0][0];
  });
  function libelle(k, court) { var c = FILTRES[k].choix.filter(function (c) { return c[0] === choixFiltre[k]; })[0]; return c ? (court && c[2] || c[1]) : ''; }
  function drawFiltres() {
    document.querySelectorAll('#filtres .filtre').forEach(function (f) {
      var k = f.dataset.filtre, F = FILTRES[k];
      f.querySelector('.filtre-val').textContent = libelle(k, true);
      f.classList.toggle('actif', k !== 'tri' && !!choixFiltre[k]);
      f.querySelector('.filtre-menu').innerHTML = '<div class="filtre-titre">' + F.titre + '</div>' + F.choix.map(function (c) {
        return '<button type="button" data-val="' + c[0] + '"' + (c[0] === choixFiltre[k] ? ' class="on"' : '') + '>' + esc(c[1]) + '</button>';
      }).join('');
    });
  }
  function fermerFiltres(sauf) {
    document.querySelectorAll('#filtres .filtre-menu').forEach(function (m) { if (m !== sauf) m.hidden = true; });
  }
  function sorted(list) {
    var q = sansAccents($('search').value.trim());
    list = list.filter(function (s) { return !q || sansAccents(s.title).indexOf(q) >= 0; });
    if (lettre && !q) list = list.filter(function (s) { return lettreDe(s.title) === lettre; });
    ['lecture', 'parution'].forEach(function (k) {
      var g = FILTRES[k].garde[choixFiltre[k]]; if (g) list = list.filter(g);
    });
    var titre = function (a, b) { return a.title.localeCompare(b.title, 'fr', {numeric: true}); };
    var pc = function (s) { return s.chapters ? s.read / s.chapters : 0; };
    var by = {
      az: titre,
      za: function (a, b) { return titre(b, a); },
      recent: function (a, b) { return (b.last_read || '').localeCompare(a.last_read || '') || titre(a, b); },
      added: function (a, b) { return b.added - a.added || titre(a, b); },
      progression: function (a, b) { return pc(b) - pc(a) || titre(a, b); }
    };
    return list.sort(by[choixFiltre.tri] || titre);
  }

  // Recherche sans accents ni majuscules, et index des lettres (comme la page Télécharger)
  function sansAccents(t) { return String(t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase(); }
  function lettreDe(t) { var c = sansAccents(t).charAt(0).toUpperCase(); return /[A-Z]/.test(c) ? c : '#'; }
  var lettre = '';
  function drawLettres() {
    var q = $('search').value.trim(), toutes = [];
    series.forEach(function (s) { var l = lettreDe(s.title); if (toutes.indexOf(l) < 0) toutes.push(l); });
    toutes.sort(function (a, b) { return a === '#' ? -1 : b === '#' ? 1 : a.localeCompare(b); });
    if (lettre && toutes.indexOf(lettre) < 0) lettre = '';
    $('lettres').hidden = !!q || series.length < 12;
    $('lettres').innerHTML = '<button type="button" data-lettre=""' + (lettre ? '' : ' class="actif"') + '>Toutes</button>' +
      toutes.map(function (l) { return '<button type="button" data-lettre="' + l + '"' + (l === lettre ? ' class="actif"' : '') + '>' + l + '</button>'; }).join('');
  }

  function drawGrid() {
    drawLettres(); drawFiltres();
    var list = sorted(series.slice());
    // « 12 séries · ✕ Tout remettre » dès qu'un filtre réduit la liste
    var filtre = choixFiltre.lecture || choixFiltre.parution || lettre;
    $('filtreResume').hidden = !filtre || !series.length;
    $('filtreResume').innerHTML = list.length + ' série' + (list.length > 1 ? 's' : '') + ' · <button type="button" id="filtreRaz">✕ Tout remettre</button>';
    if (!series.length) { $('grid').innerHTML = ''; return; }
    if (!list.length) {
      var quoi = [choixFiltre.lecture && libelle('lecture').toLowerCase(), choixFiltre.parution && libelle('parution').toLowerCase()].filter(Boolean).join(' et ');
      $('grid').innerHTML = '<div class="empty">' + ($('search').value.trim() ? 'Aucune série ne correspond à « ' + esc($('search').value) + ' ».'
        : 'Aucune série' + (quoi ? ' ' + esc(quoi) : '') + (lettre ? ' à la lettre ' + esc(lettre) : '') + '.') + '</div>';
      return;
    }
    $('grid').innerHTML = list.map(function (s) {
      var left = s.chapters - s.read, pct = s.chapters ? Math.round(100 * s.read / s.chapters) : 0;
      if (s.recherchee) return '<div class="card recherchee" tabindex="0" data-id="' + esc(s.id) + '" data-recherchee="1">' +
        (s.cover ? '<img class="cv" loading="lazy" alt="" src="' + esc(s.cover) + '">' : '<div class="cv"></div>') +
        '<span class="etat recherche">📥 Recherchée' + (s.propositions ? ' · ' + s.propositions + ' 🧲' : '') + '</span>' +
        '<div class="nm">' + esc(s.title) + '</div><div class="st">Appuie pour choisir un torrent</div><div class="bar"><i style="width:0"></i></div></div>';
      return '<div class="card" tabindex="0" data-id="' + esc(s.id) + '">' +
        '<img class="cv" loading="lazy" alt="" src="' + esc(s.cover) + '">' +
        (ETATS[s.etat] ? '<span class="etat ' + s.etat + '" title="' + ETATS[s.etat][1] + '">' + ETATS[s.etat][0] + '</span>' : '') +
        (lue(s) ? (enParution(s) ? '<span class="lue attente" title="À jour : en attente du prochain tome">⏳</span>'
                                 : '<span class="lue" title="Déjà lue">✔</span>') : '') +
        '<div class="nm">' + esc(s.title) + '</div>' +
        '<div class="st">' + esc(s.compte || (s.chapters + ' chapitre(s)')) + ' · ' + taille(s.size_mb) + '</div>' +
        '<div class="bar"><i style="width:' + pct + '%"></i></div></div>';
    }).join('');
  }

  // ---------- 📮 Demandes de mangas (lecteur : chercher et demander ; admin : accepter ou refuser) ----------
  var demResultats = [];
  var DEM_STATUT = {attente: '⏳ En attente', accepte: '✅ Acceptée', refuse: '❌ Refusée'};
  async function chargerDemandes() {
    var r = await api('/api/demandes');
    var n = r.attente || 0;
    $('nbDemandes').hidden = !(r.admin && n); $('nbDemandes').textContent = n;
    if (r.admin) $('btnDemandes').hidden = !(r.demandes || []).length;
    var l = r.demandes || [];
    $('demListe').innerHTML = l.length ? l.map(function (x) {
      return '<div class="dem-ligne ' + x.statut + '">' + (x.couverture ? '<img src="' + esc(x.couverture) + '" alt="" loading="lazy">' : '<span class="dem-vide"></span>') +
        '<div class="dem-info"><b>' + esc(x.titre) + '</b><small>' + (x.annee ? x.annee + ' · ' : '') + (r.admin ? 'par ' + esc(x.par) + ' · ' : '') + esc(x.date.slice(0, 10)) +
        '</small><span class="dem-statut">' + DEM_STATUT[x.statut] + (x.motif ? ' — ' + esc(x.motif) : '') + '</span></div><div class="dem-act">' +
        (x.statut === 'attente' ? (r.admin ? '<button type="button" data-dem="accepter" data-id="' + x.id + '">✅</button><button type="button" class="ghost" data-dem="refuser" data-id="' + x.id + '">❌</button>'
                                           : '<button type="button" class="ghost" data-dem="retirer" data-id="' + x.id + '">Retirer</button>') : '') + '</div></div>';
    }).join('') : '<div class="dem-sous">' + (r.admin ? 'Aucune demande pour l\'instant.' : 'Aucune demande pour l\'instant.') + '</div>';
  }
  function ouvrirDemandes(ouvrir) {
    $('demVue').hidden = !ouvrir;
    if (ouvrir) { chargerDemandes(); if ($('demRecherche')) $('demRecherche').focus(); }
    else if (location.hash === '#demandes') history.replaceState({}, '', location.pathname);
  }
  var demTimer = null;
  async function chercherDemande() {
    var q = $('demRecherche').value.trim();
    if (q.length < 2) { $('demResultats').innerHTML = ''; return; }
    $('demResultats').innerHTML = '<div class="dem-sous">Recherche…</div>';
    var r = await api('/api/demandes/chercher?q=' + encodeURIComponent(q));
    if (r.error) { $('demResultats').innerHTML = '<div class="dem-sous">' + esc(r.error) + '</div>'; return; }
    demResultats = r.resultats || [];
    var dans = series.map(function (s) { return sansAccents(s.title).replace(/[^a-z0-9]/g, ''); });
    $('demResultats').innerHTML = demResultats.length ? demResultats.map(function (x, i) {
      var cle = sansAccents(x.titre).replace(/[^a-z0-9]/g, ''), cle2 = sansAccents(x.original).replace(/[^a-z0-9]/g, '');
      var deja = dans.indexOf(cle) >= 0 || (cle2 && dans.indexOf(cle2) >= 0);
      return '<div class="dem-ligne">' + (x.couverture ? '<img src="' + esc(x.couverture) + '" alt="" loading="lazy">' : '<span class="dem-vide"></span>') +
        '<div class="dem-info"><b>' + esc(x.titre) + '</b><small>' + [x.original, x.annee, x.type, x.statut, x.tomes ? x.tomes + ' tome' + (x.tomes > 1 ? 's' : '') : ''].filter(Boolean).map(esc).join(' · ') + '</small></div>' +
        '<div class="dem-act">' + (deja ? '<span class="dem-statut">📚 Déjà là</span>' : x.deja ? '<span class="dem-statut">' + DEM_STATUT[x.deja] + '</span>'
          : (document.body.classList.contains('lecteur') ? '<button type="button" data-demander="' + i + '">📮 Demander</button>'
                                                          : '<button type="button" data-ajouter="' + i + '">➕ Ajouter</button>')) + '</div></div>';
    }).join('') : '<div class="dem-sous">Aucun manga trouvé.</div>';
  }

  async function loadList() {
    chargerDemandes();
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

  // Couverture de la même hauteur que la colonne d'infos : bords du haut et du bas alignés
  function ajusterCouverture() {
    var img = $('sCover'), info = document.querySelector('.series-info'), head = document.querySelector('.series-head');
    if (!head || !head.offsetWidth) return;
    info.style.minHeight = '';
    var max = head.clientWidth * 0.42, min = 90;
    var w = min;
    for (var k = 0; k < 5; k++) {                          // la largeur de la couverture change la hauteur des infos
      w = Math.max(min, Math.min(max, info.offsetHeight / 1.5));
      img.style.width = w + 'px'; img.style.height = (w * 1.5) + 'px';
    }
    var h = w * 1.5;                                       // jamais rognée (cadre des posters MouFloster gardé entier)
    img.style.height = h + 'px';
    info.style.minHeight = h + 'px';                       // couverture plus haute : le bouton descend en bas
  }
  window.addEventListener('resize', function () { if (current) ajusterCouverture(); });
  // Le contenu des infos peut changer après coup (police chargée, état de la série, rangement) : on réaligne
  var reAligner = null;
  if (window.ResizeObserver) new ResizeObserver(function () {
    cancelAnimationFrame(reAligner);
    reAligner = requestAnimationFrame(function () {
      var img = $('sCover'), info = document.querySelector('.series-info');
      if (current && info && Math.abs(info.offsetHeight - parseFloat(img.style.height || 0)) > 1) ajusterCouverture();
    });
  }).observe(document.querySelector('.series-info'));

  var lecteurGenerique = null, dernierAuto = null;
  function jouerGenerique() {
    lecteurGenerique = new Audio('/api/generique?id=' + encodeURIComponent(current.id));
    lecteurGenerique.serie = current.id; lecteurGenerique.volume = 0.7;
    lecteurGenerique.addEventListener('ended', arreterGenerique);
    lecteurGenerique.play().catch(function () { arreterGenerique(); });
    $('sEcouter').textContent = '⏸'; $('sEcouter').classList.add('joue');
  }
  // Bouton 🔊 / 🔇 dans l'en-tête : lecture automatique des génériques à l'ouverture d'une fiche
  function boutonAuto() {
    var actions = document.querySelector('.mou-actions');
    if (!actions) { setTimeout(boutonAuto, 200); return; }
    if ($('btnAutoGen')) return;
    var b = document.createElement('button');
    b.type = 'button'; b.id = 'btnAutoGen'; b.className = 'mou-btn ghost small';
    var maj = function () { var on = pref('mfAutoGenerique', '1') === '1'; b.textContent = on ? '🔊' : '🔇'; b.title = on ? 'Génériques joués à l\'ouverture d\'une fiche (appuie pour couper)' : 'Lecture automatique des génériques coupée'; };
    b.addEventListener('click', function () { setPref('mfAutoGenerique', pref('mfAutoGenerique', '1') === '1' ? '0' : '1'); maj(); if (pref('mfAutoGenerique', '1') !== '1') arreterGenerique(); });
    maj(); actions.insertBefore(b, actions.firstChild);
  }
  boutonAuto();
  function arreterGenerique() {
    if (lecteurGenerique) { lecteurGenerique.pause(); lecteurGenerique = null; }
    $('sEcouter').textContent = '🎵'; $('sEcouter').classList.remove('joue');
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
    $('sPitchTexte').textContent = s.resume || 'Aucun synopsis trouvé sur Internet. Appuie sur ✏️ pour en écrire un.';
    $('sPitchTexte').classList.toggle('vide', !s.resume);
    $('sPitchNautiljon').href = 'https://www.nautiljon.com/search.php?q=' + encodeURIComponent(s.title);
    $('sPitch').classList.remove('ouvert');
    $('sPitchEdit').hidden = true; $('sPitchTexte').hidden = false; $('sPitchModif').hidden = false;
    $('sPitchAuto').hidden = s.resume_langue !== 'perso';
    $('sPitchZone').value = s.resume || '';
    // Édition : « 📐 1600 × 2400 · Digital » (« deviné » si ce n'est ni un NFO, ni le nom de l'archive, ni ton choix)
    var ed = s.edition || {};
    var bouts = [ed.resolution ? '📐 ' + ed.resolution : '', ed.source ? ed.source + (ed.devine ? ' (deviné)' : '') : (ed.resolution ? 'source ?' : '')].filter(Boolean);
    $('sEdition').hidden = !bouts.length; $('sEdition').textContent = bouts.join(' · ');
    $('sEdition').title = ed.pourquoi ? 'Indice : ' + ed.pourquoi : '';
    $('sNfo').hidden = !(ed.nfo || (ed.archives || []).length);
    $('sNfoArchives').textContent = (ed.archives || []).length ? 'Archive' + (ed.archives.length > 1 ? 's' : '') + ' d\'origine : ' + ed.archives.join(', ') : '';
    $('sNfoTexte').textContent = ed.nfo || ''; $('sNfoTexte').hidden = !ed.nfo;
    var sv = s.suivi;
    $('sSurveiller').textContent = sv && sv.surveiller ? '👁 Ne plus surveiller' : '👁 Surveiller les nouveaux tomes';
    var props = ((sv && sv.propositions) || []).filter(function (p) { return p.statut === 'attente'; });
    $('sProps').hidden = !(sv && sv.surveiller) && !props.length;
    $('sPropsListe').innerHTML = props.length ? props.map(function (p) {
      var url = '/telecharger?torrent=' + encodeURIComponent(p.titre) + '&serie=' + encodeURIComponent(s.id) + '&proposition=' + p.id + (p.type === 'meilleur' ? '&remplacer=1' : '');
      return '<div class="prop"><div class="dem-info"><b>' + (p.type === 'meilleur' ? '⬆️ ' : '🆕 ') + esc(p.titre) + '</b><small>' +
        (p.type === 'meilleur' ? 'Meilleure version' : 'Tomes absents : ' + esc((p.tomes || []).join(', '))) + ' · ' + (p.badges || []).map(esc).join(' · ') + '</small></div>' +
        '<div class="dem-act"><a class="mou-btn small" href="' + url + '">⬇️</a><button type="button" class="ghost" data-ignorer="' + p.id + '">✕</button></div></div>';
    }).join('') : '<div class="dem-sous">Rien de nouveau' + (sv && sv.derniere_verif ? ' (vérifié le ' + esc(sv.derniere_verif) + ')' : '') + '.</div>';
    $('sEtat').hidden = !s.etat_texte;
    $('sEtat').className = 'etat-ligne ' + (s.etat || '');
    $('sEtat').textContent = s.etat_texte || '';
    $('sMissingLine').hidden = !(s.manquants && s.manquants.length);
    if (s.manquants && s.manquants.length) {
      $('sMissingLine').textContent = '⚠ ' + (s.type_manquants === 'tomes' ? 'Tomes manquants' : 'Manquants') + ' : ' + s.manquants.join(', ') + ' ›';
      $('sMissingLine').href = '/telecharger?q=' + encodeURIComponent(s.title);   // la page Télécharger ouvre la série sur Japscan
    }
    // Version animée dans Emby : lien discret vers MouFlopening (menu « ⋯ ») et bouton 🎵 pour écouter le générique
    var mfo = adresseMoufloster({moufloster: s.mouflopening, moufloster_externe: s.mouflopening_externe});
    $('sGenerique').hidden = !(s.anime && mfo);
    if (s.anime && mfo) $('sGenerique').href = mfo.replace(/\/$/, '') + '/?dossier=' + encodeURIComponent(s.anime.dossier) +
      '&de=MouFlanga&retour=' + encodeURIComponent(location.origin + location.pathname + '#' + encodeURIComponent(s.id));
    $('sEcouter').hidden = !(s.anime && s.anime.generique);
    if (lecteurGenerique && lecteurGenerique.serie !== s.id) arreterGenerique();   // une autre série : on coupe
    if (s.anime && s.anime.generique && !lecteurGenerique && pref('mfAutoGenerique', '1') === '1' && dernierAuto !== s.id) {
      dernierAuto = s.id; jouerGenerique();                // comme Emby : le générique part à l'ouverture de la fiche
    }
    fermerMenus();
    ajusterCouverture();
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
    $('btnDemandes').addEventListener('click', function () { ouvrirDemandes(true); });
    $('demFermer').addEventListener('click', function () { ouvrirDemandes(false); });
    $('demVue').addEventListener('click', async function (e) {
      if (e.target === $('demVue')) { ouvrirDemandes(false); return; }
      var b = e.target.closest('[data-demander]');
      if (b) {
        b.disabled = true;
        var r = await post('/api/demandes', {action: 'creer', serie: demResultats[+b.dataset.demander]});
        note('demMsg', r.message || r.error, r.ok ? 'ok' : 'err');
        if (r.ok) { chargerDemandes(); chercherDemande(); } else b.disabled = false;
        return;
      }
      var aj = e.target.closest('[data-ajouter]');
      if (aj) {
        var x = demResultats[+aj.dataset.ajouter];
        var nom = prompt('Nom de la série dans ta bibliothèque :', x.titre);
        if (!nom) return;
        var ra = await post('/api/suivies', {action: 'ajouter', nom: nom, serie: x});
        note('demMsg', ra.message || ra.error, ra.ok ? 'ok' : 'err');
        if (ra.ok) loadList();
        return;
      }
      var a = e.target.closest('[data-dem]'); if (!a) return;
      var corps = {action: a.dataset.dem, id: a.dataset.id};
      if (corps.action === 'refuser') { var m = prompt('Refuser cette demande ? Motif (facultatif, visible par le lecteur) :', ''); if (m === null) return; corps.motif = m; }
      var r2 = await post('/api/demandes', corps);
      note('demMsg', r2.message || r2.error, r2.ok ? 'ok' : 'err');
      chargerDemandes();
    });
    if ($('demRecherche')) $('demRecherche').addEventListener('input', function () { clearTimeout(demTimer); demTimer = setTimeout(chercherDemande, 450); });
    $('filtres').addEventListener('click', function (e) {
      var f = e.target.closest('.filtre'); if (!f) return;
      var menu = f.querySelector('.filtre-menu'), b = e.target.closest('[data-val]');
      if (b) {
        var k = f.dataset.filtre; choixFiltre[k] = b.dataset.val;
        setPref({lecture: 'mfLecture', parution: 'mfParution', tri: 'mfTri2'}[k], b.dataset.val);
        menu.hidden = true; drawGrid(); return;
      }
      if (e.target.closest('.filtre-btn')) { fermerFiltres(menu); menu.hidden = !menu.hidden; }
    });
    document.addEventListener('click', function (e) { if (!e.target.closest('#filtres')) fermerFiltres(); });
    $('filtreResume').addEventListener('click', function (e) {
      if (e.target.id !== 'filtreRaz') return;
      choixFiltre.lecture = choixFiltre.parution = ''; lettre = '';
      setPref('mfLecture', ''); setPref('mfParution', ''); drawGrid();
    });
    $('lettres').addEventListener('click', function (e) {
      var b = e.target.closest('[data-lettre]'); if (!b) return;
      lettre = b.dataset.lettre; drawGrid();
    });
    function ouvrirCarte(c) {
      if (c.dataset.recherchee) location.href = '/telecharger?torrent=' + encodeURIComponent(c.dataset.id) + '&serie=' + encodeURIComponent(c.dataset.id);
      else openSeries(c.dataset.id);
    }
    $('grid').addEventListener('click', function (e) { var c = e.target.closest('.card'); if (c) ouvrirCarte(c); });
    $('grid').addEventListener('keydown', function (e) { if (e.key === 'Enter') { var c = e.target.closest('.card'); if (c) ouvrirCarte(c); } });
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
    $('sInfos').addEventListener('click', async function () {
      $('infosTitre').textContent = 'ℹ️ ' + current.title; $('infosCorps').innerHTML = '<div class="dem-sous">Recherche des infos…</div>'; $('infosVue').hidden = false;
      var f = await api('/api/fiche?id=' + encodeURIComponent(current.id));
      var ed = f.edition || {}, st = {RELEASING: 'en cours', FINISHED: 'terminée', HIATUS: 'en pause', CANCELLED: 'arrêtée'}[f.statut] || '';
      var lignes = [
        ['Titre original', [f.titre_original, f.romaji].filter(Boolean).join(' · ')],
        ['Parution', f.debut ? f.debut + (f.fin ? ' → ' + f.fin : ' → ' + (st || '…')) + (f.fin && st ? ' (' + st + ')' : '') : st],
        ['Scénario', f.scenario], ['Dessin', f.dessin && f.dessin !== f.scenario ? f.dessin : (f.dessin ? '(même auteur)' : '')],
        ['Genres', f.genres], ['Éditeur japonais', f.editeur_jp], ['Éditeur français', f.editeur_fr],
        ['Version', (f.versions || []).join(', ')], ['Source', [ed.source ? ed.source + (ed.devine ? ' (deviné)' : '') : '', ed.resolution].filter(Boolean).join(' · ')]
      ].filter(function (l) { return l[1]; });
      $('infosCorps').innerHTML = (lignes.length ? '<dl>' + lignes.map(function (l) { return '<dt>' + l[0] + '</dt><dd>' + esc(l[1]) + '</dd>'; }).join('') + '</dl>'
        : '<div class="dem-sous">Aucune info trouvée.</div>') + (f.wikipedia ? '<a class="infos-lien" href="https://fr.wikipedia.org/wiki/' + encodeURIComponent(f.wikipedia) + '" target="_blank" rel="noopener">Wikipédia ↗</a>' : '');
    });
    $('infosFermer').addEventListener('click', function () { $('infosVue').hidden = true; });
    $('infosVue').addEventListener('click', function (e) { if (e.target === $('infosVue')) $('infosVue').hidden = true; });
    $('sSurveiller').addEventListener('click', async function () {
      fermerMenus();
      var r = await post('/api/suivies', {action: 'surveiller', nom: current.id, actif: !(current.suivi && current.suivi.surveiller)});
      note('sMsg', r.message || r.error, r.ok ? 'ok' : 'err'); if (r.ok) await openSeries(current.id, false);
    });
    $('sVerifier').addEventListener('click', async function () {
      $('sVerifier').disabled = true; note('sMsg', 'Recherche dans Prowlarr… (jusqu\'à une minute)', 'warn');
      var r = await post('/api/suivies', {action: 'verifier', nom: current.id});
      $('sVerifier').disabled = false; note('sMsg', r.message || r.error, r.ok ? 'ok' : 'err'); if (r.ok) await openSeries(current.id, false);
    });
    $('sPropsListe').addEventListener('click', async function (e) {
      var b = e.target.closest('[data-ignorer]'); if (!b) return;
      var r = await post('/api/suivies', {action: 'ignorer', nom: current.id, id: b.dataset.ignorer});
      if (r.ok) await openSeries(current.id, false);
    });
    $('sSource').addEventListener('click', async function () {
      fermerMenus();
      var v = prompt('Source de « ' + current.title + ' » : Digital, Scan, Web…\n(laisse vide pour revenir à la détection automatique)', (current.edition || {}).source || '');
      if (v === null) return;
      var r = await post('/api/edition', {series: current.id, source: v.trim()});
      note('sMsg', r.message || r.error, r.ok ? 'ok' : 'err');
      if (r.ok) await openSeries(current.id, false);
    });
    $('sEcouter').addEventListener('click', function () {
      if (lecteurGenerique) { arreterGenerique(); return; }
      jouerGenerique();
    });
    $('sPitchAnnuler').addEventListener('click', function () { editionResume(false); });
    $('sPitchOk').addEventListener('click', function () { enregistrerResume($('sPitchZone').value); });
    $('sPitchAuto').addEventListener('click', function () {
      if (confirm('Effacer ton synopsis et reprendre celui trouvé sur Internet ?')) enregistrerResume('');
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

  function showList() { arreterGenerique(); $('seriesView').style.display = 'none'; $('listView').style.display = ''; loadList(); }
  function route() {
    var h = decodeURIComponent((location.hash || '').slice(1));
    if (h === 'demandes') { showList(); ouvrirDemandes(true); }          // lien des messages Telegram
    else if (h) openSeries(h, false); else showList();
  }
})();
