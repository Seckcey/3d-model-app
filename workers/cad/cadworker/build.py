"""Deterministic FeatureSpec interpreter.

Only the feature types in BUILDERS can be built; each one is plain parameter
code against CadQuery/Open CASCADE. Nothing from a spec is evaluated or
executed. Geometry is built in millimetres; spec values are scaled from the
drawing's units on the way in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cadquery as cq

from .spec import MM_PER, Resolver, SpecError, hole_diameter

MARGIN = 1.0  # mm of overshoot so cutting tools never leave coplanar slivers
V = cq.Vector


@dataclass
class HoleInstance:
    """An expected hole axis, used to colour faces and to measure the result."""

    feature: str
    index: int
    hole_type: str
    point: tuple[float, float, float]  # on the entry face, mm
    direction: tuple[float, float, float]  # into the material
    diameter: float  # modelled bore, mm
    depth: float | None  # full-diameter depth, mm (None = through)
    face: str
    uv: tuple[float, float]  # position in the face's 2D frame, spec units
    counterbore: tuple[float, float] | None = None  # (diameter, depth) mm
    thread_step: tuple[float, float] | None = None
    thread: str | None = None


@dataclass
class Built:
    shape: cq.Shape
    holes: list[HoleInstance] = field(default_factory=list)
    extents: tuple[float, float, float] = (0.0, 0.0, 0.0)  # expected L, W, H in mm
    turned: bool = False
    log: list[str] = field(default_factory=list)


class Context:
    def __init__(self, spec: dict, variant: str, options: dict):
        self.spec = spec
        self.value = Resolver(spec, variant)
        self.scale = MM_PER[spec["units"]]
        self.options = options
        self.shape: cq.Shape | None = None
        self.L = self.W = self.H = 0.0
        self.segments: list[tuple[float, float, float]] = []  # (z0, z1, radius) mm
        self.holes: list[HoleInstance] = []
        self.log: list[str] = []

    def mm(self, raw) -> float:
        return self.value(raw) * self.scale

    def mm_pos(self, raw, what: str) -> float:
        return self.value.positive(raw, what) * self.scale

    def cut(self, tool: cq.Shape, feature_id: str) -> None:
        before = self.shape.Volume()
        result = self.shape.cut(tool).clean()
        if result.Volume() >= before - 1e-9:
            raise SpecError("feature_failed", f"{feature_id} removed no material; check its position")
        self.shape = result

    def radius_at(self, z: float) -> float:
        for z0, z1, r in self.segments:
            if z0 - 1e-9 <= z <= z1 + 1e-9:
                return r
        raise SpecError("invalid_spec", f"height {z / self.scale:.4f} is outside the part")


def _block(ctx: Context, f: dict) -> None:
    ctx.L, ctx.W, ctx.H = (ctx.mm_pos(v, f"{f['id']} size") for v in f["size"])
    ctx.shape = cq.Solid.makeBox(ctx.L, ctx.W, ctx.H)


def _turned_profile(ctx: Context, f: dict) -> None:
    z = 0.0
    solid = None
    for i, seg in enumerate(f["segments"]):
        d = ctx.mm_pos(seg["diameter"], f"{f['id']} segment {i + 1} diameter")
        length = ctx.mm_pos(seg["length"], f"{f['id']} segment {i + 1} length")
        cylinder = cq.Solid.makeCylinder(d / 2.0, length, V(0, 0, z), V(0, 0, 1))
        solid = cylinder if solid is None else solid.fuse(cylinder)
        ctx.segments.append((z, z + length, d / 2.0))
        z += length
    ctx.shape = solid.clean()
    ctx.L = ctx.W = 2.0 * max(r for _, _, r in ctx.segments)
    ctx.H = z


def _step(ctx: Context, f: dict) -> None:
    x0, x1 = (ctx.mm(v) for v in f["x"])
    y0, y1 = (ctx.mm(v) for v in f["y"])
    floor = ctx.mm(f["floor_z"])
    if not (x1 > x0 and y1 > y0 and 0 < floor < ctx.H):
        raise SpecError("invalid_spec", f"{f['id']}: step region is empty or outside the stock")

    def grow(lo, hi, size):
        return (lo - MARGIN if lo <= 1e-9 else lo, hi + MARGIN if hi >= size - 1e-9 else hi)

    x0, x1 = grow(x0, x1, ctx.L)
    y0, y1 = grow(y0, y1, ctx.W)
    tool = cq.Solid.makeBox(x1 - x0, y1 - y0, ctx.H - floor + MARGIN, V(x0, y0, floor))
    ctx.cut(tool, f["id"])


FACE_FRAMES = {
    # face: (point from (u, v, length/width/height), drilling direction)
    "top": (lambda u, v, c: (u, v, c.H), (0, 0, -1)),
    "bottom": (lambda u, v, c: (u, v, 0.0), (0, 0, 1)),
    "front": (lambda u, v, c: (u, 0.0, v), (0, 1, 0)),
    "back": (lambda u, v, c: (u, c.W, v), (0, -1, 0)),
    "left": (lambda u, v, c: (0.0, u, v), (1, 0, 0)),
    "right": (lambda u, v, c: (c.L, u, v), (-1, 0, 0)),
    "end_top": (lambda u, v, c: (u, v, c.H), (0, 0, -1)),
    "end_bottom": (lambda u, v, c: (u, v, 0.0), (0, 0, 1)),
}
THROUGH = {"top": "H", "bottom": "H", "front": "W", "back": "W", "left": "L", "right": "L",
           "end_top": "H", "end_bottom": "H"}


def _hole(ctx: Context, f: dict) -> None:
    face = f["face"]
    if face.startswith("end_") != bool(ctx.segments):
        raise SpecError("invalid_spec", f"{f['id']}: face {face} does not exist on this part")
    point_of, direction = FACE_FRAMES[face]
    d_spec, step = hole_diameter(f, ctx.value, ctx.options)
    if d_spec <= 0:
        raise SpecError("invalid_spec", f"{f['id']}: diameter must be positive")
    d = d_spec * ctx.scale
    thru = f["depth"] == "thru"
    entry_offset = 0.0
    if "from" in f:
        if face != "top":
            raise SpecError("invalid_spec", f"{f['id']}: 'from' is only supported on the top face")
        entry_offset = ctx.H - ctx.mm(f["from"])
    available = getattr(ctx, THROUGH[face]) - entry_offset
    depth = available if thru else ctx.mm_pos(f["depth"], f"{f['id']} depth")
    if depth > available + 1e-9:
        raise SpecError("invalid_spec", f"{f['id']}: depth is deeper than the material")
    cb = f.get("counterbore")
    cb_dims = (ctx.mm_pos(cb["diameter"], "counterbore diameter"),
               ctx.mm_pos(cb["depth"], "counterbore depth")) if cb else None
    if cb_dims and cb_dims[0] <= d:
        raise SpecError("invalid_spec", f"{f['id']}: counterbore must be larger than the hole")
    step_dims = None
    if step:
        step_depth = depth if step["depth"] == "thru" else ctx.mm_pos(step["depth"], "thread depth")
        if step_depth >= depth - 1e-9:
            d = step["diameter"] * ctx.scale  # threaded full depth: one bore at major diameter
        else:
            step_dims = (step["diameter"] * ctx.scale, step_depth)
    if f.get("countersink"):
        raise SpecError("unsupported_feature", f"{f['id']}: countersinks arrive in Phase 3")

    dvec = V(*direction)
    for index, raw in enumerate(f["positions"]):
        u, v = ctx.value.point(raw)
        entry = V(*point_of(u * ctx.scale, v * ctx.scale, ctx)) + dvec * entry_offset
        start = entry - dvec * MARGIN
        length = depth + MARGIN + (MARGIN if thru else 0.0)
        tool = cq.Solid.makeCylinder(d / 2.0, length, start, dvec)
        if not thru and f.get("point_angle") and f["point_angle"] < 180:
            r = d / 2.0
            cone_h = r / math.tan(math.radians(f["point_angle"]) / 2.0)
            tool = tool.fuse(cq.Solid.makeCone(r, 0.0, cone_h, entry + dvec * depth, dvec))
        if cb_dims:
            tool = tool.fuse(cq.Solid.makeCylinder(cb_dims[0] / 2.0, cb_dims[1] + MARGIN, start, dvec))
        if step_dims:
            tool = tool.fuse(cq.Solid.makeCylinder(step_dims[0] / 2.0, step_dims[1] + MARGIN, start, dvec))
        ctx.cut(tool, f"{f['id']}[{index + 1}]")
        ctx.holes.append(HoleInstance(
            feature=f["id"], index=index + 1, hole_type=f["hole_type"],
            point=tuple(entry.toTuple()), direction=tuple(float(x) for x in direction),
            diameter=d, depth=None if thru else depth, face=face, uv=(u, v),
            counterbore=cb_dims, thread_step=step_dims,
            thread=(f.get("thread") or {}).get("callout"),
        ))


def _cross_hole(ctx: Context, f: dict) -> None:
    if not ctx.segments:
        raise SpecError("invalid_spec", f"{f['id']}: cross holes need a turned part")
    z = ctx.mm(f["z"])
    radius = ctx.radius_at(z)
    d = ctx.mm_pos(f["diameter"], f"{f['id']} diameter")
    if d >= 2 * radius:
        raise SpecError("invalid_spec", f"{f['id']}: hole is wider than the shaft")
    axis = V(1, 0, 0) if f["axis"] == "x" else V(0, 1, 0)
    reach = radius + MARGIN
    start = V(0, 0, z) - axis * reach
    ctx.cut(cq.Solid.makeCylinder(d / 2.0, 2 * reach, start, axis), f["id"])
    entry = V(0, 0, z) - axis * radius
    ctx.holes.append(HoleInstance(
        feature=f["id"], index=1, hole_type=f.get("hole_type", "drilled"),
        point=tuple(entry.toTuple()), direction=tuple(axis.toTuple()), diameter=d, depth=None,
        face=f"cross_{f['axis']}", uv=(0.0, z / ctx.scale),
    ))


def _pocket(ctx: Context, f: dict) -> None:
    cx, cy = (ctx.mm(v) for v in f["center"])
    length, width = (ctx.mm_pos(v, f"{f['id']} size") for v in f["size"])
    depth = ctx.mm_pos(f["depth"], f"{f['id']} depth")
    top = ctx.mm(f["from"]) if "from" in f else ctx.H
    r = ctx.mm(f.get("corner_radius", 0))
    if r < 0 or 2 * r > min(length, width) + 1e-9:
        raise SpecError("invalid_spec", f"{f['id']}: corner radius does not fit the pocket")
    if depth >= top:
        raise SpecError("invalid_spec", f"{f['id']}: pocket is deeper than the material")
    sketch = cq.Sketch().rect(length, width)
    if r > 0:
        sketch = sketch.vertices().fillet(r)
    tool = (cq.Workplane("XY", origin=(cx, cy, top - depth)).placeSketch(sketch)
            .extrude(depth + MARGIN).val())
    ctx.cut(tool, f["id"])


def _slot(ctx: Context, f: dict) -> None:
    (sx, sy), (ex, ey) = ((ctx.mm(p[0]), ctx.mm(p[1])) for p in (f["start"], f["end"]))
    w = ctx.mm_pos(f["width"], f"{f['id']} width")
    top = ctx.mm(f["from"]) if "from" in f else ctx.H
    depth = top if f["depth"] == "thru" else ctx.mm_pos(f["depth"], f"{f['id']} depth")
    centers = math.hypot(ex - sx, ey - sy)
    angle = math.degrees(math.atan2(ey - sy, ex - sx))
    through = f["depth"] == "thru"
    base_z = top - depth - (MARGIN if through else 0.0)
    height = depth + MARGIN + (MARGIN if through else 0.0)
    tool = (cq.Workplane("XY", origin=((sx + ex) / 2, (sy + ey) / 2, base_z))
            .slot2D(centers + w, w, angle).extrude(height).val())
    ctx.cut(tool, f["id"])


def _edges(shape: cq.Shape, predicate) -> list:
    return [e for e in shape.Edges() if predicate(e)]


def _chamfer(ctx: Context, f: dict) -> None:
    c = ctx.mm_pos(f["size"], f"{f['id']} size")
    z = ctx.H if f["edges"] == "top_outer" else 0.0
    tol = 1e-6

    def outer(edge) -> bool:
        if edge.geomType() != "LINE":
            return False
        a, b = edge.startPoint(), edge.endPoint()
        if abs(a.z - z) > tol or abs(b.z - z) > tol:
            return False
        on_x = abs(a.x - b.x) < tol and (abs(a.x) < tol or abs(a.x - ctx.L) < tol)
        on_y = abs(a.y - b.y) < tol and (abs(a.y) < tol or abs(a.y - ctx.W) < tol)
        return on_x or on_y

    edges = _edges(ctx.shape, outer)
    if not edges:
        raise SpecError("feature_failed", f"{f['id']}: no outer edges found to chamfer")
    ctx.shape = ctx.shape.chamfer(c, None, edges).clean()


def _end_chamfer(ctx: Context, f: dict) -> None:
    if not ctx.segments:
        raise SpecError("invalid_spec", f"{f['id']}: end chamfers need a turned part")
    c = ctx.mm_pos(f["size"], f"{f['id']} size")
    z = 0.0 if f["end"] == "bottom" else ctx.H
    radius = ctx.radius_at(z)
    edges = _edges(ctx.shape, lambda e: e.geomType() == "CIRCLE"
                   and abs(e.Center().z - z) < 1e-6 and abs(e.radius() - radius) < 1e-6)
    if not edges:
        raise SpecError("feature_failed", f"{f['id']}: end edge not found")
    ctx.shape = ctx.shape.chamfer(c, None, edges).clean()


def _fillet_edge(ctx: Context, f: dict) -> None:
    r = ctx.mm_pos(f["radius"], f"{f['id']} radius")
    a, b = (ctx.mm(v) for v in f["at"])
    axis = f["along"]
    others = [k for k in "xyz" if k != axis]

    def match(edge) -> bool:
        if edge.geomType() != "LINE":
            return False
        p, q = edge.startPoint(), edge.endPoint()
        if any(abs(getattr(p, k) - getattr(q, k)) > 1e-6 for k in others):
            return False
        return abs(getattr(p, others[0]) - a) < 1e-6 and abs(getattr(p, others[1]) - b) < 1e-6

    edges = _edges(ctx.shape, match)
    if not edges:
        raise SpecError("feature_failed", f"{f['id']}: no edge along {axis} at the given location")
    ctx.shape = ctx.shape.fillet(r, edges).clean()


def _groove(ctx: Context, f: dict) -> None:
    if not ctx.segments:
        raise SpecError("invalid_spec", f"{f['id']}: grooves need a turned part")
    z = ctx.mm(f["z"])
    w = ctx.mm_pos(f["width"], f"{f['id']} width")
    root = ctx.mm_pos(f["root_diameter"], f"{f['id']} root diameter") / 2.0
    radius = ctx.radius_at(z + w / 2.0)
    if root >= radius:
        raise SpecError("invalid_spec", f"{f['id']}: groove root is not below the surface")
    ring = cq.Solid.makeCylinder(radius + MARGIN, w, V(0, 0, z)).cut(
        cq.Solid.makeCylinder(root, w, V(0, 0, z)))
    ctx.cut(ring, f["id"])


BUILDERS = {
    "block": _block,
    "turned_profile": _turned_profile,
    "step": _step,
    "hole": _hole,
    "cross_hole": _cross_hole,
    "pocket": _pocket,
    "slot": _slot,
    "chamfer": _chamfer,
    "end_chamfer": _end_chamfer,
    "fillet_edge": _fillet_edge,
    "groove": _groove,
}


def build(spec: dict, variant: str = "nominal", options: dict | None = None) -> Built:
    ctx = Context(spec, variant, options or {})
    for feature in spec["features"]:
        builder = BUILDERS.get(feature["type"])
        if builder is None:
            raise SpecError("unsupported_feature", f"{feature['id']}: {feature['type']} is not supported")
        try:
            builder(ctx, feature)
        except SpecError:
            raise
        except Exception as exc:  # noqa: BLE001 - kernel failures become a reportable state
            raise SpecError("feature_failed", f"{feature['id']} could not be built ({type(exc).__name__})") from exc
        ctx.log.append(f"{feature['id']} {feature['type']} ok")
    return Built(shape=ctx.shape, holes=ctx.holes, extents=(ctx.L, ctx.W, ctx.H),
                 turned=bool(ctx.segments), log=ctx.log)
