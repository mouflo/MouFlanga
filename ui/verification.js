// Page « Vérification » : affiche le navigateur du serveur et relaie les clics.
// Les fonctions $ / api / post viennent de mou-settings.js.
const img = $('vImg'), box = $('vBox'), marque = $('vMarque'), retour = $('vRetour');
let actif = false, occupe = false, clicEnCours = false, effaceMarque = null;
let zone = [0, 0];   // décalage de la capture si elle est recadrée sur le captcha (x, y dans la page)

function etat(texte, type) {
    $('vState').className = 'note ' + (type || 'warn');
    $('vState').textContent = texte;
}

// Vérification passée : retour automatique à la page où elle était (mémorisée par le bandeau de ui/verif-banniere.js)
function retourApres() {
    try {
        const r = JSON.parse(localStorage.getItem('mfRetourVerif') || 'null');
        if (!r || !r.url || Date.now() - r.t > 2 * 3600 * 1000 || r.url.indexOf('/verification') === 0) return;
        localStorage.removeItem('mfRetourVerif');
        etat('✅ Vérification passée. Retour à la page où tu étais…', 'ok');
        setTimeout(() => { location.href = r.url; }, 2000);
    } catch (e) { /* stockage bloqué : pas de retour automatique */ }
}

async function rafraichir() {
    if (occupe || clicEnCours) return;
    occupe = true;
    try {
        const e = await api('/api/japscan/verif/etat');
        if (!e.actif) {
            if (actif) { etat('✅ Vérification passée : le téléchargement reprend.', 'ok'); retourApres(); }
            else if (e.groupes) etat('🕒 ' + e.groupes + ' chapitre(s) mis de côté pour un captcha (captchas groupés) : ils arriveront ici à la fin du téléchargement, avec une alerte Telegram. Garde cette page ouverte ou reviens à ce moment-là.', 'warn');
            else etat('Aucune vérification en attente pour le moment. Cette page se mettra à jour toute seule si le site en demande une.', 'warn');
            actif = false; box.hidden = true;
            return;
        }
        if (!actif) etat('⏳ Le site attend ta vérification : clique sur la case Cloudflare ou réponds au captcha.', 'warn');
        actif = true; box.hidden = false;
        const rep = await fetch('/api/japscan/verif/capture?t=' + Date.now(), {cache: 'no-store'});
        if (rep.ok) {
            const z = (rep.headers.get('X-Zone') || '').split(',').map(Number);
            const blob = await rep.blob();
            const url = URL.createObjectURL(blob);
            const nouvelle = new Image();
            nouvelle.onload = () => {
                const ancienne = img.src;
                zone = z.length === 4 && z.every(v => !isNaN(v)) ? [z[0], z[1]] : [0, 0];
                img.src = url;
                if (ancienne && ancienne.startsWith('blob:')) URL.revokeObjectURL(ancienne);
            };
            nouvelle.src = url;
        }
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

// --- Glisser-déposer au doigt (captcha à remettre en ordre) ---
// Le doigt qui glisse sur l'image est rejoué tel quel dans le navigateur du serveur.
let trajet = null, glissementFait = false;
img.style.touchAction = 'none';   // empêche la page de défiler pendant qu'on glisse

function versImage(ev) {
    const r = img.getBoundingClientRect();
    return [(ev.clientX - r.left) * img.naturalWidth / r.width + zone[0], (ev.clientY - r.top) * img.naturalHeight / r.height + zone[1]];
}

img.addEventListener('pointerdown', ev => {
    if (clicEnCours || !img.naturalWidth) return;
    trajet = {points: [versImage(ev)], px: [ev.clientX, ev.clientY], bouge: false};
    try { img.setPointerCapture(ev.pointerId); } catch (e) { /* ignoré */ }
});

img.addEventListener('pointermove', ev => {
    if (!trajet) return;
    const dx = ev.clientX - trajet.px[0], dy = ev.clientY - trajet.px[1];
    if (Math.hypot(dx, dy) > 12) trajet.bouge = true;
    if (!trajet.bouge) return;
    const dernier = trajet.points[trajet.points.length - 1], p = versImage(ev);
    if (Math.hypot(p[0] - dernier[0], p[1] - dernier[1]) >= 6) trajet.points.push(p);
    placerMarque(ev.clientX, ev.clientY, '✋');
});

img.addEventListener('pointerup', async ev => {
    const t = trajet; trajet = null;
    if (!t || !t.bouge) return;               // simple appui : le clic normal s'en occupe
    glissementFait = true;
    setTimeout(() => { glissementFait = false; }, 600);
    const fin = versImage(ev);
    t.points.push(fin);
    // on garde au plus ~60 points pour un envoi léger
    let pts = t.points;
    if (pts.length > 30) { const pas = pts.length / 30; pts = Array.from({length: 30}, (_, k) => pts[Math.floor(k * pas)]).concat([fin]); }
    clicEnCours = true;
    box.classList.add('occupe');
    placerMarque(ev.clientX, ev.clientY, '⏳');
    retour.textContent = 'Glissement envoyé…';
    try {
        const res = await post('/api/japscan/verif/glisser', {points: pts});
        if (!res.ok) { retour.textContent = '❌ ' + (res.error || 'Le glissement a échoué.'); marque.textContent = '✖'; }
        else {
            marque.textContent = '✔';
            retour.textContent = 'Glissement effectué (' + ((res.info || {}).mode || '?') + ')' +
                ((res.info || {}).captcha ? ' · le captcha est encore là : vérifie l\'ordre ou recommence.' : ' · captcha résolu !');
        }
    } finally {
        clicEnCours = false;
        box.classList.remove('occupe');
        effaceMarque = setTimeout(() => { marque.hidden = true; }, 4000);
        rafraichir();
    }
});

img.addEventListener('pointercancel', () => { trajet = null; });

img.addEventListener('click', async ev => {
    if (glissementFait) return;
    if (clicEnCours || !img.naturalWidth) return;
    const r = img.getBoundingClientRect();
    // coordonnées dans l'image réelle (celle du navigateur du serveur)
    const x = (ev.clientX - r.left) * img.naturalWidth / r.width + zone[0];
    const y = (ev.clientY - r.top) * img.naturalHeight / r.height + zone[1];
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
            retour.textContent = `Clic effectué (${i.mode || '?'}). Réponse du site : « ${i.titre || '…'} » · autorisation Cloudflare : ${i.cookie ? 'reçue' : 'pas encore'}` +
                (i.texte ? ` · page : ${i.texte}` : '');
        }
    } finally {
        clicEnCours = false;
        box.classList.remove('occupe');
        effaceMarque = setTimeout(() => { marque.hidden = true; }, 4000);
        rafraichir();
    }
});

async function defiler(dy) {
    try { await post('/api/japscan/verif/defiler', {dy}); } catch (e) { /* ignoré */ }
    rafraichir();
}
$('vHaut').addEventListener('click', () => defiler(-500));
$('vBas').addEventListener('click', () => defiler(500));

// Captures enchaînées dès que la précédente est arrivée (le captcha a un chronomètre : chaque seconde compte)
async function boucle() {
    while (true) {
        const debut = Date.now();
        await rafraichir();
        const duree = Date.now() - debut;
        await new Promise(r => setTimeout(r, actif ? Math.max(120, 350 - duree) : 1000));
    }
}
boucle();
