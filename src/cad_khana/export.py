from __future__ import annotations

import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from build123d import Location, Rot, export_step, export_stl
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.Message import Message_ProgressRange
from OCP.Quantity import Quantity_Color, Quantity_ColorRGBA, Quantity_TypeOfColor
from OCP.RWGltf import RWGltf_CafWriter
from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
from OCP.TColStd import TColStd_IndexedDataMapOfStringString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

from cad_khana.mechanism.assembly import Assembly, SubAssembly

_DEFAULT_LINEAR_TOLERANCE_MM = 0.1
_DEFAULT_ANGULAR_TOLERANCE_RAD = 0.5
_DEFAULT_DRACO_LEVEL = 7
_EPS_POS_MM = 1e-4
_EPS_QUAT = 1e-6


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


_Trs = tuple[tuple[float, float, float], tuple[float, float, float, float]]


@dataclass(frozen=True)
class _JointGroup:
    """One jointed sub-assembly as an animation node. ``parent`` is the
    path of its nearest jointed ancestor (``None`` at the top), and
    ``members`` are the parts it *directly* owns — its own ``parts``
    plus those of non-jointed descendants, never a nested joint's.
    Member names match ``placed_parts`` names — that's how
    ``_inject_animation_into_glb`` finds the GLB nodes."""

    path: str
    parent: str | None
    members: tuple[str, ...]


@dataclass(frozen=True)
class _JointPose:
    """World frame of a jointed sub-assembly (joint included) and a
    world point on its joint axis."""

    frame: Location
    pivot: Location


def _joint_groups(assembly: Assembly) -> list[_JointGroup]:
    """Walk the subassembly tree, parents before children; ``[]`` for a
    flat assembly. Each part belongs to its *innermost* jointed
    ancestor, so groups never overlap — a part with two animated
    parents is malformed glTF. The nesting is carried by the group
    nodes instead (part → inner group → outer group), which is what
    lets each node animate its own joint's rotation alone."""

    def _owned(asm: Assembly, prefix: str) -> tuple[str, ...]:
        return tuple(f"{prefix}{p.name}" for p in asm.parts) + tuple(
            name
            for sub in asm.subassemblies
            if sub.joint is None
            for name in _owned(sub.assembly, f"{prefix}{sub.name}.")
        )

    def _under(sub: SubAssembly, prefix: str, parent: str | None) -> list[_JointGroup]:
        path = f"{prefix}{sub.name}"
        own = (
            [_JointGroup(path, parent, _owned(sub.assembly, f"{path}."))]
            if sub.joint is not None
            else []
        )
        return own + _collect(sub.assembly, f"{path}.", path if own else parent)

    def _collect(asm: Assembly, prefix: str, parent: str | None) -> list[_JointGroup]:
        return [g for sub in asm.subassemblies for g in _under(sub, prefix, parent)]

    return _collect(assembly, "", None)


