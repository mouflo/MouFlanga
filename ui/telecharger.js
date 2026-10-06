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
    metadata: {}
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

async function loadMangas() {
    const list = $("manga-list");
    list.innerHTML = '<div class="loading">Chargement des mangas...</div>';

    try {
        const resp = await fetch("/api/japscan/list");
        const data = await resp.json();

        if (!data.ok) {
            list.innerHTML = `<div class="loading" style="color: #ff6b6b;">Erreur: ${data.error}</div>`;
            return;
        }

        state.mangas = data.mangas;
        renderMangas();
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
            body: JSON.stringify({ url: selectedManga.url })
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
    list.innerHTML = state.chapters.map((ch, i) => `
        <div class="chapter-item">
            <input type="checkbox" value="${i}" class="chapter-checkbox" checked>
            <div class="chapter-item-label">
                <div class="chapter-item-name">${ch.title}</div>
            </div>
        </div>
    `).join("");

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
    const form = $("metadata-form");

    // Divise les chapitres en tomes (estimation: 10 chapitres par tome)
    const chaptersPerTome = 10;
    let html = '';

    for (let i = 0; i < selectedChapters.length; i += chaptersPerTome) {
        const tomeNum = Math.floor(i / chaptersPerTome) + 1;
        const chaptersInTome = selectedChapters.slice(i, i + chaptersPerTome).length;

        html += `
            <div class="tome-group">
                <h3>Tome ${tomeNum}</h3>
                <div class="field">
                    <label>Chapitres dans ce tome</label>
                    <input type="number" class="tome-chapters" value="${chaptersInTome}" min="1">
                </div>
                <small style="color: var(--muted);">
                    Chapitres: ${i + 1} - ${Math.min(i + chaptersPerTome, selectedChapters.length)}
                </small>
            </div>
        `;
    }

    form.innerHTML = html;

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

async function loadJobs() {
    const list = $("jobs-list");

    try {
        // En attente d'implémentation côté serveur
        list.innerHTML = '<p style="color: var(--muted);">Aucun téléchargement en cours.</p>';
    } catch (e) {
        list.innerHTML = `<p style="color: #ff6b6b;">Erreur: ${e.message}</p>`;
    }
}

// ============================================================================
// Initialisation
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
    loadMangas();
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
