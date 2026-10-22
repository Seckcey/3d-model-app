"""Phase 0 geometry benchmark: build the reference parts in the isolated CAD
worker, export STEP/GLB, reopen the STEP and check it against expectations
written independently in each spec. Shops download the files and confirm they
import correctly in their own Fusion and Mastercam installations."""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings

EXAMPLES = ("plate-with-holes.json", "bracket-block.json", "stepped-shaft.json")


def load_reference_specs() -> list[dict]:
    directory = Path(settings.FEATURE_SPEC_DIR) / "examples"
    return [json.loads((directory / name).read_text(encoding="utf-8")) for name in EXAMPLES]


def build_options(preferences: dict) -> dict:
    return {
        "step_units": preferences.get("step_units", "drawing"),
        "tapped_hole_model": preferences.get("tapped_hole_model", "tap_drill"),
        "also_export_mid_tolerance": bool(preferences.get("also_export_mid_tolerance", True)),
        "color_faces_by_hole_type": bool(preferences.get("color_faces_by_hole_type", True)),
        "filename_pattern": preferences.get("filename_pattern", "{part}_REV{rev}_{kind}"),
    }
