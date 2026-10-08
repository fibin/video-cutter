"use strict";

// ======================================================================
// Translations
// ======================================================================
// Every visible text goes through t(). Elements remember their message key
// (data-i18n + data-i18n-params) so switching the language re-renders them.

const I18N = { dict: {}, lang: "en" };

function pluralForm(n) {
  if (I18N.lang !== "uk") return n === 1 ? "one" : "many";
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return "one";
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return "few";
  return "many";
}

// A param may itself be translatable: {t: key, p: params} or {plural: base, n: count}.
function resolveParam(value) {
  if (value && typeof value === "object") {
    if (value.plural) return t(`${value.plural}_${pluralForm(value.n)}`, { n: value.n });
    if (value.t) return t(value.t, value.p || {});
  }
  return value;
}

function t(key, params = {}) {
  const table = I18N.dict[I18N.lang] || {};
  const text = table[key] ?? (I18N.dict.en || {})[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (m, name) => (params[name] !== undefined ? resolveParam(params[name]) : m));
}

function setT(el, key, params = {}) {
  el.dataset.i18n = key;
  el.dataset.i18nParams = JSON.stringify(params);
  el.textContent = t(key, params);
}

function applyI18n(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n, el.dataset.i18nParams ? JSON.parse(el.dataset.i18nParams) : {});
  });
  root.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
  root.querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
  root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
}

function setLang(lang) {
  I18N.lang = I18N.dict[lang] ? lang : "en";
  try { localStorage.setItem("vc-lang", I18N.lang); } catch (_) { /* storage may be blocked */ }
  document.documentElement.lang = I18N.lang;
  document.querySelectorAll(".lang button").forEach((b) => b.classList.toggle("active", b.dataset.lang === I18N.lang));
  applyI18n();
}

// ======================================================================
// Small helpers
// ======================================================================

const $ = (sel, root = document) => root.querySelector(sel);
const clone = (id) => document.getElementById(id).content.firstElementChild.cloneNode(true);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function parseTime(text) {
  const value = String(text).trim().replace(",", ".");
  if (value === "") return null;
  const parts = value.split(":");
  if (parts.length > 3 || parts.some((p) => p === "" || isNaN(Number(p)))) return NaN;
  return parts.reduce((acc, p) => acc * 60 + Number(p), 0);
}

function formatTime(seconds) {
  const ms = Math.round(seconds * 1000);
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const rest = ms % 1000;
  let out = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  if (rest) out += "." + String(rest).padStart(3, "0").replace(/0+$/, "");
  return h ? `${h}:${out}` : out;
}

const folderOf = (path) => path.replace(/[\\/][^\\/]*$/, "");

// Errors from the server look like {key, params, detail}; anything else is shown as text.
class AppError extends Error {
  constructor(payload) {
    super(payload.text || payload.key);
    this.payload = payload;
  }
}

function errorPayload(err) {
  if (err && err.payload) return err.payload;
  return { key: "unexpected", params: {}, detail: String((err && err.message) || err) };
}

function showError(el, err) {
  el.innerHTML = "";
  if (!err) { el.classList.add("hidden"); return; }
  const payload = errorPayload(err);
  const line = document.createElement("div");
  setT(line, payload.key, payload.params || {});
  el.appendChild(line);
  if (payload.detail) {
    const pre = document.createElement("pre");
    pre.textContent = payload.detail;
    el.appendChild(pre);
  }
  el.classList.remove("hidden");
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new AppError(data.error || { key: "server_error", params: { status: res.status } });
  return data;
}

async function pollJob(jobId, onUpdate) {
  for (;;) {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) throw new AppError({ key: "job_lost" });
    const job = await res.json();
    onUpdate(job);
    if (job.state === "done") return job;
    if (job.state === "error") throw new AppError(job.error || { key: "unexpected" });
    await sleep(500);
  }
}

// ---------- progress bar ----------

function makeProgress(slot) {
  const block = clone("tpl-progress");
  slot.appendChild(block);
  const parts = { stage: $(".stage", block), pct: $(".pct", block), bar: $(".bar", block), fill: $(".fill", block), detail: $(".detail", block) };
  return {
    hide() { block.classList.add("hidden"); },
    // stage: [key, params]; details: list of [key, params]
    show(stage, percent, details = []) {
      block.classList.remove("hidden");
      setT(parts.stage, stage[0], stage[1] || {});
      const known = typeof percent === "number";
      parts.bar.classList.toggle("indeterminate", !known);
      parts.fill.style.width = known ? `${percent}%` : "";
      parts.pct.textContent = known ? `${Math.floor(percent)}%` : "";
      parts.detail.innerHTML = "";
      details.forEach(([key, params], i) => {
        if (i) parts.detail.appendChild(document.createTextNode(" · "));
        const span = document.createElement("span");
        setT(span, key, params || {});
        parts.detail.appendChild(span);
      });
    },
  };
}

