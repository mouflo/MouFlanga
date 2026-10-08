/* MouFlanga · onglet 🧲 Torrents de la page Télécharger (Prowlarr → qBittorrent → import automatique) */
(function () {
    const $ = id => document.getElementById(id);
    const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
    const taille = o => o >= 1e9 ? (o / 1073741824).toFixed(1).replace(".", ",") + " Go" : Math.round(o / 1048576) + " Mo";
    let res = [], series = [], minuteur = null;
    const params = new URLSearchParams(location.search);
    const ETATS = {telechargement: "⬇️ Téléchargement", import: "📦 Import", fini: "✅ Importé", erreur: "⚠️ Erreur", a_valider: "❓ À valider"};

    // Nom de série proposé : texte cherché sans « intégrale », « FR », « T01-T20 »… ; série existante si elle correspond
    function nomPropose(q) {
        const t = q.replace(/\b(int[ée]grale|complete|french|vf|fr|cbz|digital|scan|t\d+\s*-\s*t?\d+|tomes?\s*\d+.*)\b/gi, " ").replace(/\s+/g, " ").trim();
        const cle = s => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");
        return series.find(s => cle(s) === cle(t)) || t.replace(/\b\w/g, c => c.toUpperCase());
    }
    async function etat() {
        const r = await (await fetch("/api/torrents")).json();
        $("tor-config").hidden = !!r.configure;
        series = r.series || [];
        $("tor-series").innerHTML = series.map(s => `<option value="${esc(s)}">`).join("");
        const l = r.torrents || [];
        $("tor-liste").innerHTML = l.length ? l.map(j => `<div class="tor-ligne ${j.etat}"><div class="tor-info"><b>${esc(j.serie)}</b><small>${esc(j.titre)}</small>
            <span>${ETATS[j.etat] || j.etat}${j.etat === "telechargement" ? " " + (j.progression || 0) + " %" : ""} · ${esc(j.message || "")}</span></div>${j.etat === "a_valider" ? `<div class="tor-choix">
                <button type="button" class="mou-btn" data-decider="${esc(j.id)}" data-remplacer="1">Remplacer tous les tomes</button>
                <button type="button" class="mou-btn" data-decider="${esc(j.id)}" data-remplacer="0">Ajouter seulement les manquants</button></div>` : ""}</div>`).join("")
            : '<p class="sub">Aucun téléchargement pour l\'instant.</p>';
        clearTimeout(minuteur);
        if (l.some(j => j.etat === "telechargement" || j.etat === "import")) minuteur = setTimeout(etat, 15000);
    }
    async function chercher() {
        const q = $("tor-q").value.trim();
        if (q.length < 2) return;
        $("tor-res").innerHTML = '<div class="loading">⏳ Recherche dans Prowlarr… (jusqu\'à une minute)</div>';
        const r = await (await fetch("/api/torrents/chercher?q=" + encodeURIComponent(q) + ($("tor-tout").checked ? "&tout=1" : ""))).json();
        if (r.error) { $("tor-res").innerHTML = `<div class="loading" style="color:#ff6b6b">${esc(r.error)}</div>`; return; }
        res = r.resultats || [];
        $("tor-res").innerHTML = res.length ? res.map((x, i) => `<div class="tor-res" data-i="${i}">
            <div class="tor-info"><b>${esc(x.titre)}</b>
            <small>${taille(x.taille)} · ${x.sources} source${x.sources > 1 ? "s" : ""} · ${esc(x.indexeur)}${x.date ? " · " + esc(x.date) : ""}</small>
            <span class="tor-badges">${x.badges.map(b => `<i>${esc(b)}</i>`).join("")}</span></div>
            <div class="tor-act">${x.page ? `<a class="mou-btn ghost small" href="${esc(x.page)}" target="_blank" rel="noopener" title="Voir sur le site">🔗</a>` : ""}
            <button type="button" class="mou-btn small" data-choisir="${i}">⬇️</button></div></div>`).join("")
            : '<div class="loading">Rien trouvé. Essaie un autre nom, ou coche « toutes les catégories ».</div>';
    }
    document.addEventListener("click", async e => {
        const c = e.target.closest("[data-choisir]");
        if (c) {
            const bloc = c.closest(".tor-res"), i = +c.dataset.choisir;
            if (bloc.querySelector(".tor-envoi")) return;
            bloc.insertAdjacentHTML("beforeend", `<div class="tor-envoi"><label>Ranger dans la série :</label>
                <input type="text" list="tor-series" value="${esc(params.get("serie") || nomPropose($("tor-q").value))}" autocapitalize="words">
                <button type="button" class="mou-btn" data-envoyer="${i}">Télécharger</button></div>`);
            return;
        }
        const env = e.target.closest("[data-envoyer]");
        if (env) {
            const x = res[+env.dataset.envoyer], serie = env.parentNode.querySelector('input[type="text"]').value.trim();
            if (!serie) return;
            env.disabled = true;
            const r = await (await fetch("/api/torrents", {method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({lien: x.lien, titre: x.titre, serie, proposition: params.get("proposition") || ""})})).json();
            env.parentNode.innerHTML = `<div class="note ${r.ok ? "ok" : "err"}">${esc(r.message || r.error)}</div>`;
            etat();
            return;
        }
        const dec = e.target.closest("[data-decider]");
        if (dec) {
            const remplacer = dec.dataset.remplacer === "1", bloc = dec.closest(".tor-choix");
            if (remplacer && !confirm("Les tomes actuels iront à la corbeille (30 jours). Continuer ?")) return;
            bloc.querySelectorAll("button").forEach(b => b.disabled = true);
            const r = await (await fetch("/api/torrents/decider", {method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({id: dec.dataset.decider, remplacer})})).json();
            bloc.innerHTML = `<div class="note ${r.ok ? "ok" : "err"}">${esc(r.message || r.error)}</div>`;
            etat();
        }
    });
    $("tor-go").addEventListener("click", chercher);
    $("tor-q").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); chercher(); } });
    document.querySelector('.tab[data-tab="torrents"]').addEventListener("click", etat);
    // Lien direct : /telecharger?torrent=<recherche>
    const q = new URLSearchParams(location.search).get("torrent");
    if (q) { document.querySelector('.tab[data-tab="torrents"]').click(); $("tor-q").value = q; chercher(); }
})();
