"use strict";

const $ = (sel) => document.querySelector(sel);
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  let data = null;
  try { data = await r.json(); } catch (_) {}
  if (!r.ok) throw new Error((data && data.error) || `HTTP ${r.status}`);
  return data;
};

let currentJobId = null;
let pollTimer = null;

// ---------- Toast ----------
function toast(msg, isErr) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("err", !!isErr);
  t.classList.remove("hidden");
  requestAnimationFrame(() => t.classList.add("show"));
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    t.classList.remove("show");
    setTimeout(() => t.classList.add("hidden"), 250);
  }, 2600);
}

// ---------- Segmented controls ----------
function initSegmented(id, onChange) {
  const el = document.getElementById(id);
  el.querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", () => {
      el.querySelectorAll("button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      el.dataset.value = b.dataset.v;
      if (onChange) onChange(b.dataset.v);
    });
  });
}
const segValue = (id) => document.getElementById(id).dataset.value;
function segSet(id, value) {
  const el = document.getElementById(id);
  el.querySelectorAll("button").forEach((b) => {
    const on = b.dataset.v === value;
    b.classList.toggle("active", on);
    if (on) el.dataset.value = value;
  });
}

// ---------- Settings ----------
async function loadSettings() {
  const s = await api("/api/settings");
  const pill = $("#tokenPill");
  if (s.token_set) {
    pill.textContent = "Token gesetzt";
    pill.className = "pill pill-ok";
    $("#tokenInput").placeholder = s.token_hint || "Token gesetzt";
  } else {
    pill.textContent = "Kein Token";
    pill.className = "pill pill-warn";
  }
  const d = s.defaults || {};
  if (d.level) $("#level").value = d.level;
  if (d.type) segSet("type", d.type);
  if (d.layout) segSet("layout", d.layout);
  if (d.paper) $("#paper").value = d.paper;
  if (d.duplex) segSet("duplex", d.duplex);
  $("#cover").checked = d.cover !== false;
  $("#cutmarks").checked = d.cut_marks !== false;
  applyLayoutState();
  return s;
}

