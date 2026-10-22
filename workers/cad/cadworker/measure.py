"""Read geometry back from the B-rep: bounding box, validity and hole axes.

Measurements come from the exact solid (analytic surfaces), never from the
display mesh.
"""

from __future__ import annotations

from dataclasses import dataclass

import cadquery as cq
from OCP.Bnd import Bnd_Box
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cylinder

from .build import HoleInstance

LENGTH_EPS_MM = 1e-4  # geometric epsilon, far below any manufacturing tolerance


def exact_bbox(shape: cq.Shape) -> tuple[float, float, float, float, float, float]:
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, box, False, False)
    return box.Get()


def is_valid(shape: cq.Shape) -> bool:
    return BRepCheck_Analyzer(shape.wrapped).IsValid()


@dataclass
class Cylinder:
    face: cq.Face
    radius: float
    origin: cq.Vector
    axis: cq.Vector
    vmin: float
    vmax: float


def cylinders(shape: cq.Shape) -> list[Cylinder]:
    found = []
    for face in shape.Faces():
        adaptor = BRepAdaptor_Surface(face.wrapped)
        if adaptor.GetType() != GeomAbs_Cylinder:
            continue
        cyl = adaptor.Cylinder()
        axis = cyl.Axis()
        loc, direction = axis.Location(), axis.Direction()
        _, _, vmin, vmax = BRepTools.UVBounds_s(face.wrapped)
        found.append(Cylinder(
            face=face, radius=cyl.Radius(),
            origin=cq.Vector(loc.X(), loc.Y(), loc.Z()),
            axis=cq.Vector(direction.X(), direction.Y(), direction.Z()),
            vmin=vmin, vmax=vmax,
        ))
    return found


@dataclass
class AxisMatch:
    faces: list[cq.Face]
    radius: float
    depth: float  # deepest point of the bore along the drilling direction, from the entry
    axis_point: cq.Vector  # where the measured axis crosses the entry plane


SEARCH_RADIUS_MM = 0.5  # find a misplaced bore so it fails on position, not as "missing"


def match_axis(cyls: list[Cylinder], hole: HoleInstance, diameter: float) -> AxisMatch | None:
    """Find bore faces of the given diameter whose axis runs near the hole's axis."""
    entry = cq.Vector(*hole.point)
    direction = cq.Vector(*hole.direction)
    best: list[tuple[float, Cylinder]] = []
    for c in cyls:
        if abs(c.radius - diameter / 2.0) > LENGTH_EPS_MM:
            continue
        if c.axis.cross(direction).Length > 1e-6:
            continue
        offset = entry - c.origin
        distance = (offset - c.axis * offset.dot(c.axis)).Length
        if distance <= SEARCH_RADIUS_MM:
            best.append((distance, c))
    if not best:
        return None
    nearest = min(d for d, _ in best)
    chosen = [c for d, c in best if d <= nearest + LENGTH_EPS_MM]
    extents = []
    for c in chosen:
        for v in (c.vmin, c.vmax):
            extents.append((c.origin + c.axis * v - entry).dot(direction))
    first = chosen[0]
    axis_point = first.origin + first.axis * (entry - first.origin).dot(first.axis)
    return AxisMatch(faces=[c.face for c in chosen],
                     radius=sum(c.radius for c in chosen) / len(chosen),
                     depth=max(extents), axis_point=axis_point)


def face_uv(face: str, point: cq.Vector) -> tuple[float, float]:
    """Inverse of build.FACE_FRAMES: a 3D point to the face's 2D drawing frame (mm)."""
    if face in ("top", "bottom", "end_top", "end_bottom"):
        return point.x, point.y
    if face in ("front", "back"):
        return point.x, point.z
    if face in ("left", "right"):
        return point.y, point.z
    if face == "cross_x":
        return point.y, point.z
    if face == "cross_y":
        return point.x, point.z
    raise ValueError(face)
