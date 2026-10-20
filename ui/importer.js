/* MouFlanga · page « Importer » : archives déposées à la racine du dossier des mangas */
let groupes = [], suivi = null;

function ligne(g, i) {
    const total = g.archives.reduce((s, a) => s + a.taille_go, 0);
    return `<div class="groupe" data-i="${i}">
        <div class="groupe-tete">
            <input type="text" class="groupe-nom" value="${esc(g.nom)}" aria-label="Nom de la série" spellcheck="false">
            <button class="btn ghost groupe-go" type="button">Importer</button>
        </div>
        <div class="groupe-info">${g.base === 'ok' ? '<span class="existe">📦 déjà importé (dossier OK)</span> · ' : ''}${g.existe ? '<span class="existe">➕ complète la série existante</span> · ' : ''}${g.archives.length} archive${g.archives.length > 1 ? 's' : ''} · ${String(total.toFixed(1)).replace('.', ',')} Go</div>
        <ul class="groupe-archives">${g.archives.map(a => `<li>${esc(a.nom)}</li>`).join('')}</ul>
    </div>`;
}

async function charger() {
    const r = await api('/api/import/racine');
    groupes = r.groupes || [];
    $('groupes').innerHTML = groupes.length ? groupes.map(ligne).join('') : '<div class="tabsinfo">Aucune archive à importer : dépose des .rar, .zip ou .7z directement dans le dossier des mangas.</div>';
    $('toutImporter').hidden = !groupes.length;
    $('toutImporter').textContent = `📥 Tout importer (${groupes.length} série${groupes.length > 1 ? 's' : ''})`;
    const f = r.file || {};
    const actif = f.en_cours || (f.attente || []).length;
    $('fileBox').hidden = !actif && !f.message;
    $('fileTitre').textContent = actif ? '⏳ Import en cours' : '✅ Dernier import';
    $('fileEtat').innerHTML = actif
        ? `<b>${esc(f.en_cours || '')}</b>${r.detail ? ' — ' + esc(r.detail) : ''}<br><span class="tabsinfo">Encore ${f.attente.length} série(s) en attente · ${f.faits.length} importée(s)${f.erreurs.length ? ' · ⚠ ' + f.erreurs.length + ' avec un problème' : ''}</span>`
        : esc(f.message || '');
    $('fileFaits').innerHTML = (f.faits || []).concat(f.erreurs || []).map(x => `<li>${esc(x)}</li>`).join('');
    clearTimeout(suivi);
    if (actif) suivi = setTimeout(charger, 4000);
}

async function importer(liste) {
    const r = await post('/api/import/racine', {groupes: liste});
    say('importMsg', r.message || r.error, r.ok);
    if (r.ok) charger();
}

function groupeDepuis(el) {
    const g = groupes[+el.dataset.i];
    return {nom: el.querySelector('.groupe-nom').value.trim(), propose: g.nom, archives: g.archives.map(a => a.nom)};
}

$('groupes').addEventListener('click', e => {
    const b = e.target.closest('.groupe-go'); if (!b) return;
    importer([groupeDepuis(b.closest('.groupe'))]);
});
$('toutImporter').addEventListener('click', async () => {
    if (!await MouConfirm(`Importer les ${groupes.length} séries ? Ça peut prendre plusieurs heures pour beaucoup de gigaoctets ; tu recevras un message Telegram à la fin.`)) return;
    importer([...document.querySelectorAll('.groupe')].map(groupeDepuis));
});
charger();

// ---------- 🔄 Dossier des torrents : relire, cocher, importer avec le traitement automatique ----------
let elements = [], suiviRescan = null;

function listeTomes(l) {
    return l.length > 8 ? l.slice(0, 8).join(', ') + '…' : l.join(', ');
}

