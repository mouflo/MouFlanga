/* Interface de téléchargement Japscan */

const $ = id => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);

let selectedManga = null;
let selectedChapters = [];
let currentJobId = null;

// État
const state = {
    mangas: [],
    chapters: [],
};

// ============================================================================
// Gestion des onglets
// ============================================================================

$$(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
        const tabName = tab.dataset.tab;

        // Désactiver tous les tabs
        $$(".tab").forEach(t => t.classList.remove("active"));
        $$(".tab-content").forEach(tc => tc.classList.remove("active"));

        // Activer le tab cliqué
        tab.classList.add("active");
        $(`${tabName}-tab`).classList.add("active");

        if (tabName === "jobs") {
            loadJobs();
        }
    });
});

// ============================================================================
// Étape 1: Liste des mangas
// ============================================================================

async function loadMangas(forcer) {
    const list = $("manga-list");
    list.innerHTML = '<div class="loading">Chargement des mangas...</div>';

    try {
        const resp = await fetch("/api/japscan/list" + (forcer ? "?rafraichir=1" : ""));
        const data = await resp.json();

        if (!data.ok) {
            list.innerHTML = `<div class="loading" style="color: #ff6b6b;">Erreur: ${data.error}</div>`;
            return;
        }

        state.mangas = data.mangas;
        renderMangas();
        ouvrirDepuisLien();
        const note = $("liste-note");
        const cat = data.catalogue;
        if (note) note.textContent = `${data.mangas.length} séries : dernières sorties${data.cache_minutes ? ` (il y a ${data.cache_minutes} min)` : ""}, tes recherches`
            + (cat ? ` et le catalogue complet (chargé le ${new Date(cat.date * 1000).toLocaleDateString("fr-FR")})` : "") + ".";
        suivreCatalogue(data.chargement_catalogue);
    } catch (e) {
        list.innerHTML = `<div class="loading" style="color: #ff6b6b;">Erreur: ${e.message}</div>`;
    }
}

// Liste alphabétique avec une séparation par lettre, et une recherche (sans accents ni majuscules)
const sansAccents = t => String(t || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const lettreDe = t => { const c = sansAccents(t).charAt(0).toUpperCase(); return /[A-Z]/.test(c) ? c : "#"; };
const TYPES = {manhwa: "manhwa", manhua: "manhua"};

function boutonRecherche() {
    const t = $("manga-search").value.trim(), b = $("btn-recherche-japscan");
    b.hidden = t.length < 2;
    b.textContent = `🔎 Chercher « ${t} » dans tout Japscan`;
}

// Recherche dans tout le catalogue de Japscan (le navigateur du serveur s'ouvre : 10 à 30 secondes)
async function rechercherJapscan() {
    const t = $("manga-search").value.trim();
    if (t.length < 2) return;
    const list = $("manga-list");
    $("manga-lettres").innerHTML = "";
    list.innerHTML = `<div class="loading">⏳ Recherche de « ${echapper(t)} » sur Japscan… (10 à 30 secondes)</div>`;
    try {
        const resp = await fetch("/api/japscan/recherche", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({q: t})});
        const data = await resp.json();
        if (!data.ok) { list.innerHTML = `<div class="loading" style="color: #ff6b6b;">${echapper(data.error || "Recherche impossible")}</div>`; return; }
        state.recherche = data.mangas;
        list.innerHTML = `<div class="lettre-titre">Sur Japscan : ${data.mangas.length} résultat(s) pour « ${echapper(t)} »</div>`
            + (data.mangas.length ? data.mangas.map(ligneSerie).join("") : `<div class="loading">Aucun manga trouvé sur Japscan.</div>`)
            + `<button type="button" class="mou-btn secondary" id="btn-retour-recentes" style="margin-top:12px">← Revenir aux séries récentes</button>`;
        $("btn-retour-recentes").addEventListener("click", () => { $("manga-search").value = ""; boutonRecherche(); renderMangas(); });
    } catch (e) {
        list.innerHTML = `<div class="loading" style="color: #ff6b6b;">Erreur : ${echapper(e.message)}</div>`;
    }
}

