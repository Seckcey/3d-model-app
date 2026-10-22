"""Phase 1 drawing intake check.

Runs locally (no external services). For each page it records size, whether
vector text is present, a sharpness estimate and preview images. It scans the
vector text for export-control markings and collects unverified "drawing
hints" (units, projection, revision, material, threads, outside processes).
Raster pages are not OCR'd until Phase 2, so their markings are reported as
"not scanned" rather than "none found".
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from .validators import PDF

PAGE_IMAGE_MAX_PX = 2400
THUMBNAIL_MAX_PX = 480
MIN_TEXT_CHARS = 25
BLUR_WARNING_SCORE = 60.0
LOW_RES_LONG_SIDE_PX = 1500

# (kind, severity, pattern). "block" markings disable external processing until
# an owner reviews the drawing.
MARKING_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    # Classified material must never be stored here; the owner removes it.
    ("CLASSIFIED", "block", re.compile(
        r"\bTOP\s+SECRET\b|\bSECRET\s*//|\bCLASSIFIED\s+BY\s*:|\bDECLASSIFY\s+ON\s*:", re.I)),
    ("ITAR", "block", re.compile(r"\bITAR\b|international\s+traffic\s+in\s+arms|\bUSML\b", re.I)),
    ("ITAR", "block", re.compile(r"22\s*C\.?\s*F\.?\s*R\.?\s*(?:parts?\s*)?12[0-9]", re.I)),
    ("EXPORT WARNING", "block", re.compile(
        r"arms\s+export\s+control\s+act|export\s+administration\s+act|DoD\s*D(?:irective)?\s*5230\.25",
        re.I)),
    ("EAR", "block", re.compile(r"export\s+administration\s+regulations", re.I)),
    ("EAR", "block", re.compile(r"15\s*C\.?\s*F\.?\s*R\.?\s*(?:parts?\s*)?7[3-7][0-9]", re.I)),
    ("ECCN", "block", re.compile(r"\bECCN\b|\bEAR99\b|\b[0-9][A-E][0-9]{3}[a-z]?\b(?=.{0,40}ECCN)", re.I)),
    ("EXPORT CONTROLLED", "block", re.compile(
        r"export[\s-]+controlled|export[\s-]+control\s+(?:warning|notice)", re.I)),
    ("CUI", "block", re.compile(r"\bCUI\b|controlled\s+unclassified\s+information", re.I)),
    ("CUI DISSEMINATION", "block", re.compile(
        r"\bFED\s*ONLY\b|\bFEDCON\b|\bNOCON\b|\bDL\s+ONLY\b|\bREL\s+TO\b|\bDISPLAY\s+ONLY\b", re.I)),
    ("NOFORN", "block", re.compile(r"\bNOFORN\b", re.I)),
    ("DISTRIBUTION STATEMENT", "block", re.compile(r"distribution\s+statement\s+[B-F]\b", re.I)),
    ("DISTRIBUTION STATEMENT", "block", re.compile(
        r"distribution\s+authorized\s+to\s+(?:U\.?\s*S\.?\s+government|DoD)"
        r"|further\s+dissemination\s+only\s+as\s+directed\s+by", re.I)),
    ("FOUO", "block", re.compile(r"\bFOUO\b|for\s+official\s+use\s+only", re.I)),
    ("DESTRUCTION NOTICE", "info", re.compile(r"destruction\s+notice", re.I)),
    ("DISTRIBUTION A", "info", re.compile(r"distribution\s+statement\s+A\b", re.I)),
    ("PROPRIETARY", "info", re.compile(r"\bproprietary\b|\bconfidential\b", re.I)),
]

OUTSIDE_PROCESSES = {
    "anodize": r"\banodi[sz]e\b|\banodi[sz]ing\b|MIL-A-8625|MIL-PRF-8625",
    "hardcoat": r"\bhard\s*coat\b|\btype\s+III\b",
    "chem film": r"\bchem(?:ical)?\s*film\b|\balodine\b|\bchromate\s+conversion\b|MIL-DTL-5541",
    "passivate": r"\bpassivat(?:e|ion)\b|AMS\s*2700|ASTM\s*A967",
    "heat treat": r"\bheat\s*treat|\bharden(?:ed)?\b|\bHRC\b|\bRockwell\b",
    "plating": r"\b(?:zinc|nickel|chrome|cadmium|electroless)\s+plat",
    "black oxide": r"\bblack\s+oxide\b",
    "powder coat": r"\bpowder\s*coat",
    "nitride": r"\bnitrid(?:e|ing)\b",
    "paint": r"\bpaint\b|\bprimer\b",
}
THREAD_PATTERN = re.compile(
    r"(?:#\d{1,2}|\d+/\d+|\d+(?:\.\d+)?)\s*-\s*\d{1,3}\s*UN[CFEJ]?R?\b(?:\s*-\s*[123][AB]\b)?"  # 1/4-20 UNC-2B
    r"|\bM\d{1,2}(?:\.\d+)?\s*[xX×]\s*\d(?:\.\d+)?\b(?:\s*-\s*\d[gGhH](?:\d[gGhH])?\b)?"  # M6x1.0-6H
    r"|\b\d+/\d+\s*-\s*\d+\s*N(?:PT|PTF)\b",  # 1/8-27 NPT
)
REVISION_PATTERN = re.compile(r"\bREV(?:ISION)?\b\.?\s*[:#]?\s*([A-Z]{1,2}|\d{1,2})\b")
# ASME Y14.35 does not use I, O, Q, S, X or Z as revision letters; the words
# are column headings that often follow "REV" in revision blocks.
NOT_REVISIONS = {"I", "O", "Q", "S", "X", "Z", "BY", "NO", "OF", "IS", "TO", "IN", "AT", "ON"}
MATERIAL_PATTERN = re.compile(r"\bMAT(?:ERIA)?L\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9 .\-/]{2,40})")
GENERAL_TOL_PATTERN = re.compile(r"\.X{1,4}\s*[±+]|X\.X{1,4}\s*[±+]|ISO\s*2768", re.I)


@dataclass
class PageResult:
    number: int
    width_in: float | None
    height_in: float | None
    text_chars: int
    has_vector_text: bool
    sharpness: float
    width_px: int
    height_px: int
    page_image: Path | None = None
    thumbnail: Path | None = None


@dataclass
class IntakeResult:
    report: dict
    status: str
    pages: list[PageResult] = field(default_factory=list)
    markings: list[dict] = field(default_factory=list)
    workdir: Path | None = None


def sharpness_score(image: Image.Image) -> float:
    """Mean of the strongest 0.5% Laplacian responses on a grayscale image.

    Thin sharp lines give strong responses; blurred scans and phone photos give
    weak ones. It is a heuristic used only to warn, never to block.
    """
    gray = np.asarray(image.convert("L"), dtype=np.float32)
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0
    lap = (
        -4 * gray[1:-1, 1:-1]
        + gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
    )
    magnitudes = np.abs(lap).ravel()
    count = max(1, magnitudes.size // 200)
    top = np.partition(magnitudes, magnitudes.size - count)[-count:]
    return round(float(top.mean()), 1)


def _fit(image: Image.Image, max_px: int) -> Image.Image:
    scale = max_px / max(image.size)
    if scale >= 1:
        return image.copy()
    return image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                        Image.LANCZOS)


def _snippet(text: str, start: int, end: int) -> str:
    """Context around a match, trimmed to whole words."""
    lo, hi = max(0, start - 50), min(len(text), end + 70)
    if lo > 0:
        space = text.find(" ", lo, start)
        lo = space + 1 if space != -1 else start
    if hi < len(text):
        space = text.rfind(" ", end, hi)
        hi = space if space != -1 else end
    return " ".join(text[lo:hi].split())[:160]


def scan_markings(text: str, page: int) -> list[dict]:
    """One finding per marking kind per page (several patterns can name the same kind)."""
    found: dict[str, dict] = {}
    for kind, severity, pattern in MARKING_PATTERNS:
        if kind in found:
            continue
        match = pattern.search(text)
        if match:
            found[kind] = {"kind": kind, "severity": severity, "page": page,
                           "text": _snippet(text, match.start(), match.end())}
    return list(found.values())


def drawing_hints(text: str) -> dict:
    upper = text.upper()
    inch = len(re.findall(r"\bINCH(?:ES)?\b", upper))
    mm = len(re.findall(r"\bMILLIMET(?:ER|RE)S?\b|\bMM\b", upper))
    units = "in" if inch > mm else "mm" if mm > inch else None
    projection = None
    if re.search(r"THIRD\s*[- ]?\s*ANGLE", upper):
        projection = "third_angle"
    elif re.search(r"FIRST\s*[- ]?\s*ANGLE", upper):
        projection = "first_angle"
    revisions = sorted(
        {m.group(1) for m in REVISION_PATTERN.finditer(upper)} - NOT_REVISIONS
    )[:5]
    materials = []
    for m in MATERIAL_PATTERN.finditer(upper):
        value = " ".join(m.group(1).split())
        if value not in materials:
            materials.append(value)
    processes = [name for name, pattern in OUTSIDE_PROCESSES.items() if re.search(pattern, text, re.I)]
    threads = sorted({" ".join(m.group(0).split()) for m in THREAD_PATTERN.finditer(text)})
    return {
        "units": units,
        "projection": projection,
        "revision_candidates": revisions,
        "material_candidates": materials[:3],
        "outside_processes": processes,
        "thread_callouts": threads[:20],
        "general_tolerance_block": bool(GENERAL_TOL_PATTERN.search(text)),
        "unless_otherwise_specified": bool(re.search(r"UNLESS\s+OTHERWISE\s+(SPECIFIED|NOTED)", upper)),
    }


def _write_previews(image: Image.Image, workdir: Path, number: int, page: PageResult) -> None:
    page_image = _fit(image, PAGE_IMAGE_MAX_PX).convert("RGB")
    page.page_image = workdir / f"page-{number}.png"
    page_image.save(page.page_image, "PNG", optimize=True)
    thumb = _fit(image, THUMBNAIL_MAX_PX).convert("RGB")
    page.thumbnail = workdir / f"thumb-{number}.webp"
    thumb.save(page.thumbnail, "WEBP", quality=82)


def run(path: Path, content_type: str, *, expected_revision: str = "") -> IntakeResult:
    workdir = Path(tempfile.mkdtemp(prefix="intake-"))
    pages: list[PageResult] = []
    markings: list[dict] = []
    all_text: list[str] = []
    warnings: list[dict] = []

    if content_type == PDF:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(str(path))
        try:
            for index in range(len(document)):
                page = document[index]
                width_pt, height_pt = page.get_size()
                textpage = page.get_textpage()
                text = textpage.get_text_bounded() or ""
                chars = len(text.strip())
                textpage.close()
                longest_in = max(width_pt, height_pt) / 72.0
                scale = min(150 / 72.0, PAGE_IMAGE_MAX_PX / max(width_pt, height_pt))
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                result = PageResult(
                    number=index + 1,
                    width_in=round(width_pt / 72.0, 2),
                    height_in=round(height_pt / 72.0, 2),
                    text_chars=chars,
                    has_vector_text=chars >= MIN_TEXT_CHARS,
                    sharpness=sharpness_score(image),
                    width_px=image.width,
                    height_px=image.height,
                )
                _write_previews(image, workdir, index + 1, result)
                image.close()
                page.close()
                pages.append(result)
                if result.has_vector_text:
                    all_text.append(text)
                    markings.extend(scan_markings(text, index + 1))
                else:
                    warnings.append({
                        "code": "raster_page",
                        "page": index + 1,
                        "message": "No vector text on this page (likely a scan). Markings and "
                                   "dimensions will need OCR in Phase 2.",
                    })
                if longest_in > 50:
                    warnings.append({"code": "unusual_page_size", "page": index + 1,
                                     "message": f"Page is {longest_in:.0f} in on its long side."})
        finally:
            document.close()
    else:
        with Image.open(path) as source:
            image = source.convert("RGB")
            dpi = source.info.get("dpi")
        result = PageResult(
            number=1,
            width_in=round(image.width / dpi[0], 2) if dpi and dpi[0] else None,
            height_in=round(image.height / dpi[1], 2) if dpi and dpi[1] else None,
            text_chars=0,
            has_vector_text=False,
            sharpness=sharpness_score(_fit(image, PAGE_IMAGE_MAX_PX)),
            width_px=image.width,
            height_px=image.height,
        )
        _write_previews(image, workdir, 1, result)
        pages.append(result)
        if max(image.width, image.height) < LOW_RES_LONG_SIDE_PX:
            warnings.append({
                "code": "low_resolution", "page": 1,
                "message": f"Image is only {image.width}x{image.height} px; small dimension text "
                           "may be unreadable. Scan at 300 dpi or upload the PDF.",
            })
        warnings.append({"code": "raster_page", "page": 1,
                         "message": "Image upload: markings and dimensions need OCR in Phase 2."})

    for page in pages:
        if page.sharpness < BLUR_WARNING_SCORE:
            warnings.append({
                "code": "possibly_blurry", "page": page.number,
                "message": f"Low sharpness score ({page.sharpness}). Check that small text is legible.",
            })

    hints = drawing_hints("\n".join(all_text)) if all_text else None
    if hints and expected_revision and hints["revision_candidates"]:
        if expected_revision.upper() not in hints["revision_candidates"]:
            warnings.append({
                "code": "revision_mismatch",
                "message": f"Title block text mentions revision {', '.join(hints['revision_candidates'])} "
                           f"but this upload is labelled revision {expected_revision}. Confirm you "
                           "are working to the right drawing.",
            })

    blocking = [m for m in markings if m["severity"] == "block"]
    any_vector = any(p.has_vector_text for p in pages)
    all_vector = all(p.has_vector_text for p in pages)
    if blocking:
        export_control = "detected"
    elif all_vector:
        export_control = "none_found"
    else:
        export_control = "not_scanned" if not any_vector else "partially_scanned"

    report = {
        "version": 1,
        "page_count": len(pages),
        "pages": [
            {
                "number": p.number,
                "width_in": p.width_in,
                "height_in": p.height_in,
                "has_vector_text": p.has_vector_text,
                "text_chars": p.text_chars,
                "sharpness": p.sharpness,
                "render_px": [p.width_px, p.height_px],
            }
            for p in pages
        ],
        "warnings": warnings,
        "export_control": {"status": export_control, "markings": markings},
        "hints": hints,
        "notes": [
            "Hints are unverified text matches for the reviewer, not extracted requirements.",
        ],
    }
    status = "warning" if warnings or blocking else "ok"
    return IntakeResult(report=report, status=status, pages=pages, markings=markings, workdir=workdir)
