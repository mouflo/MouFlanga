/* MouFlanga - Interface utilisateur */

const $ = id => document.getElementById(id);
const views = {
    list: $('manga-list-view'),
    detail: $('manga-detail-view'),
    reader: $('reader-view')
};

let currentManga = null;
let currentChapter = null;
let currentPage = 0;

// Afficher une vue
function showView(name) {
    Object.values(views).forEach(v => v.style.display = 'none');
    if (views[name]) views[name].style.display = 'block';
}

// Charger la liste des mangas
async function loadMangaList() {
    const r = await fetch('/api/manga/list');
    if (!r.ok) return;

    const data = await r.json();
    const grid = $('manga-grid');
    grid.innerHTML = '';

    data.mangas.forEach(manga => {
        const card = document.createElement('div');
        card.className = 'manga-card';
        card.onclick = () => showMangaDetail(manga.id);

        card.innerHTML = `
            <img src="${manga.cover}" alt="${manga.title}" onerror="this.src='/placeholder.svg'">
            <div class="manga-card-info">
                <div class="manga-card-title">${manga.title}</div>
                <div class="manga-card-meta">${manga.chapters} chapitres</div>
                <div class="manga-card-meta">${manga.size_mb} MB</div>
            </div>
        `;

        grid.appendChild(card);
    });
}

// Afficher le détail d'un manga
async function showMangaDetail(mangaId) {
    currentManga = mangaId;
    const r = await fetch(`/api/manga/${mangaId}/chapters`);
    if (!r.ok) return;

    const data = await r.json();
    $('manga-title').textContent = mangaId;

    const list = $('chapters-list');
    list.innerHTML = '';

    data.chapters.forEach((ch, idx) => {
        const item = document.createElement('div');
        item.className = 'chapter-item';
        item.onclick = () => readChapter(ch.path);

        item.innerHTML = `
            <span>${ch.name}</span>
            <span class="meta">${ch.size_mb} MB</span>
        `;

        list.appendChild(item);
    });

    showView('detail');
}

// Lire un chapitre
async function readChapter(chapterPath) {
    currentChapter = chapterPath;
    currentPage = 0;

    const r = await fetch(`/api/chapter/pages/${chapterPath}`);
    if (!r.ok) return;

    const data = await r.json();
    showView('reader');
    loadPage(0, data.count);
}

// Charger une page
async function loadPage(pageNum, total) {
    currentPage = pageNum;

    const r = await fetch(`/api/chapter/page/${currentChapter}?page=${pageNum}`);
    if (!r.ok) return;

    const pagesDiv = $('reader-pages');
    pagesDiv.innerHTML = `<img src="/api/chapter/page/${currentChapter}?page=${pageNum}" alt="Page ${pageNum + 1}">`;

    $('page-counter').textContent = `Page ${pageNum + 1}/${total}`;

    // Mettre à jour la progression
    await fetch('/api/settings/progress', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            manga: currentManga,
            chapter: currentChapter,
            page: pageNum
        })
    });
}

// Navigation des pages
document.addEventListener('DOMContentLoaded', () => {
    if ($('prev-page')) {
        $('prev-page').addEventListener('click', () => {
            if (currentPage > 0) loadPage(currentPage - 1);
        });
    }

    if ($('next-page')) {
        $('next-page').addEventListener('click', () => {
            if (currentPage < 99) loadPage(currentPage + 1);
        });
    }

    if ($('reader-back')) {
        $('reader-back').addEventListener('click', () => {
            showView('detail');
        });
    }

    // Charger la liste au démarrage
    loadMangaList();
    showView('list');
});
