// Page « Vérification » : affiche le navigateur du serveur et relaie les clics.
// Les fonctions $ / api / post / say viennent de mou-settings.js.
const img = $('vImg'), box = $('vBox');
let actif = false, occupe = false, dernierClic = 0;

function etat(texte, type) {
    $('vState').className = 'note ' + (type || 'warn');
    $('vState').textContent = texte;
}

async function rafraichir() {
    if (occupe) return;
    occupe = true;
    try {
        const e = await api('/api/japscan/verif/etat');
        if (!e.actif) {
            if (actif) etat('✅ Vérification passée : le téléchargement reprend.', 'ok');
            else etat('Aucune vérification en attente pour le moment. Cette page se mettra à jour toute seule si Cloudflare en demande une.', 'warn');
            actif = false; box.hidden = true;
            return;
        }
        if (!actif) etat('⏳ Cloudflare attend ton clic sur la case de vérification.', 'warn');
        actif = true; box.hidden = false;
        // Charge la nouvelle capture en arrière-plan pour éviter le clignotement
        const nouvelle = new Image();
        nouvelle.onload = () => { img.src = nouvelle.src; };
        nouvelle.src = '/api/japscan/verif/capture?t=' + Date.now();
    } catch (err) { /* réseau coupé un instant : on réessaie au prochain tour */ }
    finally { occupe = false; }
}

img.addEventListener('click', async ev => {
    const r = img.getBoundingClientRect();
    if (!img.naturalWidth) return;
    // coordonnées dans l'image réelle (celle du navigateur du serveur)
    const x = (ev.clientX - r.left) * img.naturalWidth / r.width;
    const y = (ev.clientY - r.top) * img.naturalHeight / r.height;
    const rond = document.createElement('div');
    rond.className = 'vclic';
    rond.style.left = (ev.clientX - box.getBoundingClientRect().left) + 'px';
    rond.style.top = (ev.clientY - box.getBoundingClientRect().top) + 'px';
    box.appendChild(rond); setTimeout(() => rond.remove(), 800);
    dernierClic = Date.now();
    const res = await post('/api/japscan/verif/clic', {x, y});
    if (!res.ok) etat(res.error || 'Le clic a échoué.', 'err');
    setTimeout(rafraichir, 700);
});

setInterval(rafraichir, 1500);
rafraichir();