// Arrivée depuis la bibliothèque (« ⚠ Manquants ») : /telecharger?q=<série> ouvre directement la série
let lienTraite = false;
function ouvrirDepuisLien() {
    const q = new URLSearchParams(location.search).get("q");
    if (!q || lienTraite) return;
    lienTraite = true;
    const cle = t => sansAccents(t).replace(/[^a-z0-9]/g, "");
    const exact = state.mangas.filter(m => cle(m.title) === cle(q));
    $("manga-search").value = q; boutonRecherche();
    if (exact.length === 1) { renderMangas(); selectedManga = exact[0]; loadChapters(); return; }
    if (state.mangas.some(m => sansAccents(m.title).includes(sansAccents(q)))) renderMangas();
    else rechercherJapscan();
}

function ligneSerie(m) {
    return `<button type="button" class="serie-ligne" data-id="${echapper(m.id)}"><span class="serie-nom">${echapper(m.title)}</span>`
         + (TYPES[m.type] ? `<span class="serie-type">${TYPES[m.type]}</span>` : "") + `<span class="serie-fleche">›</span></button>`;
}

function renderMangas() {
    const q = sansAccents($("manga-search").value.trim());
    const liste = state.mangas.filter(m => !q || sansAccents(m.title).includes(q));
    const list = $("manga-list");
    if (!liste.length) {
        list.innerHTML = `<div class="loading">Aucun manga ne correspond à « ${echapper($("manga-search").value)} » parmi les séries récentes : appuie sur « 🔎 Chercher dans tout Japscan ».</div>`;
        $("manga-lettres").innerHTML = "";
        return;
    }
    // Liste très longue (catalogue complet) sans recherche : une lettre à la fois
    const parLettre = !q && liste.length > 600;
    const toutes = [...new Set(liste.map(m => lettreDe(m.title)))];
    if (parLettre && !toutes.includes(state.lettre)) state.lettre = toutes.includes("A") ? "A" : toutes[0];
    const visibles = parLettre ? liste.filter(m => lettreDe(m.title) === state.lettre) : liste;
    let lettre = null, html = "";
    const lettres = [];
    for (const m of visibles) {
        const l = lettreDe(m.title);
        if (l !== lettre) { lettre = l; lettres.push(l); html += `<div class="lettre-titre" id="lettre-${l === "#" ? "num" : l}">${l}</div>`; }
        html += ligneSerie(m);
    }
    list.innerHTML = html;
    // Index des lettres : un appui fait défiler jusqu'à la lettre (ou l'affiche, quand la liste est très longue)
    $("manga-lettres").innerHTML = q ? "" : (parLettre ? toutes : lettres).map(l => `<button type="button" data-lettre="${l === "#" ? "num" : l}"${parLettre && l === state.lettre ? ' class="actif"' : ""}>${l}</button>`).join("");
    if (parLettre) list.insertAdjacentHTML("afterbegin", `<div class="tabsinfo" style="padding:6px">${visibles.length} série(s) en « ${state.lettre} » sur ${liste.length} — choisis une lettre ou tape un nom.</div>`);
}

$("manga-search").addEventListener("input", () => { boutonRecherche(); renderMangas(); });

