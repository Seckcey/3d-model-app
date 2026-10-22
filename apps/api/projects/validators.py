"""Untrusted upload checks: type by content (not extension), size, page count
and decompression-bomb limits."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
EXTENSIONS = {PDF: ".pdf", PNG: ".png", JPEG: ".jpg"}


class UploadRejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Inspection:
    content_type: str
    page_count: int
    width_px: int | None = None
    height_px: int | None = None


def sniff(head: bytes) -> str | None:
    if head.startswith(b"%PDF-"):
        return PDF
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    return None


def inspect(path: Path, *, max_pages: int) -> Inspection:
    with open(path, "rb") as handle:
        head = handle.read(16)
    content_type = sniff(head)
    if content_type is None:
        raise UploadRejected(
            "unsupported_type", "Only PDF, PNG and JPEG drawings are supported."
        )
    if content_type == PDF:
        return _inspect_pdf(path, max_pages)
    return _inspect_image(path, content_type)


def _inspect_pdf(path: Path, max_pages: int) -> Inspection:
    import pypdfium2 as pdfium

    try:
        document = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        message = str(exc).lower()
        if "password" in message:
            raise UploadRejected(
                "encrypted_pdf", "This PDF is password protected. Upload an unlocked copy."
            ) from exc
        raise UploadRejected("corrupt_pdf", "This PDF could not be opened.") from exc
    try:
        pages = len(document)
    finally:
        document.close()
    if pages == 0:
        raise UploadRejected("empty_pdf", "This PDF has no pages.")
    if pages > max_pages:
        raise UploadRejected(
            "too_many_pages",
            f"This PDF has {pages} pages; the limit is {max_pages}. Upload only the sheets "
            "for this part.",
        )
    return Inspection(content_type=PDF, page_count=pages)


def _inspect_image(path: Path, content_type: str) -> Inspection:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = settings.MAX_IMAGE_PIXELS
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
    except Image.DecompressionBombError as exc:
        raise UploadRejected("image_too_large", "This image is too large to process.") from exc
    except Exception as exc:  # noqa: BLE001 - Pillow raises many types for bad input
        raise UploadRejected("corrupt_image", "This image could not be read.") from exc
    if width * height > settings.MAX_IMAGE_PIXELS:
        raise UploadRejected("image_too_large", "This image is too large to process.")
    return Inspection(content_type=content_type, page_count=1, width_px=width, height_px=height)
