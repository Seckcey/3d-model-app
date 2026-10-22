"""Synthetic test drawings. Never use customer drawings as test fixtures."""

from __future__ import annotations

import io


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[list[str]], size: tuple[int, int] = (1224, 792)) -> bytes:
    """A small vector PDF (11x17 landscape by default) with text lines and an outline."""
    width, height = size
    objects: dict[int, bytes] = {}
    page_ids, content_ids = [], []
    next_id = 4
    for _ in pages:
        page_ids.append(next_id)
        content_ids.append(next_id + 1)
        next_id += 2
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for pid, cid, lines in zip(page_ids, content_ids, pages, strict=True):
        ops = ["BT", "/F1 14 Tf", f"60 {height - 60} Td", "18 TL"]
        ops += [f"({_escape(line)}) Tj T*" for line in lines]
        ops += ["ET", "2 w", "420 200 500 260 re S", "1 w", "520 330 m 820 330 l S"]
        stream = "\n".join(ops).encode("latin-1")
        objects[cid] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        objects[pid] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>"
        ).encode()
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for oid in sorted(objects):
        offsets[oid] = len(out)
        out += f"{oid} 0 obj\n".encode() + objects[oid] + b"\nendobj\n"
    xref = len(out)
    count = max(objects) + 1
    out += f"xref\n0 {count}\n0000000000 65535 f \n".encode()
    for oid in range(1, count):
        out += f"{offsets[oid]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


PLATE_DRAWING = [
    "UNLESS OTHERWISE SPECIFIED DIMENSIONS ARE IN INCHES",
    "TOLERANCES: .XX +/-.01  .XXX +/-.005  ANGLES +/-0.5 DEG",
    "THIRD ANGLE PROJECTION",
    "MATERIAL: 6061-T6 ALUMINUM",
    "FINISH: ANODIZE PER MIL-A-8625 TYPE II CLASS 2 BLACK",
    "4X 1/4-20 UNC-2B THRU",
    "2X M6x1.0 - 6H X 12 DEEP",
    "BREAK ALL SHARP EDGES .005-.015",
    "PART NO. BP-1001   REV C   SHEET 1 OF 1",
]

ITAR_DRAWING = PLATE_DRAWING + [
    "WARNING - This document contains technical data whose export is restricted by the",
    "Arms Export Control Act (Title 22, U.S.C., Sec 2751, et seq.) ITAR 22 CFR 120-130.",
    "DISTRIBUTION STATEMENT D. Distribution authorized to the DoD and U.S. DoD contractors only.",
]


def make_png(width: int = 2400, height: int = 1600, blurry: bool = False) -> bytes:
    from PIL import Image, ImageDraw, ImageFilter

    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle([width * 0.2, height * 0.25, width * 0.8, height * 0.75], outline=0, width=3)
    for i in range(10):
        y = int(height * 0.1) + i * 12
        draw.line([(40, y), (width // 3, y)], fill=0, width=1)
    if blurry:
        image = image.filter(ImageFilter.GaussianBlur(radius=6))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()
