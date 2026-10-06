// Page « Vérification » : affiche le navigateur du serveur et relaie les clics.
// Les fonctions $ / api / post viennent de mou-settings.js.
const img = $('vImg'), box = $('vBox'), marque = $('vMarque'), retour = $('vRetour');
let actif = false, occupe = false, clicEnCours = false, effaceMarque = null;

function etat(texte, type) {
    $('vState').className = 'note ' + (type || 'warn');
    $('vState').textContent = texte;
}

async function rafraichir() {
    if (occupe || clicEnCours) return;
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

function placerMarque(clientX, clientY, texte) {
    const b = box.getBoundingClientRect();
    marque.style.left = (clientX - b.left) + 'px';
    marque.style.top = (clientY - b.top) + 'px';
    marque.textContent = texte || '';
    marque.hidden = false;
    clearTimeout(effaceMarque);
}

img.addEventListener('click', async ev => {
    if (clicEnCours || !img.naturalWidth) return;
    const r = img.getBoundingClientRect();
    // coordonnées dans l'image réelle (celle du navigateur du serveur)
    const x = (ev.clientX - r.left) * img.naturalWidth / r.width;
    const y = (ev.clientY - r.top) * img.naturalHeight / r.height;
    clicEnCours = true;
    box.classList.add('occupe');
    placerMarque(ev.clientX, ev.clientY, '⏳');
    retour.textContent = 'Clic envoyé, en attente de la réponse de Cloudflare (3 secondes environ)…';
    try {
        const res = await post('/api/japscan/verif/clic', {x, y});
        if (!res.ok) {
            retour.textContent = '❌ ' + (res.error || 'Le clic a échoué.');
            marque.textContent = '✖';
        } else {
            const i = res.info || {};
            marque.textContent = '✔';
            retour.textContent = `Clic effectué. Réponse du site : « ${i.titre || '…'} » · autorisation Cloudflare : ${i.cookie ? 'reçue' : 'pas encore'}` +
                (i.texte ? ` · page : ${i.texte}` : '');
        }
    } finally {
        clicEnCours = false;
        box.classList.remove('occupe');
        effaceMarque = setTimeout(() => { marque.hidden = true; }, 4000);
        rafraichir();
    }
});

setInterval(rafraichir, 1000);
rafraichir();
