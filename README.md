<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
-->

# epubreader

A modular EPUB reading engine with a replaceable UI. The engine parses and
serves EPUB content and knows nothing about any toolkit; a thin frontend layer
adapts it to a concrete UI. A PyQt6 + QtWebEngine reader ships today; a web or
CLI frontend drops in without touching the engine.

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
    qt/        the PyQt6 + QtWebEngine reader (today's UI)
    ...        web / cli / … drop in here
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

```bat
setup_venv.bat        :: creates .venv, installs PyQt6 + PyQt6-WebEngine + pytest
run.bat               :: launches the reader
run.bat "C:\path\to\book.epub"   :: launch and open a book straight away
```

From any shell, without the .bat helpers:

```bash
export PYTHONPATH=src          # set PYTHONPATH=src  on Windows
python main.py [book.epub]
```

## Running the tests

```bash
export PYTHONPATH=src
python -m pytest
```

The engine and session are covered by a fast, Qt-free suite (50 tests). The Qt
frontend is exercised by hand — it needs a display and the QtWebEngine binaries,
so it is intentionally left out of the headless suite.

---

## Adding a web frontend (worked example)

1. Subclass `ReaderFrontend`.
2. Serve two kinds of route:
   - `GET /resource/<key>` → `session.book.read_resource(key)`, passed through
     `epubreader.render.inject_stylesheet(...)` for HTML sections so the theme
     is applied. This is the `key → transport` mapping.
   - navigation endpoints that call `session.next_section()`,
     `session.go_to_key(...)`, etc.
3. Implement the five presentation methods (`display_section`, `display_toc`,
   `display_metadata`, `report_error`, `run`). The base class has already wired
   them to the session's callbacks for you.

You write no parsing, no position tracking, and no persistence — those are the
engine's job and are shared across every frontend.

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
- **No script-based progress.** Reading position is read from the view's own
  scroll geometry, so progress tracking never requires running page scripts.

The default stance is closed; the user opts in to book scripts explicitly and
per-session.

---

## Layout notes

- `src/` layout; every source file carries an SPDX Apache-2.0 header.
- Persistence is JSON (progress + settings) written atomically (temp + replace).
- The engine has no third-party dependencies; only the Qt frontend needs
  `requirements.txt`.