// Choix à faire pour un élément dont des tomes sont déjà dans la bibliothèque : tout se décide ici, avant l'import
function blocChoix(g, i) {
    const deja = g.deja || [], nouveaux = g.nouveaux || [];
    if (!deja.length) return '';
    const defaut = ['remplacer', 'manquants', 'ignorer'].includes(g.regle) ? g.regle : (nouveaux.length ? 'manquants' : 'ignorer');
    const radio = (v, titre, aide) => `<label class="choix-ligne"><input type="radio" name="choix${i}" value="${v}"${defaut === v ? ' checked' : ''}><span><b>${titre}</b><small>${aide}</small></span></label>`;
    return `<div class="rescan-choix">
        <div class="rescan-alerte">⚠ ${deja.length} tome${deja.length > 1 ? 's' : ''} déjà dans la bibliothèque (${esc(listeTomes(deja))})${nouveaux.length ? ` · ${nouveaux.length} nouveau${nouveaux.length > 1 ? 'x' : ''} (${esc(listeTomes(nouveaux))})` : ' · aucun nouveau tome'}</div>
        ${radio('manquants', '➕ Ajouter seulement les manquants', nouveaux.length ? 'les tomes déjà là ne sont pas touchés' : 'rien à ajouter : ce choix ne change rien')}
        ${radio('remplacer', '♻️ Remplacer les tomes en double', `les ${deja.length} tome${deja.length > 1 ? 's' : ''} déjà là vont à la corbeille (30 jours), les nouveaux sont ajoutés`)}
        ${radio('ignorer', '⛔ Ne rien faire', 'cet élément est laissé de côté')}
        <label class="choix-toujours"><input type="checkbox" class="rescan-toujours"> Retenir ce choix pour cette série${g.regle ? ' (déjà retenu : ' + esc({remplacer: 'remplacer', manquants: 'ajouter les manquants', ignorer: 'ne rien faire'}[g.regle] || g.regle) + ')' : ''}</label>
    </div>`;
}

function ligneTorrent(g, i) {
    return `<div class="groupe" data-i="${i}">
        <div class="groupe-tete">
            <input type="checkbox" class="rescan-coche" aria-label="Importer cet élément" style="width:24px;height:24px;flex:none">
            <input type="text" class="groupe-nom" value="${esc(g.serie)}" aria-label="Nom de la série" spellcheck="false">
        </div>
        <div class="groupe-info">${g.existe ? '<span class="existe">➕ complète la série existante</span> · ' : ''}${g.fichiers} fichier${g.fichiers > 1 ? 's' : ''} · ${String(g.taille_go.toFixed(1)).replace('.', ',')} Go</div>
        <ul class="groupe-archives"><li>${esc(g.nom)}</li></ul>
        <div class="rescan-choix-zone">${blocChoix(g, i)}</div>
    </div>`;
}

async function lireTorrents(garderCoches) {
    const gardees = garderCoches ? new Set([...document.querySelectorAll('#rescanListe .groupe')].filter(el => el.querySelector('.rescan-coche').checked).map(el => elements[+el.dataset.i].nom)) : new Set();
    const r = await api('/api/import/torrents' + ($('rescanOk') && $('rescanOk').checked ? '?ok=1' : ''));
    if (r.error) { say('rescanMsg', r.error, false); return; }
    elements = r.elements || [];
    $('rescanDossier').textContent = r.dossier || 'non réglé';
    $('rescanListe').innerHTML = elements.length ? elements.map(ligneTorrent).join('')
        : '<div class="tabsinfo">' + (r.dossier ? 'Rien à importer dans ce dossier.' : 'Dossier des torrents non réglé (⚙️ Réglages → Torrents).') + '</div>';
    document.querySelectorAll('#rescanListe .groupe').forEach(el => { if (gardees.has(elements[+el.dataset.i].nom)) el.querySelector('.rescan-coche').checked = true; });
    $('rescanGo').hidden = !elements.length;
    $('rescanCherche').hidden = elements.length < 2;
    filtrerRescan();
    const f = r.file || {};
    const actif = f.en_cours || (f.attente || []).length;
    $('rescanFileBox').hidden = !actif && !f.message;
    $('rescanTitre').textContent = actif ? '⏳ Rescan en cours' : '✅ Dernier rescan';
    $('rescanFileEtat').innerHTML = actif
        ? `<b>${esc(f.en_cours || '')}</b>${r.detail ? ' — ' + esc(r.detail) : ''}<br><span class="tabsinfo">Encore ${f.attente.length} en attente · ${f.faits.length} importée(s)${f.erreurs.length ? ' · ⚠ ' + f.erreurs.length + ' avec un problème' : ''}</span>`
        : esc(f.message || '');
    $('rescanFaits').innerHTML = (f.faits || []).concat((f.erreurs || []).map(x => '⚠ ' + x)).map(x => `<li>${esc(x)}</li>`).join('');
    clearTimeout(suiviRescan);
    if (actif) suiviRescan = setTimeout(() => lireTorrents(true), 4000);
}