// Turn a job's detail into progress-bar detail lines.
function jobDetails(job) {
  const out = [];
  const d = job.detail;
  if (d && d.key === "detail_download") {
    const speed = d.params.speed ? (d.params.speed / 1024 / 1024).toFixed(1) : null;
    if (speed && d.params.eta != null) out.push(["dl_speed_eta", { speed, eta: formatTime(d.params.eta) }]);
    else if (speed) out.push(["dl_speed", { speed }]);
  } else if (d) {
    out.push([d.key, d.params]);
  }
  return out;
}

// ---------- uploads and downloads ----------

function uploadFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded, e.total); };
    xhr.upload.onload = () => onProgress(null, null);
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (_) { /* handled below */ }
      if (xhr.status === 200) resolve(data);
      else reject(new AppError(data.error || { key: "server_error", params: { status: xhr.status } }));
    };
    xhr.onerror = () => reject(new AppError({ key: "upload_failed" }));
    xhr.send(file);
  });
}

async function downloadLink(url, onJob) {
  const job = await postJson("/api/youtube", { url });
  const done = await pollJob(job.id, onJob);
  return done.result.source;
}

// ---------- confirmation dialog ----------

function confirmDialog(titleKey, bodyKey) {
  const modal = $("#modal");
  const ok = $(".modal-ok", modal);
  const cancel = $(".modal-cancel", modal);
  setT($(".modal-title", modal), titleKey);
  setT($(".modal-body", modal), bodyKey);
  modal.classList.remove("hidden");
  ok.focus();
  return new Promise((resolve) => {
    const finish = (answer) => {
      modal.classList.add("hidden");
      ok.onclick = cancel.onclick = modal.onkeydown = null;
      resolve(answer);
    };
    ok.onclick = () => finish(true);
    cancel.onclick = () => finish(false);
    modal.onkeydown = (e) => { if (e.key === "Escape") finish(false); };
  });
}

// ---------- shared widgets ----------

function setupSubtabs(panel) {
  panel.querySelectorAll(".subtab").forEach((btn) =>
    btn.addEventListener("click", () => {
      panel.querySelectorAll(".subtab").forEach((b) => b.classList.toggle("active", b === btn));
      panel.querySelectorAll(".sub-panel").forEach((p) => p.classList.toggle("hidden", p.dataset.subPanel !== btn.dataset.sub));
    }));
}

function setupDrop(panel, onFiles) {
  const drop = $(".drop", panel);
  const input = $(".file-input", panel);
  input.addEventListener("change", () => {
    if (input.files.length) onFiles([...input.files]);
    input.value = "";
  });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    drop.classList.add("over");
  }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("over")));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer.files.length) onFiles([...e.dataTransfer.files]);
  });
}

// Reordering by dragging the ⋮⋮ handle, or with the ↑ ↓ buttons.
function makeSortable(container, onChange) {
  let dragged = null;
  container.addEventListener("mousedown", (e) => {
    const handle = e.target.closest(".handle");
    if (handle) handle.closest(".item").draggable = true;
  });
  container.addEventListener("dragstart", (e) => {
    dragged = e.target.closest(".item");
    if (!dragged || !dragged.draggable) { dragged = null; e.preventDefault(); return; }
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", "");
    dragged.classList.add("dragging");
  });
  container.addEventListener("dragover", (e) => {
    if (!dragged) return;
    e.preventDefault();
    const over = e.target.closest(".item");
    if (!over || over === dragged || over.parentElement !== container) return;
    const rect = over.getBoundingClientRect();
    const after = e.clientY > rect.top + rect.height / 2;
    container.insertBefore(dragged, after ? over.nextSibling : over);
  });
  container.addEventListener("drop", (e) => { if (dragged) e.preventDefault(); });
  container.addEventListener("dragend", () => {
    if (!dragged) return;
    dragged.classList.remove("dragging");
    dragged.draggable = false;
    dragged = null;
    onChange();
  });
  container.addEventListener("click", (e) => {
    const row = e.target.closest(".item");
    if (!row) return;
    if (e.target.closest(".up") && row.previousElementSibling) {
      container.insertBefore(row, row.previousElementSibling);
      onChange();
    } else if (e.target.closest(".down") && row.nextElementSibling) {
      container.insertBefore(row.nextElementSibling, row);
      onChange();
    }
  });
}

