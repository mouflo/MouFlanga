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

  var series = [], current = null;

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
        (left > 0 ? '<span class="badge">' + left + ' à lire</span>' : '<span class="badge done">lu ✔</span>') +
        '<div class="nm">' + esc(s.title) + '</div>' +
        '<div class="st">' + s.chapters + ' fichier' + (s.chapters > 1 ? 's' : '') + ' · ' + s.size_mb + ' Mo</div>' +
        '<div class="bar"><i style="width:' + pct + '%"></i></div></div>';
    }).join('');
  }

  async function loadList() {
    var r = await api('/api/library');
    series = r.series || [];
    note('listMsg', r.error, 'warn');
    if (!r.error && !series.length) {
      $('grid').innerHTML = '<div class="empty">Aucun manga trouvé dans le dossier configuré.<br>Range des fichiers <b>.cbz</b> ou <b>.cbr</b> dans un sous-dossier par série, ou change le dossier dans ⚙️ Réglages.</div>';
    } else drawGrid();
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
    $('sCover').src = '/api/cover?id=' + encodeURIComponent(s.id);
    $('sMeta').textContent = s.chapters.length + ' fichier' + (s.chapters.length > 1 ? 's' : '') + ' · ' + read + ' lu' + (read > 1 ? 's' : '');
    var next = s.current || (s.chapters.find(function (c) { return !c.read; }) || s.chapters[0] || {}).path;
    $('sResume').textContent = (s.current ? '▶ Reprendre' : read ? '▶ Continuer' : '▶ Commencer');
    $('sResume').dataset.path = next || '';
    $('chapters').innerHTML = s.chapters.map(function (c) {
      return '<div class="chap' + (c.read ? ' read' : '') + (c.path === s.current ? ' cur' : '') + '" data-path="' + esc(c.path) + '">' +
        '<span class="dot"></span><span class="ct">' + esc(c.title) + '</span><span class="cs">' + c.size_mb + ' Mo</span>' +
        '<button class="tog" data-tog="' + esc(c.path) + '" title="Marquer ' + (c.read ? 'non lu' : 'lu') + '">' + (c.read ? '↺' : '✔') + '</button></div>';
    }).join('');
    note('sMsg', (!s.rar && s.chapters.some(function (c) { return /\.(cbr|rar)$/i.test(c.path); })) ? 'Les vrais fichiers RAR (.cbr) ne s\'ouvrent que si le serveur a « rarfile » et un outil de décompression : voir le Journal si une page refuse de s\'ouvrir.' : '', 'warn');
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
      var t = e.target.closest('[data-tog]');
      if (t) {
        e.stopPropagation();
        var c = current.chapters.find(function (x) { return x.path === t.dataset.tog; });
        await post('/api/mark', {series: current.id, path: c.path, read: !c.read});
        c.read = !c.read; drawSeries(); return;
      }
      var row = e.target.closest('.chap'); if (row) readChapter(row.dataset.path);
    });
    async function markAll(v) { await post('/api/mark', {series: current.id, all: true, read: v}); await openSeries(current.id, false); }
    $('sAllRead').addEventListener('click', function () { markAll(true); });
    $('sAllUnread').addEventListener('click', function () { if (confirm('Tout marquer comme non lu pour cette série ?')) markAll(false); });
    window.addEventListener('popstate', route);
    route();
  });

  function showList() { $('seriesView').style.display = 'none'; $('listView').style.display = ''; loadList(); }
  function route() {
    var h = decodeURIComponent((location.hash || '').slice(1));
    if (h) openSeries(h, false); else showList();
  }
})();
