# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Off-thread book opening.

:class:`Book.open` parses container/OPF/TOC and stats the file — enough to
stutter the UI on a large or slow-media book. It runs here on a QObject moved
onto a QThread; the finished :class:`Book` is delivered back via signal so the
session adopts it (and emits its first section) on the GUI thread, where touching
widgets is safe.

The worker/thread pair is held in a module-level ``_worker_refs`` registry for
the duration of the open, so neither is garbage-collected mid-flight — the same
GC-safety pattern used across the estate's threaded work.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from ...core.book import Book

# Keep (worker, thread) tuples alive while an open is in flight.
_worker_refs: set[tuple["OpenWorker", QThread]] = set()


class OpenWorker(QObject):
    """Opens a single EPUB and reports the result."""

    opened = pyqtSignal(object)   # emits a Book
    failed = pyqtSignal(str)      # emits an error message
    finished = pyqtSignal()

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self._path = Path(path)

    @pyqtSlot()
    def run(self) -> None:
        try:
            book = Book.open(self._path)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            self.failed.emit(str(exc))
        else:
            self.opened.emit(book)
        finally:
            self.finished.emit()


def open_book_async(path: str | Path, on_opened, on_failed) -> None:
    """Open ``path`` on a worker thread, dispatching results to callbacks.

    ``on_opened(book)`` and ``on_failed(message)`` are invoked on the GUI
    thread via queued signal delivery.
    """
    thread = QThread()
    worker = OpenWorker(path)
    worker.moveToThread(thread)

    ref = (worker, thread)
    _worker_refs.add(ref)

    thread.started.connect(worker.run)
    worker.opened.connect(on_opened)
    worker.failed.connect(on_failed)

    def _cleanup() -> None:
        thread.quit()
        thread.wait()
        worker.deleteLater()
        thread.deleteLater()
        _worker_refs.discard(ref)

    worker.finished.connect(_cleanup)
    thread.start()
