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
        const note = $("liste-note");
        if (note) note.textContent = data.cache_minutes ? `Liste gardée en mémoire (il y a ${data.cache_minutes} min).` : "";
    } catch (e) {
        list.innerHTML = `<div class="loading" style="color: #ff6b6b;">Erreur: ${e.message}</div>`;
    }
}

function renderMangas() {
    const list = $("manga-list");
    list.innerHTML = state.mangas.map(manga => `
        <div class="manga-item">
            <input type="checkbox" value="${manga.id}" class="manga-checkbox">
            <div class="manga-item-cover">📚</div>
            <div class="manga-item-info">
                <div class="manga-item-title">${manga.title}</div>
            </div>
        </div>
    `).join("");

    $$(".manga-checkbox").forEach(cb => {
        cb.addEventListener("change", updateMangaSelection);
    });
}

function updateMangaSelection() {
    const checked = $$(".manga-checkbox:checked");
    $("btn-next-chapters").disabled = checked.length === 0;
}

$("btn-next-chapters").addEventListener("click", () => {
    const checked = $$(".manga-checkbox:checked");
    if (checked.length === 0) return;

    if (checked.length > 1) {
        alert("Pour l'instant, sélectionne un seul manga à la fois");
        return;
    }

    selectedManga = state.mangas.find(m => m.id === checked[0].value);
    loadChapters();
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