async function saveSettings(includeToken) {
  const body = {
    defaults: {
      level: parseInt($("#level").value, 10) || 1,
      type: segValue("type"),
      layout: segValue("layout"),
      paper: $("#paper").value,
      duplex: segValue("duplex"),
      cover: $("#cover").checked,
      cut_marks: $("#cutmarks").checked,
    },
  };
  if (includeToken) body.token = $("#tokenInput").value;
  await api("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ---------- Layout dependent UI ----------
function applyLayoutState() {
  const isA6 = segValue("layout") === "a6";
  $("#paperField").classList.toggle("hidden", isA6);
}

// ---------- Export ----------
async function startExport() {
  $("#formError").classList.add("hidden");
  const sample = $("#sample").checked;
  const level = parseInt($("#level").value, 10);
  if (!sample && (!(level >= 1 && level <= 60))) {
    showFormError("Bitte ein Level zwischen 1 und 60 angeben.");
    return;
  }
  const body = {
    level, sample,
    type: segValue("type"),
    layout: segValue("layout"),
    paper: $("#paper").value,
    duplex: segValue("duplex"),
    cover: $("#cover").checked,
    cut_marks: $("#cutmarks").checked,
    no_cache: $("#nocache").checked,
  };

  const btn = $("#generate");
  btn.disabled = true;
  $("#progress").classList.remove("hidden");
  $("#progressText").textContent = "Wird erzeugt…";

  try {
    // Auswahl als Default merken (ohne Token)
    saveSettings(false).catch(() => {});
    const job = await api("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    currentJobId = job.id;
    pollJob(job.id);
  } catch (e) {
    btn.disabled = false;
    $("#progress").classList.add("hidden");
    showFormError(e.message);
  }
}

function showFormError(msg) {
  const el = $("#formError");
  el.textContent = "⚠ " + msg;
  el.classList.remove("hidden");
}

function pollJob(id) {
  clearTimeout(pollTimer);
  const tick = async () => {
    let job;
    try { job = await api(`/api/jobs/${id}`); }
    catch (_) { pollTimer = setTimeout(tick, 1500); return; }

    if (job.status === "queued") $("#progressText").textContent = "In Warteschlange…";
    else if (job.status === "running") $("#progressText").textContent = "WaniKani wird abgefragt & PDF gebaut…";

    if (job.status === "done" || job.status === "error") {
      $("#generate").disabled = false;
      $("#progress").classList.add("hidden");
      if (job.status === "done") {
        showPreview(job);
        toast(`Fertig: ${job.n_cards} Karten`);
      } else {
        showFormError(job.error || "Export fehlgeschlagen.");
        toast("Export fehlgeschlagen", true);
      }
      loadHistory();
      return;
    }
    pollTimer = setTimeout(tick, 1500);
  };
  tick();
}

// ---------- Preview ----------
function showPreview(job) {
  const src = `/api/jobs/${job.id}/pdf#toolbar=1&view=FitH`;
  const frame = $("#previewFrame");
  frame.src = src;
  frame.classList.remove("hidden");
  $("#previewEmpty").classList.add("hidden");
  const dl = $("#downloadBtn");
  dl.href = `/api/jobs/${job.id}/pdf?download=1`;
  dl.classList.remove("hidden");
}

// ---------- History ----------
function timeAgo(iso) {
  const d = new Date(iso);
  return d.toLocaleString();
}
async function loadHistory() {
  let jobs = [];
  try { jobs = await api("/api/jobs"); } catch (_) {}
  const ul = $("#historyList");
  ul.innerHTML = "";
  $("#historyEmpty").classList.toggle("hidden", jobs.length > 0);
  for (const j of jobs) {
    const li = document.createElement("li");
    li.className = "hist";
    const p = j.params || {};
    const sub = j.status === "error"
      ? `<span class="err-text">${escapeHtml(j.error || "Fehler")}</span>`
      : `${escapeHtml(layoutLabel(p.layout))} · ${p.duplex || ""} · ${timeAgo(j.created_at)}`
        + (j.n_cards ? ` · ${j.n_cards} Karten` : "");
    li.innerHTML = `
      <span class="dot ${j.status}"></span>
      <div class="h-main">
        <div class="h-title">${escapeHtml(j.title || j.id)}</div>
        <div class="h-sub">${sub}</div>
      </div>
      <div class="h-actions"></div>`;
    const actions = li.querySelector(".h-actions");
    if (j.status === "done") {
      const view = document.createElement("button");
      view.className = "chip-btn"; view.textContent = "Vorschau";
      view.onclick = () => showPreview(j);
      const dl = document.createElement("a");
      dl.className = "chip-btn"; dl.textContent = "PDF";
      dl.href = `/api/jobs/${j.id}/pdf?download=1`; dl.setAttribute("download", "");
      actions.append(view, dl);
    }
    const del = document.createElement("button");
    del.className = "chip-btn danger"; del.textContent = "✕";
    del.title = "Löschen";
    del.onclick = async () => {
      await api(`/api/jobs/${j.id}`, { method: "DELETE" });
      if (currentJobId === j.id) {
        $("#previewFrame").classList.add("hidden");
        $("#previewEmpty").classList.remove("hidden");
        $("#downloadBtn").classList.add("hidden");
      }
      loadHistory();
    };
    actions.append(del);
    ul.append(li);
  }
}
function layoutLabel(l) { return l === "a6" ? "A6 · 1/Seite" : "A4 · 4/Seite"; }
function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- Wire up ----------
document.addEventListener("DOMContentLoaded", () => {
  initSegmented("type");
  initSegmented("layout", applyLayoutState);
  initSegmented("duplex");

  $("#settingsToggle").addEventListener("click", () =>
    $("#settingsPanel").classList.toggle("hidden"));

  $("#tokenShow").addEventListener("click", () => {
    const i = $("#tokenInput");
    i.type = i.type === "password" ? "text" : "password";
  });

  $("#tokenSave").addEventListener("click", async () => {
    try {
      await saveSettings(true);
      $("#tokenInput").value = "";
      $("#tokenStatus").textContent = "Gespeichert ✓";
      $("#tokenStatus").className = "status ok";
      await loadSettings();
      toast("Einstellungen gespeichert");
    } catch (e) {
      $("#tokenStatus").textContent = e.message;
      $("#tokenStatus").className = "status err";
    }
  });

  $("#tokenTest").addEventListener("click", async () => {
    $("#tokenStatus").textContent = "Teste…";
    $("#tokenStatus").className = "status";
    try {
      const body = $("#tokenInput").value ? { token: $("#tokenInput").value } : {};
      const r = await api("/api/test-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      $("#tokenStatus").textContent = `OK – ${r.username} (Level ${r.level})`;
      $("#tokenStatus").className = "status ok";
    } catch (e) {
      $("#tokenStatus").textContent = "Fehlgeschlagen: " + e.message;
      $("#tokenStatus").className = "status err";
    }
  });

  $("#generate").addEventListener("click", startExport);
  $("#sample").addEventListener("change", (e) => {
    // Bei Demo Level irrelevant – Hinweis via disabled
    $("#level").disabled = e.target.checked;
  });

  loadSettings().catch(() => {});
  loadHistory();
});
