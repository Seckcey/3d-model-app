"""Closed-form volume of a FeatureSpec, computed without the CAD kernel.

This is an *independent* check: the solid built by Open CASCADE must match a
volume worked out from textbook formulas. It covers the benchmark feature set
when features do not overlap; anything it cannot compute returns None and the
volume check is reported as "not applicable" rather than passed.
"""

from __future__ import annotations

import math

from .spec import Resolver, hole_diameter

PI = math.pi


def _cylinder(d: float, h: float) -> float:
    return PI / 4.0 * d * d * h


def _drill_point(d: float, angle_deg: float | None) -> float:
    if not angle_deg or angle_deg >= 180:
        return 0.0
    r = d / 2.0
    h = r / math.tan(math.radians(angle_deg) / 2.0)
    return PI * r * r * h / 3.0


def _hole_through_cylinder(R: float, r: float, steps: int = 4000) -> float:
    """Volume of a radial through-hole of radius r across a cylinder of radius R."""
    total = 0.0
    a, b = -r, r
    h = (b - a) / steps
    for i in range(steps + 1):
        y = a + i * h
        f = 4.0 * math.sqrt(max(R * R - y * y, 0.0)) * math.sqrt(max(r * r - y * y, 0.0))
        weight = 1 if i in (0, steps) else (4 if i % 2 else 2)
        total += weight * f
    return total * h / 3.0


def volume(spec: dict, variant: str = "nominal", options: dict | None = None) -> float | None:
    options = options or {}
    value = Resolver(spec, variant)
    features = spec["features"]
    base = features[0]
    if base["type"] == "block":
        L, W, H = (value(v) for v in base["size"])
        total = L * W * H
        extent = {"top": H, "bottom": H, "front": W, "back": W, "left": L, "right": L}
    else:
        segments = [(value(s["diameter"]), value(s["length"])) for s in base["segments"]]
        total = sum(_cylinder(d, length) for d, length in segments)
        L = W = max(d for d, _ in segments)
        H = sum(length for _, length in segments)
        extent = {"end_top": H, "end_bottom": H}
        bounds, z = [], 0.0
        for d, length in segments:
            bounds.append((z, z + length, d / 2.0))
            z += length

        def radius_at(height: float) -> float:
            for z0, z1, r in bounds:
                if z0 <= height <= z1:
                    return r
            raise ValueError(height)

    steps = {}
    for f in features[1:]:
        kind = f["type"]
        if kind == "step":
            x0, x1 = value.point(f["x"])
            y0, y1 = value.point(f["y"])
            floor = value(f["floor_z"])
            total -= (x1 - x0) * (y1 - y0) * (H - floor)
            steps[(round(x0, 9), round(floor, 9))] = (y1 - y0)
        elif kind == "fillet_edge":
            radius = value(f["radius"])
            at = value.point(f["at"])
            key = (round(at[0], 9), round(at[1], 9))
            if f["along"] != "y" or key not in steps:
                return None  # only the concave step corner is covered
            total += (1.0 - PI / 4.0) * radius * radius * steps[key]
        elif kind == "pocket":
            length, width = value.point(f["size"])
            r = value(f.get("corner_radius", 0))
            total -= value(f["depth"]) * (length * width - (4.0 - PI) * r * r)
        elif kind == "slot":
            (sx, sy), (ex, ey) = value.point(f["start"]), value.point(f["end"])
            w = value(f["width"])
            top = value(f["from"]) if "from" in f else H
            depth = top if f["depth"] == "thru" else value(f["depth"])
            centers = math.hypot(ex - sx, ey - sy)
            total -= depth * (centers * w + PI * (w / 2.0) ** 2)
        elif kind == "chamfer":
            c = value(f["size"])
            total -= c * c * (L + W) - 4.0 / 3.0 * c ** 3
        elif kind == "end_chamfer":
            c = value(f["size"])
            r = radius_at(0.0 if f["end"] == "bottom" else H)
            total -= 2.0 * PI * (r - c / 3.0) * (c * c / 2.0)
        elif kind == "groove":
            z = value(f["z"])
            w = value(f["width"])
            r_root = value(f["root_diameter"]) / 2.0
            r = radius_at(z + w / 2.0)
            total -= PI * (r * r - r_root * r_root) * w
        elif kind == "cross_hole":
            z = value(f["z"])
            total -= _hole_through_cylinder(radius_at(z), value(f["diameter"]) / 2.0)
        elif kind == "hole":
            d, step = hole_diameter(f, value, options)
            count = len(f["positions"])
            if "from" in f and f["face"] == "top":
                available = value(f["from"])
            else:
                available = extent[f["face"]]
            thru = f["depth"] == "thru"
            depth = available if thru else value(f["depth"])
            each = _cylinder(d, depth)
            if not thru:
                each += _drill_point(d, f.get("point_angle"))
            cb = f.get("counterbore")
            if cb:
                each += _cylinder(value(cb["diameter"]), value(cb["depth"])) - _cylinder(d, value(cb["depth"]))
            if step:
                step_depth = depth if step["depth"] == "thru" else value(step["depth"])
                each += _cylinder(step["diameter"], step_depth) - _cylinder(d, step_depth)
            if f.get("countersink"):
                return None
            total -= each * count
        else:
            return None
    return total
