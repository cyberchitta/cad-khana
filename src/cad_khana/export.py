from __future__ import annotations

import shutil
import struct
import subprocess
from pathlib import Path
from typing import Callable, Sequence

from build123d import Rot, export_step, export_stl
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

from cad_khana.mechanism.assembly import Assembly

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


def _structural_groups(assembly: Assembly) -> list[list[str]]:
    """Walk the subassembly tree; each jointed sub-assembly contributes
    a group of part names that it *directly* owns (its own ``parts``
    plus the parts of any non-jointed descendants), recursing past any
    nested jointed sub-assembly so that nested joints surface as their
    own separate, non-overlapping groups. Returns ``[]`` for a flat
    assembly — the caller then falls back to trajectory inference.

    Non-overlapping groups are load-bearing for
    ``_inject_animation_into_glb``: each group's animation channel is
    applied at scene-root level to a freshly inserted animgroup node
    whose children are the group's parts. If two groups shared parts
    (e.g. an outer rotor group + an inner platform group that both
    claim the platform's parts), the inner re-parent would clash with
    the outer's, producing malformed glTF. Each part belongs to its
    *innermost* jointed ancestor, and that group's relative trajectory
    naturally captures the composed motion of every ancestor joint —
    because the relative trajectory is sampled from any one member's
    absolute pose, which already includes every ancestor's
    contribution by construction."""

    def _walk_into(asm: Assembly, prefix: str) -> list[str]:
        """Qualified paths of parts inside ``asm`` that DON'T belong to
        any nested jointed sub. Walks past jointed children (they
        become their own group elsewhere) and aggregates the rest.
        Paths must match ``placed_parts`` names — that's how
        ``_inject_animation_into_glb`` finds the GLB nodes."""
        names = [f"{prefix}{p.name}" for p in asm.parts]
        for sub in asm.subassemblies:
            if sub.joint is None:
                names.extend(_walk_into(sub.assembly, f"{prefix}{sub.name}."))
        return names

    def _collect(asm: Assembly, prefix: str, out: list[list[str]]) -> None:
        for sub in asm.subassemblies:
            sub_prefix = f"{prefix}{sub.name}."
            if sub.joint is not None:
                owned = _walk_into(sub.assembly, sub_prefix)
                if owned:
                    out.append(owned)
            _collect(sub.assembly, sub_prefix, out)

    groups: list[list[str]] = []
    _collect(assembly, "", groups)
    return groups


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
    node that carries the shared relative-trajectory animation, with the
    group's parts re-parented as children. Static parts get no animation
    channel — the frame-0 TRS from ``export_glb`` carries them.

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

    to_yup = Rot(-90, 0, 0) if y_up else None
    ref_names = {p.name for p in ref_placed}
    samples: dict[str, list[tuple[tuple[float, float, float], tuple[float, float, float, float]]]] = {
        name: [] for name in ref_names
    }
    for t in ts_list:
        a = factory(t)
        seen: set[str] = set()
        for placed in a.placed_parts:
            if placed.name not in ref_names:
                continue
            loc = placed.location if to_yup is None else to_yup * placed.location
            trsf = loc.wrapped.Transformation()
            t_vec = trsf.TranslationPart()
            q = trsf.GetRotation()
            samples[placed.name].append(
                (
                    (t_vec.X(), t_vec.Y(), t_vec.Z()),
                    (q.X(), q.Y(), q.Z(), q.W()),
                )
            )
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
    # jointed `with_subassembly(...)` becomes one group. The relative
    # trajectory is derived from one representative member's sampled
    # absolute pose (any member works — they share the joint's motion
    # by construction). Flat assemblies produce no groups; any motion
    # there falls through to the per-part TRS samplers in
    # `_inject_animation_into_glb` (correct for static / pure-translation /
    # in-place-rotation; chord-drifts on orbital motion).
    structural = _structural_groups(ref_assembly)
    groups = [
        [n for n in g if n in ref_names and len(samples[n]) == len(ts_list)]
        for g in structural
    ]
    groups = [g for g in groups if g]
    group_trajectories = [_relative_trajectory(samples[g[0]]) for g in groups]
    for traj in group_trajectories:
        _align_quaternion_hemispheres(traj)

    times_s = [i * duration_s / (len(ts_list) - 1) for i in range(len(ts_list))]
    _inject_animation_into_glb(
        glb_path,
        samples=samples,
        groups=groups,
        group_trajectories=group_trajectories,
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


def _quat_mul(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Hamilton product of two quaternions in (x, y, z, w) order."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


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


def _relative_trajectory(
    samples_for_part: list[tuple[tuple[float, float, float], tuple[float, float, float, float]]],
) -> list[tuple[tuple[float, float, float], tuple[float, float, float, float]]]:
    """Compute T[i]·T[0]⁻¹ frame-by-frame in (translation, quaternion) form.

    The first entry is the identity transform by construction. When applied
    on top of the frame-0 absolute pose, this trajectory reproduces the
    original per-frame absolute pose: ``relative[i] · sampled[0] == sampled[i]``.
    """
    p0, q0 = samples_for_part[0]
    q0_inv = (-q0[0], -q0[1], -q0[2], q0[3])
    out: list[tuple[tuple[float, float, float], tuple[float, float, float, float]]] = []
    for p, q in samples_for_part:
        q_rel = _quat_mul(q, q0_inv)
        rotated_p0 = _quat_rotate(q_rel, p0)
        p_rel = (p[0] - rotated_p0[0], p[1] - rotated_p0[1], p[2] - rotated_p0[2])
        out.append((p_rel, q_rel))
    return out


def _inject_animation_into_glb(
    glb_path: Path,
    samples: dict[str, list[tuple[tuple[float, ...], tuple[float, ...]]]],
    groups: list[list[str]],
    group_trajectories: list[list[tuple[tuple[float, ...], tuple[float, ...]]]],
    times_s: list[float],
    animation_name: str,
) -> None:
    """Append an ``animation`` block to an existing GLB written by
    ``export_glb``. Locates target nodes by ``PlacedPart.name``.

    Parts in ``groups`` are re-parented under a freshly inserted scene
    node that carries the shared relative-trajectory animation —
    children inherit the parent's slerp'd rotation and so trace the
    correct arc between keyframes. Parts not in any group fall through
    to per-part TRS samplers (correct for static, pure-translation, and
    in-place-rotation parts; only orbital motion would chord-drift
    there, and that's exactly what grouping pulls out).
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

    # Re-parent grouped parts under a fresh animated node per group.
    # The child's existing static TRS (= frame-0 absolute pose) is left
    # alone — combined with parent's R[i] animation, the child reaches
    # sampled[i] at every keyframe and slerps along the true arc in
    # between.
    grouped_parts: set[str] = set()
    scene_root_ids = list(gltf.scenes[0].nodes)
    for group_idx, (members, traj) in enumerate(zip(groups, group_trajectories)):
        child_ids = [name_to_node[m] for m in members if m in name_to_node]
        if not child_ids or len(traj) != n_frames:
            continue
        parent_idx = len(gltf.nodes)
        gltf.nodes.append(
            pygltflib.Node(name=f"animgroup_{group_idx}", children=child_ids)
        )
        child_id_set = set(child_ids)
        scene_root_ids = [i for i in scene_root_ids if i not in child_id_set]
        scene_root_ids.append(parent_idx)
        grouped_parts.update(members)

        _add_sampler_channel(
            [c for _, q in traj for c in q],
            parent_idx, "rotation", pygltflib.VEC4, 4,
        )
        p0_rel = traj[0][0]
        rel_moves_trans = any(
            abs(p[k] - p0_rel[k]) > _EPS_POS_MM for p, _ in traj[1:] for k in range(3)
        )
        if rel_moves_trans:
            _add_sampler_channel(
                [c for p, _ in traj for c in p],
                parent_idx, "translation", pygltflib.VEC3, 3,
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