function renumber(container) {
  const rows = [...container.querySelectorAll(":scope > .item")];
  rows.forEach((row, i) => {
    $(".seg-num", row).textContent = `${i + 1}.`;
    $(".up", row).disabled = i === 0;
    $(".down", row).disabled = i === rows.length - 1;
  });
}

// ---------- result block (one file, or a list when pieces are separate files) ----------

function renderResult(el, job, tab) {
  const files = job.result.files;
  const kindKey = job.kind === "join" ? "videos" : "pieces";
  el.innerHTML = "";

  const video = document.createElement("video");
  video.controls = true;
  video.preload = "metadata";
  video.src = files[0].preview_url;
  el.appendChild(video);

  const info = document.createElement("span");
  info.className = "muted";
  setT(info, "result_info", { pieces: { plural: kindKey, n: job.result.pieces }, duration: job.result.duration_text });

  const note = document.createElement("p");
  note.className = "muted small hidden";
  const showNote = (key, params) => { setT(note, key, params); note.classList.remove("hidden"); };

  async function desktopCall(fn) {
    try {
      const res = await fn();
      if (res.cancelled) return;
      if (res.error) return showNote(res.error);
      tab.saved = true;
      if (res.count) showNote("saved_all_to", { files: { plural: "files", n: res.count }, path: res.saved });
      else showNote("saved_to", { path: res.saved });
    } catch (err) {
      showNote("save_failed", { error: String((err && err.message) || err) });
    }
  }

  function fileButtons(index, entry) {
    const link = document.createElement("a");
    link.className = "button primary browser-only";
    link.href = entry.download_url;
    setT(link, "download_result");
    link.addEventListener("click", () => { tab.saved = true; });
    const save = document.createElement("button");
    save.className = "primary desktop-only";
    setT(save, "save_as");
    save.addEventListener("click", () => desktopCall(() => window.pywebview.api.save_result(job.id, index)));
    return [link, save];
  }

  if (files.length === 1) {
    const row = document.createElement("div");
    row.className = "row";
    row.append(...fileButtons(0, files[0]), info);
    el.appendChild(row);
  } else {
    const head = document.createElement("div");
    head.className = "row";
    const zip = document.createElement("a");
    zip.className = "button primary browser-only";
    zip.href = `/api/jobs/${job.id}/zip`;
    setT(zip, "download_all");
    zip.addEventListener("click", () => { tab.saved = true; });
    const saveAll = document.createElement("button");
    saveAll.className = "primary desktop-only";
    setT(saveAll, "save_all");
    saveAll.addEventListener("click", () => desktopCall(() => window.pywebview.api.save_all(job.id)));
    head.append(zip, saveAll, info);
    el.appendChild(head);

    const list = document.createElement("div");
    list.className = "file-list";
    files.forEach((entry, index) => {
      const row = document.createElement("div");
      row.className = "file-row";
      const play = document.createElement("button");
      play.className = "icon";
      play.textContent = "▶";
      play.dataset.i18nTitle = "play_piece";
      play.addEventListener("click", () => { video.src = entry.preview_url; video.play(); });
      const name = document.createElement("span");
      name.className = "file-name";
      name.textContent = `${entry.name} · ${entry.duration_text}`;
      const [link, save] = fileButtons(index, entry);
      link.classList.remove("primary");
      save.classList.remove("primary");
      row.append(play, name, link, save);
      list.appendChild(row);
    });
    el.appendChild(list);
  }

  const where = document.createElement("p");
  where.className = "muted small";
  const label = document.createElement("span");
  setT(label, files.length === 1 ? "also_saved_here" : "files_saved_here");
  const code = document.createElement("code");
  code.textContent = files.length === 1 ? files[0].path : folderOf(files[0].path);
  const show = document.createElement("button");
  show.className = "link desktop-only";
  setT(show, "show_in_folder");
  show.addEventListener("click", () => window.pywebview.api.show_in_folder(files[0].path));
  where.append(label, " ", code, " ", show);
  el.append(where, note);

  applyI18n(el);
  el.classList.remove("hidden");
}