// 🔎 Recherche dans la liste : sans accents ni majuscules, sur le nom du torrent et le nom de série (même modifié).
// Un élément caché par la recherche garde sa case cochée.
const simple = t => String(t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
function filtrerRescan() {
    const mots = simple($('rescanCherche').value).split(' ').filter(Boolean);
    let vus = 0;
    document.querySelectorAll('#rescanListe .groupe').forEach(el => {
        const g = elements[+el.dataset.i] || {};
        const texte = simple(g.nom + ' ' + g.serie + ' ' + (el.querySelector('.groupe-nom') || {}).value);
        const ok = mots.every(m => texte.includes(m));
        el.hidden = !ok;
        if (ok) vus++;
    });
    $('rescanCompte').textContent = mots.length ? `${vus} élément${vus > 1 ? 's' : ''} sur ${elements.length}` : '';
}
$('rescanCherche').addEventListener('input', filtrerRescan);
$('rescanLire').addEventListener('click', () => lireTorrents(true));
if ($('rescanOk')) $('rescanOk').addEventListener('change', () => lireTorrents(false));
$('rescanGo').addEventListener('click', async () => {
    const choisis = [...document.querySelectorAll('#rescanListe .groupe')].filter(el => el.querySelector('.rescan-coche').checked)
        .map(el => {
            const radio = el.querySelector('.rescan-choix input[type=radio]:checked'), toujours = el.querySelector('.rescan-toujours');
            return {nom: elements[+el.dataset.i].nom, base: elements[+el.dataset.i].base || 'nok', serie: el.querySelector('.groupe-nom').value.trim(),
                    choix: radio ? radio.value : '', toujours: !!(toujours && toujours.checked)};
        });
    if (!choisis.length) { say('rescanMsg', 'Coche au moins un élément.', false); return; }
    const remplace = choisis.filter(c => c.choix === 'remplacer').length;
    if (!await MouConfirm(`Importer ${choisis.length} élément${choisis.length > 1 ? 's' : ''} ?` +
        (remplace ? `\n\n♻️ ${remplace} avec remplacement des tomes en double (les anciens vont à la corbeille 30 jours).` : '') +
        '\nTu recevras un message Telegram à la fin.')) return;
    const r = await post('/api/import/torrents', {elements: choisis});
    say('rescanMsg', r.message || r.error, r.ok);
    if (r.ok) lireTorrents(false);
});
lireTorrents(false);

// Nom de série corrigé à la main : les tomes déjà là sont recalculés pour ce nom
document.getElementById('rescanListe').addEventListener('change', async e => {
    if (!e.target.classList.contains('groupe-nom')) return;
    const el = e.target.closest('.groupe'), g = elements[+el.dataset.i];
    const r = await api('/api/import/torrents/doublons?base=' + encodeURIComponent(g.base || 'nok') + '&nom=' + encodeURIComponent(g.nom) + '&serie=' + encodeURIComponent(e.target.value.trim()));
    Object.assign(g, {deja: r.deja || [], nouveaux: r.nouveaux || [], regle: r.regle || null});
    el.querySelector('.rescan-choix-zone').innerHTML = blocChoix(g, +el.dataset.i);
});
