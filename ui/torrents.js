/* MouFlanga · onglet 🧲 Torrents de la page Télécharger (Prowlarr → qBittorrent → import automatique) */
(function () {
    const $ = id => document.getElementById(id);
    const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
    const taille = o => o >= 1e9 ? (o / 1073741824).toFixed(1).replace(".", ",") + " Go" : Math.round(o / 1048576) + " Mo";
    let res = [], series = [], minuteur = null, bib = null;
    const params = new URLSearchParams(location.search);
    const ETATS = {telechargement: "⬇️ Téléchargement", import: "📦 Import", fini: "✅ Importé", erreur: "⚠️ Erreur", a_valider: "❓ À valider", rate: "⛔ Raté"};

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
            <span>${ETATS[j.etat] || j.etat}${j.etat === "telechargement" ? " " + (j.progression || 0) + " %" : ""} · ${esc(j.message || "")}</span>
            ${j.page && window.MouPageTracker ? `<div class="pt-liens">${MouPageTracker.lien(j.page)}</div>` : ""}</div>${j.etat === "a_valider" ? `<div class="tor-choix">
                <button type="button" class="mou-btn" data-decider="${esc(j.id)}" data-remplacer="1">Remplacer tous les tomes</button>
                <button type="button" class="mou-btn" data-decider="${esc(j.id)}" data-remplacer="0">Ajouter seulement les manquants</button>
                <button type="button" class="mou-btn ghost" data-decider="${esc(j.id)}" data-remplacer="ignorer">Ne rien faire</button>
                <label class="tor-toujours"><input type="checkbox" data-toujours="${esc(j.id)}"> Toujours faire ce choix pour « ${esc(j.serie)} »</label></div>` : ""}</div>`).join("")
            : '<p class="sub">Aucun téléchargement pour l\'instant.</p>';
        clearTimeout(minuteur);
        if (l.some(j => j.etat === "telechargement" || j.etat === "import")) minuteur = setTimeout(etat, 15000);
    }
    async function chercher() {
        const q = $("tor-q").value.trim();
        if (q.length < 2) return;
        $("tor-res").innerHTML = '<div class="loading">⏳ Recherche dans Prowlarr… (jusqu\'à une minute)</div>';
        const r = await (await fetch("/api/torrents/chercher?q=" + encodeURIComponent(q) + ($("tor-tout").checked ? "&tout=1" : "") + (params.get("serie") ? "&serie=" + encodeURIComponent(params.get("serie")) : ""))).json();
        if (r.error) { $("tor-res").innerHTML = `<div class="loading" style="color:#ff6b6b">${esc(r.error)}</div>`; return; }
        res = r.resultats || [];
        bib = r.bibliotheque || null;
        afficher();
    }
    // Les index (data-i, data-choisir…) restent ceux de `res` : les refusés, masqués par défaut, gardent leur place
    function afficher() {
        const montrer = $("tor-refuses").checked, nb = res.filter(x => x.rejet).length;
        $("tor-refuses-n").textContent = nb ? " (" + nb + ")" : "";
        $("tor-refuses-bloc").hidden = !nb;
        const liste = res.map((x, i) => [x, i]).filter(([x]) => montrer || !x.rejet);
        const plage = a => { const o = []; for (let i = 0; i < a.length; i++) { let j = i; while (j + 1 < a.length && a[j + 1] === a[j] + 1) j++; o.push(i === j ? "T" + a[i] : "T" + a[i] + "–T" + a[j]); i = j; } return o.join(", "); };
        const compare = x => !x.tomes ? "" : x.deja ? `<small class="tor-deja">✅ Déjà dans ta bibliothèque (${plage(x.tomes)})</small>` : `<small class="tor-nouveau">🆕 Apporte ${plage(x.nouveaux)}</small>`;
        $("tor-res").innerHTML = (bib ? `<div class="note">Comparé à ta bibliothèque : « ${esc(bib.serie)} » (${bib.possedes} tomes).</div>` : "") + (liste.length ? liste.map(([x, i]) => `<div class="tor-res${x.rejet ? " refuse" : ""}${x.deja ? " deja" : ""}" data-i="${i}">
            <div class="tor-info"><b>${x.score ? `<em class="tor-score">${x.assez_bon ? "⭐ " : ""}${x.score > 0 ? "+" : ""}${x.score}</em> ` : ""}${esc(x.titre)}</b>
            <small>${taille(x.taille)} · <span class="${x.sources ? "" : "tor-zero"}">${x.sources} source${x.sources > 1 ? "s" : ""}</span> · ${esc(x.indexeur)}${x.date ? " · " + esc(x.date) : ""}</small>
            ${compare(x)}
            ${x.rejet ? `<small class="tor-raison">❌ Refusé par ton profil : ${esc(x.rejet)}</small>` : ""}
            <span class="tor-badges">${x.badges.map(b => `<i>${esc(b)}</i>`).join("")}${(x.formats || []).map(f => `<i class="fmt">${esc(f)}</i>`).join("")}</span></div>
            <div class="tor-act">${x.page ? `<a class="mou-btn ghost small" href="${esc(x.page)}" target="_blank" rel="noopener noreferrer" title="Voir sur le site">🔗</a>
            <button type="button" class="mou-btn ghost small" data-lire-page="${i}" title="Lire la présentation et le NFO sur le tracker">📄</button>` : ""}
            <button type="button" class="mou-btn small" data-choisir="${i}">⬇️</button></div></div>`).join("")
            : '<div class="loading">' + (res.length ? "Tout est refusé par ton profil : coche « Montrer les refusés »." : "Rien trouvé. Essaie un autre nom, ou coche « toutes les catégories ».") + "</div>");
    }
    document.addEventListener("click", async e => {
        const lp = e.target.closest("[data-lire-page]");
        if (lp && window.MouPageTracker) {
            const x = res[+lp.dataset.lirePage];
            MouPageTracker.ouvrir(lp.closest(".tor-res"), {page: x.page, titre: x.titre, serie: params.get("serie") || ""});
            return;
        }
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
            const envoyer = (nom, confirme) => fetch("/api/torrents", {method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({resultat: x.id, lien: x.lien || "", titre: x.titre, page: x.page || "", serie: nom, confirme, proposition: params.get("proposition") || ""})}).then(q => q.json());
            let r = await envoyer(serie, false);
            if (!r.ok && r.proche) {          // nom proche d'une série déjà là : la rejoindre, ou garder le nom tapé
                r = await envoyer(await MouConfirm(r.error + "\n\nRanger dans « " + r.proche + " » ou garder « " + serie + " » (nouvelle série) ?", {ok: "Ranger dans « " + r.proche + " »", annuler: "Garder mon nom"}) ? r.proche : serie, true);
            }
            env.parentNode.innerHTML = `<div class="note ${r.ok ? "ok" : "err"}">${esc(r.message || r.error)}</div>`;
            etat();
            return;
        }
        const dec = e.target.closest("[data-decider]");
        if (dec) {
            const choix = dec.dataset.remplacer, bloc = dec.closest(".tor-choix");
            if (choix === "1" && !await MouConfirm("Les tomes actuels iront à la corbeille (30 jours). Continuer ?")) return;
            bloc.querySelectorAll("button").forEach(b => b.disabled = true);
            const remplacer = choix === "ignorer" ? "ignorer" : choix === "1";
            const r = await (await fetch("/api/torrents/decider", {method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({id: dec.dataset.decider, remplacer, toujours: !!(bloc.querySelector("[data-toujours]") || {}).checked})})).json();
            bloc.innerHTML = `<div class="note ${r.ok ? "ok" : "err"}">${esc(r.message || r.error)}</div>`;
            etat();
        }
    });
    // 🤖 Série complétée automatiquement : on montre d'abord ce qui serait téléchargé, puis on lance après confirmation
    async function auto(lancer) {
        const serie = $("tor-auto-serie").value.trim() || params.get("serie") || "";
        if (!serie) { $("tor-auto-res").innerHTML = '<div class="note err">Écris le nom de la série.</div>'; return; }
        $("tor-auto-res").innerHTML = '<div class="loading">⏳ Recherche dans Prowlarr… (jusqu\'à une minute)</div>';
        const r = await (await fetch("/api/torrents/auto", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({serie, lancer})})).json();
        if (r.error && !r.torrents) { $("tor-auto-res").innerHTML = `<div class="note err">${esc(r.error)}</div>`; return; }
        const l = r.torrents || [];
        const entete = `<div class="note ${r.ok ? "ok" : "err"}">${esc(r.message || r.error || "")}${r.profil ? ` Profil : « ${esc(r.profil)} ».` : " Aucun profil pour cette série."}
            ${r.attendus ? ` ${r.possedes} tome(s) sur ${r.attendus} déjà là.` : ""}${(r.manquants || []).length ? ` Rien ne couvre : T${r.manquants.join(", T")}.` : ""}</div>`;
        $("tor-auto-res").innerHTML = entete + l.map(x => `<div class="tor-res"><div class="tor-info"><b>${x.type === "meilleur" ? "⬆️ " : "🆕 "}${x.score ? `<em class="tor-score">${x.score > 0 ? "+" : ""}${x.score}</em> ` : ""}${esc(x.titre)}</b>
            <small>${x.type === "meilleur" ? "Remplace" : "Ajoute"} T${x.tomes.join(", T")} · ${taille(x.taille)} · ${x.sources} source${x.sources > 1 ? "s" : ""} · ${esc(x.indexeur)}</small>
            <span class="tor-badges">${(x.formats || []).map(f => `<i class="fmt">${esc(f)}</i>`).join("")}</span></div></div>`).join("")
            + (l.length && !lancer ? `<div class="tor-envoi"><button type="button" class="mou-btn" id="tor-auto-ok">✅ Lancer ces ${l.length} téléchargement(s)</button></div>` : "");
        if (l.length && !lancer) $("tor-auto-ok").addEventListener("click", async () => { if (await MouConfirm("Envoyer " + l.length + " torrent(s) à qBittorrent pour « " + serie + " » ? Seuls les torrents marqués ⬆️ remplacent des tomes (scan → officiel) ; les anciens vont à la corbeille.")) { await auto(true); etat(); } });
    }
    $("tor-auto-go").addEventListener("click", () => auto(false));
    $("tor-auto-serie").value = params.get("serie") || "";
    $("tor-go").addEventListener("click", chercher);
    $("tor-refuses").addEventListener("change", afficher);
    $("tor-q").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); chercher(); } });
    document.querySelector('.tab[data-tab="torrents"]').addEventListener("click", etat);
    // Lien direct : /telecharger?torrent=<recherche>
    const q = new URLSearchParams(location.search).get("torrent");
    if (q) { document.querySelector('.tab[data-tab="torrents"]').click(); $("tor-q").value = q; chercher(); }
})();
