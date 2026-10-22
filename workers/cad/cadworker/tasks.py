from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import time
from pathlib import Path

from celery.exceptions import SoftTimeLimitExceeded

from . import pipeline
from . import spec as specmod
from .celery_app import app

logger = logging.getLogger("cadworker")
# The API (same group, different user) must read and then delete staged files.
os.umask(0o007)
JOB_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_SPECS = 10


def staging_root() -> Path:
    return Path(os.environ.get("STAGING_ROOT", "/data/staging"))


def engine_versions() -> dict:
    import cadquery
    import OCP

    return {"cadquery": cadquery.__version__, "ocp": getattr(OCP, "__version__", "unknown"),
            "python": platform.python_version(), "cadworker": "0.1.0"}


def _error(code: str, message: str, retryable: bool = False) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, "retryable": retryable}}


def run(job_id: str, specs: list, options: dict) -> dict:
    started = time.monotonic()
    if not isinstance(job_id, str) or not JOB_ID.match(job_id):
        return _error("invalid_job", "Malformed job identifier.")
    if not isinstance(specs, list) or not 1 <= len(specs) <= MAX_SPECS:
        return _error("invalid_spec", f"Send between 1 and {MAX_SPECS} specs.")
    options = options if isinstance(options, dict) else {}
    outdir = staging_root() / job_id
    shutil.rmtree(outdir, ignore_errors=True)  # a retry starts from a clean directory
    outdir.mkdir(parents=True, mode=0o770)
    try:
        parts = []
        for spec in specs:
            specmod.validate(spec)
            variants = ["nominal"]
            if options.get("also_export_mid_tolerance", True) and specmod.differs_by_variant(spec):
                variants.append("mid_tolerance")
            for variant in variants:
                parts.append(pipeline.run_part(spec, variant, options, outdir))
        return {"ok": True, "engine": engine_versions(), "parts": parts,
                "elapsed_s": round(time.monotonic() - started, 3)}
    except specmod.SpecError as exc:
        shutil.rmtree(outdir, ignore_errors=True)
        return _error(exc.code, exc.message)
    except SoftTimeLimitExceeded:
        shutil.rmtree(outdir, ignore_errors=True)
        return _error("timeout", "The geometry job exceeded its time limit.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("geometry job %s crashed", job_id)
        shutil.rmtree(outdir, ignore_errors=True)
        return _error("cad_crash", f"Geometry engine error ({type(exc).__name__}).", retryable=True)


@app.task(name="cad.build_parts")
def build_parts(job_id: str, specs: list, options: dict) -> dict:
    return run(job_id, specs, options)
