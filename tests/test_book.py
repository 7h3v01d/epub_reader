# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""End-to-end engine tests over generated EPUB2 and EPUB3 fixtures."""

from __future__ import annotations

import zipfile

import pytest

from epubreader.core import Book, InvalidEpubError, ResourceNotFoundError


def test_open_epub3_metadata_and_spine(epub3_path):
    with Book.open(epub3_path) as book:
        assert book.metadata.title == "Fixture Three"
        assert book.metadata.creators == ("Leon Priest",)
        assert book.metadata.identifier == "urn:uuid:epub3-fixture-0001"
        assert book.metadata.cover_key == "OEBPS/images/cover.png"
        assert len(book.spine) == 2
        assert book.spine[0].key == "OEBPS/ch1.xhtml"


def test_open_epub2_uses_ncx_and_meta_cover(epub2_path):
    with Book.open(epub2_path) as book:
        assert book.metadata.title == "Fixture Two"
        assert book.metadata.cover_key == "OEBPS/cover.png"
        # NCX produced a nested TOC.
        assert book.toc[0].label == "Chapter One"
        assert book.toc[0].children[0].label == "Chapter Two"


def test_epub3_nav_document_parsed(epub3_path):
    with Book.open(epub3_path) as book:
        assert book.toc[0].label == "Chapter One"
        assert book.toc[0].key == "OEBPS/ch1.xhtml"
        assert book.toc[0].fragment == "top"
        assert book.toc[0].children[0].key == "OEBPS/ch2.xhtml"


def test_read_resource_serves_spaced_filename(epub3_path):
    with Book.open(epub3_path) as book:
        res = book.read_resource("OEBPS/images/pixel one.png")
        assert res.media_type == "image/png"
        assert res.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_read_missing_resource_raises(epub3_path):
    with Book.open(epub3_path) as book:
        with pytest.raises(ResourceNotFoundError):
            book.read_resource("OEBPS/does-not-exist.png")


def test_spine_index_lookup(epub3_path):
    with Book.open(epub3_path) as book:
        assert book.spine_index_for_key("OEBPS/ch2.xhtml") == 1
        assert book.spine_index_for_key("OEBPS/nope.xhtml") is None


def test_book_id_falls_back_to_hash_without_identifier(tmp_path):
    # Archive with no dc:identifier -> hashed id.
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
        'version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:title>NoId</dc:title></metadata>"
        '<manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
        "</manifest><spine><itemref idref=\"c1\"/></spine></package>"
    )
    p = tmp_path / "noid.epub"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("META-INF/container.xml",
                    '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    '<rootfiles><rootfile full-path="content.opf" '
                    'media-type="application/oebps-package+xml"/></rootfiles></container>')
        zf.writestr("content.opf", opf)
        zf.writestr("c1.xhtml", "<html><body>x</body></html>")
    with Book.open(p) as book:
        assert book.book_id.startswith("sha1:")


def test_not_a_zip_raises(tmp_path):
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"this is not a zip")
    with pytest.raises(InvalidEpubError):
        Book.open(bad)


def test_missing_container_raises(tmp_path):
    p = tmp_path / "empty.epub"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("junk.txt", "nothing here")
    with pytest.raises(InvalidEpubError):
        Book.open(p)
