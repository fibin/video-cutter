"use strict";

const $ = (sel) => document.querySelector(sel);
const state = { source: null, playUntil: null };

// ---------- time helpers ----------
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

// ---------- progress UI ----------
function showProgress(block, { stage, percent, detail }) {
  block.classList.remove("hidden");
  block.querySelector(".stage").textContent = stage || "";
  const bar = block.querySelector(".bar");
  const known = typeof percent === "number";
  bar.classList.toggle("indeterminate", !known);
  block.querySelector(".fill").style.width = known ? `${percent}%` : "";
  block.querySelector(".pct").textContent = known ? `${Math.floor(percent)}%` : "";
  block.querySelector(".detail").textContent = detail || "";
}

function showError(el, message) {
  el.textContent = message;
  el.classList.toggle("hidden", !message);
}

async function pollJob(jobId, onUpdate) {
  for (;;) {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) throw new Error("Task not found. The app may have been restarted.");
    const job = await res.json();
    onUpdate(job);
    if (job.state === "done") return job;
    if (job.state === "error") throw new Error(job.error || "Unknown error");
    await new Promise((r) => setTimeout(r, 500));
  }
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Server error (${res.status})`);
  return data;
}

// ---------- step 1: source ----------
document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".tab-panel").forEach((p) =>
      p.classList.toggle("hidden", p.dataset.panel !== tab.dataset.tab));
  }));

const drop = $("#drop");
const sourceProgress = $("#source-progress");
const sourceError = $("#source-error");

$("#file-input").addEventListener("change", (e) => {
  if (e.target.files[0]) uploadFile(e.target.files[0]);
  e.target.value = "";
});
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => {
  e.preventDefault(); drop.classList.add("over");
}));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => {
  e.preventDefault(); drop.classList.remove("over");
}));
drop.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) uploadFile(file);
});

function setSourceBusy(busy) {
  document.querySelectorAll("#step-source button, #step-source input").forEach((el) => (el.disabled = busy));
  drop.style.pointerEvents = busy ? "none" : "";
}

function uploadFile(file) {
  showError(sourceError, "");
  setSourceBusy(true);
  showProgress(sourceProgress, { stage: `Uploading "${file.name}"`, percent: 0 });
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload");
  xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const mb = (n) => (n / 1024 / 1024).toFixed(1);
    showProgress(sourceProgress, {
      stage: `Uploading "${file.name}"`,
      percent: (e.loaded / e.total) * 100,
      detail: `${mb(e.loaded)} of ${mb(e.total)} MB`,
    });
  };
  xhr.upload.onload = () =>
    showProgress(sourceProgress, { stage: "Checking the file", percent: null });
  xhr.onload = () => {
    setSourceBusy(false);
    let data = {};
    try { data = JSON.parse(xhr.responseText); } catch (_) { /* handled below */ }
    if (xhr.status !== 200) {
      sourceProgress.classList.add("hidden");
      showError(sourceError, data.error || `Upload failed (${xhr.status})`);
      return;
    }
    showProgress(sourceProgress, { stage: "Done", percent: 100 });
    setSource(data);
  };
  xhr.onerror = () => {
    setSourceBusy(false);
    sourceProgress.classList.add("hidden");
    showError(sourceError, "Could not upload the file. Is the app still running?");
  };
  xhr.send(file);
}

$("#link-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  showError(sourceError, "");
  setSourceBusy(true);
  showProgress(sourceProgress, { stage: "Preparing download", percent: null });
  try {
    const job = await postJson("/api/youtube", { url: $("#link-input").value });
    const done = await pollJob(job.id, (j) => showProgress(sourceProgress, j));
    showProgress(sourceProgress, { stage: "Done", percent: 100 });
    setSource(done.result.source);
  } catch (err) {
    sourceProgress.classList.add("hidden");
    showError(sourceError, err.message);
  } finally {
    setSourceBusy(false);
  }
});

// ---------- step 2: segments ----------
const player = $("#player");
const segmentsEl = $("#segments");

function setSource(source) {
  state.source = source;
  $("#source-title").textContent = `${source.title} · ${source.duration_text}` +
    (source.has_audio ? "" : " · no audio");
  $("#total-time").textContent = source.duration_text;
  player.src = source.video_url;
  segmentsEl.innerHTML = "";
  addSegment();
  $("#step-segments").classList.remove("hidden");
  $("#step-result").classList.remove("hidden");
  $("#result").classList.add("hidden");
  $("#cut-progress").classList.add("hidden");
  showError($("#cut-error"), "");
  $("#step-segments").scrollIntoView({ behavior: "smooth" });
}

player.addEventListener("timeupdate", () => {
  $("#current-time").textContent = formatTime(player.currentTime);
  if (state.playUntil !== null && player.currentTime >= state.playUntil) {
    player.pause();
    state.playUntil = null;
  }
});

function renumber() {
  segmentsEl.querySelectorAll(".segment").forEach((row, i) => {
    row.querySelector(".seg-num").textContent = `${i + 1}.`;
  });
  updateTotal();
}

function readSegments() {
  return [...segmentsEl.querySelectorAll(".segment")].map((row) => ({
    start: row.querySelector(".seg-start").value.trim() || "0",
    end: row.querySelector(".seg-end").value.trim(),
  }));
}

function updateTotal() {
  const duration = state.source ? state.source.duration : 0;
  let total = 0;
  let valid = true;
  segmentsEl.querySelectorAll(".segment").forEach((row) => {
    const startInput = row.querySelector(".seg-start");
    const endInput = row.querySelector(".seg-end");
    const start = parseTime(startInput.value) ?? 0;
    let end = parseTime(endInput.value);
    if (end === null) end = duration;
    const bad = isNaN(start) || isNaN(end) || end <= start || start >= duration;
    startInput.classList.toggle("invalid", isNaN(start) || start >= duration);
    endInput.classList.toggle("invalid", isNaN(end) || end <= start);
    if (bad) valid = false;
    else total += Math.min(end, duration) - start;
  });
  const mode = document.querySelector("input[name=mode]:checked").value;
  const el = $("#segments-total");
  if (!valid) el.textContent = "Check the highlighted fields";
  else if (mode === "keep") el.textContent = `Result length: ${formatTime(total)}`;
  else el.textContent = `Will be removed: ${formatTime(total)} (if pieces do not overlap)`;
}

function addSegment() {
  const row = $("#segment-template").content.firstElementChild.cloneNode(true);
  const startInput = row.querySelector(".seg-start");
  const endInput = row.querySelector(".seg-end");
  // A new piece starts where the previous one ended.
  const last = segmentsEl.querySelector(".segment:last-child .seg-end");
  if (last && last.value) startInput.value = last.value;

  row.querySelector(".set-start").onclick = () => { startInput.value = formatTime(player.currentTime); updateTotal(); };
  row.querySelector(".set-end").onclick = () => { endInput.value = formatTime(player.currentTime); updateTotal(); };
  row.querySelector(".remove").onclick = () => { row.remove(); renumber(); };
  row.querySelector(".play").onclick = () => {
    const start = parseTime(startInput.value) ?? 0;
    const end = parseTime(endInput.value);
    if (isNaN(start)) return;
    player.currentTime = start;
    state.playUntil = end === null || isNaN(end) ? null : end;
    player.play();
  };
  [startInput, endInput].forEach((i) => i.addEventListener("input", updateTotal));
  segmentsEl.appendChild(row);
  renumber();
  return row;
}

$("#add-segment").addEventListener("click", () => addSegment().querySelector(".seg-start").focus());
document.querySelectorAll("input[name=mode]").forEach((r) => r.addEventListener("change", updateTotal));

// ---------- step 3: cut ----------
$("#cut-button").addEventListener("click", async () => {
  const button = $("#cut-button");
  const progress = $("#cut-progress");
  const errorEl = $("#cut-error");
  showError(errorEl, "");
  $("#result").classList.add("hidden");
  button.disabled = true;
  showProgress(progress, { stage: "Preparing", percent: 0 });
  try {
    const job = await postJson("/api/cut", {
      source_id: state.source.id,
      segments: readSegments(),
      mode: document.querySelector("input[name=mode]:checked").value,
    });
    const done = await pollJob(job.id, (j) => showProgress(progress, {
      ...j,
      detail: [j.detail, `elapsed ${formatTime(Math.floor(j.elapsed))}`].filter(Boolean).join(" · "),
    }));
    showProgress(progress, { stage: "Done", percent: 100, detail: `in ${formatTime(Math.floor(done.elapsed))}` });
    const r = done.result;
    $("#result-player").src = r.preview_url;
    $("#download-link").href = r.download_url;
    $("#result-info").textContent = `${r.pieces} ${r.pieces === 1 ? "piece" : "pieces"} · ${r.duration_text}`;
    $("#result-path").textContent = r.path;
    $("#result").classList.remove("hidden");
  } catch (err) {
    progress.classList.add("hidden");
    showError(errorEl, err.message);
  } finally {
    button.disabled = false;
  }
});
