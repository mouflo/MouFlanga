/* MouFlanga · page d'un torrent sur son tracker : lien vers la page et volet « 📄 » avec sa présentation, son NFO et ce qui a été ajouté
   à la fiche de la série. Utilisé par la fiche d'une série (propositions de torrents) et par la page Télécharger (résultats de recherche).
   Le texte vient d'un inconnu : il n'est jamais mis dans la page comme du HTML (échappé partout), et seules les adresses https s'ouvrent. */
(function () {
    'use strict';
    var esc = function (s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; });
    };
    var taille = function (o) { return o >= 1e9 ? (o / 1073741824).toFixed(1).replace('.', ',') + ' Go' : Math.round(o / 1048576) + ' Mo'; };
    function https(u) { return /^https:\/\//i.test(u || '') ? u : ''; }
    function hote(u) { try { return new URL(u).hostname.replace(/^www\./, ''); } catch (e) { return ''; } }

    // 🔗 lien vers la page du torrent sur son tracker (dans un nouvel onglet)
    function lien(page) {
        var u = https(page);
        return u ? '<a class="pt-lien" href="' + esc(u) + '" target="_blank" rel="noopener noreferrer" title="Ouvrir la page du torrent sur son tracker">🔗 ' + esc(hote(u)) + '</a>' : '';
    }

    // « C411 · Pika · 191 p. · 1499 × 2250 · CBZ » : l'essentiel d'une page lue (t = {tracker, editeur, pages, resolution, format, qualite, isbn})
    function ligne(t) {
        if (!t || t.erreur) return '';
        var parts = [t.tracker, t.editeur, t.pages ? t.pages + ' p.' : '', t.resolution ? String(t.resolution).replace('x', ' × ') : '', t.format, t.qualite,
                     t.isbn ? 'ISBN ' + t.isbn : ''];
        return parts.filter(Boolean).map(esc).join(' · ');
    }
    function depuisPage(p) {
        var i = (p && p.infos) || {};
        return {tracker: p.tracker, editeur: i.editeur, pages: i.pages, resolution: i.resolution, format: i.format, qualite: i.qualite,
                isbn: Object.keys(i.isbn || {}).map(function (k) { return i.isbn[k]; })[0] || i.isbn_unique};
    }

    function pied(page, relire) {
        return '<div class="pt-pied">' + lien(page) + (relire ? '<button type="button" class="ghost pt-relire" data-relire="1">↻ Relire</button>' : '') + '</div>';
    }

    function rendre(r, page) {
        var p = r.page, i = p.infos || {}, puces = [];
        if (i.auteur) puces.push('✍️ ' + i.auteur);
        if (i.editeur) puces.push('🏢 ' + i.editeur);
        if (i.date) puces.push('📅 ' + i.date);
        if (i.genre) puces.push('🏷 ' + i.genre);
        if (i.pages) puces.push('📖 ' + i.pages + ' pages');
        if (i.resolution) puces.push('📐 ' + String(i.resolution).replace('x', ' × '));
        [i.format, i.qualite, i.statut].forEach(function (x) { if (x) puces.push(x); });
        var isbn = Object.keys(i.isbn || {}).map(function (k) { return (Object.keys(i.isbn).length > 1 ? 'T' + k + ' ' : '') + i.isbn[k]; });
        if (!isbn.length && i.isbn_unique) isbn.push(i.isbn_unique);
        if (isbn.length) puces.push('ISBN ' + isbn.join(' · '));
        var meta = [p.taille ? taille(p.taille) : '', p.sources ? p.sources + ' source' + (p.sources > 1 ? 's' : '') : '', p.date, p.equipe ? 'par ' + p.equipe : ''].filter(Boolean);
        var h = '<div class="pt-tete"><b>' + esc(p.tracker) + ' · ' + esc(p.titre) + '</b>' + (meta.length ? '<small>' + meta.map(esc).join(' · ') + '</small>' : '') + '</div>';
        if (puces.length) h += '<div class="pt-puces">' + puces.map(function (x) { return '<i>' + esc(x) + '</i>'; }).join('') + '</div>';
        if (i.synopsis) h += '<p class="pt-synopsis">' + esc(i.synopsis) + '</p>';
        else if (i.synopsis_en) h += '<p class="pt-synopsis">' + esc(i.synopsis_en) + '</p><small class="pt-sous">(résumé en anglais : pas ajouté à la fiche)</small>';
        else if (!p.presentation && !p.nfo) h += '<p class="pt-etat">Cette page ne contient ni présentation ni NFO.</p>';
        if (!i.synopsis && !i.synopsis_en && p.presentation) h += '<details><summary>📝 Présentation</summary><pre class="pt-nfo">' + esc(p.presentation) + '</pre></details>';
        if (p.nfo) h += '<details><summary>📄 NFO</summary><pre class="pt-nfo">' + esc(p.nfo) + '</pre></details>';
        if ((p.fichiers || []).length) {
            h += '<details><summary>📁 ' + p.fichiers.length + ' fichier' + (p.fichiers.length > 1 ? 's' : '') + '</summary><ul class="pt-fichiers">' +
                p.fichiers.slice(0, 40).map(function (f) { return '<li>' + esc(f.nom) + (f.taille ? ' <small>(' + taille(f.taille) + ')</small>' : '') + '</li>'; }).join('') + '</ul></details>';
        }
        if (r.message) h += '<div class="pt-note' + (r.serie_ok === false ? ' warn' : '') + '">' + esc(r.message) + '</div>';
        return h + pied(page || p.url, true);
    }

    async function charger(volet, params, force, apres) {
        volet.innerHTML = '<div class="pt-etat">⏳ Lecture de la page… (quelques secondes)</div>';
        var r;
        try {
            r = await (await fetch('/api/torrents/page', {method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(force ? Object.assign({force: true}, params) : params)})).json();
        } catch (e) { r = {ok: false, error: 'MouFlanga ne répond pas : réessaie dans un instant.'}; }
        if (!r.ok) {
            volet.innerHTML = '<div class="pt-etat err">' + esc(r.error || 'Lecture impossible.') + '</div>' + pied(params.page, !r.definitif);
        } else {
            volet.innerHTML = rendre(r, params.page);
        }
        var b = volet.querySelector('[data-relire]');
        if (b) b.addEventListener('click', function () { charger(volet, params, true, apres); });
        if (r.ok && apres) apres(r);
    }

    // Ouvre (ou ferme) le volet sous une ligne. params : {serie, proposition} pour une proposition, {page, titre[, serie]} pour un résultat.
    function ouvrir(ligneEl, params, apres) {
        var suivant = ligneEl.nextElementSibling;
        if (suivant && suivant.classList.contains('pt-volet')) { suivant.remove(); return; }
        var volet = document.createElement('div');
        volet.className = 'pt-volet';
        ligneEl.insertAdjacentElement('afterend', volet);
        charger(volet, params, false, apres);
    }

    window.MouPageTracker = {lien: lien, ligne: ligne, depuisPage: depuisPage, ouvrir: ouvrir, https: https};
})();