// Catalogue complet : chargement en arrière-plan (20 à 30 minutes), avec sa progression
let suiviCatalogue = null;
function suivreCatalogue(e) {
    const zone = $("catalogue-etat"), b = $("btn-catalogue");
    clearTimeout(suiviCatalogue);
    if (e && e.en_cours) {
        b.hidden = true;
        zone.textContent = e.pages ? `⏳ Catalogue : page ${e.page} sur ${e.pages} · ${e.series} séries lues` : `⏳ ${e.message || "Chargement du catalogue…"}`;
        suiviCatalogue = setTimeout(async () => {
            const r = await (await fetch("/api/japscan/catalogue")).json();
            if (r.en_cours) suivreCatalogue(r); else { zone.textContent = r.message || ""; b.hidden = false; loadMangas(); }
        }, 5000);
    } else {
        b.hidden = false;
        zone.textContent = (e && e.message) || "";
    }
}
$("btn-catalogue").addEventListener("click", async () => {
    if (!confirm("Charger tout le catalogue de Japscan (environ 17 000 séries) ?\n\nÇa prend 20 à 30 minutes en arrière-plan ; pendant ce temps, pas de téléchargement. Tu recevras un message Telegram à la fin.")) return;
    const r = await (await fetch("/api/japscan/catalogue", {method: "POST"})).json();
    if (!r.ok) { $("catalogue-etat").textContent = r.error || "Impossible"; return; }
    suivreCatalogue({en_cours: true, message: r.message});
});
$("manga-search").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); rechercherJapscan(); } });
$("btn-recherche-japscan").addEventListener("click", rechercherJapscan);
$("manga-lettres").addEventListener("click", e => {
    const b = e.target.closest("[data-lettre]");
    if (!b) return;
    const l = b.dataset.lettre === "num" ? "#" : b.dataset.lettre;
    if (state.mangas.length > 600) { state.lettre = l; renderMangas(); return; }
    const t = $("lettre-" + b.dataset.lettre); if (t) t.scrollIntoView({behavior: "smooth", block: "start"});
});
$("manga-list").addEventListener("click", e => {
    const ligne = e.target.closest(".serie-ligne");
    if (!ligne) return;
    selectedManga = state.mangas.find(m => m.id === ligne.dataset.id) || (state.recherche || []).find(m => m.id === ligne.dataset.id);
    if (selectedManga) loadChapters();
});


// ============================================================================
// Étape 2: Sélection des chapitres
// ============================================================================

