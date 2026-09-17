<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
-->

# epubreader

A modular EPUB reading engine with a replaceable UI. The engine parses and
serves EPUB content and knows nothing about any toolkit; a thin frontend layer
adapts it to a concrete UI. **Two frontends ship on the same engine** — a PyQt6 +
QtWebEngine desktop reader and a FastAPI + vanilla-JS web reader — which is the
proof that the seam works: a CLI or any other UI drops in the same way.

- **Author:** Leon Priest (<github.com/7h3v01d>)
- **License:** Apache-2.0
- **Target:** Python 3.11.5 on Windows (pure-stdlib engine runs anywhere)

---

## Why it is built this way

The whole point of the layout is that **the UI is a plug, not the machine.** The
engine, the reading session, and the shared rendering transforms are all
Qt-free, standard-library-only Python. The Qt window is one implementation of a
small contract. Replace it and everything below is reused verbatim.

```
epubreader/
  core/        UI-agnostic engine  — parse, validate, serve resources   (stdlib only)
  session/     stateful reading session + JSON progress persistence      (stdlib only)
  render.py    shared theme / stylesheet injection (any frontend reuses) (stdlib only)
  frontend/    ReaderFrontend — the abstract contract (the replaceable seam)
  frontends/
    qt/        the PyQt6 + QtWebEngine desktop reader
    web/       the FastAPI + vanilla-JS web reader
    ...        cli / … drop in here
```

Each layer imports only downward. `core` has **zero** Qt imports; importing the
package does not import PyQt6 at all (the Qt frontend is loaded lazily).

### Features live in the engine, not the UI

Reader features are built once, in the engine or session, so every frontend
inherits them:

- **Full-text search** (`core/search.py`) — `search_book()` walks the spine,
  extracts visible text (script/style/`<title>` excluded), and returns
  `SearchHit`s carrying a spine locator, a section title, a context snippet, and
  the match offsets within it. No URLs, nothing toolkit-specific. The session
  exposes `search()` and `go_to_search_hit()`; the latter navigates and asks the
  frontend to highlight via the section's one-shot `highlight` field (Qt maps it
  to `findText`, a browser to native find — no page scripting needed).
- **Bookmarks** (`core/locators.py` + the store) — `Bookmark` wraps a `Locator`
  with a label and timestamp, persisted per book through the same
  `ProgressStore` that holds reading position, so they survive restarts and any
  frontend restores them identically. The session offers
  `add_bookmark()`/`remove_bookmark()`/`bookmarks()`/`go_to_bookmark()`.

A web or CLI frontend gets search and bookmarks for free — it only renders the
results and calls the same session methods the Qt window does.

### The modular hinge

The session emits a **transport-neutral** `RenderedSection` that carries
`section.key` — the resource's path *inside the EPUB archive* — never a URL.
Each frontend maps that key to its own transport:

| Frontend | maps `key` → |
|----------|--------------|
| Qt       | `epub://book/<key>` (custom URL scheme handler) |
| Web      | `/resource/<key>` (an HTTP route) |
| CLI      | direct bytes from `session.book.read_resource(key)` |

That single indirection is what keeps the engine unaware of the UI.

---

## Running it (Windows)

**Desktop (PyQt6):**

```bat
setup_venv.bat        :: creates .venv, installs both frontends' deps + pytest
run.bat               :: launches the desktop reader
run.bat "C:\path\to\book.epub"   :: launch and open a book straight away
```

**Web (FastAPI):**

```bat
run_web.bat                       :: serves at http://127.0.0.1:8000
run_web.bat "C:\path\to\book.epub"
```

In the web reader you can also open a book from the browser — click **Open** to
pick an `.epub`, or drag one anywhere onto the window. The file is uploaded to
the local server, written to a private temp file, and opened through the same
engine; the previous upload's temp file is cleaned up automatically.

From any shell, without the .bat helpers:

```bash
export PYTHONPATH=src                          # set PYTHONPATH=src  on Windows
python main.py [book.epub]                      # desktop
python -m epubreader.frontends.web.app [book.epub] [--host H --port P]   # web
```

Reading position and bookmarks live in one JSON state file, so a book bookmarked
in the desktop reader shows the same bookmarks in the web reader.

## Running the tests

```bash
export PYTHONPATH=src
python -m pytest
```

The engine, session, frontend contract, and the web routes are covered by a
fast, headless suite (105 tests; the web tests use FastAPI's `TestClient`, no
browser). The Qt window is exercised by hand — it needs a display and the
QtWebEngine binaries — so it is intentionally left out of the suite. The web
tests skip themselves automatically if FastAPI isn't installed.

---

## The web frontend, as the worked example

`frontends/web/` is the reference for adding any HTTP UI, and shows the seam is
real rather than aspirational:

1. `WebFrontend` subclasses `ReaderFrontend` — the **same** contract the Qt
   window implements. Its `display_*` callbacks record the latest state into a
   view-model; the HTTP routes serialise that on demand. (Push contract meets
   pull transport: a request that calls `session.next_section()` triggers
   `display_section` synchronously, and the same response returns the result.)
2. `GET /resource/<key>` is the `key → transport` mapping: it serves
   `session.book.read_resource(key)` through `render.inject_stylesheet(...)` for
   HTML, so relative links inside the book resolve correctly because the URL
   path mirrors the archive path exactly.
3. Navigation, search, and bookmark endpoints just call the corresponding
   session methods. No parsing, position tracking, or persistence is
   reimplemented — those are the engine's job, shared across every frontend.

A `find`-based search highlight and scroll-driven progress reporting are wired
through the same one-shot `highlight` field and `report_progress` the Qt view
uses. To add a CLI next, the pattern is identical: implement the five methods,
map `key` to direct bytes.

### The contract

```python
class ReaderFrontend:
    def display_section(self, section: RenderedSection) -> None: ...
    def display_toc(self, toc: tuple[NavPoint, ...]) -> None: ...
    def display_metadata(self, metadata: Metadata) -> None: ...
    def report_error(self, message: str) -> None: ...
    def run(self) -> int: ...
```

Two callback channels are kept deliberately separate:

- **`on_book_opened`** fires once per book → rebuild metadata and the TOC.
- **`on_section`** fires on every page turn *and* on settings changes → render
  only the section.

Keeping them apart means a theme change or a page turn never clears and rebuilds
the TOC tree underneath a user who has expanded or selected a node.

---

## Security posture (deny-first)

- **One choke point.** Every byte a frontend serves comes through
  `Book.read_resource(key)`, which only returns entries whose canonicalised key
  is present in the archive's own namelist. Path-traversal keys never resolve.
- **Sandboxed Qt renderer.** The reader runs an off-the-record QtWebEngine
  profile (no disk cache) behind:
  - a custom `epub://` scheme handler (the *only* way content loads);
  - a request interceptor with a fixed allow-list (`epub`, `data`, `blob`,
    `about`, `qrc`, `chrome`) that blocks everything else — no network, no
    `file://`;
  - a hardened page with JavaScript **off by default** (opt-in per book via the
    toolbar), and remote content, local file access, plugins, and screen capture
    all disabled.
- **Sandboxed web renderer.** Book content is served into a `sandbox`ed
  `<iframe>` (`allow-same-origin` so the shell can read scroll position and run
  `find`), and every `/resource` response carries a strict Content-Security-Policy
  (`default-src 'none'`; same-origin images/CSS/fonts and `data:` only). Because
  the iframe shares an origin with the reader shell, the web frontend **never**
  runs book JavaScript (`script-src 'none'`, no `allow-scripts`) — otherwise a
  book script could reach the parent document and the control-plane API. The
  `allow_scripts` setting affects only the desktop renderer, which is an
  isolated, network-blocked native profile with no parent to escape to.
- **Fail-closed script permission.** Opening any book resets scripts off, so a
  trusted book's opt-in can never be inherited by an unrelated (hostile) one.
- **Local control plane has a trust boundary.** The web server issues a
  per-launch capability token that the shell must present on every `/api/`
  request, validates the `Host` header (anti-DNS-rebinding), and rejects
  cross-origin state-changing requests — these stay enforced for a remote bind
  too. A non-loopback bind is refused unless `--allow-remote` is passed, and even
  then is treated as convenience rather than authentication (the token is
  embedded in the served page). The HTTP surface has no server-side file-open
  route; the browser only uploads book bytes.
- **Hostile-archive budgets.** EPUBs are preflighted for file size and declared
  entry count *before* the zip is parsed, then for member count, per-member and
  total uncompressed size, and compression ratio; every resource read is streamed
  under a size cap. Uploads stream straight to disk under a size cap.
- **Untrusted persistence.** The state file is treated as untrusted input at
  every level: a corrupt or wrong-typed document is quarantined, and individual
  fields (a hostile `spine_index`, a non-string `theme`) are coerced rather than
  crashing startup. Bookmark writes are atomic per-bookmark under a cross-process
  lock, so a desktop and a web reader adding bookmarks concurrently keep both.
- **Content-addressed identity.** A book's storage id folds in a fingerprint of
  its archive, so two books sharing a `dc:identifier` don't merge progress.
- **No script-based progress.** Reading position is read from scroll geometry —
  the view's own in Qt, the iframe's in the browser — so progress tracking never
  requires running book scripts.

The default stance is closed throughout.

---

## Layout notes

- `src/` layout; every source file carries an SPDX Apache-2.0 header.
- Persistence is JSON (progress + settings + bookmarks) written via a locked,
  atomic read-modify-write, shared safely across frontends.
- The engine has no third-party dependencies. The desktop frontend needs
  `requirements.txt` (PyQt6); the web frontend needs `requirements-web.txt`
  (FastAPI + uvicorn). Neither is required to use the other.
