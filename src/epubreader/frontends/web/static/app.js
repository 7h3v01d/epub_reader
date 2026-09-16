// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"use strict";

const $ = (id) => document.getElementById(id);
const page = $("page");
let allowScripts = false;

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.status === 204 ? null : res.json();
}

function setStatus(text, isError) {
  $("status-text").textContent = text;
  $("status").classList.toggle("error", !!isError);
}

// ---- section rendering ----------------------------------------------------
function showSection(section) {
  if (!section) {
    $("empty").style.display = "flex";
    page.removeAttribute("src");
    return;
  }
  $("empty").style.display = "none";
  // Deny-first: book content is sandboxed. allow-same-origin lets the shell
  // read scroll position and run find(); scripts stay off unless opted in.
  page.setAttribute(
    "sandbox",
    allowScripts ? "allow-same-origin allow-scripts" : "allow-same-origin"
  );
  const frag = section.fragment ? "#" + encodeURIComponent(section.fragment) : "";
  const parts = section.key.split("/").map(encodeURIComponent).join("/");
  page._highlight = section.highlight || "";
  page.src = "/resource/" + parts + frag;

  $("prev").disabled = section.is_first;
  $("next").disabled = section.is_last;
  setStatus(`${section.title}  —  ${section.spine_index + 1}/${section.total_sections}`);
}

page.addEventListener("load", () => {
  let win;
  try { win = page.contentWindow; } catch (_e) { return; }
  if (!win) return;
  // Apply a pending search highlight once the section is in the DOM.
  if (page._highlight) {
    try { win.find(page._highlight, false, false, true); } catch (_e) { /* find unsupported */ }
    page._highlight = "";
  }
  // Report scroll fraction back to the session (no book scripting needed).
  win.addEventListener("scroll", debounce(() => {
    try {
      const el = win.document.scrollingElement || win.document.documentElement;
      const max = el.scrollHeight - win.innerHeight;
      const frac = max > 0 ? el.scrollTop / max : 0;
      api("POST", "/api/progress", { progress: Math.max(0, Math.min(1, frac)) });
    } catch (_e) { /* cross-origin or detached */ }
  }, 400));
});

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// ---- state ----------------------------------------------------------------
function applyState(state) {
  if (!state) return;
  if (state.settings) {
    $("theme").value = state.settings.theme;
    $("scale").value = state.settings.font_scale;
    allowScripts = !!state.settings.allow_scripts;
    $("scripts").checked = allowScripts;
  }
  if (state.error) setStatus(state.error, true);
  showSection(state.section);
}

async function refreshAll() {
  const state = await api("GET", "/api/state");
  applyState(state);
  if (state.is_open) {
    renderToc(await api("GET", "/api/toc"));
    renderBookmarks(await api("GET", "/api/bookmarks"));
  }
}

// ---- contents -------------------------------------------------------------
function renderToc(points, depth = 0, into = null) {
  const list = into || (($("toc").innerHTML = ""), $("toc"));
  for (const p of points) {
    const li = document.createElement("li");
    li.textContent = p.label;
    if (depth > 0) li.className = "nested";
    li.onclick = () => act(api("POST", "/api/goto", { key: p.key, fragment: p.fragment }));
    list.appendChild(li);
    if (p.children && p.children.length) renderToc(p.children, depth + 1, list);
  }
}

// ---- search ---------------------------------------------------------------
const runSearch = debounce(async () => {
  const q = $("q").value.trim();
  if (!q) { $("results").innerHTML = ""; $("q-count").textContent = ""; return; }
  const params = new URLSearchParams({ q, case: $("q-case").checked, word: $("q-word").checked });
  const hits = await api("GET", "/api/search?" + params.toString());
  const ul = $("results");
  ul.innerHTML = "";
  for (const h of hits) {
    const li = document.createElement("li");
    const sec = document.createElement("span");
    sec.className = "sec";
    sec.textContent = h.section_title;
    li.appendChild(sec);
    li.appendChild(document.createTextNode(h.snippet.slice(0, h.match_start)));
    const mk = document.createElement("mark");
    mk.textContent = h.snippet.slice(h.match_start, h.match_end);
    li.appendChild(mk);
    li.appendChild(document.createTextNode(h.snippet.slice(h.match_end)));
    li.onclick = () => act(api("POST", "/api/search/goto", { hit: h }));
    ul.appendChild(li);
  }
  $("q-count").textContent = hits.length ? `${hits.length} match${hits.length === 1 ? "" : "es"}` : "No matches";
}, 250);

// ---- bookmarks ------------------------------------------------------------
function renderBookmarks(bookmarks) {
  const ul = $("bookmarks");
  ul.innerHTML = "";
  for (const b of bookmarks) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = b.label || `Section ${b.spine_index + 1}`;
    label.style.cursor = "pointer";
    label.onclick = () => act(api("POST", `/api/bookmarks/${b.id}/goto`));
    const rm = document.createElement("button");
    rm.className = "rm";
    rm.textContent = "✕";
    rm.title = "Remove";
    rm.onclick = async (e) => { e.stopPropagation(); renderBookmarks((await api("DELETE", `/api/bookmarks/${b.id}`)).bookmarks); };
    li.appendChild(label);
    li.appendChild(rm);
    ul.appendChild(li);
  }
}

// ---- helpers --------------------------------------------------------------
async function act(promise) {
  try { applyState(await promise); } catch (e) { setStatus(e.message, true); }
}

async function pushSettings() {
  const body = {
    theme: $("theme").value,
    font_scale: parseFloat($("scale").value) || 1.0,
    allow_scripts: $("scripts").checked,
  };
  await act(api("POST", "/api/settings", body));
}

// ---- wiring ---------------------------------------------------------------
$("prev").onclick = () => act(api("POST", "/api/prev"));
$("next").onclick = () => act(api("POST", "/api/next"));
$("theme").onchange = pushSettings;
$("scale").onchange = pushSettings;
$("scripts").onchange = pushSettings;
$("q").oninput = runSearch;
$("q-case").onchange = runSearch;
$("q-word").onchange = runSearch;
$("add-bookmark").onclick = async () => renderBookmarks((await api("POST", "/api/bookmarks", { label: "" })).bookmarks);

for (const tab of document.querySelectorAll(".tab")) {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.querySelector(`.panel[data-panel="${tab.dataset.tab}"]`).classList.add("active");
  };
}

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if (e.key === "ArrowRight") $("next").click();
  if (e.key === "ArrowLeft") $("prev").click();
});

refreshAll().catch((e) => setStatus(e.message, true));
