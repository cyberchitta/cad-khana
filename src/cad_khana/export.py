from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from build123d import Rot, export_step, export_stl
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.Message import Message_ProgressRange
from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
from OCP.RWGltf import RWGltf_CafWriter
from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
from OCP.TColStd import TColStd_IndexedDataMapOfStringString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

from cad_khana.mechanism.assembly import Assembly

_DEFAULT_LINEAR_TOLERANCE_MM = 0.1
_DEFAULT_ANGULAR_TOLERANCE_RAD = 0.5
_DEFAULT_DRACO_LEVEL = 7


def export_assembly(
    assembly: Assembly,
    out: Path,
    stem: str = "assembly",
) -> tuple[Path, ...]:
    out.mkdir(parents=True, exist_ok=True)
    compound = assembly.compound
    stl_path = out / f"{stem}.stl"
    step_path = out / f"{stem}.step"
    export_stl(compound, str(stl_path))
    export_step(compound, str(step_path))
    return (stl_path, step_path)


def export_glb(
    assembly: Assembly,
    out: Path,
    name: str = "assembly.glb",
    linear_tolerance_mm: float = _DEFAULT_LINEAR_TOLERANCE_MM,
    angular_tolerance_rad: float = _DEFAULT_ANGULAR_TOLERANCE_RAD,
    y_up: bool = True,
    draco: bool = True,
    draco_level: int = _DEFAULT_DRACO_LEVEL,
) -> Path:
    """Export ``assembly`` as a glTF 2.0 binary at ``<out>/<name>``.

    Each PlacedPart becomes a named node in the GLB scene graph; its
    build123d ``Color`` (if set) is written as a flat sRGB baseColor.
    No PBR maps, no lighting — this is the geometry-truth artifact.
    For PBR materials baked from chitra-cad's catalog use
    ``chitra_cad.export.export_glb`` instead.

    ``y_up`` pre-rotates Z-up CAD coordinates to glTF's Y-up convention
    (this OCP build doesn't expose ``RWMesh_CoordinateSystemConverter``).

    ``draco`` enables Draco mesh compression by post-processing the
    raw GLB with ``gltf-pipeline`` (``npm install -g gltf-pipeline``).
    OCP exposes ``RWGltf_DracoParameters`` but its fields aren't bound,
    so the writer itself can't enable Draco — the shell-out is the
    practical path. ``draco_level`` 0–10 trades encode time for ratio
    (Cesium's default is 7).
    """
    out.mkdir(parents=True, exist_ok=True)
    glb_path = out / name

    app = XCAFApp_Application.GetApplication_s()
    fmt = TCollection_ExtendedString("BinXCAF")
    doc = TDocStd_Document(fmt)
    app.NewDocument(fmt, doc)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

    to_yup = Rot(-90, 0, 0) if y_up else None

    for placed in assembly.parts:
        part = placed.part.moved(placed.location)
        if to_yup is not None:
            part = to_yup * part
        shape = part.wrapped
        BRepMesh_IncrementalMesh(
            shape, linear_tolerance_mm, False, angular_tolerance_rad, True
        )
        label = shape_tool.AddShape(shape, False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(placed.name))
        if placed.color is not None:
            r, g, b, _a = tuple(placed.color)
            q = Quantity_Color(r, g, b, Quantity_TypeOfColor.Quantity_TOC_sRGB)
            color_tool.SetColor(label, q, XCAFDoc_ColorType.XCAFDoc_ColorSurf)

    writer = RWGltf_CafWriter(TCollection_AsciiString(str(glb_path)), True)
    ok = writer.Perform(
        doc, TColStd_IndexedDataMapOfStringString(), Message_ProgressRange()
    )
    if not ok:
        raise RuntimeError(f"RWGltf_CafWriter failed writing {glb_path}")

    if draco:
        _compress_draco(glb_path, level=draco_level)
    return glb_path


def _compress_draco(glb_path: Path, level: int) -> None:
    """Re-write ``glb_path`` in place with Draco mesh compression via
    ``gltf-pipeline``. Raises ``RuntimeError`` if the tool isn't on PATH.
    """
    tool = shutil.which("gltf-pipeline")
    if tool is None:
        raise RuntimeError(
            "draco compression requires 'gltf-pipeline' on PATH "
            "(install with `npm install -g gltf-pipeline`). "
            "Pass draco=False to skip."
        )
    tmp = glb_path.with_suffix(".draco.glb")
    result = subprocess.run(
        [
            tool,
            "-i", str(glb_path),
            "-o", str(tmp),
            "-d",
            "--draco.compressionLevel", str(level),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"gltf-pipeline failed (exit {result.returncode}):\n{result.stderr}"
        )
    tmp.replace(glb_path)
