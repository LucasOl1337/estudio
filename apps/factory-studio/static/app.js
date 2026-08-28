const state = {
  targets: [],
  library: { purposes: [], categories: [], cases: [], templates: [] },
  mode: "full-library",
  provider: "codex",
  purpose: "",
  category: "",
  selected: new Set(),
  running: false,
  startedAt: 0,
  current: "",
  okCount: 0,
};

const $ = (id) => document.getElementById(id);

async function boot() {
  const meta = await (await fetch("/api/meta")).json();
  $("meta-line").textContent = `${meta.cases} casos · ${meta.templates} templates · ${meta.purposes} propósitos`;
  state.library = await (await fetch("/api/library")).json();
  renderPurposes();
  renderCategories();
  await reloadTargets();
  const prefer = ["LUCAS", "JULIANA", "NETALLY"];
  const pick =
    prefer.map((n) => state.targets.find((t) => t.name.toUpperCase() === n)).find(Boolean) ||
    state.targets.find((t) => t.photos.length) ||
    state.targets[0];
  if (pick) $("target").value = pick.name;
  renderPhotos();
  renderCases();
  connectLog();
  pollStatus();
  maybeGallery();
}

async function reloadTargets() {
  state.targets = await (await fetch("/api/targets")).json();
  const sel = $("target");
  const current = sel.value;
  sel.innerHTML = state.targets.map((t) => `<option value="${esc(t.name)}">${esc(t.name)} · ${t.photos.length} fotos</option>`).join("");
  if (current && state.targets.some((t) => t.name === current)) sel.value = current;
  renderArchives();
}

function renderArchives() {
  const all = $("archives-all")?.checked !== false;
  const current = $("target").value;
  const groups = [];
  for (const t of state.targets) {
    if (!all && t.name !== current) continue;
    const runs = (t.runs || [])
      .filter((r) => r.images || r.missing)
      .sort((a, b) => (b.updated || "").localeCompare(a.updated || "") || b.images - a.images);
    if (!runs.length) continue;
    groups.push({ target: t.name, runs });
  }
  const box = $("archives");
  if (!groups.length) {
    box.innerHTML = `<span class="empty">Nenhuma leva com imagem ainda.</span>`;
    return;
  }
  box.innerHTML = groups
    .map((g) => {
      const rows = g.runs
        .map((r) => {
          const broken = r.missing && !r.images;
          const meta = [
            r.updated ? r.updated.replace(" ", " · ") : "",
            r.images ? `${r.images} imagens` : "",
            r.grok ? `${r.grok} grok` : "",
            r.codex ? `${r.codex} codex` : "",
            r.missing ? `${r.missing} sem arquivo` : "",
          ]
            .filter(Boolean)
            .join(" · ");
          const btn = broken
            ? `<span class="dead">não dá para abrir</span>`
            : `<button type="button" class="ghost" data-open-target="${esc(g.target)}" data-open-focus="${esc(r.focus)}">Abrir</button>`;
          return `<div class="archive ${broken ? "is-dead" : ""}">
            <span class="run">${esc(r.focus)}</span>
            <span class="n">${esc(meta)}</span>
            ${btn}
          </div>`;
        })
        .join("");
      return `<div class="archive-group">
        <h3>${esc(g.target)} <small>${g.runs.length} levas</small></h3>
        ${rows}
      </div>`;
    })
    .join("");
}

function currentTarget() {
  return state.targets.find((t) => t.name === $("target").value);
}

function renderPhotos() {
  const t = currentTarget();
  const box = $("photos");
  if (!t || !t.photos.length) {
    box.innerHTML = `<span class="empty">Nenhuma foto válida neste alvo. (Arquivos quebrados ou vazios são ignorados.)</span>`;
    return;
  }
  box.innerHTML = t.photos
    .map(
      (p) =>
        `<img class="ph" src="/api/photo/${encodeURIComponent(t.name)}/${p.rel.split("/").map(encodeURIComponent).join("/")}" alt="${esc(p.rel)}" title="${esc(p.rel)}">`
    )
    .join("");
}

function renderPurposes() {
  $("purposes").innerHTML = `<button type="button" class="chip ${state.purpose === "" ? "on" : ""}" data-id="">Todos</button>` +
    state.library.purposes
      .map(
        (p) =>
          `<button type="button" class="chip ${state.purpose === p.id ? "on" : ""}" data-id="${esc(p.id)}">${esc(p.label_pt)} ${p.count}</button>`
      )
      .join("");
}

