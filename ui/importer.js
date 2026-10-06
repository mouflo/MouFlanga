/* MouFlanga · page « Importer » : archives déposées à la racine du dossier des mangas */
let groupes = [], suivi = null;

function ligne(g, i) {
    const total = g.archives.reduce((s, a) => s + a.taille_go, 0);
    return `<div class="groupe" data-i="${i}">
        <div class="groupe-tete">
            <input type="text" class="groupe-nom" value="${esc(g.nom)}" aria-label="Nom de la série" spellcheck="false">
            <button class="btn ghost groupe-go" type="button">Importer</button>
        </div>
        <div class="groupe-info">${g.existe ? '<span class="existe">➕ complète la série existante</span> · ' : ''}${g.archives.length} archive${g.archives.length > 1 ? 's' : ''} · ${String(total.toFixed(1)).replace('.', ',')} Go</div>
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
$('toutImporter').addEventListener('click', () => {
    if (!confirm(`Importer les ${groupes.length} séries ? Ça peut prendre plusieurs heures pour beaucoup de gigaoctets ; tu recevras un message Telegram à la fin.`)) return;
    importer([...document.querySelectorAll('.groupe')].map(groupeDepuis));
});
charger();