// Runs a cut or join job for a tab: confirmation, progress, tab status, result.
async function runJob(tab, { confirmKey, start }) {
  const q = (sel) => $(sel, tab.panel);
  if (tab.running) return;
  if (tab.hasResult && !(await confirmDialog(confirmKey, "confirm_redo_body"))) return;
  const button = q(".run-button");
  const progress = tab.runProgress;
  showError(q(".run-error"), null);
  q(".result").classList.add("hidden");
  button.disabled = true;
  tab.hasResult = false;
  tab.saved = false;
  tab.running = true;
  progress.show(["preparing"], 0);
  tab.setStatus("running", 0);
  try {
    const job = await start();
    const done = await pollJob(job.id, (j) => {
      const details = jobDetails(j);
      if (j.state === "running") details.push(["elapsed", { time: formatTime(Math.floor(j.elapsed)) }]);
      progress.show([j.stage], j.percent, details);
      tab.setStatus(j.state === "queued" ? "queued" : "running", j.percent);
    });
    progress.show(["done"], 100, [["took", { time: formatTime(Math.floor(done.elapsed)) }]]);
    renderResult(q(".result"), done, tab);
    tab.hasResult = true;
    tab.setStatus("done");
  } catch (err) {
    progress.hide();
    showError(q(".run-error"), err);
    tab.setStatus("error");
  } finally {
    tab.running = false;
    button.disabled = false;
    if (tab.refresh) tab.refresh();
  }
}

// ======================================================================
// Tabs
// ======================================================================

const tabs = [];
const counters = { cut: 0, join: 0 };

function selectTab(tab) {
  tabs.forEach((other) => {
    other.tabEl.classList.toggle("active", other === tab);
    other.tabEl.setAttribute("aria-selected", String(other === tab));
    other.panel.classList.toggle("hidden", other !== tab);
  });
}

async function closeTab(tab) {
  if (tab.running && !(await confirmDialog("confirm_close_title", "confirm_close_running"))) return;
  if (!tab.running && tab.hasResult && !tab.saved && !(await confirmDialog("confirm_close_title", "confirm_close_result"))) return;
  const index = tabs.indexOf(tab);
  if (index < 0) return;
  tabs.splice(index, 1);
  tab.tabEl.remove();
  tab.panel.querySelectorAll("video").forEach((v) => v.removeAttribute("src"));
  tab.panel.remove();
  if (!tabs.length) createTab("cut");
  else selectTab(tabs[Math.max(0, index - 1)]);
}

function createTab(kind) {
  const tab = { kind, n: ++counters[kind], hasResult: false, running: false, saved: false };
  tab.tabEl = clone("tpl-tab");
  tab.panel = clone(kind === "cut" ? "tpl-cut" : "tpl-join");
  const titleEl = $(".tab-title", tab.tabEl);
  const statusEl = $(".tab-status", tab.tabEl);

  tab.setTitle = (text) => {
    if (text) {
      delete titleEl.dataset.i18n;
      titleEl.textContent = text;
      titleEl.title = text;
    } else {
      setT(titleEl, kind === "cut" ? "tab_cut" : "tab_join", { n: tab.n });
    }
  };
  tab.setStatus = (status, percent) => {
    statusEl.className = `tab-status ${status || ""}`;
    statusEl.textContent =
      status === "running" ? (typeof percent === "number" ? `${Math.floor(percent)}%` : "…")
        : status === "queued" ? "⏳" : status === "done" ? "✓" : status === "error" ? "!" : "";
  };
  tab.setTitle(null);

  tab.tabEl.addEventListener("click", (e) => { if (!e.target.closest(".tab-close")) selectTab(tab); });
  tab.tabEl.addEventListener("keydown", (e) => { if (e.key === "Enter") selectTab(tab); });
  $(".tab-close", tab.tabEl).addEventListener("click", () => closeTab(tab));

  $("#tabs-list").appendChild(tab.tabEl);
  $("#panels").appendChild(tab.panel);
  tab.runProgress = makeProgress($(".run-progress", tab.panel));
  setupSubtabs(tab.panel);
  (kind === "cut" ? setupCutTab : setupJoinTab)(tab);
  applyI18n(tab.tabEl);
  applyI18n(tab.panel);
  tabs.push(tab);
  selectTab(tab);
  return tab;
}

// ======================================================================
// "Cut one video" tab
// ======================================================================

