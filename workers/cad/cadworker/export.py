"""STEP and GLB export with face colours, part names and declared units.

Bores are coloured by hole type so a programmer can tell a tapped hole from a
drilled or reamed hole of the same size after import (Mastercam's hole finder
cannot). The STEP header names the part, revision, variant and units, and
states that the drawing governs.
"""

from __future__ import annotations

import re
from pathlib import Path

import cadquery as cq
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.IFSelect import IFSelect_ReturnStatus
from OCP.Interface import Interface_Static
from OCP.Message import Message_ProgressRange
from OCP.Quantity import Quantity_Color, Quantity_TOC_sRGB
from OCP.RWGltf import RWGltf_CafWriter
from OCP.RWMesh import RWMesh_CoordinateSystem
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_StepModelType
from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
from OCP.TColStd import TColStd_IndexedDataMapOfStringString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool
from OCP.XSControl import XSControl_WorkSession

BASE_COLOR = (0.78, 0.80, 0.83)
HOLE_COLORS = {
    "tapped": (0.10, 0.45, 0.90),
    "reamed": (0.86, 0.16, 0.16),
    "bored": (0.95, 0.55, 0.10),
    "clearance": (0.20, 0.66, 0.32),
    "drilled": (0.58, 0.38, 0.80),
    "counterbore": (0.08, 0.66, 0.66),
}
STEP_UNITS = {"in": "INCH", "mm": "MM"}


def _color(rgb) -> Quantity_Color:
    return Quantity_Color(rgb[0], rgb[1], rgb[2], Quantity_TOC_sRGB)  # palette is sRGB


def _document(shape: cq.Shape, name: str, face_colors: list[tuple[str, list]] | None):
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    app.InitDocument(doc)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    label = shape_tool.AddShape(shape.wrapped, False)
    TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
    color_tool.SetColor(label, _color(BASE_COLOR), XCAFDoc_ColorType.XCAFDoc_ColorSurf)
    for kind, faces in face_colors or []:
        rgb = HOLE_COLORS.get(kind)
        if not rgb:
            continue
        for face in faces:
            sub = shape_tool.AddSubShape(label, face.wrapped)
            if not sub.IsNull():
                TDataStd_Name.Set_s(sub, TCollection_ExtendedString(f"{kind} hole"))
                color_tool.SetColor(sub, _color(rgb), XCAFDoc_ColorType.XCAFDoc_ColorSurf)
    shape_tool.UpdateAssemblies()
    return doc


def _ascii(text: str) -> str:
    cleaned = text.encode("ascii", "replace").decode("ascii").replace("?", "-")
    return cleaned.replace("'", "''")


def write_step(shape: cq.Shape, path: Path, *, name: str, units: str, description: str,
               face_colors=None, schema: str = "AP214") -> None:
    doc = _document(shape, name, face_colors)
    session = XSControl_WorkSession()
    writer = STEPCAFControl_Writer(session, False)
    writer.SetColorMode(True)
    writer.SetNameMode(True)
    writer.SetLayerMode(False)
    Interface_Static.SetCVal_s("write.step.schema", "AP242DIS" if schema == "AP242" else "AP214IS")
    Interface_Static.SetIVal_s("write.surfacecurve.mode", 1)
    Interface_Static.SetIVal_s("write.stepcaf.subshapes.name", 1)
    Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
    Interface_Static.SetCVal_s("write.step.unit", STEP_UNITS[units])
    Interface_Static.SetCVal_s("write.step.product.name", name)
    writer.Transfer(doc, STEPControl_StepModelType.STEPControl_AsIs)
    status = writer.Write(str(path))
    if status != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise RuntimeError(f"STEP writer failed: {status}")
    _rewrite_header(path, description)


def _rewrite_header(path: Path, description: str) -> None:
    text = path.read_text(encoding="ascii", errors="replace")
    head, sep, body = text.partition("ENDSEC;")
    head = re.sub(r"FILE_DESCRIPTION\(\(.*?\),", f"FILE_DESCRIPTION(('{_ascii(description)}'),",
                  head, count=1, flags=re.S)
    head = re.sub(r"(FILE_NAME\('[^']*','[^']*',)\(.*?\),\(.*?\),",
                  r"\1('Blueprint to CAD'),('8 West Ventures'),", head, count=1, flags=re.S)
    path.write_text(head + sep + body, encoding="ascii")


def write_glb(shape: cq.Shape, path: Path, *, name: str, face_colors=None,
              linear_deflection: float = 0.05, angular_deflection: float = 0.3) -> None:
    """Display mesh for the browser viewer (metres, Y-up). Never used for measurements."""
    BRepMesh_IncrementalMesh(shape.wrapped, linear_deflection, False, angular_deflection, True)
    doc = _document(shape, name, face_colors)
    writer = RWGltf_CafWriter(TCollection_AsciiString(str(path)), True)
    converter = writer.ChangeCoordinateSystemConverter()
    converter.SetInputLengthUnit(0.001)
    converter.SetInputCoordinateSystem(RWMesh_CoordinateSystem.RWMesh_CoordinateSystem_Zup)
    ok = writer.Perform(doc, TColStd_IndexedDataMapOfStringString(), Message_ProgressRange())
    if not ok:
        raise RuntimeError("GLB writer failed")


def reimport_step(path: Path) -> cq.Shape:
    """Read a STEP back (in millimetres) for the round-trip check."""
    Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
    return cq.importers.importStep(str(path)).val()


def declared_unit(path: Path) -> str | None:
    head = path.read_text(encoding="ascii", errors="replace")[:200000].upper()
    if "'INCH'" in head or "INCH" in re.findall(r"CONVERSION_BASED_UNIT\s*\(\s*'([A-Z]+)'", head):
        return "in"
    if re.search(r"SI_UNIT\s*\(\s*\.MILLI\.\s*,\s*\.METRE\.\s*\)", head):
        return "mm"
    return None
