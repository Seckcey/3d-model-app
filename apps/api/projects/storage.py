"""Private file storage on the host volume.

Layout under FILES_ROOT (paths stored in the database are relative):
    orgs/<org-id>/sources/<uuid>.<ext>     immutable original drawings
    orgs/<org-id>/artifacts/<uuid>.<ext>   generated files
    staging/<job-id>/...                   worker output before publication
    tmp/                                   upload spooling
Everything is on one filesystem so publication is an atomic rename.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse

CHUNK = 1024 * 1024


@dataclass
class StoredFile:
    storage_path: str
    sha256: str
    size_bytes: int


def root() -> Path:
    return Path(settings.FILES_ROOT)


def ensure_layout() -> None:
    for sub in ("orgs", "staging", "tmp"):
        (root() / sub).mkdir(parents=True, exist_ok=True)


def absolute(storage_path: str) -> Path:
    """Resolve a stored relative path, refusing anything outside FILES_ROOT."""
    base = root().resolve()
    candidate = (base / storage_path).resolve()
    if base != candidate and base not in candidate.parents:
        raise Http404("Invalid storage path")
    return candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TooLarge(Exception):
    pass


def spool_upload(uploaded_file, max_bytes: int) -> tuple[Path, str, int]:
    """Copy an upload to a private temp file, hashing as we go."""
    ensure_layout()
    digest = hashlib.sha256()
    size = 0
    fd, tmp_name = tempfile.mkstemp(dir=root() / "tmp", prefix="upload-")
    try:
        with os.fdopen(fd, "wb") as out:
            for chunk in uploaded_file.chunks(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise TooLarge()
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return Path(tmp_name), digest.hexdigest(), size


def publish(tmp_path: Path, organization_id, *, area: str, extension: str) -> str:
    """Move a finished file into its permanent, read-only location."""
    if area not in {"sources", "artifacts"}:
        raise ValueError(area)
    relative = Path("orgs") / str(organization_id) / area / f"{uuid.uuid4()}{extension}"
    destination = root() / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(tmp_path, 0o440)
    os.replace(tmp_path, destination)
    return relative.as_posix()


def publish_copy(source: Path, organization_id, *, area: str, extension: str) -> str:
    """Publish a staged file produced by a worker (copied then renamed atomically)."""
    ensure_layout()
    fd, tmp_name = tempfile.mkstemp(dir=root() / "tmp", prefix="publish-")
    os.close(fd)
    shutil.copyfile(source, tmp_name)
    return publish(Path(tmp_name), organization_id, area=area, extension=extension)


def remove(storage_path: str) -> None:
    try:
        absolute(storage_path).unlink(missing_ok=True)
    except Http404:
        pass


_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_download_name(name: str, fallback: str = "download") -> str:
    cleaned = _UNSAFE.sub("_", name or "").strip(" .")[:150]
    return cleaned or fallback


def serve(storage_path: str, *, download_name: str, content_type: str | None = None,
          inline: bool = False) -> HttpResponse:
    path = absolute(storage_path)
    if not path.exists():
        raise Http404("File is missing from storage")
    name = safe_download_name(download_name)
    ctype = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    disposition = "inline" if inline else "attachment"
    if settings.USE_X_ACCEL_REDIRECT:
        response = HttpResponse(content_type=ctype)
        response["X-Accel-Redirect"] = settings.X_ACCEL_PREFIX + storage_path
        response["Content-Disposition"] = f'{disposition}; filename="{name}"'
    else:
        response = FileResponse(open(path, "rb"), content_type=ctype, as_attachment=not inline,
                                filename=name)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
