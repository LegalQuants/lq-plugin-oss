"""Minimal standard-library PDF writer for closing-bible fixtures.

Every page is a `/Type /Page` object whose `/Contents` stream shows its text
with `Tj`, so a stdlib content-stream probe (the shape of
`diligence/scripts/shared/build_manifest.py: probe_pdf_stdlib`) finds it,
and a proper xref table so `pdfinfo` / `pdftotext` read it too.

- `encrypt=True` writes a real standard security handler (RC4 40-bit, R2,
  empty user password) so `/Encrypt` sits in the trailer and `pdfinfo`
  reports `Encrypted: yes` instead of failing.
- `corrupt=True` truncates the file so `%%EOF` is gone.

No pypdf. The same code is copied, not imported, by
the synthetic closing fixture builder used by the public tests.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

# The standard 32-byte padding string from the PDF specification.
_PAD = bytes.fromhex("28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a")
_OWNER_PASSWORD = b"owner"
_PERMISSIONS = -1
_FILE_ID = bytes.fromhex("5f2a9c1e4b7d3a6f8e1c2b4d6a8f0e1c")


def _rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    out = bytearray()
    i = j = 0
    for byte in data:
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out.append(byte ^ s[(s[i] + s[j]) & 0xFF])
    return bytes(out)


def _standard_security() -> tuple[bytes, bytes, bytes]:
    """(O, U, file key) for RC4 40-bit, revision 2, empty user password."""

    owner_key = hashlib.md5((_OWNER_PASSWORD + _PAD)[:32]).digest()[:5]
    o_entry = _rc4(owner_key, _PAD)
    key = hashlib.md5(
        _PAD + o_entry + struct.pack("<i", _PERMISSIONS) + _FILE_ID
    ).digest()[:5]
    u_entry = _rc4(key, _PAD)
    return o_entry, u_entry, key


def _object_key(file_key: bytes, number: int) -> bytes:
    return hashlib.md5(file_key + struct.pack("<I", number)[:3] + b"\x00\x00").digest()[
        :10
    ]


def _escape(text: str) -> bytes:
    raw = text.encode("latin-1", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _content(text: str) -> bytes:
    lines = text.split("\n") if text else []
    ops = [b"BT", b"/F1 12 Tf", b"72 720 Td", b"14 TL"]
    for line in lines:
        ops.append(b"(" + _escape(line) + b") Tj T*")
    ops.append(b"ET")
    return b"\n".join(ops) + b"\n"


def _hex(data: bytes) -> bytes:
    return b"<" + data.hex().encode("ascii") + b">"


def write_pdf(
    path: Path | str,
    pages: list[str],
    *,
    encrypt: bool = False,
    corrupt: bool = False,
) -> Path:
    """Write a PDF whose pages carry `pages[i]` as text (blank page for "")."""

    if not pages:
        raise ValueError("a PDF needs at least one page")
    path = Path(path)
    file_key: bytes | None = None
    security: tuple[bytes, bytes, bytes] | None = None
    if encrypt:
        security = _standard_security()
        file_key = security[2]

    # Object numbering: 1 catalog, 2 pages, 3 font, then page/content pairs,
    # then the encrypt dictionary last.
    objects: dict[int, bytes] = {}
    first_page = 4
    kids = []
    for i, text in enumerate(pages):
        page_num = first_page + 2 * i
        content_num = page_num + 1
        kids.append(f"{page_num} 0 R")
        objects[page_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>"
        ).encode("ascii")
        stream = _content(text)
        if file_key is not None:
            stream = _rc4(_object_key(file_key, content_num), stream)
        objects[content_num] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = (
        f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>"
    ).encode("ascii")
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    encrypt_num = None
    if security is not None:
        o_entry, u_entry, _ = security
        encrypt_num = first_page + 2 * len(pages)
        objects[encrypt_num] = (
            b"<< /Filter /Standard /V 1 /R 2 /Length 40 /P "
            + str(_PERMISSIONS).encode("ascii")
            + b" /O "
            + _hex(o_entry)
            + b" /U "
            + _hex(u_entry)
            + b" >>"
        )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode("ascii") + objects[num] + b"\nendobj\n"
    size = max(objects) + 1
    xref_at = len(out)
    out += f"xref\n0 {size}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for num in range(1, size):
        out += f"{offsets[num]:010d} 00000 n \n".encode("ascii")
    trailer = f"<< /Size {size} /Root 1 0 R".encode("ascii")
    if encrypt_num is not None:
        trailer += f" /Encrypt {encrypt_num} 0 R".encode("ascii")
        trailer += b" /ID [" + _hex(_FILE_ID) + b" " + _hex(_FILE_ID) + b"]"
    trailer += b" >>"
    out += b"trailer\n" + trailer + b"\n"
    out += f"startxref\n{xref_at}\n%%EOF\n".encode("ascii")

    data = bytes(out)
    if corrupt:
        data = data[: max(16, len(data) // 2)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