function setupCutTab(tab) {
  const panel = tab.panel;
  const q = (sel) => $(sel, panel);
  const player = q(".player");
  const segmentsEl = q(".segments");
  const sourceProgress = makeProgress(q(".source-progress"));
  let source = null;
  let playUntil = null;

  function setBusy(busy) {
    q(".step-source").querySelectorAll("button, input").forEach((el) => (el.disabled = busy));
    q(".drop").style.pointerEvents = busy ? "none" : "";
  }

  function setSource(src) {
    source = src;
    tab.setTitle(src.title);
    setT(q(".source-title"), src.has_audio ? "source_line" : "source_line_silent", { title: src.title, duration: src.duration_text });
    setT(q(".player-time"), "position", { current: "00:00", total: src.duration_text });
    player.src = src.video_url;
    segmentsEl.innerHTML = "";
    addSegment();
    q(".step-segments").classList.remove("hidden");
    q(".step-result").classList.remove("hidden");
    q(".result").classList.add("hidden");
    tab.runProgress.hide();
    showError(q(".run-error"), null);
    tab.hasResult = false;
    tab.setStatus("");
    q(".step-segments").scrollIntoView({ behavior: "smooth" });
  }

  async function loadSource(load) {
    showError(q(".source-error"), null);
    setBusy(true);
    try {
      const src = await load();
      sourceProgress.show(["done"], 100);
      setSource(src);
    } catch (err) {
      sourceProgress.hide();
      showError(q(".source-error"), err);
    } finally {
      setBusy(false);
    }
  }

  setupDrop(panel, (files) => loadSource(() => {
    const file = files[0];
    sourceProgress.show(["uploading", { name: file.name }], 0);
    return uploadFile(file, (loaded, total) => {
      if (loaded === null) return sourceProgress.show(["stage_checking"], null);
      const mb = (n) => (n / 1024 / 1024).toFixed(1);
      sourceProgress.show(["uploading", { name: file.name }], (loaded / total) * 100, [["mb_of", { loaded: mb(loaded), total: mb(total) }]]);
    });
  }));

  q(".link-form").addEventListener("submit", (e) => {
    e.preventDefault();
    loadSource(() => {
      sourceProgress.show(["preparing_download"], null);
      return downloadLink(q(".link-input").value, (j) => sourceProgress.show([j.stage], j.percent, jobDetails(j)));
    });
  });

  player.addEventListener("timeupdate", () => {
    if (source) setT(q(".player-time"), "position", { current: formatTime(player.currentTime), total: source.duration_text });
    if (playUntil !== null && player.currentTime >= playUntil) {
      player.pause();
      playUntil = null;
    }
  });

  function readSegments() {
    return [...segmentsEl.querySelectorAll(".segment")].map((row) => ({
      start: $(".seg-start", row).value.trim() || "0",
      end: $(".seg-end", row).value.trim(),
    }));
  }

  function updateTotal() {
    renumber(segmentsEl);
    const duration = source ? source.duration : 0;
    let total = 0;
    let valid = true;
    segmentsEl.querySelectorAll(".segment").forEach((row) => {
      const startInput = $(".seg-start", row);
      const endInput = $(".seg-end", row);
      const start = parseTime(startInput.value) ?? 0;
      let end = parseTime(endInput.value);
      if (end === null) end = duration;
      const bad = isNaN(start) || isNaN(end) || end <= start || start >= duration;
      startInput.classList.toggle("invalid", isNaN(start) || start >= duration);
      endInput.classList.toggle("invalid", isNaN(end) || end <= start);
      if (bad) valid = false;
      else total += Math.min(end, duration) - start;
    });
    const el = q(".segments-total");
    if (!valid) setT(el, "check_fields");
    else setT(el, q(".mode:checked").value === "keep" ? "total_keep" : "total_remove", { total: formatTime(total) });
  }

  function addSegment() {
    const row = clone("tpl-segment");
    const startInput = $(".seg-start", row);
    const endInput = $(".seg-end", row);
    // A new piece starts where the previous one ended.
    const last = segmentsEl.querySelector(".segment:last-child .seg-end");
    if (last && last.value) startInput.value = last.value;

    $(".set-start", row).onclick = () => { startInput.value = formatTime(player.currentTime); updateTotal(); };
    $(".set-end", row).onclick = () => { endInput.value = formatTime(player.currentTime); updateTotal(); };
    $(".remove", row).onclick = () => { row.remove(); updateTotal(); };
    $(".play", row).onclick = () => {
      const start = parseTime(startInput.value) ?? 0;
      const end = parseTime(endInput.value);
      if (isNaN(start)) return;
      player.currentTime = start;
      playUntil = end === null || isNaN(end) ? null : end;
      player.play();
    };
    [startInput, endInput].forEach((i) => i.addEventListener("input", updateTotal));
    applyI18n(row);
    segmentsEl.appendChild(row);
    updateTotal();
    return row;
  }

  makeSortable(segmentsEl, updateTotal);
  q(".add-segment").addEventListener("click", () => $(".seg-start", addSegment()).focus());
  panel.querySelectorAll(".mode").forEach((r) => {
    r.name = `mode-${tab.n}`; // radio groups must be unique per tab
    r.addEventListener("change", updateTotal);
  });

  q(".run-button").addEventListener("click", () => runJob(tab, {
    confirmKey: "confirm_recut_title",
    start: () => postJson("/api/cut", {
      source_id: source.id,
      segments: readSegments(),
      mode: q(".mode:checked").value,
      separate: q(".separate").checked,
    }),
  }));
}

