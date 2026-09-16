# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Parser for ``META-INF/container.xml`` — locates the OPF package document."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from .exceptions import InvalidEpubError
from .paths import canonical_key

_CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
_OPF_MEDIA_TYPE = "application/oebps-package+xml"


def find_opf_key(container_xml: bytes) -> str:
    """Return the canonical archive key of the OPF package document.

    Prefers a rootfile whose media-type is the OPF type; falls back to the
    first rootfile present. Raises :class:`InvalidEpubError` if none exist.
    """
    try:
        root = ET.fromstring(container_xml)
    except ET.ParseError as exc:  # pragma: no cover - exercised via Book
        raise InvalidEpubError(f"container.xml is not well-formed: {exc}") from exc

    rootfiles = root.findall(f".//{{{_CONTAINER_NS}}}rootfile")
    if not rootfiles:
        # Some producers omit the namespace; retry namespace-agnostically.
        rootfiles = [el for el in root.iter() if el.tag.endswith("rootfile")]
    if not rootfiles:
        raise InvalidEpubError("container.xml declares no rootfile")

    preferred = next(
        (rf for rf in rootfiles if rf.get("media-type") == _OPF_MEDIA_TYPE),
        rootfiles[0],
    )
    full_path = preferred.get("full-path")
    if not full_path:
        raise InvalidEpubError("rootfile has no full-path attribute")
    return canonical_key(full_path)