function renderCategories() {
  $("categories").innerHTML = `<button type="button" class="chip ${state.category === "" ? "on" : ""}" data-id="">Todas</button>` +
    state.library.categories
      .map(
        (c) =>
          `<button type="button" class="chip ${state.category === c.name ? "on" : ""}" data-id="${esc(c.name)}">${esc(c.name)} ${c.count}</button>`
      )
      .join("");
}

function filteredCases() {
  const q = ($("search")?.value || "").trim().toLowerCase();
  return state.library.cases.filter((c) => {
    if (state.purpose && c.purpose !== state.purpose) return false;
    if (state.category && c.category !== state.category) return false;
    if (q && !(`${c.id} ${c.title_pt}`.toLowerCase().includes(q))) return false;
    return true;
  });
}

function renderCases() {
  const wrap = $("cases-wrap");
  wrap.hidden = state.mode !== "selected-library";
  updateHint();
  if (wrap.hidden) return;
  const list = filteredCases();
  $("sel-count").textContent = String(state.selected.size);
  $("cases").innerHTML = list
    .slice(0, 180)
    .map((c) => {
      const on = state.selected.has(c.id) ? "on" : "";
      const img = c.has_thumb
        ? `<img loading="lazy" src="/api/thumbs/${c.id}" alt="">`
        : `<img alt="">`;
      return `<button type="button" class="case ${on}" data-id="${c.id}"><span>${img}</span><span class="meta"><span class="cid">${c.id}</span><span class="t">${esc(c.title_pt)}</span></span></button>`;
    })
    .join("");
}

function updateHint() {
  if (state.mode === "full-library") {
    $("sel-hint").textContent = "Biblioteca inteira — não precisa marcar casos.";
  } else if (state.mode === "full-templates") {
    $("sel-hint").textContent = `${state.library.templates.length} templates da fila.`;
  } else {
    $("sel-hint").textContent = `Marcados ${state.selected.size} de no máximo 20. Filtro mostra ${filteredCases().length}.`;
  }
}

$("modes").addEventListener("click", (e) => {
  const btn = e.target.closest(".mode");
  if (!btn) return;
  state.mode = btn.dataset.mode;
  [...$("modes").children].forEach((b) => b.classList.toggle("on", b === btn));
  renderCases();
});

$("purposes").addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  state.purpose = btn.dataset.id;
  renderPurposes();
  renderCases();
});

$("categories").addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  state.category = btn.dataset.id;
  renderCategories();
  renderCases();
});

$("cases").addEventListener("click", (e) => {
  const btn = e.target.closest(".case");
  if (!btn) return;
  const id = Number(btn.dataset.id);
  if (state.selected.has(id)) state.selected.delete(id);
  else {
    if (state.selected.size >= 20) {
      alert("No máximo 20 casos por disparo.");
      return;
    }
    state.selected.add(id);
  }
  renderCases();
});

$("search").addEventListener("input", renderCases);
$("target").addEventListener("change", () => {
  renderPhotos();
  maybeGallery();
  renderArchives();
});

$("archives-all")?.addEventListener("change", renderArchives);

$("archives").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-open-target]");
  if (!btn) return;
  const target = btn.dataset.openTarget;
  const focus = btn.dataset.openFocus;
  $("target").value = target;
  $("focus").value = focus;
  renderPhotos();
  maybeGallery();
  openGallery(target, focus);
});

$("providers").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  state.provider = btn.dataset.p;
  [...$("providers").children].forEach((b) => b.classList.toggle("on", b === btn));
});

$("create-btn").addEventListener("click", async () => {
  const name = $("new-name").value.trim();
  if (!name) return;
  const fd = new FormData();
  fd.append("name", name);
  const res = await fetch("/api/targets", { method: "POST", body: fd });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    alert(typeof body === "string" ? body : body.error || await res.text());
    return;
  }
  $("new-name").value = "";
  await reloadTargets();
  $("target").value = body.name;
  renderPhotos();
});

$("photo-input").addEventListener("change", async (e) => {
  const files = [...e.target.files];
  if (!files.length) return;
  const name = $("target").value;
  if (!name) {
    alert("Cria ou escolhe um alvo antes.");
    return;
  }
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  const res = await fetch(`/api/targets/${encodeURIComponent(name)}/photos`, { method: "POST", body: fd });
  if (!res.ok) {
    alert(await res.text());
    return;
  }
  e.target.value = "";
  await reloadTargets();
  $("target").value = name;
  renderPhotos();
});