def _joint_poses(
    assembly: Assembly, frame: Location = Location(), prefix: str = ""
) -> dict[str, _JointPose]:
    """Dotted path → pose for every jointed sub-assembly — the
    frame-side mirror of ``Assembly.joint_angles``."""

    def _pose(sub: SubAssembly) -> _JointPose:
        axis_frame = frame * sub.location if sub.joint.frame == "local" else frame
        return _JointPose(
            frame=frame * sub.effective_location,
            pivot=axis_frame * Location(sub.joint.axis.position),
        )

    own = {
        f"{prefix}{s.name}": _pose(s)
        for s in assembly.subassemblies
        if s.joint is not None
    }
    nested = {
        path: pose
        for s in assembly.subassemblies
        for path, pose in _joint_poses(
            s.assembly, frame * s.effective_location, f"{prefix}{s.name}."
        ).items()
    }
    return own | nested


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

    Two post-processing passes run via ``gltf-transform``
    (``bun install -g @gltf-transform/cli``):

    * Always: ``join --keepMeshes true --keepNamed true``. OCP's writer
      emits one primitive per face-style (~30+ primitives per shape),
      which inflates the glTF JSON to several × the binary payload.
      Joining per-node collapses primitives within each named node
      without merging across nodes (preserves per-PlacedPart names that
      the animation channels and `<model-viewer>` material switches
      target).
    * ``draco`` (optional): re-encodes mesh attribute buffers with
      Draco. OCP exposes ``RWGltf_DracoParameters`` but its fields
      aren't bound, so doing it via shell-out is the practical path.
      ``draco_level`` 0–10 trades encode time for ratio (Cesium's
      default is 7).
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

    # ``placed_parts`` walks any sub-assembly tree, composing the
    # joint+placement chain so leaf parts arrive at their world-frame
    # position. Static export doesn't need to preserve the hierarchy in
    # the glTF scene graph — that work happens in
    # ``export_animated_glb`` where the structural groups give the
    # animation channels their handles.
    for placed in assembly.placed_parts:
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
            r, g, b, a = tuple(placed.color)
            rgb = Quantity_Color(r, g, b, Quantity_TypeOfColor.Quantity_TOC_sRGB)
            rgba = Quantity_ColorRGBA(rgb, a)
            color_tool.SetColor(label, rgba, XCAFDoc_ColorType.XCAFDoc_ColorSurf)

    writer = RWGltf_CafWriter(TCollection_AsciiString(str(glb_path)), True)
    ok = writer.Perform(
        doc, TColStd_IndexedDataMapOfStringString(), Message_ProgressRange()
    )
    if not ok:
        raise RuntimeError(f"RWGltf_CafWriter failed writing {glb_path}")

    _gltf_transform_join(glb_path)
    if draco:
        _gltf_transform_draco(glb_path, level=draco_level)
    return glb_path