async function loadChapters() {
    const chaptersList = $("chapters-list");
    chaptersList.innerHTML = '<div class="loading">Chargement des chapitres...</div>';

    $("manga-title-display").textContent = selectedManga.title;
    $("step-list").style.display = "none";
    $("step-chapters").style.display = "block";

    try {
        const resp = await fetch(`/api/japscan/chapters/${selectedManga.id}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: selectedManga.url, title: selectedManga.title })
        });

        const data = await resp.json();
        if (!data.ok) {
            chaptersList.innerHTML = `<div class="loading" style="color: #ff6b6b;">Erreur: ${data.error}</div>`;
            return;
        }

        state.chapters = data.chapters;
        renderChapters();
    } catch (e) {
        chaptersList.innerHTML = `<div class="loading" style="color: #ff6b6b;">Erreur: ${e.message}</div>`;
    }
}

function renderChapters() {
    const list = $("chapters-list");
    // Les chapitres déjà dans la bibliothèque sont marqués et décochés : seuls les manquants sont cochés
    list.innerHTML = state.chapters.map((ch, i) => `
        <div class="chapter-item${ch.deja ? " deja" : ""}">
            <input type="checkbox" value="${i}" class="chapter-checkbox"${ch.deja ? "" : " checked"}>
            <div class="chapter-item-label">
                <div class="chapter-item-name">${echapper(ch.title)}${ch.deja ? ' <span class="badge-deja">✓ déjà téléchargé</span>' : ""}</div>
            </div>
        </div>
    `).join("");
    const deja = state.chapters.filter(ch => ch.deja).length;
    $("chap-manquants").textContent = deja
        ? `${deja} chapitre(s) déjà dans ta bibliothèque, ${state.chapters.length - deja} manquant(s) : seuls les manquants sont cochés.`
        : "";

    $$(".chapter-checkbox").forEach(cb => {
        cb.addEventListener("change", updateChapterSelection);
    });
    // Tout est coché au départ : on le prend en compte tout de suite (sinon « Suivant » reste grisé)
    updateChapterSelection();
}

function updateChapterSelection() {
    // On retrouve les chapitres par leur position (deux chapitres peuvent avoir le même titre)
    selectedChapters = [...$$(".chapter-checkbox")]
        .filter(cb => cb.checked)
        .map(cb => state.chapters[Number(cb.value)])
        .filter(Boolean);
    $("btn-next-metadata").disabled = selectedChapters.length === 0;
    $("chap-count").textContent = `${selectedChapters.length} chapitre(s) sélectionné(s) sur ${state.chapters.length}`;
}

function cocherChapitres(test) {
    $$(".chapter-checkbox").forEach(cb => {
        const ch = state.chapters[Number(cb.value)];
        cb.checked = test(ch);
    });
    updateChapterSelection();
}

$("btn-chap-all").addEventListener("click", () => cocherChapitres(() => true));
$("btn-chap-none").addEventListener("click", () => cocherChapitres(() => false));
$("btn-chap-manquants").addEventListener("click", () => cocherChapitres(ch => !ch.deja));
$("btn-chap-range").addEventListener("click", () => {
    const de = parseFloat($("chap-from").value);
    const a = parseFloat($("chap-to").value);
    if (isNaN(de) && isNaN(a)) return;
    // On compare avec le numéro du chapitre sur le site (chapter_id), pas avec sa position
    cocherChapitres(ch => {
        const n = parseFloat(ch.chapter_id);
        return !isNaN(n) && (isNaN(de) || n >= de) && (isNaN(a) || n <= a);
    });
});

$("btn-back-manga").addEventListener("click", () => {
    $("step-chapters").style.display = "none";
    $("step-list").style.display = "block";
    selectedManga = null;
    selectedChapters = [];
});

$("btn-next-metadata").addEventListener("click", () => {
    if (selectedChapters.length === 0) return;
    generateMetadataForm();
});

// ============================================================================
// Étape 3: Confirmation des métadonnées
// ============================================================================

function generateMetadataForm() {
    // Récapitulatif avant de lancer : combien de chapitres, lesquels, et où ils seront rangés
    const nums = selectedChapters.map(ch => ch.chapter_id).filter(Boolean);
    const deja = state.chapters.filter(ch => ch.deja).length;
    const titres = selectedChapters.slice(0, 8).map(ch => `<li>${echapper(ch.title)}</li>`).join("")
        + (selectedChapters.length > 8 ? `<li>… et ${selectedChapters.length - 8} autre(s)</li>` : "");
    $("metadata-form").innerHTML = `
        <div class="tome-group">
            <h3>${echapper(selectedManga.title)}</h3>
            <p><b>${selectedChapters.length} chapitre(s)</b>${nums.length > 1 ? ` (du ${echapper(nums[0])} au ${echapper(nums[nums.length - 1])})` : ""}
               ${deja ? `· ${deja} déjà dans ta bibliothèque` : ""}</p>
            <ul style="margin: 8px 0 0; padding-left: 20px; color: var(--muted);">${titres}</ul>
            <p style="color: var(--muted); margin-top: 10px;">Un fichier .cbz par chapitre, rangé dans le dossier « ${echapper(selectedManga.title)} » de ta bibliothèque.</p>
        </div>`;

    $("step-chapters").style.display = "none";
    $("step-metadata").style.display = "block";
}

$("btn-back-chapters").addEventListener("click", () => {
    $("step-metadata").style.display = "none";
    $("step-chapters").style.display = "block";
});

$("btn-download").addEventListener("click", startDownload);

// ============================================================================
// Étape 4: Téléchargement
// ============================================================================

async function startDownload() {
    if (!selectedManga || selectedChapters.length === 0) {
        alert("Erreur: données manquantes");
        return;
    }

    $("step-metadata").style.display = "none";
    $("step-downloading").style.display = "block";

    try {
        const resp = await fetch("/api/japscan/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                title: selectedManga.title,
                chapters: selectedChapters
            })
        });

        const data = await resp.json();
        if (!data.ok) {
            alert(`Erreur: ${data.error}`);
            return;
        }

        currentJobId = data.job_id;
        monitorDownload();
    } catch (e) {
        alert(`Erreur: ${e.message}`);
    }
}

async function monitorDownload() {
    const pollInterval = setInterval(async () => {
        try {
            const resp = await fetch(`/api/japscan/job/${currentJobId}`);
            const data = await resp.json();

            if (!data.ok) {
                clearInterval(pollInterval);
                return;
            }

            const job = data.job;
            updateDownloadUI(job);

            if (job.status !== "running") {
                clearInterval(pollInterval);
            }
        } catch (e) {
            console.error("Erreur monitoring:", e);
        }
    }, 500);
}

function updateDownloadUI(job) {
    const progress = job.total > 0 ? (job.progress / job.total) * 100 : 0;

    $("progress-fill").style.width = progress + "%";
    $("progress-text").textContent = `${job.progress} / ${job.total} chapitres`;

    if (job.status === "completed") {
        $("progress-fill").style.width = "100%";
        $("progress-text").innerHTML = `✅ Téléchargement terminé! <br><small>${job.downloaded.length} fichiers créés</small>`;
    } else if (job.status === "error") {
        $("progress-text").innerHTML = `❌ Erreur: ${job.error}`;
    }
}

// ============================================================================
// Tab: Jobs en cours
// ============================================================================

const LIBELLES_JOB = {
    running: "⏳ En cours", completed: "✅ Terminé", error: "❌ Arrêté",
    annule: "⏹ Annulé",
};

function echapper(t) {
    return String(t == null ? "" : t).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
}

async function loadJobs() {
    const list = $("jobs-list");

    try {
        const resp = await fetch("/api/japscan/jobs");
        const data = await resp.json();
        const jobs = (data.jobs || []);

        // Pastille sur l'onglet quand un téléchargement tourne
        const nb = jobs.filter(j => j.status === "running").length;
        const onglet = document.querySelector('.tab[data-tab="jobs"]');
        if (onglet) onglet.textContent = nb ? `⏳ En cours (${nb})` : "⏳ En cours";

        if (jobs.length === 0) {
            list.innerHTML = '<p style="color: var(--muted);">Aucun téléchargement en cours.</p>';
            return;
        }
        list.innerHTML = jobs.map(j => {
            const pct = j.total > 0 ? Math.round(j.progress / j.total * 100) : 0;
            const bouton = j.status === "running"
                ? `<button class="mou-btn secondary" data-annuler="${echapper(j.id)}" type="button">Annuler</button>` : "";
            const actuel = (j.status === "running" && j.en_cours ? `<small>Chapitre en cours : ${echapper(j.en_cours)}</small><br>` : "")
                + (j.status === "running" && j.en_attente_captcha ? `<small>🛡️ ${j.en_attente_captcha} chapitre(s) attendent un captcha : <a href="/verification">page Vérification</a></small><br>` : "")
                + (j.status !== "running" && j.captchas != null ? `<small>Captchas demandés : ${j.captchas}</small><br>` : "");
            const erreur = j.error ? `<small style="color: #ff6b6b;">${echapper(j.error)}</small><br>` : "";
            return `
            <div class="job-item" style="background: var(--card); border-radius: 8px; padding: 12px 16px; margin: 12px 0;">
                <strong>${echapper(j.title)}</strong> — ${LIBELLES_JOB[j.status] || echapper(j.status)}
                <div class="progress-bar" style="margin: 8px 0;"><div class="progress-fill" style="width: ${pct}%"></div></div>
                <small>${j.progress} / ${j.total} chapitres · ${j.downloaded} fichier(s) créé(s) · ${j.failed} sans page</small><br>
                ${actuel}${erreur}${bouton}
            </div>`;
        }).join("");
        list.querySelectorAll("[data-annuler]").forEach(b => b.addEventListener("click", async () => {
            b.disabled = true;
            await fetch(`/api/japscan/job/${b.dataset.annuler}/annuler`, { method: "POST" });
            loadJobs();
        }));
    } catch (e) {
        list.innerHTML = `<p style="color: #ff6b6b;">Erreur: ${e.message}</p>`;
    }
}

// Mise à jour régulière : on garde l'état des téléchargements même si la page a été rechargée
setInterval(loadJobs, 3000);

// ============================================================================
// Initialisation
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
    loadMangas();
    const bouton = $("btn-refresh-list");
    if (bouton) bouton.addEventListener("click", () => loadMangas(true));
    loadJobs();
});

// Bandeau « vérification Cloudflare en attente » (mis à jour toutes les 3 secondes)
async function surveillerVerification() {
    try {
        const r = await fetch("/api/japscan/verif/etat");
        const d = await r.json();
        const b = document.getElementById("verif-banner");
        if (b) b.style.display = d.actif ? "block" : "none";
    } catch (e) { /* réseau coupé un instant */ }
}
setInterval(surveillerVerification, 3000);
surveillerVerification();
