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
    lecture: {titre: '📖 Ma lecture', choix: [['', 'Toutes'], ['lecture', 'En cours de lecture', 'En cours'], ['nonlu', 'Pas commencées'], ['lu', 'Déjà lues'], ['favori', '⭐ Mes favorites', '⭐ Favorites']],
      garde: {lecture: function (s) { return s.read > 0 && s.read < s.chapters; }, nonlu: function (s) { return !s.read; }, lu: lue,
              favori: function (s) { return !!s.favori; }}},
    parution: {titre: '🗞 Parution', choix: [['', 'Toutes'], ['fini', 'Complètes'], ['manque', 'Il en manque'], ['parution', 'En cours de parution', 'En parution']],
      garde: {fini: function (s) { return s.etat === 'fini'; }, manque: function (s) { return !!s.manque; }, parution: enParution}},
    univers: {titre: '🌌 Univers', choix: [['', 'Tous']]},
    tri: {titre: '↕ Tri', choix: [['az', 'A → Z'], ['za', 'Z → A'], ['added', 'Ajoutées récemment', 'Ajoutées'], ['recent', 'Lues récemment', 'Lues réc.'], ['progression', 'Progression'], ['univers', 'Univers (ordre de lecture)', 'Univers'], ['auteur', 'Auteur', 'Auteur'], ['editeur', 'Éditeur', 'Éditeur'], ['note', 'Mieux notées', 'Notes'], ['note_bas', 'Moins bien notées', 'Pires notes']]}
  };
  var choixFiltre = {lecture: pref('mfLecture', ''), parution: pref('mfParution', ''), univers: '', tri: pref('mfTri2', 'az')};
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
  function sorted(list, toutes) {
    if (!toutes) {                                   // « toutes » = toute la bibliothèque, seul le tri compte (flèches ‹ ›)
      var q = sansAccents($('search').value.trim());
      var qc = compact(q);                              // « belzebub » trouve « Beelzebub » (lettres doublées ignorées)
      list = list.filter(function (s) { return !q || sansAccents(s.title + ' ' + (s.auteur || '') + ' ' + (s.editeur || '') + ' ' + (s.univers || '')).indexOf(q) >= 0 || (qc.length >= 3 && compact(s.title).indexOf(qc) >= 0); });   // recherche aussi par auteur et éditeur
      if (lettre && !q) list = list.filter(function (s) { return lettreDe(s.title) === lettre; });
      if (choixFiltre.univers) list = list.filter(function (s) { return s.univers === choixFiltre.univers; });
      ['lecture', 'parution'].forEach(function (k) {
        var g = FILTRES[k].garde[choixFiltre[k]]; if (g) list = list.filter(g);
      });
    }
    var titre = function (a, b) { return a.title.localeCompare(b.title, 'fr', {numeric: true}); };
    var pc = function (s) { return s.chapters ? s.read / s.chapters : 0; };
    var by = {
      az: titre,
      za: function (a, b) { return titre(b, a); },
      recent: function (a, b) { return (b.last_read || '').localeCompare(a.last_read || '') || titre(a, b); },
      added: function (a, b) { return b.added - a.added || titre(a, b); },
      progression: function (a, b) { return pc(b) - pc(a) || titre(a, b); },
      univers: function (a, b) {                       // d'abord les univers (par nom), dans l'ordre de lecture, puis le reste
        if (!a.univers !== !b.univers) return a.univers ? -1 : 1;
        return (a.univers || '').localeCompare(b.univers || '', 'fr')
          || ((a.ordre_univers || 9999) - (b.ordre_univers || 9999)) || titre(a, b);
      },
      auteur: function (a, b) { return (a.auteur || '\uffff').localeCompare(b.auteur || '\uffff', 'fr') || titre(a, b); },
      editeur: function (a, b) { return (a.editeur || '\uffff').localeCompare(b.editeur || '\uffff', 'fr') || titre(a, b); },
      // séries sans note toujours en dernier, dans les deux sens
      note: function (a, b) { return (b.note || -1) - (a.note || -1) || titre(a, b); },
      note_bas: function (a, b) { return (a.note || 99) - (b.note || 99) || titre(a, b); }
    };
    return list.sort(by[choixFiltre.tri] || titre);
  }

  // Recherche sans accents ni majuscules, et index des lettres (comme la page Télécharger)
  function sansAccents(t) { return String(t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase(); }
  function compact(t) { return sansAccents(t).replace(/(.)\1+/g, '$1'); }
  function lettreDe(t) { var c = sansAccents(t).charAt(0).toUpperCase(); return /[A-Z]/.test(c) ? c : '#'; }
  var lettre = '';
  function drawLettres() {
    var q = $('search').value.trim(), toutes = [];
    series.forEach(function (s) { var l = lettreDe(s.title); if (toutes.indexOf(l) < 0) toutes.push(l); });
    toutes.sort(function (a, b) { return a === '#' ? -1 : b === '#' ? 1 : a.localeCompare(b); });
    if (lettre && toutes.indexOf(lettre) < 0) lettre = '';
    $('lettres').hidden = !!q || series.length < 12;
    // Alphabet complet (pour un alignement régulier) ; les lettres sans série sont grisées
    var alphabet = ['#'].concat('ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split(''));
    $('lettres').innerHTML = '<button type="button" class="toutes' + (lettre ? '' : ' actif') + '" data-lettre="" title="Toutes les lettres" aria-label="Toutes les lettres">✱</button>' +
      alphabet.map(function (l) {
        var ok = toutes.indexOf(l) >= 0;
        return '<button type="button"' + (ok ? ' data-lettre="' + l + '"' : ' disabled') + (l === lettre ? ' class="actif"' : '') + '>' + l + '</button>';
      }).join('');
  }

  var GRILLE_PAGE = 36, grilleListe = [], grilleRendu = 0, grilleObs = null;     // défilement infini de la bibliothèque

  function drawGrid() {
    var noms = [];
    series.forEach(function (s) { if (s.univers && noms.indexOf(s.univers) < 0) noms.push(s.univers); });
    noms.sort(function (a, b) { return a.localeCompare(b, 'fr'); });
    FILTRES.univers.choix = [['', 'Tous']].concat(noms.map(function (n) { return [n, n]; }));
    if (choixFiltre.univers && noms.indexOf(choixFiltre.univers) < 0) choixFiltre.univers = '';
    drawLettres(); drawFiltres();
    var list = sorted(series.slice());
    // « 12 séries · ✕ Tout remettre » dès qu'un filtre réduit la liste
    var filtre = choixFiltre.lecture || choixFiltre.parution || choixFiltre.univers || lettre;
    $('filtreResume').hidden = !filtre || !series.length;
    $('filtreResume').innerHTML = list.length + ' série' + (list.length > 1 ? 's' : '') + ' · <button type="button" id="filtreRaz">✕ Tout remettre</button>';
    if (!series.length) { $('grid').innerHTML = ''; return; }
    if (!list.length) {
      var quoi = [choixFiltre.lecture && libelle('lecture').toLowerCase(), choixFiltre.parution && libelle('parution').toLowerCase(), choixFiltre.univers && 'dans l\'univers « ' + choixFiltre.univers + ' »'].filter(Boolean).join(' et ');
      $('grid').innerHTML = '<div class="empty">' + ($('search').value.trim() ? 'Aucune série ne correspond à « ' + esc($('search').value) + ' ».'
        : 'Aucune série' + (quoi ? ' ' + esc(quoi) : '') + (lettre ? ' à la lettre ' + esc(lettre) : '') + '.') + '</div>';
      return;
    }
    // Défilement infini : les premières cartes tout de suite, les suivantes quand on approche du bas de la page
    var rendu = (list.length === grilleListe.length && grilleRendu) ? grilleRendu : GRILLE_PAGE;
    grilleListe = list;
    grilleRendu = 0;
    $('grid').innerHTML = '';
    grilleSuite(Math.max(rendu, GRILLE_PAGE));
  }

  function carteGrille(s) {
      var left = s.chapters - s.read, pct = s.chapters ? Math.round(100 * s.read / s.chapters) : 0;
      if (s.recherchee) return '<div class="card recherchee" tabindex="0" data-id="' + esc(s.id) + '" data-recherchee="1">' +
        (s.cover ? '<img class="cv" loading="lazy" alt="" src="' + esc(s.cover) + '">' : '<div class="cv"></div>') +
        '<span class="etat recherche">📥 Recherchée' + (s.propositions ? ' · ' + s.propositions + ' 🧲' : '') + '</span>' +
        '<button type="button" class="carte-retirer" data-retirer-suivie="' + esc(s.id) + '" title="Supprimer cette fiche" aria-label="Supprimer cette fiche">✕</button>' +
        '<div class="nm">' + esc(s.title) + '</div><div class="st">Appuie pour choisir un torrent</div><div class="bar"><i style="width:0"></i></div></div>';
      return '<div class="card" tabindex="0" data-id="' + esc(s.id) + '">' +
        '<img class="cv" loading="lazy" alt="" src="' + esc(s.cover) + '">' +
        '<button type="button" class="fav' + (s.favori ? ' on' : '') + '" data-favori="' + esc(s.id) + '" aria-pressed="' + (s.favori ? 'true' : 'false') +
        '" title="' + (s.favori ? 'Retirer des favorites' : 'Mettre en favorite') + '" aria-label="Favorite">' + (s.favori ? '★' : '☆') + '</button>' +
        (ETATS[s.etat] ? '<span class="etat ' + s.etat + '" title="' + ETATS[s.etat][1] + '">' + ETATS[s.etat][0] + '</span>' : '') +
        (lue(s) ? (enParution(s) ? '<span class="lue attente" title="À jour : en attente du prochain tome">⏳</span>'
                                 : '<span class="lue" title="Déjà lue">✔</span>') : '') +
        '<div class="nm">' + esc(s.title) + '</div>' +
        '<div class="st">' + esc(s.compte || (s.chapters + ' chapitre(s)')) + ' · ' + taille(s.size_mb) +
        (s.note ? ' · <span class="note" title="Note ' + esc(s.note_source) + '">' + String(s.note).replace('.', ',') + '/10</span>' : '') + '</div>' +
        '<div class="bar"><i style="width:' + pct + '%"></i></div></div>';
  }

  function grilleSuite(jusqua) {
    var fin = Math.min(grilleListe.length, jusqua || grilleRendu + GRILLE_PAGE);
    if (fin > grilleRendu) {
      $('grid').insertAdjacentHTML('beforeend', grilleListe.slice(grilleRendu, fin).map(carteGrille).join(''));
      grilleRendu = fin;
    }
    var sentinelle = document.getElementById('grilleSuite');
    if (grilleRendu >= grilleListe.length) {            // tout est affiché : plus rien à surveiller
      if (sentinelle) sentinelle.remove();
      if (grilleObs) { grilleObs.disconnect(); grilleObs = null; }
      return;
    }
    if (!sentinelle) {
      sentinelle = document.createElement('div');
      sentinelle.id = 'grilleSuite';
      sentinelle.style.cssText = 'height:1px;width:100%';
      $('grid').after(sentinelle);
    }
    if (!('IntersectionObserver' in window)) { grilleSuite(grilleListe.length); return; }       // vieux navigateur : tout
    if (!grilleObs) {
      grilleObs = new IntersectionObserver(function (entries) {
        if (entries.some(function (e) { return e.isIntersecting; })) grilleSuite();
      }, {rootMargin: '900px 0px'});
    }
    grilleObs.disconnect();
    grilleObs.observe(sentinelle);                      // si la sentinelle est déjà visible, la suite arrive aussitôt
  }

  // ---------- 📮 Demandes de mangas (lecteur : chercher et demander ; admin : accepter ou refuser) ----------
  var demResultats = [], demListeCourante = [];
  var DEM_STATUT = {attente: '⏳ En attente', accepte: '✅ Acceptée', refuse: '❌ Refusée', dispo: '📚 Disponible'};
  async function chargerDemandes() {
    var r = await api('/api/demandes');
    var n = r.attente || 0;
    $('nbDemandes').hidden = !(r.admin && n); $('nbDemandes').textContent = n;
    var l = r.demandes || [];
    demListeCourante = l;
    $('demListe').innerHTML = l.length ? l.map(function (x, i) {
      return '<div class="dem-ligne ' + x.statut + '">' + (x.couverture ? '<img src="' + esc(x.couverture) + '" alt="" loading="lazy">' : '<span class="dem-vide"></span>') +
        '<div class="dem-info"><b class="dem-nom" role="link" tabindex="0" data-voir-dem="' + i + '" title="Ouvrir la fiche">' + esc(x.titre) + '</b><small>' + (x.annee ? x.annee + ' · ' : '') + (r.admin ? 'par ' + esc(x.par) + ' · ' : '') + esc(x.date.slice(0, 10)) +
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
        '<div class="dem-info"><b>' + esc(x.titre) + '</b><small>' + [x.source, x.original, x.annee, x.type, x.statut, x.tomes ? x.tomes + ' tome' + (x.tomes > 1 ? 's' : '') : ''].filter(Boolean).map(esc).join(' · ') + '</small></div>' +
        '<div class="dem-act">' + (deja ? '<span class="dem-statut">📚 Déjà là</span>' : x.deja ? '<span class="dem-statut">' + DEM_STATUT[x.deja] + '</span>'
          : (document.body.classList.contains('lecteur') ? '<button type="button" data-demander="' + i + '">📮 Demander</button>'
                                                          : '<button type="button" data-ajouter="' + i + '">➕ Ajouter</button>')) + '</div></div>';
    }).join('') : '<div class="dem-sous">Aucun manga trouvé.</div>';
    if (r.indisponibles && r.indisponibles.length) $('demResultats').innerHTML += '<div class="dem-sous">Sources sans réponse : ' + esc(r.indisponibles.join(', ')) + '</div>';
    if (!document.body.classList.contains('lecteur')) $('demResultats').innerHTML += '<div class="dem-sous"><button type="button" data-manuel="1">✏️ Pas trouvé ? Saisir le manga à la main (titre, auteur, éditeur, lien)</button></div>';
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
    majNavSeries();
    if (!document.body.classList.contains('lecteur')) api('/api/optimiser?series=' + encodeURIComponent(id)).then(function (o) { if (!window.MFAllege) return; if (o && o.en_cours) window.MFAllege.veiller(id); window.MFAllege.ligne(id, o); });
    else $('sAllege').hidden = true;
  }

  // ‹ › : série précédente / suivante dans TOUTE la bibliothèque, dans l'ordre du tri choisi (lettre, filtres et recherche ne limitent pas)
  function voisinsSeries() {
    var l = sorted(series.slice(), true).filter(function (s) { return !s.recherchee; });
    var i = current ? l.findIndex(function (s) { return s.id === current.id; }) : -1;
    return {prec: i > 0 ? l[i - 1] : null, suiv: i >= 0 && i < l.length - 1 ? l[i + 1] : null};
  }
  async function majNavSeries() {
    if (!series.length) { var r = await api('/api/library'); series = r.series || []; }
    var v = voisinsSeries(), style = pref('mfNavStyle', 'bas');
    document.body.classList.toggle('nav-bas', style === 'bas'); document.body.classList.toggle('nav-cotes', style === 'cotes');
    $('serPrec').hidden = !v.prec || style === 'aucune'; $('serSuiv').hidden = !v.suiv || style === 'aucune';
    $('serPrec').title = v.prec ? v.prec.title : ''; $('serSuiv').title = v.suiv ? v.suiv.title : '';
    // « bas » : la flèche à part du nom (le nom long est coupé par « … », la flèche reste visible)
    $('serPrec').innerHTML = '<span class="fl">‹</span>' + (style === 'bas' && v.prec ? '<span class="nm">' + esc(v.prec.title) + '</span>' : '');
    $('serSuiv').innerHTML = (style === 'bas' && v.suiv ? '<span class="nm">' + esc(v.suiv.title) + '</span>' : '') + '<span class="fl">›</span>';
  }


  var lecteurGenerique = null, dernierAuto = null;
  // Un seul lecteur audio, « débloqué » au premier appui (les téléphones refusent un son lancé sans appui) :
  // ensuite le générique peut partir tout seul à l'ouverture d'une fiche.
  var audioGen = new Audio(), audioDebloque = false;
  audioGen.addEventListener('ended', function () { if (lecteurGenerique) arreterGenerique(); });
  function debloquerAudio() {
    if (audioDebloque) return;
    audioDebloque = true;
    audioGen.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=';
    var p = audioGen.play(); if (p && p.catch) p.catch(function () {});
  }
  ['pointerdown', 'touchend', 'keydown'].forEach(function (t) { document.addEventListener(t, debloquerAudio, {capture: true, passive: true}); });
  function jouerGenerique(auto) {
    lecteurGenerique = audioGen;
    lecteurGenerique.serie = current.id; audioGen.volume = 0.7;
    audioGen.src = '/api/generique?id=' + encodeURIComponent(current.id);
    $('sEcouter').textContent = '⏸'; $('sEcouter').classList.add('joue');
    var p = audioGen.play();
    if (p && p.catch) p.catch(function () {
      arreterGenerique();
      if (auto) {                                   // refusé (aucun appui encore) : il part au premier appui sur la page
        var reessai = function () { document.removeEventListener('pointerdown', reessai, true); if (current && current.id === lecteurGenerique_cible && !lecteurGenerique) jouerGenerique(); };
        lecteurGenerique_cible = current.id;
        document.addEventListener('pointerdown', reessai, true);
      }
    });
  }
  var lecteurGenerique_cible = null;
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
    // 🎛 Affichage (admin et lecteurs) : style des flèches entre séries, générique automatique
    var r = document.createElement('button');
    r.type = 'button'; r.id = 'btnAffichage'; r.className = 'mou-btn ghost small'; r.textContent = '🎛'; r.title = 'Affichage';
    r.addEventListener('click', function () { $('affNav').value = pref('mfNavStyle', 'bas'); $('affAuto').value = pref('mfAutoGenerique', '1'); $('affVue').hidden = false; });
    actions.insertBefore(r, b.nextSibling);
    window._majBoutonAuto = maj;
  }
  boutonAuto();
  function arreterGenerique() {
    if (lecteurGenerique) { lecteurGenerique.pause(); lecteurGenerique = null; }
    lecteurGenerique_cible = null;
    $('sEcouter').textContent = '🎵'; $('sEcouter').classList.remove('joue');
  }

  function drawSeries() {
    var s = current, read = s.chapters.filter(function (c) { return c.read; }).length;
    $('sTitle').textContent = s.title; $('sTitle').classList.remove('deplie');
    $('sCover').src = s.cover_externe && !s.cover_perso ? s.cover_externe : '/api/cover?id=' + encodeURIComponent(s.id) + '&v=' + (s.cover_v || 0);
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
    // Édition : « 📐 1600 × 2400 · Digital ✓ » (✓ vert si sûr : NFO, nom de l'archive ou ton choix ; ? orange si deviné)
    $('sRattacherSuggere').hidden = !s.rattacher_a;
    if (s.rattacher_a) $('sRattacherSuggere').innerHTML = '📎 Ça ressemble à un hors-série de « ' + esc(s.rattacher_a) + ' ». ' +
      '<button type="button" class="mou-btn" data-rattacher="' + esc(s.rattacher_a) + '">Le rattacher</button>';
    var ed = s.edition || {};
    var cat = categorieSource(ed.source, ed.devine);
    var src = (ed.source || ed.resolution) ? '<span class="src-pastille" style="--c:' + cat.couleur + '">' + esc(cat.nom) + '</span>' +
      '<button type="button" class="src-aide" data-legende="1" aria-label="Légende des sources">?</button>' : '';
    var bouts = [ed.edition ? '🏷 ' + esc(ed.edition) : '', ed.resolution ? '📐 ' + esc(ed.resolution) : '', src].filter(Boolean);
    $('sEdition').hidden = !bouts.length; $('sEdition').innerHTML = bouts.join(' · ');
    $('sEdition').title = ed.pourquoi ? 'Indice : ' + ed.pourquoi : '';
    $('sNfo').hidden = !(ed.nfo || (ed.archives || []).length);
    $('sNfoArchives').textContent = (ed.archives || []).length ? 'Archive' + (ed.archives.length > 1 ? 's' : '') + ' d\'origine : ' + ed.archives.join(', ') : '';
    $('sNfoTexte').textContent = ed.nfo || ''; $('sNfoTexte').hidden = !ed.nfo;
    var sv = s.suivi;
    $('sSurveiller').textContent = sv && sv.surveiller ? '👁 Ne plus surveiller' : '👁 Surveiller les nouveaux tomes';
    var props = ((sv && sv.propositions) || []).filter(function (p) { return p.statut === 'attente'; });
    $('sProps').hidden = !(sv && sv.surveiller) && !props.length;
    $('sPropsListe').innerHTML = props.length ? props.map(function (p) {
      var url = '/telecharger?torrent=' + encodeURIComponent(p.titre) + '&serie=' + encodeURIComponent(s.id) + '&proposition=' + p.id + (p.type === 'meilleur' || p.type === 'equipe' ? '&remplacer=1' : '');
      return '<div class="prop"><div class="dem-info"><b>' + ({meilleur: '⬆️ ', equipe: '🔁 '}[p.type] || '🆕 ') + esc(p.titre) + '</b><small>' +
        (p.type === 'meilleur' ? 'Meilleure version' : p.type === 'equipe' ? 'Même équipe que la série pour les tomes ' + esc((p.tomes || []).join(', ')) : 'Tomes absents : ' + esc((p.tomes || []).join(', '))) + ' · ' + (p.badges || []).map(esc).join(' · ') + '</small></div>' +
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
      dernierAuto = s.id; jouerGenerique(true);            // comme Emby : le générique part à l'ouverture de la fiche
    }
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
    // Série ajoutée mais encore sans tomes : pas de lecture, un accès direct au choix du torrent
    $('sResume').hidden = !!s.recherchee; $('sMore').parentNode.hidden = !!s.recherchee;
    var lt = $('sTorrent');
    if (!lt) {
      lt = document.createElement('a'); lt.id = 'sTorrent'; lt.className = 'mou-btn'; lt.textContent = '🧲 Choisir un torrent';
      $('sResume').parentNode.insertBefore(lt, $('sResume'));
    }
    lt.hidden = !s.recherchee;
    lt.href = '/telecharger?torrent=' + encodeURIComponent(s.id) + '&serie=' + encodeURIComponent(s.id);
    // Chapitres groupés par tome (« Tome 02 », « Hors tome ») : un appui sur le titre ouvre ou ferme le tome.
    // Au départ, seul le tome en cours de lecture (ou le premier avec des chapitres à lire) est ouvert.
    function ligne(c) {
      return '<div class="chap' + (c.read ? ' read' : '') + (c.key === s.current ? ' cur' : '') + '" data-path="' + esc(c.key) + '">' +
        '<span class="dot"></span><span class="ct">' + esc(c.title) + (c.sous ? '<small class="ct2">' + esc(c.sous) + '</small>' : '') + '</span>' +
        (c.tome != null ? '<button class="tog tinfo' + (c.titres_ch ? ' vert' : '') + '" data-tinfo="' + c.tome + '" title="Infos du tome">ⓘ</button>' : '') +
        (c.groupe === 'Hors-série' ? '<button class="tog" data-hs="' + esc(c.key) + '" title="Identifier ce hors-série">🔎</button>' : '') + '<span class="cs">' + taille(c.size_mb) + '</span>' +
        '<button class="tog" data-tog="' + esc(c.key) + '" title="Marquer ' + (c.read ? 'non lu' : 'lu') + '">' + (c.read ? '↺' : '✔') + '</button>' +
        '<button class="tog del" data-del="' + esc(c.key) + '" title="Supprimer ce chapitre">🗑</button></div>';
    }
    var groupes = [];
    s.chapters.forEach(function (c) {
      var g = groupes[groupes.length - 1];
      if (!g || g.nom !== (c.groupe || '')) groupes.push(g = {nom: c.groupe || '', titre: c.groupe_titre || '', chapitres: []});
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
        '<span class="fleche">▸</span><span class="tn">📚 ' + esc(g.nom) + (cur ? ' <small>· en cours</small>' : '') +
        (g.titre ? '<small class="tome-nom">« ' + esc(g.titre) + ' »</small>' : '') + '</span>' +
        (/^Tome \d+/.test(g.nom) ? '<span class="tog tinfo' + (g.chapitres.some(function (c) { return c.titres_ch; }) ? ' vert' : '') + '" role="button" data-tinfo="' + parseInt(g.nom.slice(5), 10) + '" title="Infos du tome">ⓘ</span>' : '') +
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

  // Titre d'un chapitre de la fenêtre ⓘ : cliquable quand le chapitre est dans la série (même numéro, même tome)
  // Sources : nom + couleur (légende au point 3.20) ; « ? » = l'appli a un doute, à vérifier
  var SOURCES = [
    {nom: 'Scantrad', couleur: '#e05252', quoi: 'scan du Weekly Jump, nettoyé et traduit'},
    {nom: 'Scan 🥇', couleur: '#e6c229', quoi: 'scan de la version officielle, nettoyé, recadré, simple et double page'},
    {nom: 'Scan 🥈', couleur: '#e08a2c', quoi: 'scan de la version officielle brute'},
    {nom: 'Digital', couleur: '#52b54b', quoi: 'ebook officiel'},
    {nom: '?', couleur: '#8a8a8a', quoi: 'à vérifier : l\'appli n\'est pas sûre'}];
  function categorieSource(source, devine) {
    var s = String(source || '').toLowerCase();
    var trouve = SOURCES.find(function (x) { return x.nom.toLowerCase() === s; }) ||
      (/digital|ebook|e-book/.test(s) ? SOURCES[3] : /trad|web|jump/.test(s) ? SOURCES[0] : /🥇|clean|nettoy/.test(s) ? SOURCES[1] : /🥈|brut|raw/.test(s) ? SOURCES[2] : null);
    if (!trouve || devine) return {nom: trouve ? trouve.nom + ' ?' : (source ? source + ' ?' : '?'), couleur: SOURCES[4].couleur};
    return trouve;
  }
  function legendeSources() {
    var o = document.createElement('div'); o.className = 'choix-fond';
    o.innerHTML = '<div class="choix-boite"><h3>Légende des sources</h3>' + SOURCES.map(function (x) {
      return '<p><span class="src-pastille" style="--c:' + x.couleur + '">' + esc(x.nom) + '</span> ' + esc(x.quoi) + '</p>'; }).join('') +
      '<button type="button" class="mou-btn ghost">Fermer</button></div>';
    o.addEventListener('click', function (e) { if (e.target === o || e.target.closest('button')) o.remove(); });
    document.body.appendChild(o);
  }
  document.addEventListener('click', function (e) { if (e.target.closest('[data-legende]')) { e.stopPropagation(); legendeSources(); } });

  function lienChapitre(texte, tome) {
    var propre = String(texte).replace(/[{}]+/g, '');
    var m = /^([\d.]+)\./.exec(propre);
    var groupe = 'Tome ' + String(tome).padStart(2, '0');
    var e = m ? (current.chapters || []).find(function (x) { return Math.abs(x.num - parseFloat(m[1])) < 1e-6 && (x.groupe === groupe || String(x.tome) === String(Number(tome))); }) : null;
    return e ? '<a href="#" class="tchap-lien" data-cle="' + esc(e.key) + '">' + esc(propre) + '</a>' : esc(propre);
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
      if (e.target.closest('[data-manuel]')) {
        var titre = prompt('Titre du manga (obligatoire) :', $('demRecherche').value.trim());
        if (!titre || !titre.trim()) return;
        var auteur = prompt('Auteur (facultatif) :', '') || '';
        var editeur = prompt('Éditeur (facultatif) :', '') || '';
        var lien = prompt('Lien vers le site qui décrit le manga (facultatif) :', '') || '';
        var rm = await post('/api/suivies', {action: 'ajouter', nom: titre.trim(), serie: {titre: titre.trim(), auteur: auteur.trim(), editeur: editeur.trim(), lien: lien.trim(), source: 'Saisie manuelle'}});
        note('demMsg', rm.message || rm.error, rm.ok ? 'ok' : 'err');
        if (rm.ok) loadList();
        return;
      }
      var vo = e.target.closest('[data-voir],[data-voir-dem]');
      if (vo && !document.body.classList.contains('lecteur')) {      // toucher le nom : la fiche dans MouFlanga (la série est ajoutée si besoin)
        var xv = vo.dataset.voirDem !== undefined ? demListeCourante[+vo.dataset.voirDem] : demResultats[+vo.dataset.voir];
        if (!xv) return;
        var cv = sansAccents(xv.titre).replace(/[^a-z0-9]/g, '');
        var ex = series.filter(function (z) { return sansAccents(z.title).replace(/[^a-z0-9]/g, '') === cv; })[0];
        var nomv = ex ? ex.id : xv.titre.trim();
        if (!ex) {
          var rv = await post('/api/suivies', {action: 'ajouter', nom: nomv, serie: xv});
          if (!rv.ok) { note('demMsg', rv.error || 'Ajout impossible', 'err'); return; }
          await loadList();
        }
        ouvrirDemandes(false);
        openSeries(nomv);
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
    $('grid').addEventListener('click', async function (e) {
      var fv = e.target.closest('[data-favori]');
      if (fv) {                                             // ⭐ cocher / décocher sans ouvrir la série
        e.stopPropagation();
        var sf = series.filter(function (s) { return s.id === fv.dataset.favori; })[0]; if (!sf) return;
        var veut = !sf.favori; sf.favori = veut; drawGrid();
        var rf = await post('/api/favori', {series: sf.id, favori: veut});
        if (!rf.ok) { sf.favori = !veut; drawGrid(); alert(rf.error || 'Favori impossible'); }
        return;
      }
      var x = e.target.closest('[data-retirer-suivie]');
      if (x) {                                              // fiche grisée (série ajoutée, encore rien sur le NAS) : on la supprime
        e.stopPropagation();
        if (!confirm('Supprimer la fiche « ' + x.dataset.retirerSuivie + ' » ? Elle n\'est plus suivie (aucun fichier n\'est touché).')) return;
        var r = await post('/api/suivies', {action: 'retirer', nom: x.dataset.retirerSuivie});
        if (r.ok) { series = series.filter(function (s) { return s.id !== x.dataset.retirerSuivie; }); drawGrid(); }
        else alert(r.error || 'Suppression impossible');
        return;
      }
      var c = e.target.closest('.card'); if (c) ouvrirCarte(c);
    });
    $('grid').addEventListener('keydown', function (e) { if (e.key === 'Enter') { if (e.target.closest('[data-favori]')) return; var c = e.target.closest('.card'); if (c) ouvrirCarte(c); } });
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
      var hs = e.target.closest('[data-hs]');
      if (hs) {
        e.stopPropagation();
        var rang = hs.closest('.chap'), titre = rang ? (rang.querySelector('.ct') || {}).textContent : '';
        ouvrirHorsSerie(hs.dataset.hs, titre || 'hors-série');
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
    document.addEventListener('click', function (e) {
    var l = e.target.closest && e.target.closest('.tchap-lien');
    if (l) { e.preventDefault(); readChapter(l.dataset.cle); }
  });
  $('sCouvertures').addEventListener('click', function () { location.href = '/couvertures?id=' + encodeURIComponent(current.id); });

  // 🔎 Identification d'un hors-série : résultats AniList / MangaDex, saisie à la main, ou retrait
  var hsCandidats = [], hsCle = '', hsDernier = null;
  function ouvrirHorsSerie(cle, titre) {
    hsCle = cle;
    $('infosTitre').textContent = '🔎 Hors-série : ' + titre;
    $('infosCorps').innerHTML = '<div class="dem-sous">Recherche sur AniList et MangaDex…</div>';
    $('infosVue').hidden = false;
    api('/api/hors-serie/candidats?id=' + encodeURIComponent(current.id) + '&key=' + encodeURIComponent(cle)).then(function (r) {
      if (r.error) { $('infosCorps').innerHTML = '<div class="dem-sous">' + esc(r.error) + '</div>'; return; }
      hsCandidats = r.candidats || [];
      hsDernier = r;
      hsAffiche(r);
    });
  }
  function hsAffiche(r) {
      var lien = '<div class="ident-lien"><label for="hsLien">Lien d\'une page du hors-série (Glénat, éditeur, boutique…)</label>' +
        '<input type="url" id="hsLien" placeholder="https://…" autocomplete="off" autocapitalize="off">' +
        '<button type="button" class="mou-btn" data-hs-lire="1">📖 Lire les infos de cette page</button></div>';
      var actuel = r.identifie ? '<p class="dem-sous">Actuellement : <b>' + esc(r.identifie.titre) + '</b>' +
        (r.identifie.annee ? ' · ' + esc(r.identifie.annee) : '') + (r.identifie.auteur ? ' · ' + esc(r.identifie.auteur) : '') + '</p>' : '';
      var lignes = hsCandidats.map(function (c, i) {
        return '<li class="ident-ligne"><div><b>' + esc(c.titre) + '</b><small>' + [c.type, c.annee, c.auteur, c.editeur, c.pages ? c.pages + ' pages' : '', c.source, c.statut, c.apres_tome ? 'à lire après le tome ' + c.apres_tome : ''].filter(Boolean).map(esc).join(' · ') + '</small>' +
          (c.descriptif ? '<small class="hs-desc">' + esc(c.descriptif) + '</small>' : '') + '</div>' +
          '<button type="button" class="mou-btn" data-hs-choix="' + i + '">Choisir</button></li>';
      }).join('');
      $('infosCorps').innerHTML = lien + actuel + (hsCandidats.length ? '<ul class="ident-liste">' + lignes + '</ul>'
        : '<div class="dem-sous">Rien trouvé sur ces sources pour « ' + esc(r.titre) + ' ».</div>') +
        '<div class="ident-actions"><button type="button" class="mou-btn ghost" data-hs-manuel="1">✏️ Saisir le hors-série à la main</button>' +
        ' <button type="button" class="mou-btn ghost" data-hs-renommer="1">🏷 Renommer</button>' +
        (r.identifie ? ' <button type="button" class="mou-btn ghost" data-hs-retirer="1">Retirer l\'identification</button>' : '') + '</div>';
  }
  async function enregistrerHorsSerie(corps) {
    var r = await post('/api/hors-serie', Object.assign({series: current.id, key: hsCle}, corps));
    note('listMsg', r.message || r.error, r.ok ? 'ok' : 'err');
    if (r.ok) { $('infosVue').hidden = true; openSeries(current.id, false); }
  }
  $('infosCorps').addEventListener('click', function (e) {
    var b = e.target.closest('[data-hs-choix],[data-hs-manuel],[data-hs-retirer],[data-hs-lire],[data-hs-renommer]'); if (!b) return;
    if (b.dataset.hsRenommer) {
      var nouveau = prompt('Nouveau nom affiché pour ce hors-série :', ($('infosTitre').textContent || '').replace(/^🔎 Hors-série : /, ''));
      if (!nouveau || !nouveau.trim()) return;
      return enregistrerHorsSerie({action: 'renommer', titre: nouveau.trim()});
    }
    if (b.dataset.hsLire) {
      var adresse = ($('hsLien').value || '').trim();
      if (!adresse) { note('listMsg', 'Colle d\'abord le lien de la page.', 'err'); return; }
      b.disabled = true;
      api('/api/hors-serie/lien?id=' + encodeURIComponent(current.id) + '&key=' + encodeURIComponent(hsCle) + '&url=' + encodeURIComponent(adresse)).then(function (r) {
        b.disabled = false;
        if (r.error) { note('listMsg', r.error, 'err'); return; }
        hsCandidats = [r.candidat].concat(hsCandidats.filter(function (c) { return c.lien !== r.candidat.lien; }));
        hsAffiche(hsDernier || {titre: r.candidat.titre});
        note('listMsg', 'Infos lues sur la page : vérifie puis choisis-les.', 'ok');
      });
      return;
    }
    if (b.dataset.hsRetirer) return enregistrerHorsSerie({action: 'retirer'});
    if (b.dataset.hsManuel) {
      var titre = prompt('Titre du hors-série (obligatoire) :', '');
      if (!titre || !titre.trim()) return;
      var annee = prompt('Année (facultatif) :', '') || '';
      var auteur = prompt('Auteur (facultatif) :', '') || '';
      var lien = prompt('Lien vers le site qui le décrit (facultatif) :', '') || '';
      return enregistrerHorsSerie({action: 'choisir', titre: titre.trim(), annee: annee.trim(), auteur: auteur.trim(), source: 'Saisie manuelle', lien: lien.trim()});
    }
    var c = hsCandidats[+b.dataset.hsChoix];
    if (c) enregistrerHorsSerie({action: 'choisir', titre: c.titre, annee: c.annee || '', auteur: c.auteur || '', editeur: c.editeur || '', source: c.source, lien: c.lien || '',
      descriptif: c.descriptif || '', type: c.type || '', sortie: c.sortie || '', pages: c.pages || '', apres_tome: c.apres_tome || ''});
  });


  $('sUnivers').addEventListener('click', async function () {
      var actuel = current.univers || '';
      var nom = prompt('Univers de « ' + current.title + ' » (ex. Seven Deadly Sins). Laisse vide pour la sortir de son univers :', actuel);
      if (nom === null) return;
      nom = nom.trim();
      var ordre = '', description = '';
      if (nom) {
        ordre = prompt('Rang de lecture dans l\'univers (1, 2, 3…) — facultatif :', current.ordre_univers || '') || '';
        description = prompt('Description de l\'univers (facultatif, gardée une fois pour toutes) :', '') || '';
      }
      var r = await post('/api/univers', {series: current.id, univers: nom, ordre: ordre.trim(), description: description.trim()});
      note('listMsg', r.message || r.error, r.ok ? 'ok' : 'err');
      if (r.ok) loadList();
    });

  $('sIdentifier').addEventListener('click', async function () {
      var serie = current.id, r = await post('/api/identifier', {series: serie});
      if (!r.ok) { note('listMsg', r.error); return; }
      suivreIdentification(serie);
    });

    // 📎 Rattacher une série (artbook, databook…) comme hors-série d'une autre
    async function rattacher(cible) {
      if (!cible || !confirm('Rattacher « ' + current.title + ' » comme hors-série de « ' + cible + ' » ? Ses fichiers rejoignent cette série (groupe Hors-série).')) return;
      var r = await post('/api/rattacher', {series: current.id, cible: cible});
      if (!r.ok) { note('sMsg', r.error, 'err'); return; }
      series = []; history.replaceState({s: r.id}, '', '#' + encodeURIComponent(r.id));
      await openSeries(r.id, false); note('sMsg', r.message, 'ok');
    }
    $('sRattacherSuggere').addEventListener('click', function (e) { var b = e.target.closest('[data-rattacher]'); if (b) rattacher(b.dataset.rattacher); });
    $('sRattacher').addEventListener('click', async function () {
      fermerMenus();
      if (!series.length) { var l = await api('/api/library'); series = l.series || []; }
      var noms = series.filter(function (x) { return !x.recherchee && x.id !== current.id; }).map(function (x) { return x.id; });
      var tape = prompt('Nom de la série dont « ' + current.title + ' » est un hors-série :', current.rattacher_a || '');
      if (!tape) return;
      var cle = function (t) { return t.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]/g, ''); };
      var cible = noms.find(function (n) { return cle(n) === cle(tape); }) || noms.find(function (n) { return cle(n).indexOf(cle(tape)) === 0; });
      if (!cible) { note('sMsg', 'Aucune série « ' + tape + ' » dans la bibliothèque.', 'err'); return; }
      rattacher(cible);
    });

    // 🪶 Alléger (sans perte visible) / 🧼 éclaircir le papier : analyse d'abord, puis application après accord
    var suiviAllege = null;
    $('sAllege').addEventListener('click', function (e) { if (e.target.closest('#sAllegeVoir')) $('sAlleger').click(); });
    $('sAlleger').addEventListener('click', function () {
      fermerMenus();
      $('infosTitre').textContent = '🪶 Alléger ou ✨ améliorer « ' + current.title + ' »';
      $('infosCorps').innerHTML = '<div class="dem-sous">Chaque tome est recompressé à la qualité la plus légère qui reste invisible à l\'écran (vérifiée sur des pages d\'essai). ' +
        'Les tomes encore partagés par qBittorrent sont allégés à part : le fichier du torrent n\'est jamais touché (la place n\'est rendue qu\'une fois le torrent supprimé). Les anciens fichiers vont à la corbeille (30 jours).</div>' +
        '<div class="ident-actions"><label>Largeur des pages : <select id="allLargeur"><option value="">garder</option><option value="1600" selected>1600 px (tablette)</option><option value="1200">1200 px (téléphone)</option></select></label></div>' +
        '<div class="amel"><div class="ident-actions"><label>✨ Améliorer l\'image (vieux scans) : <select id="allProfil">' + PROFILS_AMEL.map(function (p) { return '<option value="' + p[0] + '">' + p[1] + '</option>'; }).join('') + '<option value="perso">Personnalisée</option></select></label></div>' +
        '<div class="dem-sous">Rien n\'est fait tout seul : choisis un niveau, regarde l\'aperçu, et seulement si ça te plaît, applique. Les pages en couleur ne sont jamais touchées.</div>' +
        '<details id="allFin"><summary>Réglage fin</summary>' + REGLAGES_AMEL.map(function (r) {
          return '<div class="amel-ligne"><label for="am_' + r[0] + '">' + r[1] + '<small>' + r[2] + '</small></label><select id="am_' + r[0] + '" data-am="' + r[0] + '">' +
            (r[3] || ['Non', 'Léger', 'Moyen', 'Fort']).map(function (n, i) { return '<option value="' + i + '">' + n + '</option>'; }).join('') + '</select></div>';
        }).join('') + '</details></div>' +
        '<div class="ident-actions"><label>Qualité de l\'image : <select id="allQualMode"><option value="">Automatique (recommandé)</option><option value="m">Manuelle</option></select></label></div>' +
        '<div id="allQualManuelle" hidden><input type="range" id="allQual" min="40" max="98" step="1" value="85" style="width:100%"> <div class="dem-sous"><b id="allQualVal">85</b> / 100 : 100 = identique à l\'original, plus bas = fichier plus léger. 90 et plus : aucune différence visible ; 80-88 : très léger, visible seulement en zoomant ; sous 70 : défauts qui se voient.</div></div>' +
        '<div class="ident-actions"><button type="button" class="mou-btn" id="allComparer">👁 Comparer avant / après (en direct)</button></div>' +
        '<div id="allCmp"></div>' +
        '<div class="dbl"><div class="dem-titre">📖 Doubles pages en simples pages</div>' +
        '<div class="dem-sous">Chaque image plus large que haute est coupée en deux pages (pour tout le monde, pas seulement à l\'écran). ' +
        'Les vraies doubles (une seule grande image) restent entières : touche-les dans la planche pour les garder.</div>' +
        '<div class="ident-actions"><label>Sens : <select id="dblSens"><option value="manga">manga (droite → gauche)</option><option value="occidental">occidental (gauche → droite)</option></select></label></div>' +
        '<div class="ident-actions"><button type="button" class="mou-btn" id="dblVoir">🔍 Voir les doubles pages</button></div>' +
        '<div id="dblPlanche"></div></div>' +
        '<div class="ident-actions"><button type="button" class="mou-btn" data-alleger="0">🔍 Analyser tous les tomes (rien n\'est modifié)</button></div><div id="allRes"></div>';
      $('infosVue').hidden = false;
      suivreAllegement();
    });
    // ✨ Profils d'amélioration (ordre d'optimiser.AMELIORATIONS ; 0 = non … 3 = fort)
    var PROFILS_AMEL = [['0,0,0,0,0,0,0,0', 'Non (image d\'origine)'], ['1,1,1,1,0,1,0,0', 'Légère (scan un peu gris)'],
      ['2,2,2,1,1,2,0,0', 'Vieux scan (papier gris, trames, escaliers)'], ['3,3,3,2,2,3,0,0', 'Très abîmé (crado, délavé)']];
    var REGLAGES_AMEL = [['debruit', '🌫 Enlever le grain', 'le grain et les petits carrés de compression'],
      ['trames', '▦ Adoucir les trames', 'aplats gris pointillés → gris uni ; fort = textures fines aussi lissées'],
      ['papier', '🧼 Blanchir le papier', 'fond gris ou jauni, bulles comprises ; fort = gris très pâles effacés'],
      ['noirs', '⬛ Noirs plus francs', 'encre et texte délavés'],
      ['taches', '🧽 Effacer les poussières', 'petits points isolés sur le papier'],
      ['lisser', '〰 Lisser les traits', 'fini l\'effet escalier (bords arrondis), même taille de page'],
      ['nettete', '🔪 Plus net', 'à éviter avec « Lisser » ; fort = peut faire des contours'],
      ['agrandir', '🔍 Agrandir ×2', 'petits scans seulement : plus fin en zoomant, mais fichier 2 à 3 fois plus lourd', ['Non', '×2']]];
    function amelioration() {
      return REGLAGES_AMEL.map(function (r) { var e = $('am_' + r[0]); return e ? e.value : '0'; }).join(',');
    }
    function optionsAllegement() {
      return {largeur: $('allLargeur').value, amelio: amelioration(), qualite: $('allQualMode').value === 'm' ? $('allQual').value : ''};
    }
    async function suivreAllegement() {
      clearTimeout(suiviAllege);
      if ($('infosVue').hidden || !$('allRes')) return;
      var r = await api('/api/optimiser?series=' + encodeURIComponent(current.id));
      if (!$('allRes')) return;
      var lignes = (r.rapport || []).map(function (x) {
        return '<li>' + esc(x.fichier) + (!r.appliquer && !r.en_cours && x.qualite ? ' <button type="button" class="tog" data-comparer="' + esc(x.fichier) + '" title="Comparer avant / après">👁</button>' : '') + ' <small>' + (x.note ? esc(x.note) : (x.taille_mo + ' Mo · ' + (x.gagne_mo != null ? (x.gagne_mo >= 0 ? '−' : '+') + Math.abs(x.gagne_mo) + ' Mo' : '≈ ' + (x.gain >= 0 ? '−' : '+') + Math.abs(Math.round(x.gain * 100)) + ' %') + ' (qualité JPEG ' + x.qualite + '/100, écart ' + x.psnr + ' dB)')) + '</small></li>';
      }).join('');
      $('allRes').innerHTML = (r.en_cours ? '<div class="dem-sous">' + esc(r.message || '') + ' ' + (r.fait || 0) + ' / ' + (r.total || '?') + ' tomes · ça continue en arrière-plan, tu peux fermer cette fenêtre : une notification arrive à la fin.</div>' +
          '<progress max="' + (r.total || 1) + '" value="' + (r.fait || 0) + '" style="width:100%"></progress>' : (r.message ? '<div class="dem-sous"><b>' + esc(r.message) + '</b></div>' : '')) +
        (lignes ? '<ol class="tchap">' + lignes + '</ol>' : '') +
        (!r.en_cours && r.message && !r.appliquer && (r.gain > 0 || r.eclairer) ? '<div class="ident-actions"><button type="button" class="mou-btn" data-alleger="1">🪶 Appliquer à toute la série</button></div>' : '');
      if (r.en_cours) suiviAllege = setTimeout(suivreAllegement, 3000);
    }
    // Bulle « terminé » même si la fenêtre est fermée (le travail, lui, tourne sur le serveur)
    // Ligne permanente sous le titre : le résultat d'une analyse reste accessible après fermeture de la fenêtre
    async function majLigneAllege(id, o) {
      var l = $('sAllege'); if (!l) return;
      if (!o) o = await api('/api/optimiser?series=' + encodeURIComponent(id));
      if (!current || current.id !== id) return;
      var pret = o && !o.en_cours && o.message && (o.rapport || []).length && !o.appliquer && (o.gain > 0 || o.eclairer);
      l.hidden = !pret;
      if (pret) l.innerHTML = '🪶 Analyse prête : ' + esc(o.message) + ' <button type="button" class="mou-btn small" id="sAllegeVoir">👁 Comparer et alléger</button>';
    }
    window.MFAllege = {ligne: function (id, o) { return majLigneAllege(id, o); }, veiller: function (id) { veillerAllegement(id); }};   // appelé à l'ouverture d'une série (autre bloc)
    var veilleAllege = {};
    function veillerAllegement(id) {
      if (veilleAllege[id]) return;
      veilleAllege[id] = true;
      (async function boucle() {
        var r = await api('/api/optimiser?series=' + encodeURIComponent(id));
        if (r && r.en_cours) { setTimeout(boucle, 4000); return; }
        delete veilleAllege[id];
        if (r && r.message) {
          window.MouToast('🪶 ' + id + ' : ' + (r.appliquer ? 'allègement terminé. ' : 'analyse prête. ') + r.message, 'ok');
          if (current && current.id === id && !$('infosVue').hidden) suivreAllegement();
          else if (current && current.id === id) rafraichirSerie(id);
          majLigneAllege(id, r);
        }
      })();
    }
    // 👁 Comparer avant / après EN DIRECT : mêmes réglages que « Appliquer » (largeur, éclaircir, qualité) ; toucher l'image = détail à l'échelle réelle
    var cmp = null, cmpMinuterie = null;
    function urlCmp(cote) {
      var o = optionsAllegement();
      return '/api/optimiser/comparer?series=' + encodeURIComponent(current.id) + '&fichier=' + encodeURIComponent(cmp.fichier) + '&page=' + cmp.page +
        '&largeur=' + encodeURIComponent(o.largeur) + '&am=' + encodeURIComponent(o.amelio) + '&q=' + encodeURIComponent(o.qualite) +
        (cmp.zoom ? '&fx=' + cmp.zoom[0].toFixed(3) + '&fy=' + cmp.zoom[1].toFixed(3) : '') + '&cote=' + cote;
    }
    function ouvrirComparaison(fichier) {
      cmp = {fichier: fichier || '', page: 5, cote: 'rideau', rideau: 50, zoom: null, pages: 0, tomes: []};
      dessinerComparaison(); $('allCmp').scrollIntoView({block: 'start'});
    }
    function majComparaison() {                                   // un réglage a bougé : l'image se recalcule (après une courte pause)
      if (!cmp) return;
      clearTimeout(cmpMinuterie);
      cmpMinuterie = setTimeout(function () {
        if (!$('cmpImg') || !cmp) return;
        $('cmpInfo').textContent = 'Calcul…';
        imagesCmp();
        chargerInfoCmp();
      }, 350);
    }
    function chargerInfoCmp() {
      api(urlCmp('info')).then(function (i) {
        if (!$('cmpInfo') || !cmp) return;
        if (i.error) { $('cmpInfo').textContent = i.error; return; }
        cmp.pages = i.pages; cmp.fichier = i.fichier; cmp.tomes = i.tomes;
        var sel = $('cmpTome');
        if (sel && !sel.options.length) { sel.innerHTML = i.tomes.map(function (n) { return '<option>' + esc(n) + '</option>'; }).join(''); }
        if (sel) sel.value = i.fichier;
        $('cmpPage').textContent = 'page ' + (i.page + 1) + ' / ' + i.pages;
        var gain = i.avant_ko ? Math.round(100 * (1 - i.apres_ko / i.avant_ko)) : 0;
        $('cmpInfo').textContent = (i.couleur ? '🎨 Page en couleur : l\'amélioration ne la touche pas. ' : i.ameliore ? '✨ Amélioration appliquée. ' : '') + (i.inchange ? 'Cette page garde ses octets d\'origine (' + i.avant_ko + ' Ko) : rien à gagner à ce réglage.'
          : 'Qualité ' + i.qualite + '/100 (' + (i.auto ? 'choisie automatiquement' : 'manuelle') + ') · Avant ' + i.avant_ko + ' Ko (' + i.dimensions[0][0] + '×' + i.dimensions[0][1] + ') → Après ' + i.apres_ko + ' Ko (' + i.dimensions[1][0] + '×' + i.dimensions[1][1] + ') · ' + (gain >= 0 ? '−' : '+') + Math.abs(gain) + ' % sur cette page');
      });
    }
    function dessinerComparaison() {
      var z = $('allCmp'); if (!z || !cmp) return;
      z.innerHTML = '<div class="cmp"><div class="dem-titre">👁 Avant / après</div>' +
        '<select id="cmpTome" class="mou-field" style="width:100%">' + (cmp.tomes || []).map(function (n) { return '<option' + (n === cmp.fichier ? ' selected' : '') + '>' + esc(n) + '</option>'; }).join('') + '</select>' +
        '<div class="cmp-barre"><button type="button" class="mou-btn ghost small" data-cmp="prec">◀</button>' +
        '<span id="cmpPage">page ' + (cmp.page + 1) + (cmp.pages ? ' / ' + cmp.pages : '') + '</span>' +
        '<button type="button" class="mou-btn ghost small" data-cmp="suiv">▶</button>' +
        '<button type="button" class="mou-btn ghost small" data-cmp="fermer">✕</button></div>' +
        '<div class="cmp-cote">' + [['avant', 'Avant'], ['rideau', '↔ Rideau'], ['apres', 'Après']].map(function (c) {
          return '<button type="button" class="mou-btn' + (cmp.cote === c[0] ? '' : ' ghost') + '" data-cmp="' + c[0] + '">' + c[1] + '</button>'; }).join('') + '</div>' +
        '<div class="cmp-boite" id="cmpBoite"><img id="cmpImg" class="cmp-img" alt="">' +
        '<img id="cmpImg2" class="cmp-img cmp-dessus" alt=""><div class="cmp-trait" id="cmpTrait"></div>' +
        '<span class="cmp-et g">Avant</span><span class="cmp-et d">Après</span></div>' +
        '<input type="range" id="cmpRideau" min="0" max="100" value="' + cmp.rideau + '" aria-label="Rideau avant / après">' +
        '<div class="dem-sous" id="cmpInfo">Calcul…</div>' +
        '<div class="dem-sous">' + (cmp.zoom ? 'Détail à l\'échelle réelle : touche l\'image pour revenir à la page entière.' : 'Rideau : glisse le doigt sur l\'image (ou la barre) : à gauche l\'original, à droite le résultat. Touche un endroit pour le voir de près. Les réglages au-dessus mettent l\'image à jour.') + '</div></div>';
      imagesCmp();
      chargerInfoCmp();
    }
    // Avant, Après, ou les deux superposés avec un rideau (l'original à gauche du trait, le résultat à droite)
    function imagesCmp() {
      var a = $('cmpImg'), b = $('cmpImg2'); if (!a || !cmp) return;
      var rideau = cmp.cote === 'rideau';
      a.onload = function () { if (cmp && cmp.cote === 'rideau') poserRideau(cmp.rideau); };
      a.src = urlCmp(rideau ? 'avant' : cmp.cote);
      b.hidden = $('cmpTrait').hidden = $('cmpRideau').hidden = !rideau;
      document.querySelectorAll('.cmp-et').forEach(function (x) { x.hidden = !rideau; });
      if (rideau) { b.src = urlCmp('apres'); poserRideau(cmp.rideau); }
      else (new Image()).src = urlCmp(cmp.cote === 'avant' ? 'apres' : 'avant');   // l'autre côté se charge déjà
      document.querySelectorAll('[data-cmp=avant],[data-cmp=apres],[data-cmp=rideau]').forEach(function (x) { x.classList.toggle('ghost', x.dataset.cmp !== cmp.cote); });
    }
    function poserRideau(v) {
      cmp.rideau = Math.max(0, Math.min(100, v));
      var b = $('cmpImg2'), t = $('cmpTrait'), a = $('cmpImg'); if (!b) return;
      // le trait suit l'image réellement affichée (elle peut être centrée avec des bandes noires)
      var bw = a.clientWidth, dw = a.naturalWidth && a.naturalHeight ? Math.min(bw, a.naturalWidth * a.clientHeight / a.naturalHeight) : bw,
          x = (bw - dw) / 2 + dw * cmp.rideau / 100;
      b.style.clipPath = 'inset(0 0 0 ' + x + 'px)';
      t.style.left = x + 'px';
      if ($('cmpRideau')) $('cmpRideau').value = Math.round(cmp.rideau);
    }
    var glisse = null;                          // doigt qui fait glisser le rideau (sinon : simple toucher = zoom)
    function xRideau(e) {
      var a = $('cmpImg'), r = a.getBoundingClientRect(),
          dw = a.naturalWidth ? Math.min(r.width, a.naturalWidth * r.height / a.naturalHeight) : r.width;
      return 100 * (e.clientX - r.left - (r.width - dw) / 2) / dw;
    }
    $('infosCorps').addEventListener('pointerdown', function (e) {
      if (!cmp || cmp.cote !== 'rideau' || !e.target.closest('#cmpBoite')) return;
      glisse = {x: e.clientX, bouge: false};
    });
    $('infosCorps').addEventListener('pointermove', function (e) {
      if (!glisse) return;
      if (!glisse.bouge && Math.abs(e.clientX - glisse.x) < 8) return;
      glisse.bouge = true; poserRideau(xRideau(e));
    });
    document.addEventListener('pointerup', function () { if (glisse) setTimeout(function () { glisse = null; }, 0); });
    document.addEventListener('pointercancel', function () { glisse = null; });
    window.addEventListener('resize', function () { if (cmp && cmp.cote === 'rideau') poserRideau(cmp.rideau); });
    $('infosCorps').addEventListener('input', function (e) {
      if (e.target.id === 'allQual') { $('allQualVal').textContent = e.target.value; majComparaison(); }
      else if (e.target.id === 'cmpRideau' && cmp) poserRideau(+e.target.value);
    });
    $('infosCorps').addEventListener('change', function (e) {
      if (e.target.id === 'allQualMode') { $('allQualManuelle').hidden = e.target.value !== 'm'; majComparaison(); }
      else if (e.target.id === 'allLargeur') majComparaison();
      else if (e.target.id === 'allProfil') {
        if (e.target.value !== 'perso') { var v = e.target.value.split(','); REGLAGES_AMEL.forEach(function (r, i) { $('am_' + r[0]).value = v[i]; }); }
        else $('allFin').open = true;
        if (!cmp) ouvrirComparaison(''); else majComparaison();
      }
      else if (e.target.dataset && e.target.dataset.am) {
        var am = amelioration(); $('allProfil').value = PROFILS_AMEL.some(function (p) { return p[0] === am; }) ? am : 'perso';
        if (!cmp) ouvrirComparaison(''); else majComparaison();
      }
      else if (e.target.id === 'cmpTome' && cmp) { cmp.fichier = e.target.value; cmp.zoom = null; dessinerComparaison(); }
    });
    $('infosCorps').addEventListener('click', function (e) {
      if (e.target.closest('#allComparer')) { ouvrirComparaison(''); return; }
      var c = e.target.closest('[data-comparer]');
      if (c) { ouvrirComparaison(c.dataset.comparer); return; }
      var b = e.target.closest('[data-cmp]');
      if (b && cmp) {
        var a = b.dataset.cmp;
        if (a === 'fermer') { cmp = null; $('allCmp').innerHTML = ''; return; }
        if (a === 'avant' || a === 'apres' || a === 'rideau') { cmp.cote = a; imagesCmp(); return; }
        cmp.page = Math.max(0, Math.min((cmp.pages || 1) - 1, cmp.page + (a === 'suiv' ? 1 : -1))); cmp.zoom = null; dessinerComparaison(); return;
      }
      var img = e.target.closest('#cmpBoite') && $('cmpImg');
      if (img && cmp && glisse && glisse.bouge) return;               // c'était un glissement du rideau, pas un toucher
      if (img && cmp) {
        if (cmp.zoom) cmp.zoom = null;
        else {                                   // position réelle dans l'image (elle est centrée dans son cadre)
          var r = img.getBoundingClientRect(), sc = Math.min(r.width / img.naturalWidth, r.height / img.naturalHeight),
              dw = img.naturalWidth * sc, dh = img.naturalHeight * sc;
          cmp.zoom = [(e.clientX - r.left - (r.width - dw) / 2) / dw, (e.clientY - r.top - (r.height - dh) / 2) / dh];
        }
        dessinerComparaison();
      }
    });
    // 📖 Doubles pages : un tome à la fois ; planche de vignettes, tout est coupé par défaut, on touche les vraies doubles pour les garder
    var dblGardees = {}, dblTomes = [], dblCourant = '', dblCol = 2;
    try { dblCol = Math.max(1, Math.min(3, parseInt(localStorage.getItem('mfDblCol'), 10) || 2)); } catch (e) {}
    function dblSerie() { return encodeURIComponent(current.id); }
    function dblTome() { return dblTomes.filter(function (t) { return t.fichier === dblCourant; })[0]; }
    async function voirDoubles() {
      var ancien = $('dblEtat') ? $('dblEtat').innerHTML : '';          // le message de la dernière découpe reste affiché
      $('dblPlanche').innerHTML = '<div class="dem-sous">Recherche des doubles pages…</div>';
      var r = await api('/api/doubles?series=' + dblSerie());
      if (r.error) { $('dblPlanche').innerHTML = '<div class="dem-sous">' + esc(r.error) + '</div>'; return; }
      dblTomes = r.tomes || []; dblGardees = {}; dblCourant = '';
      if (!dblTomes.length) { $('dblPlanche').innerHTML = '<div class="dem-sous">Aucune double page dans cette série.</div>'; return; }
      $('dblPlanche').innerHTML = '<div class="dem-sous">Choisis un tome :</div><div class="dbl-liste">' + dblTomes.map(function (t) {
        return '<button type="button" class="mou-btn ghost" data-dbl-tome="' + esc(t.fichier) + '">' + (t.fait ? '<span class="dbl-point" title="Déjà découpé"></span>' : '') +
          esc(t.fichier.replace(/\.(cbz|zip)$/i, '')) + ' · ' + (t.fait ? 'déjà découpé' + (t.date ? ' le ' + esc(t.date) : '') + (t.pages.length ? ' · ' + t.pages.length + ' double(s) gardée(s)' : '') : t.pages.length + ' double(s)') + '</button>';
      }).join('') + '</div><div id="dblTome"></div><div id="dblEtat">' + ancien + '</div>';
    }
    function grilleDoubles() {
      var t = dblTome(); if (!t || !$('dblGrille')) return;
      var w = {1: 700, 2: 450, 3: 300}[dblCol];
      $('dblGrille').style.gridTemplateColumns = 'repeat(' + dblCol + ', 1fr)';
      $('dblGrille').innerHTML = t.pages.map(function (pg, i) {
        var c = t.fichier + '|' + pg.index;
        return '<button type="button" class="dbl-tuile' + (dblGardees[c] ? ' garde' : '') + '" data-dbl-tuile="' + esc(c) + '">' +
          '<img loading="lazy" alt="" src="/api/doubles/image?series=' + dblSerie() + '&fichier=' + encodeURIComponent(t.fichier) + '&n=' + pg.index + '&w=' + w + '">' +
          '<span>' + (i + 1) + '</span></button>';
      }).join('');
    }
    function planchesDoubles(fichier) {
      dblCourant = fichier; dblGardees = {};
      document.querySelectorAll('[data-dbl-tome]').forEach(function (b) { b.classList.toggle('ghost', b.dataset.dblTome !== fichier); });
      var deja = dblTome();
      if (deja && deja.fait && !deja.pages.length) { $('dblTome').innerHTML = '<div class="dem-sous">🟢 Ce tome est déjà découpé : plus aucune double page.</div>'; return; }
      $('dblTome').innerHTML = (deja && deja.fait ? '<div class="dem-sous">🟢 Ce tome est déjà découpé : les doubles ci-dessous sont celles que tu avais gardées entières.</div>' : '') +
        '<div class="ident-actions"><label>Vignettes par ligne : <select id="dblCols">' +
        [1, 2, 3].map(function (n) { return '<option value="' + n + '"' + (n === dblCol ? ' selected' : '') + '>' + n + '</option>'; }).join('') + '</select></label></div>' +
        '<div class="dbl-grille" id="dblGrille"></div><div class="ident-actions" id="dblBilan"></div>';
      grilleDoubles(); majBilanDoubles();
    }
    function majBilanDoubles() {
      var t = dblTome(); if (!t || !$('dblBilan')) return;
      var gardees = Object.keys(dblGardees).length;
      $('dblBilan').innerHTML = '<div class="dem-sous">' + (t.pages.length - gardees) + ' double(s) seront coupées, ' + gardees + ' gardée(s) entière(s).</div>' +
        '<button type="button" class="mou-btn" id="dblCouper">✂️ Découper ce tome en simples pages</button>';
    }
    $('infosCorps').addEventListener('change', function (e) {
      if (e.target.id !== 'dblCols') return;
      dblCol = parseInt(e.target.value, 10) || 2;
      try { localStorage.setItem('mfDblCol', String(dblCol)); } catch (x) {}
      grilleDoubles();
    });
    $('infosCorps').addEventListener('click', async function (e) {
      if (e.target.closest('#dblVoir')) { voirDoubles(); return; }
      var tm = e.target.closest('[data-dbl-tome]');
      if (tm) { planchesDoubles(tm.dataset.dblTome); return; }
      var t = e.target.closest('[data-dbl-tuile]');
      if (t) {
        var c = t.dataset.dblTuile;
        if (dblGardees[c]) delete dblGardees[c]; else dblGardees[c] = true;
        t.classList.toggle('garde', !!dblGardees[c]); majBilanDoubles(); return;
      }
      if (e.target.closest('#dblCouper')) {
        var tome = dblTome(); if (!tome) return;
        var indices = tome.pages.filter(function (pg) { return !dblGardees[tome.fichier + '|' + pg.index]; }).map(function (pg) { return pg.index; });
        if (!indices.length) { alert('Toutes les doubles sont gardées entières : rien à couper.'); return; }
        if (!confirm('Couper ' + indices.length + ' double(s) en deux dans « ' + tome.fichier + ' » ? L\'ancien fichier va à la corbeille (30 jours).')) return;
        var r = await post('/api/doubles/couper', {series: current.id, sens: $('dblSens').value, plan: [{fichier: tome.fichier, indices: indices}]});
        if (!r.ok) { alert(r.error || 'Impossible'); return; }
        suivreDoubles();
      }
    });
    async function suivreDoubles() {
      var r = await api('/api/doubles/etat?series=' + dblSerie());
      if (!$('dblEtat')) return;
      if (r.en_cours) {
        $('dblEtat').innerHTML = '<div class="dem-sous">Découpe en cours : ' + (r.fait || 0) + ' / ' + (r.total || '?') + ' tome(s)…</div>';
        setTimeout(suivreDoubles, 3000); return;
      }
      if (r.message) {
        $('dblEtat').innerHTML = '<div class="dem-sous"><b>' + esc(r.message) + '</b></div>' + (r.rapport || []).map(function (x) {
          return '<div class="dem-sous">' + esc(x.fichier) + (x.pages ? ' : ' + x.pages_avant + ' → ' + x.pages + ' pages' : '') + (x.note ? ' (' + esc(x.note) + ')' : '') + '</div>';
        }).join('');
        window.MouToast && window.MouToast('📖 ' + r.message, 'ok');
        rafraichirSerie(current.id);
        voirDoubles();                                               // la liste des tomes se met à jour (nombre de doubles restantes)
      }
    }
    $('infosCorps').addEventListener('click', async function (e) {
      var b = e.target.closest('[data-alleger]'); if (!b) return;
      var appliquer = b.dataset.alleger === '1';
      if (appliquer && !confirm('Alléger tous les tomes de « ' + current.title + ' » avec ces réglages ? Les anciens fichiers vont à la corbeille (30 jours).')) return;
      var r = await post('/api/optimiser', Object.assign({series: current.id, appliquer: appliquer}, optionsAllegement()));
      if (!r.ok) { alert(r.error || 'Impossible'); return; }
      if (appliquer) { cmp = null; if ($('allCmp')) $('allCmp').innerHTML = ''; }
      setTimeout(suivreAllegement, 800);
      veillerAllegement(current.id);
    });

    // 📱 Tomes gardés sur ce téléphone (lecture sans réseau) et notifications
    function fichierDuTome(n) {
      var es = (current.chapters || []).filter(function (c) { return String(c.tome) === String(Number(n)) || c.groupe === 'Tome ' + String(n).padStart(2, '0'); });
      if (!es.length) return null;
      var path = es[0].path;
      return {path: path, mo: es.filter(function (c) { return c.path === path; }).reduce(function (t, c) { return t + (c.size_mb || 0); }, 0), cle: es[0].key};
    }
    function boutonGarder(n) {
      var f = fichierDuTome(n), hl = window.MFHorsLigne;
      if (!f || !hl || !('caches' in window)) return '';
      return '<div class="ident-actions" id="garderZone">' + (hl.estGarde(current.id, f.path)
        ? '<span class="dem-sous">📱 Ce tome est sur ce téléphone.</span> <button type="button" class="mou-btn ghost" data-oublier="' + n + '">Le retirer</button>'
        : '<button type="button" class="mou-btn ghost" data-garder="' + n + '">⬇️ Garder sur ce téléphone (' + Math.round(f.mo) + ' Mo)</button>') + '</div>';
    }
    $('infosCorps').addEventListener('click', async function (e) {
      var b = e.target.closest('[data-garder],[data-oublier]'); if (!b) return;
      var n = b.dataset.garder || b.dataset.oublier, f = fichierDuTome(n), hl = window.MFHorsLigne;
      if (b.dataset.oublier) { await hl.retirer(current.id, f.path); afficherTome(n, false); return; }
      var p = await hl.place();
      if (!confirm('Garder ce tome sur le téléphone pour le lire sans réseau ?\nTaille : ' + Math.round(f.mo) + ' Mo' +
        (p ? '\nPlace libre pour l\'appli : ' + (p.libre / 1073741824).toFixed(1) + ' Go' : ''))) return;
      b.disabled = true;
      try {
        await hl.garder({serie: current.id, path: f.path, cle: f.cle, titre: current.title + ' · Tome ' + String(n).padStart(2, '0'), tailleMo: f.mo},
          function (k, total) { b.textContent = '⬇️ ' + k + ' / ' + total + ' pages…'; });
        afficherTome(n, false);
      } catch (x) { b.disabled = false; alert(x.message); }
    });
    $('btnTelephone').addEventListener('click', async function () {
      var hl = window.MFHorsLigne;
      $('infosTitre').textContent = '📱 Sur ce téléphone';
      $('infosVue').hidden = false;
      if (!hl) { $('infosCorps').innerHTML = '<div class="dem-sous">Indisponible dans ce navigateur.</div>'; return; }
      var l = hl.liste(), p = await hl.place(), total = l.reduce(function (t, x) { return t + (x.octets || 0); }, 0);
      var tomes = l.length ? '<ol class="tchap">' + l.map(function (x) {
        return '<li><a href="/lire?s=' + encodeURIComponent(x.serie) + '&c=' + encodeURIComponent(x.cle) + '">' + esc(x.titre) + '</a> <small>' +
          Math.round((x.octets || 0) / 1048576) + ' Mo · ' + esc(x.date) + '</small> <button type="button" class="tog" data-retirer-tel="' + esc(x.serie) + '|' + esc(x.path) + '">🗑</button></li>';
      }).join('') + '</ol>' : '<div class="dem-sous">Aucun tome gardé. Dans la fenêtre ⓘ d\'un tome : « ⬇️ Garder sur ce téléphone ».</div>';
      $('infosCorps').innerHTML = '<div class="dem-titre">Tomes lisibles sans réseau</div>' + tomes +
        '<div class="dem-sous">' + Math.round(total / 1048576) + ' Mo utilisés' + (p ? ' · ' + (p.libre / 1073741824).toFixed(1) + ' Go encore disponibles' : '') + '</div>' +
        '<div class="ident-actions"><label><input type="checkbox" id="telEffacerLu"' + (hl.effacerSiLu() ? ' checked' : '') + '> Effacer un tome du téléphone une fois lu</label></div>' +
        '<div class="dem-titre">🔔 Notifications sur ce téléphone</div><div id="telNotif" class="dem-sous">…</div>';
      dessinerNotifications();
    });
    async function dessinerNotifications() {
      var hl = window.MFHorsLigne, z = $('telNotif'); if (!z) return;
      var e;
      try { e = await hl.etatNotifications(); } catch (x) { z.textContent = 'Indisponible : ' + x.message; return; }
      if (!e.possible) { z.textContent = 'Ce navigateur ne gère pas les notifications. Sur iPhone, ajoute d\'abord MouFlanga à l\'écran d\'accueil.'; return; }
      z.innerHTML = (e.sujets || []).map(function (s) {
        return '<label class="tel-sujet"><input type="checkbox" data-sujet="' + s.id + '"' + (!e.abonne || e.choisis.indexOf(s.id) >= 0 ? ' checked' : '') + '> ' + esc(s.nom) + '</label>';
      }).join('') + '<div class="ident-actions">' +
        (e.abonne ? '<button type="button" class="mou-btn" data-notif="maj">Enregistrer</button><button type="button" class="mou-btn ghost" data-notif="essai">Essai</button><button type="button" class="mou-btn ghost" data-notif="couper">Couper</button>'
          : '<button type="button" class="mou-btn" data-notif="maj">🔔 Activer sur ce téléphone</button>') + '</div>' +
        '<small>Telegram continue de recevoir les alertes (historique).</small>';
    }
    $('infosCorps').addEventListener('change', function (e) {
      if (e.target.id === 'telEffacerLu') { try { localStorage.setItem('mfEffacerLu', e.target.checked ? '1' : '0'); } catch (x) {} }
    });
    $('infosCorps').addEventListener('click', async function (e) {
      var r = e.target.closest('[data-retirer-tel]');
      if (r) { var p = r.dataset.retirerTel.split('|'); await window.MFHorsLigne.retirer(p[0], p.slice(1).join('|')); $('btnTelephone').click(); return; }
      var b = e.target.closest('[data-notif]'); if (!b) return;
      var hl = window.MFHorsLigne;
      try {
        if (b.dataset.notif === 'couper') await hl.couperNotifications();
        else if (b.dataset.notif === 'essai') { var x = await hl.essaiNotification(); alert(x.message || x.error); }
        else await hl.activerNotifications([].slice.call(document.querySelectorAll('[data-sujet]')).filter(function (c) { return c.checked; }).map(function (c) { return c.dataset.sujet; }));
      } catch (x) { alert(x.message); }
      dessinerNotifications();
    });

    $('sDecouper').addEventListener('click', function () { fermerMenus(); location.href = '/decouper?id=' + encodeURIComponent(current.id); });

    // 🔎 Choisir soi-même la fiche AniList (série mal reconnue : Crows, Prisonnier Riku…)
    var STATUTS_AL = {FINISHED: 'terminée', RELEASING: 'en cours', HIATUS: 'en pause', CANCELLED: 'arrêtée', NOT_YET_RELEASED: 'à paraître'};
    $('sChoisirFiche').addEventListener('click', function () {
      fermerMenus();
      $('infosTitre').textContent = '🔎 Fiche de « ' + current.title + ' »';
      $('infosCorps').innerHTML = '<div class="dem-sous">Tape le titre japonais, anglais ou l\'auteur, puis choisis la bonne fiche.' +
        (current.anilist_choisi ? ' Fiche choisie à la main : n° ' + esc(current.anilist_choisi) + '.' : (current.anilist ? ' Fiche trouvée automatiquement : n° ' + esc(current.anilist) + '.' : ' Aucune fiche trouvée pour l\'instant.')) + '</div>' +
        '<div class="ident-actions"><input type="search" id="ficheQ" class="fiche-q" value="' + esc(current.title) + '" style="flex:1;min-width:0"><button type="button" class="mou-btn" id="ficheGo">Chercher</button></div>' +
        (current.anilist_choisi ? '<div class="ident-actions"><button type="button" class="mou-btn ghost" data-fiche-auto="1">↺ Revenir à la recherche automatique</button></div>' : '') +
        '<div id="ficheRes"></div>';
      $('infosVue').hidden = false;
      var chercher = async function () {
        $('ficheRes').innerHTML = '<div class="dem-sous">Recherche…</div>';
        var r = await api('/api/identifier/chercher?q=' + encodeURIComponent($('ficheQ').value));
        if (r.error) { $('ficheRes').innerHTML = '<div class="dem-sous">' + esc(r.error) + '</div>'; return; }
        $('ficheRes').innerHTML = (r.resultats || []).map(function (m) {
          return '<div class="fiche-choix' + (m.id === (current.anilist_choisi || current.anilist) ? ' actuelle' : '') + '">' + (m.couverture ? '<img src="' + esc(m.couverture) + '" alt="">' : '<div></div>') +
            '<div><b>' + esc(m.titre) + '</b>' + (m.anglais && m.anglais !== m.titre ? '<small>' + esc(m.anglais) + '</small>' : '') + (m.natif ? '<small>' + esc(m.natif) + '</small>' : '') +
            '<small>' + [m.annee, STATUTS_AL[m.statut] || '', m.tomes ? m.tomes + ' tomes' : '', m.format === 'NOVEL' ? 'roman' : ''].filter(Boolean).join(' · ') +
            (m.lien ? ' · <a href="' + esc(m.lien) + '" target="_blank" rel="noopener">voir ↗</a>' : '') + '</small>' +
            '<button type="button" class="mou-btn" data-fiche="' + m.id + '">C\'est celle-ci</button></div></div>';
        }).join('') || '<div class="dem-sous">Aucun résultat : essaie un autre titre.</div>';
      };
      $('ficheGo').addEventListener('click', chercher);
      $('ficheQ').addEventListener('keydown', function (e) { if (e.key === 'Enter') chercher(); });
      chercher();
    });
    $('infosCorps').addEventListener('click', async function (e) {
      var b = e.target.closest('[data-fiche],[data-fiche-auto]'); if (!b) return;
      var r = await post('/api/identifier/choisir', {series: current.id, anilist: b.dataset.fiche || null});
      if (!r.ok) { alert(r.error || 'Impossible'); return; }
      suivreIdentification(current.id);
    });

    // 🔄 Fenêtre d'avancement : chaque étape de la ré-identification, mise à jour toutes les 1,5 s
    var ICONE_ETAPE = {attente: '⏳', en_cours: '🔄', ok: '✅', echec: '⚠️'};
    function suivreIdentification(serie) {
      var nom = serie;
      $('infosTitre').textContent = '🔄 Identification : ' + nom;
      $('infosVue').hidden = false;
      function dessiner(r) {
        var lignes = (r.etapes || []).map(function (e) {
          return '<li class="ident-' + e.etat + '"><span>' + (ICONE_ETAPE[e.etat] || '•') + '</span><div><b>' + esc(e.nom) + '</b>'
            + (e.detail ? '<small>' + esc(e.detail) + '</small>' : '') + '</div></li>';
        }).join('');
        var fin = r.fini ? '<p class="dem-sous"><b>Terminé.</b> La fiche de la série a été rechargée avec les nouvelles infos.</p>'
          : '<p class="dem-sous">En cours… tu peux fermer cette fenêtre : la fiche se rechargera toute seule à la fin.</p>';
        $('infosCorps').innerHTML = '<ul class="ident-liste">' + lignes + '</ul>' + fin;
      }
      var visible = function () { return !$('infosVue').hidden && $('infosTitre').textContent === '🔄 Identification : ' + nom; };
      async function boucle() {
        // fenêtre fermée : on continue d'interroger (sans rien dessiner) pour recharger la fiche à la fin
        var r = await api('/api/identifier/etat?series=' + encodeURIComponent(serie));
        if (r.error) { if (visible()) $('infosCorps').innerHTML = '<div class="dem-sous">' + esc(r.error) + '</div>'; return; }
        if (visible()) dessiner(r);
        if (r.fini) {
          loadList();
          if (current && current.id === serie) await openSeries(serie, false);   // la page de la série affiche les nouvelles infos
          return;
        }
        setTimeout(boucle, 1500);
      }
      $('infosCorps').innerHTML = '<div class="dem-sous">Démarrage…</div>';
      boucle();
    }

    $('sRenommer').addEventListener('click', async function () {
      var nom = prompt('Nouveau nom de la série :', current.title);
      if (!nom || nom.trim() === current.title) return;
      var r = await post('/api/renommer', {series: current.id, nom: nom.trim()});
      if (!r.ok && r.existe) {
        var choix = await choixFusion(r, current.title, nom.trim());
        if (!choix) return;
        r = await post('/api/renommer', {series: current.id, nom: nom.trim(), fusionner: choix});
      }
      if (!r.ok) { note('sMsg', r.error); return; }
      history.replaceState({s: r.id}, '', '#' + encodeURIComponent(r.id));
      await openSeries(r.id, false);
      note('sMsg', r.message || 'Série renommée.', 'ok');
    });
    // Fusion avec une série déjà là : ajouter seulement les tomes manquants, tout remplacer, ou ne rien faire
    function choixFusion(r, source, cible) {
      return new Promise(function (fin) {
        var o = document.createElement('div'); o.className = 'choix-fond';
        o.innerHTML = '<div class="choix-boite" role="dialog"><h3>' + esc(r.error) + '</h3>' +
          '<p>« ' + esc(source) + ' » : ' + r.tomes_source + ' tome(s) · « ' + esc(cible) + ' » : ' + r.tomes_cible + ' tome(s)<br>' +
          r.communs + ' tome(s) en commun · ' + r.manquants + ' tome(s) que « ' + esc(cible) + ' » n\'a pas.</p>' +
          (r.communs ? '<p class="dem-sous">⚠️ Si ce sont deux éditions différentes (Perfect, Deluxe…), leurs tomes ne contiennent pas les mêmes chapitres : mieux vaut garder deux séries.</p>' : '') +
          (r.partage ? '<p class="dem-sous">⚠️ Fichiers encore partagés par qBittorrent : la fusion sera refusée tant que le torrent n\'est pas retiré.</p>' : '') +
          '<button type="button" class="mou-btn" data-choix="manquants">➕ Ajouter seulement les tomes manquants</button>' +
          '<button type="button" class="mou-btn" data-choix="remplacer">♻️ Remplacer les tomes en double (mêmes numéros seulement)</button>' +
          '<button type="button" class="mou-btn" data-choix="serie">🔁 Remplacer toute la série (« ' + esc(cible) + ' » entière à la corbeille)</button>' +
          '<button type="button" class="mou-btn ghost" data-choix="">✋ Ne rien faire</button></div>';
        o.addEventListener('click', function (e) {
          var b = e.target.closest('[data-choix]');
          if (!b && e.target !== o) return;
          o.remove(); fin(b ? b.dataset.choix : '');
        });
        document.body.appendChild(o);
      });
    }
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
    $('serPrec').addEventListener('click', function () { var v = voisinsSeries(); if (v.prec) openSeries(v.prec.id); });
    $('affFermer').addEventListener('click', function () { $('affVue').hidden = true; });
    $('affVue').addEventListener('click', function (e) { if (e.target === $('affVue')) $('affVue').hidden = true; });
    $('affNav').addEventListener('change', function () { setPref('mfNavStyle', $('affNav').value); if (current) majNavSeries(); });
    $('affAuto').addEventListener('change', function () { setPref('mfAutoGenerique', $('affAuto').value); if (window._majBoutonAuto) window._majBoutonAuto(); if ($('affAuto').value !== '1') arreterGenerique(); });
    $('serSuiv').addEventListener('click', function () { var v = voisinsSeries(); if (v.suiv) openSeries(v.suiv.id); });
    $('sInfos').addEventListener('click', async function () {
      $('infosTitre').textContent = 'ℹ️ ' + current.title; $('infosCorps').innerHTML = '<div class="dem-sous">Recherche des infos…</div>'; $('infosVue').hidden = false;
      var f = await api('/api/fiche?id=' + encodeURIComponent(current.id));
      var ed = f.edition || {}, st = {RELEASING: 'en cours', FINISHED: 'terminée', HIATUS: 'en pause', CANCELLED: 'arrêtée'}[f.statut] || '';
      var lignes = [
        ['Titre original', [f.titre_original, f.romaji].filter(Boolean).join(' · ')],
        ['Parution', f.debut ? f.debut + (f.fin ? ' → ' + f.fin : ' → ' + (st || '…')) + (f.fin && st ? ' (' + st + ')' : '') : st],
        ['Note', f.note ? String(f.note).replace('.', ',') + ' / 10 (' + f.note_source + ')' : ''], ['Scénario', f.scenario], ['Dessin', f.dessin && f.dessin !== f.scenario ? f.dessin : (f.dessin ? '(même auteur)' : '')],
        ['Genres', f.genres], ['Éditeur japonais', f.editeur_jp], ['Éditeur français', f.editeur_fr], ['Autres éditeurs (MangaUpdates)', f.editeurs_mu], ['Tomes de ton édition', f.volumes_edition ? String(f.volumes_edition) : ''], ['Volumes (MangaUpdates)', f.volumes_mu ? String(f.volumes_mu) : ''], ['Sources consultées', (f.sources || []).join(', ')],
        ['Univers', f.univers ? f.univers + (f.ordre_univers ? ' · tome ' + f.ordre_univers + ' de la lecture' : '') : ''], ['Autres œuvres de l\'univers', (f.membres_univers || []).join(' → ')],
        ['Trouvée sur', f.source_suivi], ['Version', (f.versions || []).join(', ')], ['Source', [ed.source ? ed.source + (ed.devine ? ' (deviné)' : '') : '', ed.resolution].filter(Boolean).join(' · ')]
      ].filter(function (l) { return l[1]; });
      $('infosCorps').innerHTML = (lignes.length ? '<dl>' + lignes.map(function (l) { return '<dt>' + l[0] + '</dt><dd>' + esc(l[1]) + '</dd>'; }).join('') + '</dl>'
        : '<div class="dem-sous">Aucune info trouvée.</div>') + (f.wikipedia ? '<a class="infos-lien" href="https://fr.wikipedia.org/wiki/' + encodeURIComponent(f.wikipedia) + '" target="_blank" rel="noopener">Wikipédia ↗</a>' : '') + (/^https?:\/\//.test(f.lien_source || '') ? '<a class="infos-lien" href="' + esc(f.lien_source) + '" target="_blank" rel="noopener">Site source ↗</a>' : '');
    });
    $('sTitle').addEventListener('click', function () { this.classList.toggle('deplie'); });         // titre complet au toucher
    $('infosFermer').addEventListener('click', function () { $('infosVue').hidden = true; });
    // ⓘ d'un tome : titre, sortie en France, couverture, résumé, chapitres (Wikipédia)
    $('chapters').addEventListener('click', async function (e) {
      var b = e.target.closest('[data-tinfo]'); if (!b) return;
      e.stopPropagation(); e.preventDefault();
      afficherTome(b.dataset.tinfo, true);
    }, true);
    var suiviSommaire = null;
    async function afficherTome(n, premier) {
      clearTimeout(suiviSommaire);
      if (premier) { $('infosTitre').textContent = 'ℹ️ Tome ' + String(n).padStart(2, '0'); $('infosCorps').innerHTML = '<div class="dem-sous">…</div>'; $('infosVue').hidden = false; }
      if ($('infosVue').hidden) return;
      var d = await api('/api/tome?id=' + encodeURIComponent(current.id) + '&tome=' + n);
      if ($('infosVue').hidden || $('infosTitre').textContent !== 'ℹ️ Tome ' + String(n).padStart(2, '0')) return;
      var som = d.sommaire || {};
      var cov = '/api/tome/couverture?id=' + encodeURIComponent(current.id) + '&tome=' + n;
      var prov = d.provenance || {};
      var provTexte = (prov.equipe ? 'Équipe : ' + prov.equipe + ' · ' : '') + (prov.origine || '') + (prov.manuel ? ' (saisi à la main)' : '');
      var champs = [['Titre', d.titre], ['Sortie en France', d.sortie], ['Provenance', provTexte.trim() ? provTexte : '']].filter(function (x) { return x[1]; });
      var chap = d.chapitres || [], pagesCh = d.chapitres_pages || [];
      var lien = function (c, i) {                    // chapitre lu dans le sommaire d'un tome complet : ouvert à sa page
        if (d.fichier && pagesCh[i] != null) return '<a href="/lire?s=' + encodeURIComponent(current.id) + '&c=' + encodeURIComponent(d.fichier) + '&p=' + pagesCh[i] + '">' + esc(c) + '</a>';
        return lienChapitre(c, n);
      };
      $('infosCorps').innerHTML = '<div class="tome-fiche"><img class="tome-couv" src="' + cov + '" alt="" data-grand="' + cov + '&grand=1">' +
        '<div class="tome-champs">' + (champs.length ? champs.map(function (x) { return '<div class="champ"><small>' + x[0] + '</small><div>' + esc(x[1]) + '</div></div>'; }).join('')
          : (chap.length ? '' : '<div class="dem-sous">Pas d\'infos sur ce tome.</div>')) + '</div></div>' +
        (d.resume ? '<div class="dem-titre">Résumé' + (d.resume_source ? ' <small>(' + esc(d.resume_source) + ')</small>' : '') + '</div><p class="tome-resume" id="tomeResumeTexte">' + esc(d.resume) + '</p>' : '') +
        '<div class="ident-actions admin-seul"><button type="button" class="mou-btn ghost" id="tomeResumeModif" data-tome="' + n + '">✏️ ' + (d.resume ? 'Modifier' : 'Écrire') + ' le résumé du tome</button></div>' +
        '<div id="tomeResumeEdit" hidden><textarea id="tomeResumeZone" class="mou-field" rows="8" style="width:100%" maxlength="5000"></textarea>' +
        '<div class="ident-actions"><button type="button" class="mou-btn" id="tomeResumeSave" data-tome="' + n + '">💾 Enregistrer</button>' +
        '<button type="button" class="mou-btn ghost" id="tomeResumeAuto" data-tome="' + n + '"' + (d.resume_manuel ? '' : ' hidden') + '>↩️ Remettre le résumé automatique</button>' +
        '<button type="button" class="mou-btn ghost" id="tomeResumeCancel">Annuler</button></div></div>' +
        (som.en_cours ? '<div class="dem-sous">🔍 Lecture du sommaire dans les premières pages… (environ une minute)</div>'
          : (som.message && !chap.length ? '<div class="dem-sous">' + esc(som.message) + '</div>' : '')) +
        (som.manquants && som.manquants.length ? '<div class="tome-statut verif">⚠️ Il manque dans la liste le' + (som.manquants.length > 1 ? 's chapitres ' : ' chapitre ') +
          esc(som.manquants.join(', ')) + ' : le sommaire du tome les compte-t-il ? Corrige la liste (✏️) ou relis le sommaire.</div>' : '') +
        (som.lu ? '<div class="tome-statut ' + (som.manuel || som.fichier ? 'ok' : 'verif') + '">' +
          (som.fichier ? '✅ Chapitres écrits dans le fichier' :
           som.manuel ? '✅ Validé à la main' + (som.valide_le ? ' le ' + esc(som.valide_le) : '') + ' : rien à revérifier' :
           '⚠️ Lu automatiquement : titres fiables, pages approximatives. À vérifier, puis valider.' +
           '<div class="ident-actions admin-seul"><button type="button" class="mou-btn" data-valider="' + n + '">✅ C\'est bon, valider</button></div>') + '</div>' : '') +
        (chap.length ? '<div class="dem-titre">Chapitres' + (d.chapitres_langue === 'en' ? ' <small>(titres en anglais)</small>' : '') +
          (d.chapitres_source ? ' <small>(' + esc(d.chapitres_source) + ')</small>' : '') + '</div><ol class="tchap">' + chap.map(function (c, i) { return '<li>' + lien(c, i) + '</li>'; }).join('') + '</ol>' +
          '<div class="ident-actions admin-seul"><button type="button" class="mou-btn ghost" id="chapEditer">✏️ Corriger les chapitres</button>' +
          '</div>' +
          '<div id="chapEdition" hidden><textarea id="chapTexte" class="mou-field" rows="' + Math.min(14, chap.length + 2) + '" spellcheck="false" style="width:100%"></textarea>' +
          '<div class="dem-sous">Une ligne par chapitre, avec son numéro : « 2. La valeur de la vie ». Après <b>@</b> : la page du lecteur où le chapitre commence (« 2. La valeur de la vie @64 »). Sans @, la page déjà connue est gardée.</div>' +
          '<div class="ident-actions"><label>Décaler toutes les pages de <input type="number" id="chapDecalage" value="0" style="width:4.5em"></label>' +
          '<button type="button" class="mou-btn ghost" id="chapDecaler">↔ Appliquer</button></div>' +
          '<div class="ident-actions"><button type="button" class="mou-btn" id="chapEnregistrer" data-tome="' + n + '">💾 Enregistrer</button>' +
          '<button type="button" class="mou-btn ghost" id="chapAnnuler">Annuler</button></div></div>' : '') +
        boutonGarder(n) +
        '<div class="ident-actions"><button type="button" class="mou-btn ghost" data-prov="' + n + '">✏️ Noter la provenance (équipe, origine)</button>' +
        (som.possible && !som.en_cours ? '<button type="button" class="mou-btn ghost admin-seul" data-sommaire="' + n + '"' + (som.manuel ? ' data-manuel="1"' : '') + '>🔍 ' + (som.lu ? 'Relire' : 'Lire') + ' le sommaire du tome</button>' : '') + '</div>' +
        (d.ecriture_possible ? '<div class="ident-actions admin-seul"><button type="button" class="mou-btn ghost" id="chapEcrire" data-tome="' + n + '" title="Résumé, chapitres, provenance… suivent le fichier quand tu le partages">📝 Écrire les infos dans le fichier</button></div>' : '') +
        '<div id="chapEcrireMsg" class="dem-sous"></div>' ;
      var zone = $('chapTexte');
      if (zone) zone.value = chap.map(function (c, i) { return c + (d.fichier && pagesCh[i] != null ? ' @' + (pagesCh[i] + 1) : ''); }).join('\n');
      var im = $('infosCorps').querySelector('.tome-couv');
      if (im) im.addEventListener('error', function () { im.style.display = 'none'; });
      if (som.en_cours) suiviSommaire = setTimeout(function () { afficherTome(n, false); }, 4000);
    }
    $('infosCorps').addEventListener('click', async function (e) {         // ✏️ résumé du tome écrit à la main
      var m = e.target.closest('#tomeResumeModif');
      if (m) {
        var t = $('tomeResumeTexte'); $('tomeResumeZone').value = t ? t.textContent : '';
        $('tomeResumeEdit').hidden = false; m.hidden = true; $('tomeResumeZone').focus(); return;
      }
      if (e.target.closest('#tomeResumeCancel')) { $('tomeResumeEdit').hidden = true; $('tomeResumeModif').hidden = false; return; }
      var sv = e.target.closest('#tomeResumeSave, #tomeResumeAuto'); if (!sv) return;
      var texte = sv.id === 'tomeResumeAuto' ? '' : $('tomeResumeZone').value;
      sv.disabled = true;
      var r = await post('/api/tome/resume', {series: current.id, tome: sv.dataset.tome, texte: texte});
      if (!r.ok) { sv.disabled = false; alert(r.error || 'Impossible'); return; }
      window.MouToast('✅ ' + r.message, 'ok');
      afficherTome(sv.dataset.tome, false);
    });
    $('infosCorps').addEventListener('click', async function (e) {         // 🔍 relire le sommaire imprimé du tome (OCR)
      var b = e.target.closest('[data-sommaire]'); if (!b) return;
      if (b.dataset.manuel && !confirm('Tu as corrigé ces chapitres à la main. Relire le sommaire les remplace par la lecture automatique. Continuer ?')) return;
      b.disabled = true;
      var r = await post('/api/tome/sommaire', {series: current.id, tome: b.dataset.sommaire, force: !!b.dataset.manuel});
      if (!r.ok) { b.disabled = false; alert(r.error || 'Impossible'); return; }
      afficherTome(b.dataset.sommaire, false);
    });
    $('infosCorps').addEventListener('click', async function (e) {         // ✅ chapitres lus automatiquement : vérifiés, validés
      var v = e.target.closest('[data-valider]'); if (!v) return;
      v.disabled = true;
      var r = await post('/api/tome/valider', {series: current.id, tome: v.dataset.valider});
      if (!r.ok) { v.disabled = false; alert(r.error || 'Impossible'); return; }
      window.MouToast('✅ ' + r.message, 'ok');
      afficherTome(v.dataset.valider, false);
    });
    $('infosCorps').addEventListener('click', async function (e) {         // ✏️ corriger la liste des chapitres à la main
      if (e.target.closest('#chapEditer')) { $('chapEdition').hidden = false; $('chapEditer').hidden = true; $('chapTexte').focus(); return; }
      var w = e.target.closest('#chapEcrire');
      if (w) {                                                              // 📝 chapitres écrits dans le .cbz (partage de la série)
        if (!confirm('Écrire les infos du tome (résumé, chapitres, provenance…) dans son fichier ? Le fichier est réécrit (l\'ancien va à la corbeille 30 jours).')) return;
        w.disabled = true;
        var rr = await post('/api/tome/chapitres/ecrire', {series: current.id, tome: w.dataset.tome});
        if (!rr.ok) { w.disabled = false; alert(rr.error || 'Impossible'); return; }
        var msg = $('chapEcrireMsg'); if (msg) msg.textContent = '📝 ' + rr.message + ' (ça continue même si tu fermes la fenêtre)';
        (async function suivre() {
          var st = await api('/api/tome/chapitres/ecrire?series=' + encodeURIComponent(current.id) + '&tome=' + w.dataset.tome);
          if (st && st.en_cours) { setTimeout(suivre, 3000); return; }
          if (st && st.message) { window.MouToast((st.ok ? '📝 ' : '⚠️ ') + st.message, st.ok ? 'ok' : 'err'); var m2 = $('chapEcrireMsg'); if (m2) m2.textContent = st.message; }
          if (st && st.ok && !$('infosVue').hidden) afficherTome(w.dataset.tome, false);
        })();
        return;
      }
      if (e.target.closest('#chapAnnuler')) { $('chapEdition').hidden = true; $('chapEditer').hidden = false; return; }
      if (e.target.closest('#chapDecaler')) {                               // même décalage pour tous les « @page »
        var dec = parseInt($('chapDecalage').value, 10) || 0;
        $('chapTexte').value = $('chapTexte').value.split('\n').map(function (l) {
          return l.replace(/@\s*(\d+)\s*$/, function (_, v) { return '@' + Math.max(1, parseInt(v, 10) + dec); });
        }).join('\n');
        return;
      }
      var b = e.target.closest('#chapEnregistrer'); if (!b) return;
      b.disabled = true;
      var r = await post('/api/tome/chapitres', {series: current.id, tome: b.dataset.tome, texte: $('chapTexte').value});
      b.disabled = false;
      if (!r.ok) { alert(r.error || 'Impossible'); return; }
      window.MouToast('✏️ ' + r.message, 'ok');
      afficherTome(b.dataset.tome, false);
    });
    $('infosVue').addEventListener('click', function (e) { if (e.target === $('infosVue')) $('infosVue').hidden = true; });
    $('infosCorps').addEventListener('click', async function (e) {         // provenance d'un tome : équipe et origine notées à la main
      var pv = e.target.closest('[data-prov]'); if (!pv) return;
      var equipe = prompt('Équipe de scan de ce tome (ex. PapriKa) :', '');
      if (equipe === null) return;
      var origine = prompt('Origine (torrent, Japscan, achat…) — facultatif :', '') || '';
      var r = await post('/api/tome/provenance', {series: current.id, tome: pv.dataset.prov, equipe: equipe.trim(), origine: origine.trim()});
      note('listMsg', r.message || r.error, r.ok ? 'ok' : 'err');
      if (r.ok) $('infosVue').hidden = true;
    });
    $('infosCorps').addEventListener('click', function (e) {              // toucher la couverture du tome = grand format
      var im = e.target.closest('.tome-couv'); if (!im) return;
      var o = document.createElement('div'); o.className = 'couv-grand';
      o.innerHTML = '<img src="' + im.dataset.grand + '" alt="">';
      o.addEventListener('click', function () { o.remove(); });
      document.body.appendChild(o);
    });
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
    // 📝 Réécrire les infos de chaque tome complet dans son fichier (résumé, provenance, sommaire, chapitres lus)
    async function suivreInfosTous(serie) {
      var st = await api('/api/tomes/infos-ecrire?series=' + encodeURIComponent(serie));
      if (st && st.en_cours) { setTimeout(function () { suivreInfosTous(serie); }, 3000); return; }
      if (st && st.message) window.MouToast('📝 ' + st.message, /Erreurs|Échec/.test(st.message) ? 'err' : 'ok');
    }
    $('sInfosTous').addEventListener('click', async function () {
      fermerMenus();
      var etat = await api('/api/tomes/infos-ecrire?series=' + encodeURIComponent(current.id));
      if (!etat || !etat.total) { note('sMsg', 'Aucun tome complet en .cbz à réécrire pour cette série.', 'err'); return; }
      if (etat.en_cours) { note('sMsg', 'Une réécriture est déjà en cours pour cette série.'); suivreInfosTous(current.id); return; }
      var exclus = (etat.exclus || []).map(function (x) { return 'tome ' + x.tome + ' (' + x.raison + ')'; });
      var question = 'Réécrire DANS LE FICHIER de ' + etat.total + ' tome(s) de « ' + current.title + ' » ?\n\n' +
        'Pour chaque tome : le résumé, la date de sortie, la provenance, l\'état du sommaire et les chapitres lus sont écrits dans le fichier du tome.\n' +
        'Chaque fichier est réécrit ; l\'ancien part à la corbeille (30 jours).\n' +
        'Les fichiers partagés par qBittorrent ne sont pas touchés dans le torrent.' +
        (exclus.length ? '\n\nNon réécrits : ' + exclus.join(', ') + '.' : '') + '\n\nLe travail continue même si tu fermes la page.';
      if (!confirm(question)) return;
      var r = await post('/api/tomes/infos-ecrire', {series: current.id});
      if (!r.ok) { note('sMsg', r.error, 'err'); return; }
      note('sMsg', '📝 Réécriture de ' + etat.total + ' tome(s) en cours…', 'ok');
      suivreInfosTous(current.id);
    });
    $('sSource').addEventListener('click', async function () {
      fermerMenus();
      var v = await new Promise(function (fin) {
        var o = document.createElement('div'); o.className = 'choix-fond';
        o.innerHTML = '<div class="choix-boite"><h3>Source de « ' + esc(current.title) + ' »</h3>' + SOURCES.map(function (x) {
          return '<button type="button" class="mou-btn ghost src-choix" data-src="' + esc(x.nom) + '"><span class="src-pastille" style="--c:' + x.couleur + '">' + esc(x.nom) + '</span> <small>' + esc(x.quoi) + '</small></button>'; }).join('') +
          '<button type="button" class="mou-btn ghost" data-src="">↺ Détection automatique</button><button type="button" class="mou-btn ghost" data-annuler="1">Annuler</button></div>';
        o.addEventListener('click', function (e) {
          var b = e.target.closest('[data-src],[data-annuler]');
          if (!b && e.target !== o) return;
          o.remove(); fin(b && !b.dataset.annuler ? b.dataset.src : null);
        });
        document.body.appendChild(o);
      });
      if (v === null) return;
      var r = await post('/api/edition', {series: current.id, source: v});
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

  function showList() { arreterGenerique(); $('seriesView').style.display = 'none'; $('listView').style.display = ''; loadList(); verifierChoix(); }
  // Bandeau : les tâches qui attendent un choix (remplacer tout / ajouter les manquants) — admin seulement
  async function verifierChoix() {
    try {
      var r = await (await fetch('/api/torrents?leger=1')).json();
      var n = (r.torrents || []).filter(function (t) { return t.etat === 'a_valider'; }).length;
      var b = $('choixBandeau');
      if (!b) { b = document.createElement('a'); b.id = 'choixBandeau'; b.className = 'verif-bandeau'; b.href = '/telecharger'; $('listView').prepend(b); }
      b.hidden = !n;
      b.textContent = n ? '❓ ' + n + ' choix à faire : remplacer tous les tomes ou ajouter les manquants (ouvrir Télécharger)' : '';
    } catch (e) { /* lecteur ou réseau indisponible : rien à afficher */ }
  }
  function route() {
    var h = decodeURIComponent((location.hash || '').slice(1));
    if (h === 'demandes') { showList(); ouvrirDemandes(true); }          // lien des messages Telegram
    else if (h) openSeries(h, false); else showList();
  }
})();
