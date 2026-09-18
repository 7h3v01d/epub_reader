<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
-->

# epubreader

A modular EPUB reading engine with a replaceable UI. The engine parses and
serves EPUB content and knows nothing about any toolkit; a thin frontend layer
adapts it to a concrete UI. **Three frontends ship on the same engine** — a PyQt6 +
QtWebEngine desktop reader, a FastAPI + vanilla-JS web reader, and a terminal reader — which is the
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
    cli/       the terminal reader (pure standard library)
```

Each layer imports only downward. `core` has **zero** Qt imports; importing the
package does not import PyQt6 at all (the Qt frontend is loaded lazily).

### Features live in the engine, not the UI

Reader features are built once, in the engine or session, so every frontend
inherits them:

- **Full-text search** (`core/search.py`) — `search_book()` walks the spine,
  extracts visible text (script/style/`<title>` excluded), and returns
  `SearchHit`s carrying a spine locator, a section title, a context snippet, and
  an engine-owned **literal locator** for the match: the exact matched text, the
  run of text before it within its block, and that literal's occurrence index.
  A frontend highlights by finding that literal (a plain substring search, no
  regex, no case-folding, no `\b`) at the given occurrence — so engine and
  frontend can never disagree on which occurrence is meant, even across Unicode
  word-boundary or case-folding differences between Python and a browser. The
  session exposes `search()` and `go_to_search_hit()`; the latter navigates and
  carries the one-shot locator on the emitted section. `find_literal()` is the
  reference implementation each frontend mirrors (and the CLI, reusing the same
  extractor, matches it exactly).
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

## Installing

The project is a proper package (`pyproject.toml`, `src/` layout). The engine and
terminal reader have no third-party dependencies; the GUI and web frontends pull
their toolkits in as extras:

```bash
pip install .            # engine + terminal reader (epubreader-cli), no deps
pip install .[qt]        # + PyQt6 desktop reader (epubreader)
pip install .[web]       # + FastAPI web reader (epubreader-web)
pip install .[dev]       # + test tooling
```

Installing provides console entry points (`epubreader-cli`, `epubreader-web`, and
the `epubreader` GUI), so the `PYTHONPATH=src` form below is only needed when
running from a checkout without installing.

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

**Terminal (pure standard library, no dependencies):**

```bat
run_cli.bat "C:\path\to\book.epub"
```

```bash
export PYTHONPATH=src
python -m epubreader.frontends.cli.app book.epub [--width N] [--no-color]
```

The terminal reader takes commands (`n`/`p` to turn sections, `t` for contents,
`/text` to search, `j <n>` to jump to a hit, `b` to bookmark, `h` for help). It
reuses the engine's own text extractor, so its search matching is identical to
the engine's. All three readers share one state file, so a book's position and
bookmarks follow you between the desktop, web, and terminal.

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
python -m pytest      # pyproject sets pythonpath = src, so no PYTHONPATH needed
```

The engine, session, frontend contract, the web routes, and the terminal reader
are covered by a fast, headless suite (136 tests; the web tests use FastAPI's
`TestClient` and the CLI's command handler is a pure function, so neither needs a
browser or a terminal). The Qt window is exercised by hand — it needs a display
and the QtWebEngine binaries — so it is intentionally left out of the suite. The
web tests skip themselves automatically if FastAPI isn't installed.

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
- **Hostile-archive budgets.** Before the zip is parsed, the archive's file size
  and its central directory are bounded and the directory's entries are counted
  by walking it directly (the EOCD's declared count is never trusted), so a lying
  header can't force a `ZipInfo` allocation per member. Members are then bounded
  for count, per-member and total uncompressed size, and compression ratio; every
  resource read is streamed under a size cap. Uploads stream straight to disk
  under a size cap, cleaned up in a `finally`. A book with no readable spine
  document is rejected at open rather than failing later at render time.
- **Content-addressed, fixed-size identity.** A book's storage id is
  `epub:` + SHA-256 over the archive's bytes (mixing in the normalized
  identifier) — always ~69 chars. The publisher-controlled `dc:identifier` is
  never used as a storage key directly, so a hostile multi-megabyte identifier
  can't bloat the state file; and scroll-driven progress writes are throttled
  (with a flush on navigation, bookmark, and close) so persistence isn't rewritten
  on every scroll event.
- **Remote bind stays pinned.** For a wildcard bind (`0.0.0.0`) the machine's
  real interface addresses are resolved and accepted as `Host`, so a LAN client
  using the actual IP works while arbitrary Host values are still refused.
- **Untrusted persistence.** The state file is treated as untrusted input at
  every level: a corrupt or wrong-typed document is quarantined, and individual
  fields (a hostile `spine_index`, a non-string `theme`) are coerced rather than
  crashing startup. Bookmark writes are atomic per-bookmark under a cross-process
  lock, so a desktop and a web reader adding bookmarks concurrently keep both.
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
