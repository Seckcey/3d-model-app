"""Checks that a built solid satisfies its spec.

Every expected value comes from the spec (the drawing's numbers) or from the
closed-form calculator in analytic.py; every measured value is read back from
the B-rep. A plausible-looking solid with a missing or misplaced feature fails.
"""

from __future__ import annotations

from . import analytic, measure
from .build import Built
from .spec import MM_PER, Resolver

EPS = {"in": 1e-5, "mm": 2.5e-4}  # geometric epsilon in spec units
VOLUME_REL_EPS = 1e-6


def _check(checks, *, check, expected, measured, eps, feature="", instance=None, dims=None,
           units="", label=""):
    if measured is None:
        status = "fail"
    elif isinstance(expected, bool) or isinstance(expected, int) and not isinstance(expected, float):
        status = "pass" if measured == expected else "fail"
    else:
        status = "pass" if abs(measured - expected) <= eps else "fail"
    checks.append({
        "check": check, "label": label, "feature": feature, "instance": instance,
        "dims": dims or [], "expected": expected,
        "measured": round(measured, 6) if isinstance(measured, float) else measured,
        "units": units, "status": status,
    })


def validate(spec: dict, built: Built, *, variant: str, options: dict) -> dict:
    units = spec["units"]
    scale = MM_PER[units]
    eps = EPS[units]
    value = Resolver(spec, variant)
    checks: list[dict] = []
    shape = built.shape

    _check(checks, check="valid_solid", label="Solid is topologically valid", expected=True,
           measured=measure.is_valid(shape), eps=0)
    _check(checks, check="solid_count", label="Exactly one body", expected=1,
           measured=len(shape.Solids()), eps=0)

    xmin, ymin, zmin, xmax, ymax, zmax = measure.exact_bbox(shape)
    base = spec["features"][0]
    if base["type"] == "block":
        expected_extents = [value(v) for v in base["size"]]
        labels = ["Overall length (X)", "Overall width (Y)", "Overall height (Z)"]
        base_dims = [[v["dim"]] if isinstance(v, dict) else [] for v in base["size"]]
    else:
        diameters = [value(s["diameter"]) for s in base["segments"]]
        expected_extents = [max(diameters), max(diameters), sum(value(s["length"]) for s in base["segments"])]
        labels = ["Largest diameter (X)", "Largest diameter (Y)", "Overall length (Z)"]
        base_dims = [[], [], [s["length"]["dim"] for s in base["segments"] if isinstance(s["length"], dict)]]
    for label, expected, lo, hi, dims in zip(labels, expected_extents, (xmin, ymin, zmin),
                                             (xmax, ymax, zmax), base_dims, strict=True):
        _check(checks, check="extent", label=label, expected=round(expected, 6),
               measured=(hi - lo) / scale, eps=eps, feature=base["id"], dims=dims, units=units)
    origin_ok = abs(zmin) / scale <= eps and (built.turned or (abs(xmin) / scale <= eps
                                                                and abs(ymin) / scale <= eps))
    checks.append({"check": "origin", "label": "Origin at datum reference frame", "feature": base["id"],
                   "instance": None, "dims": [], "expected": "A/B/C", "measured":
                   [round(xmin / scale, 6), round(ymin / scale, 6), round(zmin / scale, 6)],
                   "units": units, "status": "pass" if origin_ok else "fail"})

    expected_volume = analytic.volume(spec, variant, options)
    measured_volume = shape.Volume() / scale ** 3
    if expected_volume is None:
        checks.append({"check": "volume", "label": "Volume vs closed-form calculation", "feature": "",
                       "instance": None, "dims": [], "expected": None,
                       "measured": round(measured_volume, 6), "units": f"{units}^3",
                       "status": "not_applicable"})
    else:
        _check(checks, check="volume", label="Volume vs closed-form calculation",
               expected=round(expected_volume, 6), measured=measured_volume,
               eps=max(abs(expected_volume) * VOLUME_REL_EPS, 1e-9), units=f"{units}^3")

    cyls = measure.cylinders(shape)
    hole_faces: list[tuple] = []
    features = {f["id"]: f for f in spec["features"]}
    for hole in built.holes:
        f = features[hole.feature]
        dims = f.get("dims", [])
        label = f"{hole.feature} #{hole.index}" + (f" {hole.thread}" if hole.thread else "")
        match = measure.match_axis(cyls, hole, hole.diameter)
        _check(checks, check="hole_diameter", label=f"{label} bore Ø", feature=hole.feature,
               instance=hole.index, dims=dims, units=units, expected=round(hole.diameter / scale, 6),
               measured=(2 * match.radius / scale) if match else None, eps=eps)
        if match is None:
            continue
        hole_faces.append((hole.hole_type, match.faces))
        measured_uv = [c / scale for c in measure.face_uv(hole.face, match.axis_point)]
        offset = ((measured_uv[0] - hole.uv[0]) ** 2 + (measured_uv[1] - hole.uv[1]) ** 2) ** 0.5
        checks.append({
            "check": "hole_position", "label": f"{label} position on {hole.face}",
            "feature": hole.feature, "instance": hole.index, "dims": dims, "units": units,
            "expected": [round(c, 6) for c in hole.uv],
            "measured": [round(c, 6) for c in measured_uv],
            "status": "pass" if offset <= eps else "fail",
        })
        if hole.depth is not None:
            _check(checks, check="hole_depth", label=f"{label} full-diameter depth",
                   feature=hole.feature, instance=hole.index, dims=dims, units=units,
                   expected=round(hole.depth / scale, 6), measured=match.depth / scale, eps=eps)
        for extra, kind, what in ((hole.counterbore, "counterbore", "counterbore"),
                                  (hole.thread_step, "thread_step", "thread major Ø step")):
            if not extra:
                continue
            step_match = measure.match_axis(cyls, hole, extra[0])
            _check(checks, check=f"{kind}_diameter", label=f"{label} {what}", feature=hole.feature,
                   instance=hole.index, dims=dims, units=units, expected=round(extra[0] / scale, 6),
                   measured=(2 * step_match.radius / scale) if step_match else None, eps=eps)
            if step_match:
                hole_faces.append(("counterbore" if kind == "counterbore" else hole.hole_type,
                                   step_match.faces))
                _check(checks, check=f"{kind}_depth", label=f"{label} {what} depth",
                       feature=hole.feature, instance=hole.index, dims=dims, units=units,
                       expected=round(extra[1] / scale, 6), measured=step_match.depth / scale, eps=eps)

    failed = [c for c in checks if c["status"] == "fail"]
    return {
        "passed": not failed,
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": sum(1 for c in checks if c["status"] == "pass"),
            "failed": len(failed),
            "not_applicable": sum(1 for c in checks if c["status"] == "not_applicable"),
            "volume": round(measured_volume, 6),
            "volume_units": f"{units}^3",
            "bbox": [round((xmax - xmin) / scale, 6), round((ymax - ymin) / scale, 6),
                     round((zmax - zmin) / scale, 6)],
        },
        "_hole_faces": hole_faces,
    }