$("go").addEventListener("click", () => {
  const payload = {
    target: $("target").value,
    mode: state.mode,
    focus: $("focus").value.trim() || "estudio-v1",
    providers: state.provider,
    copy_language: $("lang").value,
    dry_run: $("dry").checked,
    case_ids: [...state.selected],
  };
  setBusy(true, "Disparando… média 1–2 min por imagem.");
  fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then(async (res) => {
    if (!res.ok) {
      setBusy(false, await res.text());
      return;
    }
    appendLog(">> disparado");
  }).catch((err) => setBusy(false, String(err)));
});

$("stop").addEventListener("click", () => {
  $("stop").disabled = true;
  $("stop").textContent = "Parando…";
  setLive("Parando a fila…");
  fetch("/api/run/stop", { method: "POST" }).finally(() => {
    $("stop").textContent = "Parar";
    $("stop").disabled = false;
  });
});

function openGallery(target, focus) {
  fetch(`/api/runs/${encodeURIComponent(target)}/${encodeURIComponent(focus)}/open`, { method: "POST" }).then(
    async (res) => {
      if (!res.ok) setLive(await res.text());
    }
  );
}

$("open-gal").addEventListener("click", () => {
  const t = $("target").value;
  const focus = $("focus").value.trim() || "estudio-v1";
  if (!t) return;
  $("open-gal").disabled = true;
  openGallery(t, focus);
  setTimeout(() => {
    $("open-gal").disabled = false;
  }, 400);
});

$("theme-btn").addEventListener("click", () => {
  const html = document.documentElement;
  const next = html.getAttribute("data-theme") === "dark" ? "light" : "dark";
  html.setAttribute("data-theme", next);
  $("theme-btn").textContent = next === "dark" ? "claro" : "escuro";
});

function connectLog() {
  const es = new EventSource("/api/run/log");
  es.onmessage = (ev) => {
    const line = ev.data;
    appendLog(line);
    const gen = line.match(/GEN (\S+)/);
    if (gen) {
      state.current = gen[1];
      setLive(liveText());
    }
    if (/^\s*OK /.test(line) || line.includes(" bytes ")) {
      state.okCount += 1;
      maybeGallery();
    }
    if (/SKIP |terminou|saiu com|parado/.test(line)) maybeGallery();
  };
}

function appendLog(line) {
  const pre = $("log");
  if (pre.textContent.startsWith("Aguardando")) pre.textContent = "";
  pre.textContent += line + "\n";
  pre.scrollTop = pre.scrollHeight;
}

function setBusy(on, message) {
  state.running = on;
  if (on) {
    state.startedAt = Date.now();
    state.okCount = 0;
    state.current = "";
  }
  $("go").disabled = on;
  $("go").textContent = on ? "Gerando…" : "Gerar";
  setLive(message);
  $("live").classList.toggle("busy", on);
}

function setLive(message) {
  $("live").textContent = message;
}

function liveText() {
  const elapsed = state.startedAt ? Math.round((Date.now() - state.startedAt) / 1000) : 0;
  const now = state.current ? ` agora ${state.current}` : "";
  const done = state.okCount ? ` · ${state.okCount} prontas` : "";
  return `Rodando ${fmt(elapsed)}${now}${done}. Média 1–2 min por imagem.`;
}

function fmt(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m ? `${m}m${String(s).padStart(2, "0")}s` : `${s}s`;
}

async function pollStatus() {
  try {
    const s = await (await fetch("/api/run/status")).json();
    if (s.running) {
      if (!state.running) setBusy(true, liveText());
      setLive(liveText());
      maybeGallery();
      if (Date.now() - (state.lastArchive || 0) > 5000) {
        state.lastArchive = Date.now();
        reloadTargets();
      }
    } else if (state.running) {
      setBusy(false, state.okCount ? `${state.okCount} imagens na galeria.` : "Fila parada.");
      maybeGallery();
      reloadTargets();
    }
  } catch (_) {}
  setTimeout(pollStatus, 1000);
}

async function maybeGallery() {
  const t = $("target").value;
  const focus = $("focus").value.trim() || "estudio-v1";
  if (!t) return;
  const res = await fetch(`/api/runs/${encodeURIComponent(t)}/${encodeURIComponent(focus)}`);
  if (!res.ok) return;
  const items = await res.json();
  if (!items.length) {
    $("gallery").innerHTML = `<span class="empty">Nada gerado nesta leva ainda.</span>`;
    return;
  }
  $("gallery").innerHTML = items
    .map(
      (it) =>
        `<a href="${esc(it.url)}" target="_blank"><img loading="lazy" src="${esc(it.url)}" alt=""><span>${esc(it.provider)} · ${esc(it.file)}</span></a>`
    )
    .join("");
}

function esc(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

boot();