// ======================================================================
// "Join several videos" tab
// ======================================================================

function setupJoinTab(tab) {
  const panel = tab.panel;
  const q = (sel) => $(sel, panel);
  const list = q(".join-items");
  const items = new Map(); // row element -> {source, loading}

  function refresh() {
    renumber(list);
    const rows = [...list.children];
    const ready = rows.map((r) => items.get(r)).filter((it) => it.source);
    const busy = rows.some((r) => items.get(r).loading);
    const total = ready.reduce((acc, it) => acc + it.source.duration, 0);
    if (!rows.length) setT(q(".join-total"), "join_empty");
    else setT(q(".join-total"), "join_total", { videos: { plural: "videos", n: ready.length }, duration: formatTime(total) });
    q(".run-button").disabled = tab.running || busy || ready.length < 2 || ready.length !== rows.length;
  }
  tab.refresh = refresh;

  function addItem(title) {
    const row = clone("tpl-join-item");
    const titleEl = $(".join-item-title", row);
    const status = $(".join-item-status", row);
    titleEl.textContent = title;
    const item = { source: null, loading: true };
    items.set(row, item);
    $(".remove", row).onclick = () => { items.delete(row); row.remove(); refresh(); };
    applyI18n(row);
    list.appendChild(row);
    refresh();
    return {
      status: (key, params) => setT(status, key, params),
      ready: (src) => {
        item.source = src;
        item.loading = false;
        titleEl.textContent = src.title;
        setT(status, src.has_audio ? "item_duration" : "item_silent", { duration: src.duration_text });
        refresh();
      },
      fail: (err) => {
        item.loading = false;
        status.classList.add("error");
        const payload = errorPayload(err);
        setT(status, payload.key, payload.params || {});
        refresh();
      },
    };
  }

  setupDrop(panel, (files) => {
    files.forEach((file) => {
      const it = addItem(file.name);
      it.status("item_uploading", { pct: 0 });
      uploadFile(file, (loaded, total) => {
        if (loaded === null) it.status("item_checking");
        else it.status("item_uploading", { pct: Math.floor((loaded / total) * 100) });
      }).then(it.ready, it.fail);
    });
  });

  q(".link-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = q(".link-input");
    const url = input.value.trim();
    input.value = "";
    const it = addItem(url);
    it.status("item_preparing");
    downloadLink(url, (j) => {
      if (j.stage === "stage_checking") it.status("item_checking");
      else it.status("item_downloading", { pct: Math.floor(j.percent || 0) });
    }).then(it.ready, it.fail);
  });

  makeSortable(list, refresh);
  refresh();

  q(".run-button").addEventListener("click", () => runJob(tab, {
    confirmKey: "confirm_rejoin_title",
    start: () => postJson("/api/join", { source_ids: [...list.children].map((r) => items.get(r).source.id) }),
  }));
}

// ======================================================================
// Start-up
// ======================================================================

// In the desktop window, downloads become native Save dialogs (see .desktop-only in CSS).
function enableDesktop() {
  document.body.classList.add("desktop");
}

// Dropping a file outside a drop zone must not navigate away from the app.
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

document.querySelectorAll(".lang button").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.lang)));
$("#new-cut").addEventListener("click", () => createTab("cut"));
$("#new-join").addEventListener("click", () => createTab("join"));

(async function init() {
  try {
    I18N.dict = await (await fetch("/static/i18n.json")).json();
  } catch (_) {
    I18N.dict = {};
  }
  let saved = null;
  try { saved = localStorage.getItem("vc-lang"); } catch (_) { /* storage may be blocked */ }
  setLang(saved || "en");
  createTab("cut");
  if (window.pywebview && window.pywebview.api) enableDesktop();
  else window.addEventListener("pywebviewready", enableDesktop);
})();
