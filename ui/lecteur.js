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
  var dir = pref('mfDir', 'rtl'), mode = pref('mfMode', 'page'), fit = pref('mfFit', 'height'), double = pref('mfDouble', 'decoupe');
  var demi = 0, versFin = false, large = false;          // doubles pages : moitié affichée (0 = la première à lire)
  var zoom = {s: 1, x: 0, y: 0};

  async function api(url, opts) {
    var res = await fetch(url, opts), data = {};
    if (res.status === 401) { location.href = '/login'; throw new Error('Session expirée'); }
    try { data = await res.json(); } catch (e) {}
    if (!res.ok && !data.error) data.error = 'Erreur ' + res.status;
    return data;
  }
  function post(url, body) { return api(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})}); }
  function pageUrl(n) { return '/api/page?path=' + encodeURIComponent(path) + '&n=' + (debut + n); }
  function showMsg(t) { var m = $('msg'); m.textContent = t || ''; m.classList.toggle('show', !!t); }

  function applyOptions() {
    document.body.classList.toggle('rtl', dir === 'rtl');
    var small = window.innerWidth < 700;
    $('optDir').textContent = dir === 'rtl' ? (small ? '⟵' : '⟵ Manga') : (small ? '⟶' : 'Occident ⟶');
    $('optMode').textContent = mode === 'page' ? (small ? '📄' : '📄 Page') : (small ? '📜' : '📜 Défilement');
    $('optFit').textContent = fit === 'width' ? (small ? '↔' : '↔ Largeur') : (small ? '↕' : '↕ Page entière');
    $('optFit').style.display = mode === 'page' ? '' : 'none';
    $('optDouble').style.display = mode === 'page' ? '' : 'none';
    $('optDouble').textContent = double === 'decoupe' ? (small ? '◫' : '◫ Coupées') : (small ? '▭' : '▭ Entières');
    $('stage').classList.toggle('mode-scroll', mode === 'scroll');
    $('stage').classList.toggle('fit-height', fit === 'height');
    $('slider').style.direction = dir === 'rtl' && mode === 'page' ? 'rtl' : 'ltr';
  }

  function updateInfo() {
    $('rCount').textContent = count ? (page + 1) + ' / ' + count : '';
    $('slider').max = Math.max(1, count); $('slider').value = page + 1;
    $('prevCh').disabled = idx <= 0; $('nextCh').disabled = idx < 0 || idx >= chapters.length - 1;
  }

  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () { save(false); }, 500);
  }
  function save(force) {
    var finished = count > 0 && page >= count - 1;
    if (finished) finishedSent[cle] = true;
    var body = JSON.stringify({series: seriesId, path: cle, page: page, finished: finished});
    if (force && navigator.sendBeacon) { navigator.sendBeacon('/api/progress', new Blob([body], {type: 'application/json'})); return; }
    fetch('/api/progress', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: body, keepalive: true}).catch(function () {});
  }

  function go(n, scrollTo) {
    if (!count) return;
    n = Math.max(0, Math.min(count - 1, n));
    if (n !== page || !versFin) demi = 0;
    remiseZoom();
    page = n; updateInfo(); scheduleSave();
    if (mode === 'page') {
      $('img').src = pageUrl(n);
      $('stage').scrollTop = 0;
      for (var k = 1; k <= 2; k++) if (n + k < count) { var pre = new Image(); pre.src = pageUrl(n + k); }
    } else if (scrollTo !== false) {
      var el = $('scroll').children[n]; if (el) el.scrollIntoView();
    }
  }
  function coupee() { return mode === 'page' && large && double === 'decoupe'; }
  function next() {
    if (coupee() && demi === 0) { demi = 1; majDouble(); remiseZoom(); return; }   // 2e moitié de la double page
    if (page < count - 1) go(page + 1); else if (idx < chapters.length - 1) openChapter(idx + 1); else showToast('Dernier chapitre terminé 🎉');
  }
  function prev() {
    if (coupee() && demi === 1) { demi = 0; majDouble(); remiseZoom(); return; }
    if (page > 0) { versFin = true; go(page - 1); } else if (idx > 0) openChapter(idx - 1, true);
  }

  // ---------- Doubles pages : une page plus large que haute est montrée moitié par moitié ----------
  function majDouble() {
    var im = $('img');
    large = im.naturalWidth > im.naturalHeight * 1.2;
    var c = coupee();
    im.classList.toggle('moitie', c);
    if (c) {
      var premiere = dir === 'rtl' ? '100%' : '0%', seconde = dir === 'rtl' ? '0%' : '100%';
      // Taille d'une moitié, calculée pour tenir dans l'écran sans rien couper
      var st = $('stage'), w = st.clientWidth, h = st.clientHeight, r = im.naturalWidth / 2 / im.naturalHeight;
      if (fit === 'height' && w / h > r) w = h * r;
      im.style.width = w + 'px'; im.style.height = (w / r) + 'px';
      im.style.objectPosition = (demi === 0 ? premiere : seconde) + ' 50%';
    } else { im.style.width = ''; im.style.height = ''; im.style.objectPosition = ''; }
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
    else if (t.length === 1) t0 = {x0: t[0].clientX, y0: t[0].clientY, zx: zoom.x, zy: zoom.y, temps: Date.now()};
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
    if (zoom.s === 1 && Math.abs(dx) > 60 && Math.abs(dx) > 1.5 * Math.abs(dy) && Date.now() - t0.temps < 700) {
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
    $('rChapter').textContent = (c.groupe ? c.groupe + ' · ' : '') + c.title;
    if (c.nb) count = c.nb;
    else {
      var info = await api('/api/pages?path=' + encodeURIComponent(path));
      if (info.error) { count = 0; showMsg('⚠️ ' + info.error); updateInfo(); return; }
      count = info.count;
    }
    history.replaceState(null, '', '/lire?s=' + encodeURIComponent(seriesId) + '&c=' + encodeURIComponent(cle));
    var an = $('annonce'); an.textContent = (c.groupe ? c.groupe + ' · ' : '') + c.title; an.classList.add('show');
    clearTimeout(an._t); an._t = setTimeout(function () { an.classList.remove('show'); }, 1800);
    page = Math.max(0, Math.min(count - 1, pageVoulue));
    showMsg('');
    if (mode === 'scroll') buildScroll();
    go(page);
  }

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
    if (versFin) { large = $('img').naturalWidth > $('img').naturalHeight * 1.2; if (coupee()) demi = 1; versFin = false; }
    majDouble();
  });
  $('optDouble').addEventListener('click', function () { double = double === 'decoupe' ? 'entiere' : 'decoupe'; setPref('mfDouble', double); demi = 0; applyOptions(); majDouble(); });
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
  $('prevCh').addEventListener('click', function () { if (idx > 0) openChapter(idx - 1); });
  $('nextCh').addEventListener('click', function () { if (idx < chapters.length - 1) openChapter(idx + 1); });
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