def _gltf_transform(args: list[str]) -> None:
    """Shell out to ``gltf-transform``. Raises if the tool isn't on PATH."""
    tool = shutil.which("gltf-transform")
    if tool is None:
        raise RuntimeError(
            "gltf-transform not on PATH (install with "
            "`bun install -g @gltf-transform/cli`)."
        )
    result = subprocess.run(
        [tool, *args], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"gltf-transform {args[0]} failed (exit {result.returncode}):\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _gltf_transform_join(glb_path: Path) -> None:
    """Merge primitives per node — collapses OCP's per-face-style
    primitive explosion (~30× per shape on m03), the main driver of
    JSON bloat in the output GLB. ``--keepMeshes`` / ``--keepNamed``
    keep distinct named nodes (the animation channels target them by
    name; merging across nodes would lose those handles)."""
    _gltf_transform(
        [
            "join",
            str(glb_path),
            str(glb_path),
            "--keepMeshes", "true",
            "--keepNamed", "true",
        ]
    )


def _gltf_transform_draco(glb_path: Path, level: int) -> None:
    """Re-encode mesh attribute buffers with Draco. Lossy on the
    geometry by design (level controls the loss/ratio trade-off)."""
    _gltf_transform(
        [
            "draco",
            str(glb_path),
            str(glb_path),
            "--encode-speed", str(10 - level),
            "--decode-speed", "5",
        ]
    )


def export_animated_glb(
    factory: Callable[[float], Assembly],
    ts: Sequence[float],
    out: Path,
    name: str = "assembly.glb",
    duration_s: float = 5.0,
    linear_tolerance_mm: float = _DEFAULT_LINEAR_TOLERANCE_MM,
    angular_tolerance_rad: float = _DEFAULT_ANGULAR_TOLERANCE_RAD,
    y_up: bool = True,
    draco: bool = True,
    draco_level: int = _DEFAULT_DRACO_LEVEL,
    animation_name: str = "default",
) -> Path:
    """Sweep ``factory(t)`` over ``ts`` and write an animated glTF.

    Geometry is tessellated once from ``factory(ts[0])`` — same path as
    ``export_glb``. The sweep then samples each ``PlacedPart.location``
    at every ``t`` and injects per-node translation + rotation samplers
    (``LINEAR`` interpolation) targeting the matching node by name.

    Animation grouping is driven by the assembly's sub-assembly tree:
    each jointed ``with_subassembly(...)`` contributes one ``animgroup_N``
    node seated on its joint axis and nested under its parent joint's
    node, carrying that joint's own rotation, with the group's parts
    re-parented as children. Static parts get no animation channel —
    the frame-0 TRS from ``export_glb`` carries them.

    Flat assemblies (no jointed sub-assemblies) produce no animgroups;
    any motion in such an assembly falls through to per-part TRS
    samplers, which lerp between keyframes and chord-drift on orbital
    motion. Express orbital motion as a ``RevoluteJoint`` on a
    sub-assembly to get the correct slerp arc.

    glTF time values are spread evenly over ``duration_s`` seconds
    regardless of what ``t`` units mean to the factory. With
    ``<model-viewer autoplay>``, the consumer loops the sweep in
    ``duration_s``.

    Parts that appear or disappear between frames are not handled yet —
    a part missing from ``factory(t)`` for some ``t`` raises. Add when
    a real driver needs it.
    """
    ts_list = list(ts)
    if len(ts_list) < 2:
        raise ValueError("export_animated_glb requires len(ts) >= 2")

    ref_assembly = factory(ts_list[0])

    # Per-frame TRS samplers extract only PlacedPart.location, so any
    # transform attached to the *part itself* (the build123d Part's
    # internal Location) is silently dropped from the animation. Static
    # frame 0 renders correctly via export_glb's
    # ``placed.part.moved(placed.location)``, but every animation
    # sampler thereafter overwrites the node TRS with placed.location
    # alone — producing animations with quietly wrong geometry.
    #
    # Only flag *dynamic* parts (those whose placed.location varies
    # across frames). Static parts get no animation channel — their
    # frame-0 TRS carries them — so part-internal location is harmless
    # there. Probe with the middle frame; ts_list[-1] would loop back
    # to ts_list[0] for cyclic animations, missing motion entirely.
    # Numerical comparison: OCP's TopLoc_Location.IsIdentity() on a
    # compose-inverse product is fooled by floating-point noise even
    # when locations are mathematically identical.
    def _moved(l_ref, l_probe, tol: float = 1e-6) -> bool:
        pr, pp = l_ref.position, l_probe.position
        orr, op = l_ref.orientation, l_probe.orientation
        return (
            abs(pr.X - pp.X) > tol or abs(pr.Y - pp.Y) > tol or abs(pr.Z - pp.Z) > tol
            or abs(orr.X - op.X) > tol or abs(orr.Y - op.Y) > tol or abs(orr.Z - op.Z) > tol
        )

    ref_placed = ref_assembly.placed_parts
    ref_locs = {p.name: p.location for p in ref_placed}
    probe = factory(ts_list[len(ts_list) // 2])
    probe_placed = probe.placed_parts
    dynamic = {
        p.name for p in probe_placed
        if p.name in ref_locs and _moved(ref_locs[p.name], p.location)
    }
    violators = [
        (p.name, str(p.part.location))
        for p in ref_placed
        if p.name in dynamic and not p.part.location.wrapped.IsIdentity()
    ]
    if violators:
        names = ", ".join(n for n, _ in violators[:3])
        extra = f" (+{len(violators) - 3} more)" if len(violators) > 3 else ""
        raise ValueError(
            f"export_animated_glb: {len(violators)} dynamic part(s) have "
            f"non-identity part-internal Location ({names}{extra}). Per-frame "
            f"TRS samplers extract only PlacedPart.location, so any transform "
            f"attached to the part itself is silently dropped — producing "
            f"animations with quietly wrong geometry past frame 0. Fix: factor "
            f"the transform out of the part-creation function and into the "
            f"assembly placement. e.g. for `def thing(): return Rot(0, 20, 0) "
            f"* Box(L, W, T)`, return a plain `Box(L, W, T)` and bake the "
            f"`Rot` into `location=` at `.with_part(...)`. First offender: "
            f"{violators[0][0]!r} has part.location = {violators[0][1]}."
        )

    glb_path = export_glb(
        ref_assembly,
        out=out,
        name=name,
        linear_tolerance_mm=linear_tolerance_mm,
        angular_tolerance_rad=angular_tolerance_rad,
        y_up=y_up,
        draco=False,
    )

    to_world = Rot(-90, 0, 0) if y_up else Location()
    ref_names = {p.name for p in ref_placed}
    samples: dict[str, list[_Trs]] = {name: [] for name in ref_names}
    poses: list[dict[str, _JointPose]] = []
    for t in ts_list:
        a = factory(t)
        poses.append(_joint_poses(a))
        seen: set[str] = set()
        for placed in a.placed_parts:
            if placed.name not in ref_names:
                continue
            samples[placed.name].append(_trs(to_world * placed.location))
            seen.add(placed.name)
        missing = ref_names - seen
        if missing:
            raise NotImplementedError(
                f"export_animated_glb: parts {sorted(missing)} present at "
                f"t={ts_list[0]} but missing at t={t}. Appearing/"
                "disappearing parts not yet supported."
            )

    for ss in samples.values():
        _align_quaternion_hemispheres(ss)

    # Rigid-body groups are *given* by the sub-assembly tree: each
    # jointed `with_subassembly(...)` becomes one group node, nested
    # like the joints. Flat assemblies produce no groups; any motion
    # there falls through to the per-part TRS samplers in
    # `_inject_animation_into_glb` (correct for static / pure-translation /
    # in-place-rotation; chord-drifts on orbital motion).
    times_s = [i * duration_s / (len(ts_list) - 1) for i in range(len(ts_list))]
    _inject_animation_into_glb(
        glb_path,
        samples=samples,
        tracks=_group_tracks(_joint_groups(ref_assembly), poses, to_world),
        times_s=times_s,
        animation_name=animation_name,
    )

    if draco:
        _gltf_transform_draco(glb_path, level=draco_level)
    return glb_path


def _align_quaternion_hemispheres(
    trajectory: list[tuple[tuple[float, ...], tuple[float, ...]]],
) -> None:
    """Flip signs in place so consecutive quaternions share a hemisphere.

    A unit quaternion ``q`` and ``-q`` represent the same rotation; glTF
    LINEAR sampling on rotation channels (defined to slerp) still benefits
    from a consistent sign, otherwise some viewers spin the long way.
    """
    for i in range(1, len(trajectory)):
        prev_q = trajectory[i - 1][1]
        cur_q = trajectory[i][1]
        dot = sum(a * b for a, b in zip(prev_q, cur_q))
        if dot < 0.0:
            trajectory[i] = (trajectory[i][0], tuple(-c for c in cur_q))


def _trs(location: Location) -> _Trs:
    trsf = location.wrapped.Transformation()
    t, q = trsf.TranslationPart(), trsf.GetRotation()
    return ((t.X(), t.Y(), t.Z()), (q.X(), q.Y(), q.Z(), q.W()))


def _quat_rotate(
    q: tuple[float, float, float, float],
    v: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Rotate 3-vector ``v`` by unit quaternion ``q`` (xyzw)."""
    qx, qy, qz, qw = q
    vx, vy, vz = v
    cx = qy * vz - qz * vy
    cy = qz * vx - qx * vz
    cz = qx * vy - qy * vx
    tx = cx + qw * vx
    ty = cy + qw * vy
    tz = cz + qw * vz
    rx = qy * tz - qz * ty
    ry = qz * tx - qx * tz
    rz = qx * ty - qy * tx
    return (vx + 2 * rx, vy + 2 * ry, vz + 2 * rz)


@dataclass(frozen=True)
class _GroupTrack:
    """A joint group's animation node: where it sits (``pivot``, a
    world point on the joint axis at frame 0) and its per-frame TRS in
    its parent node's frame."""

    group: _JointGroup
    pivot: tuple[float, float, float]
    trs: list[_Trs]


def _group_tracks(
    groups: list[_JointGroup],
    poses: list[dict[str, _JointPose]],
    to_world: Location,
) -> list[_GroupTrack]:
    """Each group node's own motion, with its ancestors' divided out.

    A group's world motion since frame 0 is ``D[i] = W[i]·W[0]⁻¹``; under
    a parent node already carrying ``D_parent``, the node owes only
    ``D_parent[i]⁻¹·D[i]`` — for a revolute joint, a rotation about the
    joint's frame-0 axis line. Expressed about the scene origin that
    rotation drags along a translation ``c − R·c`` which is itself an
    arc, and LINEAR lerps it down the chord while the rotation slerps.
    So the node sits *on the axis* instead: translation ``p + R·c`` is
    constant (= ``c``) for as long as the joint is all that moves, and
    members are offset by ``−c`` to compensate. Motion the joint doesn't
    account for survives as a varying translation, exact at keyframes.
    """
    first = poses[0]
    origin = (0.0, 0.0, 0.0)

    def _drift(path: str | None) -> list[Location]:
        return [
            Location()
            if path is None
            else to_world * f[path].frame * first[path].frame.inverse() * to_world.inverse()
            for f in poses
        ]

    def _pivot(path: str | None) -> tuple[float, float, float]:
        return origin if path is None else _trs(to_world * first[path].pivot)[0]

    def _track(group: _JointGroup) -> _GroupTrack:
        pivot, seat = _pivot(group.path), _pivot(group.parent)
        local = [
            _trs(up.inverse() * own)
            for up, own in zip(_drift(group.parent), _drift(group.path))
        ]
        trs = [
            (tuple(p + rc - s for p, rc, s in zip(pos, _quat_rotate(q, pivot), seat)), q)
            for pos, q in local
        ]
        _align_quaternion_hemispheres(trs)
        return _GroupTrack(group, pivot, trs)

    return [_track(g) for g in groups]


def _inject_animation_into_glb(
    glb_path: Path,
    samples: dict[str, list[_Trs]],
    tracks: list[_GroupTrack],
    times_s: list[float],
    animation_name: str,
) -> None:
    """Append an ``animation`` block to an existing GLB written by
    ``export_glb``. Locates target nodes by ``PlacedPart.name``.

    Each track becomes an ``animgroup_N`` node seated on its joint axis
    and nested under its parent joint's node, with the group's parts
    re-parented beneath it — children inherit the slerp'd rotation and
    so trace the correct arc between keyframes. Parts not in any group
    fall through to per-part TRS samplers (correct for static,
    pure-translation, and in-place-rotation parts; only orbital motion
    would chord-drift there, and that's exactly what grouping pulls
    out).
    """
    import pygltflib

    gltf = pygltflib.GLTF2().load(str(glb_path))
    if gltf is None:
        raise RuntimeError(f"pygltflib could not load {glb_path}")
    blob = bytearray(gltf.binary_blob())

    name_to_node = {n.name: i for i, n in enumerate(gltf.nodes) if n.name}
    n_frames = len(times_s)

    def _pad4() -> None:
        while len(blob) % 4:
            blob.append(0)

    def _append_floats(values: Sequence[float]) -> tuple[int, int]:
        _pad4()
        offset = len(blob)
        data = struct.pack(f"<{len(values)}f", *values)
        blob.extend(data)
        return offset, len(data)

    def _add_buffer_view(offset: int, length: int) -> int:
        gltf.bufferViews.append(
            pygltflib.BufferView(
                buffer=0, byteOffset=offset, byteLength=length
            )
        )
        return len(gltf.bufferViews) - 1

    def _add_accessor(
        bv_idx: int,
        count: int,
        component_type: int,
        type_: str,
        mn: list[float] | None = None,
        mx: list[float] | None = None,
    ) -> int:
        acc = pygltflib.Accessor(
            bufferView=bv_idx,
            byteOffset=0,
            componentType=component_type,
            count=count,
            type=type_,
        )
        if mn is not None:
            acc.min = mn
        if mx is not None:
            acc.max = mx
        gltf.accessors.append(acc)
        return len(gltf.accessors) - 1

    time_offset, time_len = _append_floats(times_s)
    time_bv = _add_buffer_view(time_offset, time_len)
    time_acc = _add_accessor(
        time_bv,
        n_frames,
        pygltflib.FLOAT,
        pygltflib.SCALAR,
        mn=[times_s[0]],
        mx=[times_s[-1]],
    )

    samplers: list[pygltflib.AnimationSampler] = []
    channels: list[pygltflib.AnimationChannel] = []

    def _add_sampler_channel(
        flat: list[float], node_idx: int, path: str, type_: str, components: int
    ) -> None:
        offset, length = _append_floats(flat)
        bv = _add_buffer_view(offset, length)
        acc = _add_accessor(bv, len(flat) // components, pygltflib.FLOAT, type_)
        samplers.append(
            pygltflib.AnimationSampler(
                input=time_acc, output=acc, interpolation="LINEAR"
            )
        )
        channels.append(
            pygltflib.AnimationChannel(
                sampler=len(samplers) - 1,
                target=pygltflib.AnimationChannelTarget(node=node_idx, path=path),
            )
        )

    # Re-parent grouped parts under a fresh animated node per group,
    # and nested groups under their parent's. A member keeps its static
    # frame-0 pose, shifted by the group's pivot so the node can sit on
    # the joint axis — combined with the group's R[i] animation, it
    # reaches sampled[i] at every keyframe and slerps along the true
    # arc in between.
    group_node = {
        track.group.path: len(gltf.nodes) + i for i, track in enumerate(tracks)
    }
    grouped_parts: set[str] = set()
    scene_root_ids = list(gltf.scenes[0].nodes)
    for group_idx, track in enumerate(tracks):
        member_ids = [name_to_node[m] for m in track.group.members if m in name_to_node]
        for member_id in member_ids:
            member = gltf.nodes[member_id]
            member.translation = [
                t - c for t, c in zip(member.translation or [0.0, 0.0, 0.0], track.pivot)
            ]
        nested_ids = [
            group_node[t.group.path] for t in tracks if t.group.parent == track.group.path
        ]
        gltf.nodes.append(
            pygltflib.Node(
                name=f"animgroup_{group_idx}",
                children=member_ids + nested_ids,
                translation=list(track.trs[0][0]),
            )
        )
        node_idx = group_node[track.group.path]
        scene_root_ids = [i for i in scene_root_ids if i not in set(member_ids)]
        if track.group.parent is None:
            scene_root_ids.append(node_idx)
        grouped_parts.update(track.group.members)

        _add_sampler_channel(
            [c for _, q in track.trs for c in q],
            node_idx, "rotation", pygltflib.VEC4, 4,
        )
        p0 = track.trs[0][0]
        moves_trans = any(
            abs(p[k] - p0[k]) > _EPS_POS_MM for p, _ in track.trs[1:] for k in range(3)
        )
        if moves_trans:
            _add_sampler_channel(
                [c for p, _ in track.trs for c in p],
                node_idx, "translation", pygltflib.VEC3, 3,
            )

    gltf.scenes[0].nodes = scene_root_ids

    for part_name, node_idx in name_to_node.items():
        if part_name in grouped_parts or part_name not in samples:
            continue
        ss = samples[part_name]
        if len(ss) != n_frames:
            continue
        p0 = ss[0][0]
        q0 = ss[0][1]
        moves_trans = any(
            abs(p[k] - p0[k]) > _EPS_POS_MM for p, _ in ss[1:] for k in range(3)
        )
        moves_rot = any(
            sum((q[k] - q0[k]) ** 2 for k in range(4)) > _EPS_QUAT
            for _, q in ss[1:]
        )

        if moves_trans:
            _add_sampler_channel(
                [c for pos, _ in ss for c in pos],
                node_idx, "translation", pygltflib.VEC3, 3,
            )
        if moves_rot:
            _add_sampler_channel(
                [c for _, q in ss for c in q],
                node_idx, "rotation", pygltflib.VEC4, 4,
            )

    if not samplers:
        return

    gltf.animations.append(
        pygltflib.Animation(
            samplers=samplers, channels=channels, name=animation_name
        )
    )
    gltf.buffers[0].byteLength = len(blob)
    gltf.set_binary_blob(bytes(blob))
    gltf.save(str(glb_path))
