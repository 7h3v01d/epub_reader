// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"use strict";

const $ = (id) => document.getElementById(id);
const page = $("page");

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (window.API_TOKEN) opts.headers["X-API-Token"] = window.API_TOKEN;
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
  // Deny-first: book content is sandboxed with allow-same-origin (so the shell
  // can read scroll position and run find) but never allow-scripts — book
  // JavaScript never runs on the web frontend, which shares an origin with the
  // reader control plane.
  page.setAttribute("sandbox", "allow-same-origin");
  const frag = section.fragment ? "#" + encodeURIComponent(section.fragment) : "";
  const parts = section.key.split("/").map(encodeURIComponent).join("/");
  page._highlight = section.highlight || "";
  page._ordinal = section.highlight_ordinal || 0;
  page._hlCase = !!section.highlight_case;
  page._hlWord = !!section.highlight_whole_word;
  page._progress = section.fragment ? 0 : (section.progress || 0);
  page.src = "/resource/" + parts + frag;

  $("prev").disabled = section.is_first;
  $("next").disabled = section.is_last;
  setStatus(`${section.title}  —  ${section.spine_index + 1}/${section.total_sections}`);
}

// Locate and select the Nth occurrence of a query in the iframe document,
// building the SAME regex the engine used (escaped, optional \b, case flag) so
// the ordinal the engine assigned targets the same match. A newline is inserted
// between text nodes with different parents to approximate the engine's block
// breaks (which matter for whole-word boundaries).
function highlightOccurrence(win, query, ordinal, caseSensitive, wholeWord) {
  const doc = win.document;
  const root = doc.body || doc.documentElement;
  if (!root || !query) return false;
  let pattern = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  if (wholeWord) pattern = "\\b" + pattern + "\\b";
  const re = new RegExp(pattern, caseSensitive ? "g" : "gi");

  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let text = "";
  let node;
  let lastParent = null;
  while ((node = walker.nextNode())) {
    const parent = node.parentNode;
    if (parent && /^(SCRIPT|STYLE)$/.test(parent.nodeName)) continue;
    if (lastParent !== null && parent !== lastParent) text += "\n";
    nodes.push({ node, start: text.length });
    text += node.nodeValue;
    lastParent = parent;
  }

  let m;
  let count = 0;
  let target = null;
  while ((m = re.exec(text))) {
    if (count === ordinal) { target = { start: m.index, end: m.index + m[0].length }; break; }
    count++;
    if (m.index === re.lastIndex) re.lastIndex++;
  }
  if (!target) return false;

  const locate = (abs) => {
    for (let i = nodes.length - 1; i >= 0; i--) {
      if (abs >= nodes[i].start && abs - nodes[i].start <= nodes[i].node.nodeValue.length) {
        return { node: nodes[i].node, offset: abs - nodes[i].start };
      }
    }
    return null;
  };
  const s = locate(target.start);
  const e = locate(target.end);
  if (!s || !e) return false;
  const range = doc.createRange();
  try {
    range.setStart(s.node, s.offset);
    range.setEnd(e.node, e.offset);
  } catch (_e) { return false; }
  const sel = win.getSelection();
  if (sel) { sel.removeAllRanges(); sel.addRange(range); }
  const rect = range.getBoundingClientRect();
  win.scrollTo(0, (win.scrollY || 0) + rect.top - win.innerHeight / 3);
  return true;
}

page.addEventListener("load", () => {
  let win;
  try { win = page.contentWindow; } catch (_e) { return; }
  if (!win) return;
  // Apply a pending search highlight once the section is in the DOM, using the
  // engine's own semantics (case sensitivity + whole-word) so the Nth match the
  // engine counted is the one revealed — native find() would count differently.
  if (page._highlight) {
    try { highlightOccurrence(win, page._highlight, page._ordinal, page._hlCase, page._hlWord); }
    catch (_e) { /* DOM unavailable */ }
    page._highlight = "";
  } else if (page._progress > 0) {
    // Restore reading position: scroll to the stored fraction of the section.
    try {
      const el = win.document.scrollingElement || win.document.documentElement;
      const max = el.scrollHeight - win.innerHeight;
      if (max > 0) el.scrollTop = max * page._progress;
    } catch (_e) { /* cross-origin or detached */ }
  }
  page._progress = 0;
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
  }
  if (state.error) setStatus(state.error, true);
  showSection(state.section);
}

async function refreshAll() {
  const state = await api("GET", "/api/state");
  applyState(state);
  if (state.is_open) await loadSidebars();
}

async function loadSidebars() {
  renderToc(await api("GET", "/api/toc"));
  renderBookmarks(await api("GET", "/api/bookmarks"));
}

async function afterOpen(state) {
  applyState(state);
  if (state && state.is_open) await loadSidebars();
}

async function uploadFile(file) {
  if (!file) return;
  if (!/\.epub$/i.test(file.name)) { setStatus("Not an .epub file", true); return; }
  setStatus(`Opening ${file.name} …`);
  try {
    const headers = {};
    if (window.API_TOKEN) headers["X-API-Token"] = window.API_TOKEN;
    const res = await fetch("/api/upload?name=" + encodeURIComponent(file.name), {
      method: "POST",
      headers,
      body: file,
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    await afterOpen(await res.json());
  } catch (e) {
    setStatus(e.message, true);
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
    allow_scripts: false,     // web frontend never runs book scripts
  };
  await act(api("POST", "/api/settings", body));
}

// ---- wiring ---------------------------------------------------------------
// ---- open: file button + drag-and-drop ------------------------------------
$("open").onclick = () => $("file").click();
$("file").onchange = (e) => {
  const file = e.target.files[0];
  e.target.value = "";                 // allow re-selecting the same file
  uploadFile(file);
};
$("empty").onclick = () => $("file").click();

const dropzone = $("dropzone");
let dragDepth = 0;
const dragHasFiles = (e) =>
  e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");

window.addEventListener("dragenter", (e) => {
  if (!dragHasFiles(e)) return;
  e.preventDefault();
  dragDepth++;
  dropzone.hidden = false;             // overlay sits above the iframe, so it
});                                     // reliably captures the drop
window.addEventListener("dragover", (e) => { if (dragHasFiles(e)) e.preventDefault(); });
window.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) dropzone.hidden = true;
});
window.addEventListener("drop", (e) => {
  e.preventDefault();                  // never let the browser navigate to the file
  dragDepth = 0;
  dropzone.hidden = true;
  const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (file) uploadFile(file);
});

// ---- navigation + settings wiring -----------------------------------------
$("prev").onclick = () => act(api("POST", "/api/prev"));
$("next").onclick = () => act(api("POST", "/api/next"));
$("theme").onchange = pushSettings;
$("scale").onchange = pushSettings;
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
