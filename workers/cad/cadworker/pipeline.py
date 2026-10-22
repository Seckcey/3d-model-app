"""One part, one variant: build, verify, export, reopen and re-verify."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import build, export, measure, naming, validate
from .spec import MM_PER

DISCLAIMER = (
    "Reference geometry generated from the specification below. The customer drawing governs. "
    "Tolerances, GD&T and surface finish are requirements recorded in this report, not "
    "properties of the solid. Threads are represented by plain bores sized per the shop "
    "preference; thread data is listed in the hole table."
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entry(path: Path, kind: str) -> dict:
    return {"name": path.name, "kind": kind, "sha256": _sha256(path), "size": path.stat().st_size}


def hole_table(spec: dict, built: build.Built) -> list[dict]:
    scale = MM_PER[spec["units"]]
    rows = []
    for hole in built.holes:
        rows.append({
            "feature": hole.feature, "instance": hole.index, "type": hole.hole_type,
            "face": hole.face, "u": round(hole.uv[0], 4), "v": round(hole.uv[1], 4),
            "modeled_diameter": round(hole.diameter / scale, 4),
            "depth": "THRU" if hole.depth is None else round(hole.depth / scale, 4),
            "thread": hole.thread or "",
            "counterbore": (f"Ø{hole.counterbore[0] / scale:.4f} x {hole.counterbore[1] / scale:.4f}"
                            if hole.counterbore else ""),
        })
    return rows


def run_part(spec: dict, variant: str, options: dict, outdir: Path) -> dict:
    part = spec["part"]
    built = build.build(spec, variant, options)
    report = validate.validate(spec, built, variant=variant, options=options)
    hole_faces = report.pop("_hole_faces")
    colors = hole_faces if options.get("color_faces_by_hole_type", True) else []
    units_out = spec["units"] if options.get("step_units", "drawing") == "drawing" else options["step_units"]
    base = naming.filename(options.get("filename_pattern"), part=part["number"],
                           rev=part.get("revision", ""), variant=variant, units=units_out,
                           customer=options.get("customer", ""))
    tapped_model = options.get("tapped_hole_model", "tap_drill")
    description = (
        f"Blueprint to CAD reference geometry. Part {part['number']} rev {part.get('revision', '')}. "
        f"Variant {naming.VARIANT_TAGS[variant]}. Units {naming.UNIT_TAGS[units_out]}. "
        f"Tapped holes modeled as {tapped_model}. The drawing governs; tolerances and GD&T "
        "are not represented in this solid."
    )

    step_path = outdir / f"{base}.step"
    export.write_step(built.shape, step_path, name=part["number"], units=units_out,
                      description=description, face_colors=colors,
                      schema=options.get("step_schema", "AP214"))

    # Reopen the exported file and compare it with the solid we built.
    reopened = export.reimport_step(step_path)
    original_volume = built.shape.Volume()
    reopened_volume = reopened.Volume()
    rel = abs(reopened_volume - original_volume) / original_volume
    checks = report["checks"]
    checks.append({"check": "step_roundtrip_volume", "label": "STEP reopens with the same volume",
                   "feature": "", "instance": None, "dims": [], "expected": 0.0,
                   "measured": float(f"{rel:.3e}"), "units": "relative",
                   "status": "pass" if rel <= 1e-6 else "fail"})
    a, b = measure.exact_bbox(built.shape), measure.exact_bbox(reopened)
    drift = max(abs(x - y) for x, y in zip(a, b, strict=True))
    checks.append({"check": "step_roundtrip_bbox", "label": "STEP reopens at the same size and origin",
                   "feature": "", "instance": None, "dims": [], "expected": 0.0,
                   "measured": round(drift / MM_PER[spec["units"]], 9), "units": spec["units"],
                   "status": "pass" if drift <= 1e-4 else "fail"})
    declared = export.declared_unit(step_path)
    checks.append({"check": "step_units", "label": "STEP declares the intended length unit",
                   "feature": "", "instance": None, "dims": [], "expected": units_out,
                   "measured": declared, "units": "",
                   "status": "pass" if declared == units_out else "fail"})
    failed = [c for c in checks if c["status"] == "fail"]
    report["passed"] = not failed
    report["summary"].update({
        "total": len(checks),
        "passed": sum(1 for c in checks if c["status"] == "pass"),
        "failed": len(failed),
    })

    glb_path = outdir / f"{base}.glb"
    export.write_glb(built.shape, glb_path, name=part["number"], face_colors=colors)

    document = {
        "schema": "bpcad-check-report/1",
        "part": part,
        "family": spec["family"],
        "variant": variant,
        "units": spec["units"],
        "step_units": units_out,
        "options": {k: options.get(k) for k in ("tapped_hole_model", "tap_drill_basis",
                                                 "step_units", "step_schema")},
        "material": spec.get("material"),
        "dimensions": spec["dimensions"],
        "notes": spec.get("notes", []),
        "hole_table": hole_table(spec, built),
        "color_legend": {k: "#" + "".join(f"{int(c * 255):02x}" for c in v)
                         for k, v in export.HOLE_COLORS.items()},
        "validation": report,
        "build_log": built.log,
        "disclaimer": DISCLAIMER,
    }
    report_path = outdir / f"{base}.report.json"
    report_path.write_text(json.dumps(document, indent=2), encoding="utf-8")

    return {
        "part": part["number"],
        "title": part.get("name", ""),
        "variant": variant,
        "validation": {"passed": report["passed"], "summary": report["summary"],
                       "checks": report["checks"]},
        "hole_table": document["hole_table"],
        "files": [_entry(step_path, "step"), _entry(glb_path, "glb"), _entry(report_path, "report")],
    }
