/* MouFlanga · lecteur : une page à la fois ou défilement, sens manga ou occidental, reprise automatique */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var q = new URLSearchParams(location.search);
  // « c » est la clé du chapitre : chemin du fichier (un fichier = un chapitre) ou « #12 » (chapitre d'un fichier de tome)
  var seriesId = q.get('s') || '', cle = q.get('c') || '', startPage = parseInt(q.get('p') || '0', 10) || 0;
  var chapters = [], idx = -1, count = 0, page = 0, saveTimer = null, finishedSent = {};
  var path = '', debut = 0;     // fichier lu et position de la 1re page du chapitre dans ce fichier
  function pref(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }
  function setPref(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  var dir = pref('mfDir', 'rtl'), mode = pref('mfMode', 'page'), fit = pref('mfFit', 'height'), double = pref('mfDouble', 'glisse');
  var demi = 0, versFin = false, large = false;          // doubles pages : moitié affichée (0 = la première à lire)
  var placer = false, depuisFin = false;                 // « glissées » : replacer l'image au début (ou à la fin) de la double page
  var zoom = {s: 1, x: 0, y: 0};
  // Chapitres à l'intérieur d'un tome complet (un fichier = un tome) : [{num, titre, image, verifie}], image = page du fichier
  var interne = [], titreEntree = '';
  // 🎯 Vérification des pages des chapitres (administrateur, « &verif=1 ») : chapitre en cours et écarts des dernières corrections
  var verif = q.get('verif') === '1' && document.body.classList.contains('admin'), vk = -1, ecartsVerif = [], revue = false, tomeValide = false;
  function esc(t) { return String(t == null ? '' : t).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); }

  async function api(url, opts) {
    var res = await fetch(url, opts), data = {};
    if (res.status === 401) { location.href = '/login'; throw new Error('Session expirée'); }
    try { data = await res.json(); } catch (e) {}
    if (!res.ok && !data.error) data.error = 'Erreur ' + res.status;
    return data;
  }
  function post(url, body) { return api(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})}); }
  // « v » change quand une page a été retirée du fichier : les images gardées en cache ne sont plus les bonnes
  function pageUrl(n) { var v = pref('mfV:' + path, ''); return '/api/page?path=' + encodeURIComponent(path) + '&n=' + (debut + n) + (v ? '&v=' + v : ''); }
  function showMsg(t) { var m = $('msg'); m.textContent = t || ''; m.classList.toggle('show', !!t); }

  function applyOptions() {
    document.body.classList.toggle('rtl', dir === 'rtl');
    var small = window.innerWidth < 700;
    $('optDir').textContent = dir === 'rtl' ? (small ? '⟵' : '⟵ Manga') : (small ? '⟶' : 'Occident ⟶');
    $('optMode').textContent = mode === 'page' ? (small ? '📄' : '📄 Page') : (small ? '📜' : '📜 Défilement');
    $('optFit').textContent = fit === 'width' ? (small ? '↔' : '↔ Largeur') : (small ? '↕' : '↕ Page entière');
    $('optFit').style.display = mode === 'page' ? '' : 'none';
    $('optDouble').style.display = mode === 'page' ? '' : 'none';
    $('optDouble').textContent = double === 'decoupe' ? (small ? '◫' : '◫ Coupées') : double === 'glisse' ? (small ? '⇆' : '⇆ Glissées') : (small ? '▭' : '▭ Entières');
    $('stage').classList.toggle('mode-scroll', mode === 'scroll');
    $('stage').classList.toggle('fit-height', fit === 'height');
    $('slider').style.direction = dir === 'rtl' && mode === 'page' ? 'rtl' : 'ltr';
  }

  function places() { return interne.filter(function (x) { return x.image != null; }).sort(function (a, b) { return a.image - b.image; }); }
  function chapIci() { var p = places(), k = -1; for (var i = 0; i < p.length; i++) if (p[i].image <= page) k = i; return {liste: p, k: k}; }
  function nomChap(x) { return 'Chapitre ' + x.num + (x.titre ? ' : ' + x.titre : ''); }
  function updateInfo() {
    $('rCount').textContent = count ? (page + 1) + ' / ' + count : '';
    $('slider').max = Math.max(1, count); $('slider').value = page + 1;
    var ic = chapIci(), suivant = ic.liste.some(function (x) { return x.image > page; });
    $('prevCh').disabled = idx <= 0 && ic.k < 1; $('nextCh').disabled = (idx < 0 || idx >= chapters.length - 1) && !suivant;
    $('rChapter').textContent = titreEntree + (ic.k >= 0 ? ' · ' + nomChap(ic.liste[ic.k]) : '');
    majVerif();
  }
  function annoncer(t) {
    var an = $('annonce'); an.textContent = t; an.classList.add('show');
    clearTimeout(an._t); an._t = setTimeout(function () { an.classList.remove('show'); }, 1800);
  }

  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () { save(false); }, 500);
  }
  function save(force) {
    if (verif) return;                                   // 🎯 vérification : ta position de lecture n'est pas touchée
    var finished = count > 0 && page >= count - 1;
    if (finished) finishedSent[cle] = true;
    var body = JSON.stringify({series: seriesId, path: cle, page: page, finished: finished});
    var hl = window.MFHorsLigne;
    if (finished && hl && hl.effacerSiLu() && hl.estGarde(seriesId, path)) hl.retirer(seriesId, path);    // « effacer une fois lu »
    if (!navigator.onLine && hl) { hl.noterProgression(body); return; }                       // sans réseau : envoyée au retour
    if (force && navigator.sendBeacon && navigator.sendBeacon('/api/progress', new Blob([body], {type: 'application/json'}))) return;
    fetch('/api/progress', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: body, keepalive: true})
      .catch(function () { if (hl) hl.noterProgression(body); });
  }

  // 🗑 (administrateur) : la page affichée est retirée du tome, puis le chapitre est rouvert à la même place
  if ($('optRetirer')) $('optRetirer').addEventListener('click', async function () {
    if (!count || !path) return;
    if (!await MouConfirm('Retirer la page ' + (page + 1) + ' de ce tome ? (crédits, pub d\'équipe…) L\'ancien fichier va à la corbeille (' + corb() + ').')) return;
    var r = await post('/api/parasites/page', {series: seriesId, fichier: path, index: debut + page});
    if (!r.ok) { MouAlert(r.error || 'Impossible'); return; }
    setPref('mfV:' + path, String(Date.now()));
    save(true);
    var u = new URL(location.href); u.searchParams.set('p', String(Math.min(page, Math.max(0, count - 2))));
    location.replace(u.toString());
  });

  function go(n, scrollTo) {
    if (!count) return;
    n = Math.max(0, Math.min(count - 1, n));
    if (n !== page || !versFin) demi = 0;
    remiseZoom();
    page = n; updateInfo(); scheduleSave();
    if (mode === 'page') {
      placer = true;
      $('img').src = pageUrl(n);
      $('stage').scrollTop = 0;
      for (var k = 1; k <= 2; k++) if (n + k < count) { var pre = new Image(); pre.src = pageUrl(n + k); }
    } else if (scrollTo !== false) {
      var el = $('scroll').children[n]; if (el) el.scrollIntoView();
    }
  }
  // Doubles pages découpées seulement en portrait : téléphone tourné en paysage = double page entière
  function portrait() { var st = $('stage'); return st.clientHeight > st.clientWidth; }
  function coupee() { return mode === 'page' && large && double === 'decoupe' && portrait(); }
  // « Glissées » : la double page prend toute la hauteur et déborde sur les côtés ; un doigt la fait glisser, on ne tourne la page qu'au bord
  function glisse() { return mode === 'page' && large && double === 'glisse' && portrait(); }
  function maxGlisse() { var st = $('stage'); return Math.max(0, st.scrollWidth - st.clientWidth); }
  // Appui sur le bord ou touche : va au bout de la double page ; renvoie true si elle a bougé (sinon on tourne la page)
  function glisserVers(droite) {
    var st = $('stage'), cible = droite ? maxGlisse() : 0;
    if (Math.abs(st.scrollLeft - cible) <= 4) return false;
    st.scrollTo({left: cible, behavior: 'smooth'});
    return true;
  }
  function next() {
    if (glisse() && glisserVers(dir !== 'rtl')) return;
    if (coupee() && demi === 0) { demi = 1; majDouble(); remiseZoom(); return; }   // 2e moitié de la double page
    if (page < count - 1) go(page + 1); else if (idx < chapters.length - 1) openChapter(idx + 1); else showToast('Dernier chapitre terminé 🎉');
  }
  function prev() {
    if (glisse() && glisserVers(dir === 'rtl')) return;
    if (coupee() && demi === 1) { demi = 0; majDouble(); remiseZoom(); return; }
    if (page > 0) { versFin = true; go(page - 1); } else if (idx > 0) openChapter(idx - 1, true);
  }

  // ---------- Doubles pages : une page plus large que haute est montrée moitié par moitié ----------
  function majDouble() {
    var im = $('img');
    large = im.naturalWidth > im.naturalHeight * 1.2;
    var c = coupee(), g = glisse();
    im.classList.toggle('moitie', c);
    $('stage').classList.toggle('glisse', g);
    if (g) {
      // Toute la hauteur de l'écran, largeur proportionnelle : l'image déborde et se parcourt au doigt
      var sg = $('stage'), hg = sg.clientHeight;
      im.style.height = hg + 'px'; im.style.width = (hg * im.naturalWidth / im.naturalHeight) + 'px'; im.style.objectPosition = '';
      if (placer) {      // début de la double page = côté où l'on commence à lire (sens manga : à droite) ; en revenant en arrière, l'autre bout
        placer = false;
        sg.scrollLeft = (dir === 'rtl') !== depuisFin ? maxGlisse() : 0;
        depuisFin = false;
      }
    } else if (c) {
      var premiere = dir === 'rtl' ? '100%' : '0%', seconde = dir === 'rtl' ? '0%' : '100%';
      // Taille d'une moitié, calculée pour tenir dans l'écran sans rien couper
      var st = $('stage'), w = st.clientWidth, h = st.clientHeight, r = im.naturalWidth / 2 / im.naturalHeight;
      if (fit === 'height' && w / h > r) w = h * r;
      im.style.width = w + 'px'; im.style.height = (w / r) + 'px';
      im.style.objectPosition = (demi === 0 ? premiere : seconde) + ' 50%';
    } else if (large && mode === 'page') {
      placer = false;
      // Double page entière (paysage, ou « ▭ Entières ») : toujours en entier dans l'écran, quel que soit l'ajustement
      var st2 = $('stage'), w2 = st2.clientWidth, h2 = st2.clientHeight, r2 = im.naturalWidth / im.naturalHeight;
      if (w2 / h2 > r2) w2 = h2 * r2;
      im.style.width = w2 + 'px'; im.style.height = (w2 / r2) + 'px'; im.style.objectPosition = '';
      st2.scrollTop = 0;
    } else { placer = false; im.style.width = ''; im.style.height = ''; im.style.objectPosition = ''; }
  }

  // ---------- Zoom (deux doigts, deux appuis au centre) ----------
  function appliquerZoom(anime) {
    var im = $('img');
    im.style.transition = anime ? 'transform .18s' : 'none';
    if (zoom.s > 1) {
      var mx = im.clientWidth * (zoom.s - 1) / 2, my = im.clientHeight * (zoom.s - 1) / 2;
      zoom.x = Math.max(-mx, Math.min(mx, zoom.x)); zoom.y = Math.max(-my, Math.min(my, zoom.y));
      im.style.transform = 'translate(' + zoom.x + 'px,' + zoom.y + 'px) scale(' + zoom.s + ')';
    } else { im.style.transform = ''; zoom = {s: 1, x: 0, y: 0}; }
    $('stage').classList.toggle('zoome', zoom.s > 1);
  }
  function remiseZoom() { zoom = {s: 1, x: 0, y: 0}; appliquerZoom(false); }
  function zoomerA(cx, cy) {
    var r = $('img').getBoundingClientRect(), s = 2.5;
    var dx = cx - (r.left + r.width / 2), dy = cy - (r.top + r.height / 2);
    zoom = {s: s, x: dx * (1 - s), y: dy * (1 - s)};
    appliquerZoom(true);
  }

  // ---------- Gestes : glisser pour tourner, pincer pour zoomer, un doigt pour se déplacer une fois zoomé ----------
  var t0 = null, geste = 0;
  function dist(a, b) { return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY); }
  $('stage').addEventListener('touchstart', function (e) {
    if (mode !== 'page') return;
    var t = e.touches;
    if (t.length === 2) t0 = {pince: true, d: dist(t[0], t[1]), s: zoom.s, x: zoom.x, y: zoom.y,
                              mx: (t[0].clientX + t[1].clientX) / 2, my: (t[0].clientY + t[1].clientY) / 2};
    else if (t.length === 1) t0 = {x0: t[0].clientX, y0: t[0].clientY, zx: zoom.x, zy: zoom.y, temps: Date.now(), sl: $('stage').scrollLeft};
  }, {passive: true});
  $('stage').addEventListener('touchmove', function (e) {
    if (mode !== 'page' || !t0) return;
    var t = e.touches;
    if (t0.pince && t.length === 2) {
      e.preventDefault();
      zoom.s = Math.max(1, Math.min(4, t0.s * dist(t[0], t[1]) / t0.d));
      zoom.x = t0.x + ((t[0].clientX + t[1].clientX) / 2 - t0.mx);
      zoom.y = t0.y + ((t[0].clientY + t[1].clientY) / 2 - t0.my);
      appliquerZoom(false); geste = Date.now();
    } else if (!t0.pince && t.length === 1 && zoom.s > 1) {
      e.preventDefault();
      zoom.x = t0.zx + (t[0].clientX - t0.x0); zoom.y = t0.zy + (t[0].clientY - t0.y0);
      appliquerZoom(false); geste = Date.now();
    }
  }, {passive: false});
  $('stage').addEventListener('touchend', function (e) {
    if (mode !== 'page' || !t0) return;
    if (t0.pince) { if (zoom.s < 1.1) remiseZoom(); t0 = null; return; }
    var t = e.changedTouches[0], dx = t.clientX - t0.x0, dy = t.clientY - t0.y0;
    // Double page « glissée » : le doigt la fait glisser ; on ne tourne la page que si elle était déjà au bord et ne peut plus bouger
    var bord = true;
    if (glisse()) {
      var sl = $('stage').scrollLeft, mx = maxGlisse();
      bord = Math.abs(sl - t0.sl) <= 2 && (dx > 0 ? t0.sl <= 2 : t0.sl >= mx - 2);
      if (Math.abs(sl - t0.sl) > 2) geste = Date.now();       // elle a glissé : ce n'est pas un appui sur un bord
    }
    if (bord && zoom.s === 1 && Math.abs(dx) > 60 && Math.abs(dx) > 1.5 * Math.abs(dy) && Date.now() - t0.temps < 700) {
      geste = Date.now();
      // Doigt vers la droite = on « tire » la page de gauche : suivante en sens manga, précédente en sens occidental
      if (dx > 0) { dir === 'rtl' ? next() : prev(); } else { dir === 'rtl' ? prev() : next(); }
    }
    t0 = null;
  });
  function gesteRecent() { return Date.now() - geste < 450 || zoom.s > 1; }
  function showToast(t) { showMsg(''); var b = $('rCount'); var old = b.textContent; b.textContent = t; setTimeout(function () { b.textContent = old; }, 2500); }

  // Changement de chapitre (et de tome) sans recharger la page : on enchaîne comme dans un livre
  async function openChapter(i, atEnd) {
    if (i < 0 || i >= chapters.length) return;
    if (count) save(true);
    await charger(i, atEnd ? 1e9 : 0);
  }

  async function charger(i, pageVoulue) {
    var c = chapters[i];
    idx = i; cle = c.key; path = c.path; debut = c.debut || 0;
    titreEntree = (c.groupe ? c.groupe + ' · ' : '') + c.title;
    $('rChapter').textContent = titreEntree;
    if (c.nb) count = c.nb;
    else {
      var info = await api('/api/pages?path=' + encodeURIComponent(path));
      if (info.error) { count = 0; showMsg('⚠️ ' + info.error); updateInfo(); return; }
      count = info.count;
    }
    history.replaceState(null, '', '/lire?s=' + encodeURIComponent(seriesId) + '&c=' + encodeURIComponent(cle) + (verif ? '&verif=1' : ''));
    annoncer(titreEntree);
    page = Math.max(0, Math.min(count - 1, pageVoulue));
    showMsg('');
    await chargerInternes(c);
    if (mode === 'scroll') buildScroll();
    go(page);
    if (verif) demarrerVerif();
  }

  // ---------- Chapitres d'un tome complet ----------
  async function chargerInternes(c) {
    interne = []; tomeValide = false;
    if (c.tome != null && !c.nb) {
      try { var r = await api('/api/lecteur/chapitres?s=' + encodeURIComponent(seriesId) + '&tome=' + encodeURIComponent(c.tome)); interne = r.chapitres || []; tomeValide = !!r.valide; }
      catch (e) { interne = []; }                        // hors ligne : le tome se lit quand même, sans ses chapitres
    }
    var memeFichier = chapters.filter(function (x) { return x.path === path; }).length > 1;
    $('optChap').hidden = !(places().length || memeFichier);
  }
  function listeChapitres() {
    var ol = $('listeChapItems'), h = '';
    if (interne.length) {
      var ic = chapIci();
      interne.forEach(function (x) {
        var ici = ic.k >= 0 && ic.liste[ic.k] === x;
        h += '<li class="' + (x.image == null ? 'sans' : ici ? 'ici' : '') + '"' + (x.image != null ? ' data-page="' + x.image + '"' : '') + '>' +
          esc(nomChap(x)) + (x.image == null ? ' <small>(page inconnue)</small>' : '') + '</li>';
      });
    } else {
      chapters.forEach(function (x, j) { if (x.path === path) h += '<li class="' + (j === idx ? 'ici' : '') + '" data-entree="' + j + '">' + esc(x.title) + '</li>'; });
    }
    ol.innerHTML = h; $('listeChap').hidden = false;
  }
  $('optChap').addEventListener('click', listeChapitres);
  $('listeChapFermer').addEventListener('click', function () { $('listeChap').hidden = true; });
  $('listeChap').addEventListener('click', function (e) {
    if (e.target === $('listeChap')) { $('listeChap').hidden = true; return; }
    var li = e.target.closest('li'); if (!li) return;
    if (li.dataset.page != null) { $('listeChap').hidden = true; go(+li.dataset.page); var ic = chapIci(); if (ic.k >= 0) annoncer(nomChap(ic.liste[ic.k])); }
    else if (li.dataset.entree != null) { $('listeChap').hidden = true; openChapter(+li.dataset.entree); }
  });

  // ---------- 🎯 Vérification des pages des chapitres (administrateur) ----------
  function placeVerif(k) {                               // page à montrer pour le chapitre k (sans page : juste après le précédent connu)
    if (interne[k].image != null) return interne[k].image;
    var avant = -1;
    for (var j = 0; j < k; j++) if (interne[j].image != null) avant = interne[j].image;
    return Math.max(0, Math.min(count - 1, avant + 1));
  }
  function prochainAVerifier(depuis) {
    for (var j = depuis; j < interne.length; j++) if (!interne[j].verifie) return j;
    return interne.length;
  }
  function demarrerVerif() {
    if (!interne.length) { showMsg('🎯 Pas de chapitres connus pour ce tome : saisis-les d\'abord sur sa fiche (✏️ Corriger les chapitres).'); return; }
    ecartsVerif = []; revue = false;
    vk = prochainAVerifier(0);
    afficherVerif(true);
  }
  function afficherVerif(aller) {
    var b = $('verif'); b.hidden = false;
    if (vk >= interne.length) {
      b.innerHTML = '<div class="verif-titre">🎯 Les ' + interne.length + ' chapitres de ce tome sont vérifiés.</div>' +
        '<div class="verif-sous">' + (tomeValide ? '✅ Tome validé : l\'appli n\'y touche plus.' : 'Tout est enregistré. Valide le tome pour que l\'appli n\'y touche plus.') + '</div>' +
        '<div class="verif-boutons">' + (tomeValide ? '' : '<button class="rbtn ok" data-v="valider">✅ Valider le tome</button>') +
        '<button class="rbtn" data-v="suivant">Tome suivant ▶</button><button class="rbtn" data-v="revoir">↺ Revoir</button>' +
        '<button class="rbtn" data-v="quitter">✖ Fermer</button></div>';
      return;
    }
    var x = interne[vk];
    b.innerHTML = '<div class="verif-titre">🎯 ' + (revue ? '↺ ' : '') + (vk + 1) + ' / ' + interne.length + ' · ' + esc(nomChap(x)) + '</div>' +
      '<div class="verif-sous">' + (x.image != null ? '<button class="verif-lien" data-v="retour" title="Revenir sur cette page">Page ' +
        (x.verifie ? 'vérifiée' : 'proposée') + ' : ' + (x.image + 1) + '</button>' : 'Pas encore de page : va sur la première page du chapitre') +
      ' · page affichée : <b id="verifIci">' + (page + 1) + '</b></div>' +
      '<div class="verif-boutons"><button class="rbtn" data-v="moins">− 1 page</button><button class="rbtn" data-v="plus">+ 1 page</button>' +
      '<button class="rbtn principal" data-v="ici" id="verifPose"></button>' +
      (x.image != null ? '<button class="rbtn ok" data-v="ok" id="verifOk"></button>' : '') +
      '<button class="rbtn" data-v="quitter" title="Quitter la vérification">✖</button></div>';
    if (aller) go(placeVerif(vk));
    majVerif();
  }
  // Les boutons disent quelle page ils enregistrent : la page affichée (📍) ou la page déjà proposée (✅), où que tu sois
  function majVerif() {
    if ($('verifIci')) $('verifIci').textContent = page + 1;
    var x = interne[vk], pose = $('verifPose'), ok = $('verifOk');
    if (!x || !pose) return;
    var ailleurs = x.image != null && page !== x.image;
    pose.textContent = ailleurs ? '📍 Il commence page ' + (page + 1) : '📍 Le chapitre commence ici';
    if (ok) ok.textContent = ailleurs ? '✅ Garder la page ' + (x.image + 1) : '✅ C\'est la bonne page';
  }
  function apresEnregistrement(r) {
    interne = r.chapitres || interne;
    if (r.valide != null) tomeValide = r.valide;
    if (r.tomes_recales && window.MouToast) window.MouToast('📐 Série : les chapitres commencent ' + Math.abs(r.decalage) + ' page(s) ' +
      (r.decalage < 0 ? 'avant' : 'après') + ' la page trouvée par l\'appli. ' + r.tomes_recales + ' tome(s) lu(s) automatiquement recalé(s).', 'ok');
  }
  $('verif').addEventListener('click', async function (e) {
    var bt = e.target.closest('[data-v]'); if (!bt) return;
    var v = bt.dataset.v, c = chapters[idx], x = interne[vk];
    if (v === 'moins') { go(page - 1); return; }
    if (v === 'plus') { go(page + 1); return; }
    if (v === 'quitter') { verif = false; $('verif').hidden = true; history.replaceState(null, '', '/lire?s=' + encodeURIComponent(seriesId) + '&c=' + encodeURIComponent(cle)); return; }
    if (v === 'revoir') { vk = 0; revue = true; ecartsVerif = []; afficherVerif(true); return; }      // tous les chapitres, même vérifiés
    if (v === 'retour') { if (x && x.image != null) go(x.image); return; }
    if (v === 'valider') {
      var rv = await post('/api/tome/valider', {series: seriesId, tome: c.tome});
      if (!rv.ok) { MouAlert(rv.error || 'Impossible'); return; }
      if (window.MouToast) window.MouToast('✅ ' + rv.message, 'ok');
      tomeValide = true; afficherVerif(false);
      return;
    }
    if (v === 'suivant') {
      for (var j = idx + 1; j < chapters.length; j++) if (chapters[j].tome != null && !chapters[j].nb) { openChapter(j); return; }
      MouAlert('C\'était le dernier tome de la série.'); return;
    }
    if (!x) return;
    bt.disabled = true;
    var corps = {series: seriesId, tome: c.tome, num: x.num};
    var ecart = null;
    if (v === 'ici') { corps.image = page; ecart = x.image != null ? page - x.image : null; }
    var r = await post('/api/tome/chapitre_page', corps);
    bt.disabled = false;
    if (!r.ok) { MouAlert(r.error || 'Impossible'); return; }
    apresEnregistrement(r);
    if (ecart) ecartsVerif.push(ecart); else ecartsVerif = [];
    var restants = interne.filter(function (y) { return !y.verifie && y.image != null && y.num > x.num; }).length;
    var n = ecartsVerif.length;
    if (n >= 2 && ecartsVerif[n - 1] === ecartsVerif[n - 2] && restants &&
        await MouConfirm('Les deux derniers chapitres commençaient ' + Math.abs(ecart) + ' page(s) ' + (ecart < 0 ? 'avant' : 'après') +
                         ' la page enregistrée. Décaler pareil les ' + restants + ' chapitre(s) suivant(s) ? (tu les vérifies quand même un par un)')) {
      var rd = await post('/api/tome/chapitres_decaler', {series: seriesId, tome: c.tome, apres: x.num, decalage: ecart});
      if (!rd.ok) MouAlert(rd.error || 'Impossible'); else interne = rd.chapitres || interne;
      ecartsVerif = [];
    }
    vk = revue ? vk + 1 : prochainAVerifier(vk + 1);
    afficherVerif(true);
  });

  function buildScroll() {
    var box = $('scroll'); box.innerHTML = '';
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        var img = e.target;
        if (e.isIntersecting && !img.src) { img.src = pageUrl(+img.dataset.n); img.onload = function () { img.classList.add('loaded'); }; }
      });
    }, {root: $('stage'), rootMargin: '1200px 0px'});
    for (var i = 0; i < count; i++) {
      var im = document.createElement('img'); im.dataset.n = i; im.alt = ''; im.decoding = 'async';
      box.appendChild(im); io.observe(im);
    }
    // En défilement, la fin du chapitre propose le suivant (même s'il est dans le tome d'après)
    if (idx < chapters.length - 1) {
      var suite = document.createElement('button'); suite.className = 'suite';
      suite.textContent = '▶ ' + (chapters[idx + 1].groupe && chapters[idx + 1].groupe !== chapters[idx].groupe ? chapters[idx + 1].groupe + ' · ' : '') + chapters[idx + 1].title;
      suite.addEventListener('click', function (e) { e.stopPropagation(); openChapter(idx + 1); });
      box.appendChild(suite);
    }
  }

  var scrollTick = false;
  function whichPage() {
    var st = $('stage'), kids = $('scroll').children, y = st.scrollTop + st.clientHeight * 0.3, lo = 0, hi = Math.min(kids.length, count) - 1;
    while (lo < hi) { var mid = (lo + hi + 1) >> 1; if (kids[mid].offsetTop <= y) lo = mid; else hi = mid - 1; }
    return lo;
  }
  $('stage').addEventListener('scroll', function () {
    if (mode !== 'scroll' || scrollTick) return;
    scrollTick = true;
    requestAnimationFrame(function () {
      scrollTick = false;
      var n = whichPage();
      if (n !== page) { page = n; updateInfo(); scheduleSave(); }
    });
  });

  async function init() {
    if (!seriesId || !cle) { showMsg('Chapitre non précisé.'); return; }
    $('rBack').href = '/#' + encodeURIComponent(seriesId);
    $('rSeries').textContent = seriesId;
    applyOptions();
    var s = await api('/api/series?id=' + encodeURIComponent(seriesId));
    chapters = s.chapters || [];
    // Ancienne adresse (chemin d'un fichier rangé depuis en tomes) : on retrouve le chapitre par son numéro
    idx = chapters.findIndex(function (c) { return c.key === cle; });
    if (idx < 0) idx = chapters.findIndex(function (c) { return c.path === cle; });
    if (idx < 0) { showMsg('Chapitre introuvable (il a peut-être été supprimé).'); updateInfo(); return; }
    await charger(idx, startPage);
    $('stage').focus();
  }

  // ----- Commandes -----
  $('zoneL').addEventListener('click', function () { if (!gesteRecent()) { dir === 'rtl' ? next() : prev(); } });
  $('zoneR').addEventListener('click', function () { if (!gesteRecent()) { dir === 'rtl' ? prev() : next(); } });
  // Centre : un appui cache ou montre les barres ; deux appuis rapprochés zooment (ou dézooment)
  var dernierAppui = 0, appuiTimer = null;
  $('single').addEventListener('click', function (e) {
    if (Date.now() - geste < 450) return;
    if (Date.now() - dernierAppui < 300) {
      clearTimeout(appuiTimer); dernierAppui = 0;
      if (zoom.s > 1) { zoom.s = 1; appliquerZoom(true); } else zoomerA(e.clientX, e.clientY);
      return;
    }
    dernierAppui = Date.now();
    appuiTimer = setTimeout(function () { if (zoom.s === 1) document.body.classList.toggle('hide-ui'); }, 300);
  });
  $('img').addEventListener('load', function () {
    if (versFin) { large = $('img').naturalWidth > $('img').naturalHeight * 1.2; if (coupee()) demi = 1; if (glisse()) depuisFin = true; versFin = false; }
    majDouble();
  });
  $('optDouble').addEventListener('click', function () { double = double === 'decoupe' ? 'glisse' : double === 'glisse' ? 'entiere' : 'decoupe'; setPref('mfDouble', double); demi = 0; placer = true; depuisFin = false; applyOptions(); majDouble(); });
  // Aide : boutons et gestes (montrée d'office la première fois)
  function aide(ouvrir) { $('aide').hidden = !ouvrir; if (!ouvrir) setPref('mfAideVue', '1'); }
  $('optAide').addEventListener('click', function () { aide(true); });
  $('aideFermer').addEventListener('click', function () { aide(false); });
  $('aide').addEventListener('click', function (e) { if (e.target === $('aide')) aide(false); });
  if (!pref('mfAideVue', '')) aide(true);
  // L'écran reste allumé pendant la lecture
  var verrouEcran = null;
  async function garderEcran() { try { if ('wakeLock' in navigator && !document.hidden) verrouEcran = await navigator.wakeLock.request('screen'); } catch (e) {} }
  garderEcran();
  window.addEventListener('resize', function () { majDouble(); });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) garderEcran(); });
  $('scroll').addEventListener('click', function () { document.body.classList.toggle('hide-ui'); });
  // ⏮ ⏭ : dans un tome complet dont les chapitres sont connus, d'un chapitre à l'autre ; sinon (ou au bout), le fichier voisin
  $('prevCh').addEventListener('click', function () {
    var ic = chapIci();
    if (ic.k >= 1) { go(ic.liste[ic.k - 1].image); annoncer(nomChap(ic.liste[ic.k - 1])); return; }
    if (idx > 0) openChapter(idx - 1);
  });
  $('nextCh').addEventListener('click', function () {
    var suiv = places().filter(function (x) { return x.image > page; })[0];
    if (suiv) { go(suiv.image); annoncer(nomChap(suiv)); return; }
    if (idx < chapters.length - 1) openChapter(idx + 1);
  });
  $('slider').addEventListener('input', function () { go(+$('slider').value - 1); });
  $('optDir').addEventListener('click', function () { dir = dir === 'rtl' ? 'ltr' : 'rtl'; setPref('mfDir', dir); applyOptions(); majDouble(); });
  $('optFit').addEventListener('click', function () { fit = fit === 'width' ? 'height' : 'width'; setPref('mfFit', fit); applyOptions(); majDouble(); });
  $('optMode').addEventListener('click', function () {
    mode = mode === 'page' ? 'scroll' : 'page'; setPref('mfMode', mode); applyOptions();
    if (mode === 'scroll') { buildScroll(); go(page); } else { $('scroll').innerHTML = ''; go(page); }
  });
  $('optFull').addEventListener('click', function () {
    if (document.fullscreenElement) document.exitFullscreen(); else if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen().catch(function () {});
  });
  document.addEventListener('keydown', function (e) {
    if (e.target && e.target.tagName === 'INPUT' && e.target.type !== 'range') return;
    var k = e.key;
    if (k === 'ArrowRight') { e.preventDefault(); dir === 'rtl' ? prev() : next(); }
    else if (k === 'ArrowLeft') { e.preventDefault(); dir === 'rtl' ? next() : prev(); }
    else if (mode === 'page' && (k === ' ' || k === 'PageDown')) { e.preventDefault(); next(); }
    else if (mode === 'page' && k === 'PageUp') { e.preventDefault(); prev(); }
    else if (k === 'Home') go(0);
    else if (k === 'End') go(count - 1);
    else if (k === 'f' || k === 'F') $('optFull').click();
    else if (k === 'h' || k === 'H') document.body.classList.toggle('hide-ui');
    else if (k === 'Escape' && !document.fullscreenElement) location.href = $('rBack').href;
  });
  window.addEventListener('pagehide', function () { if (count) save(true); });
  document.addEventListener('visibilitychange', function () { if (document.hidden && count) save(true); });
  $('img').addEventListener('error', function () { showMsg('⚠️ Cette page n\'a pas pu être lue (voir le Journal dans l\'appli).'); });
  $('img').addEventListener('load', function () { showMsg(''); });
  init().catch(function (e) { showMsg('Erreur : ' + e.message); });
})();
