"""End-to-end tests for ``export_animated_glb``: the exported glTF is
evaluated the way a viewer would (LINEAR translation, slerp'd rotation,
node hierarchy composed) and compared against the factory's own
``placed_parts`` — at keyframes and *between* them, which is where an
off-origin joint used to leave its arc along the chord.
"""

import shutil
import struct
from pathlib import Path

import numpy as np
import pygltflib
import pytest
from build123d import Axis, Box, BuildPart, Location, Pos, Rot

from cad_khana.export import export_animated_glb
from cad_khana.mechanism.assembly import Assembly, RevoluteJoint

pytestmark = pytest.mark.skipif(
    shutil.which("gltf-transform") is None, reason="gltf-transform not installed"
)

TS = [0.0, 1.0, 2.0]
DURATION_S = 4.0


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def _factory(t: float) -> Assembly:
    """A hinge nested under a turning stack, its axis 200 mm off the
    stack's — plus a parent-frame door hinge that misses the origin."""
    trap = Assembly().with_part("flap", _cube(), location=Pos(30, 0, 0))
    stack = (
        Assembly()
        .with_part("drum", _cube(20))
        .with_subassembly(
            "trap",
            trap,
            location=Pos(200, 0, 50),
            joint=RevoluteJoint(axis=Axis.Y, angle_deg=50 * t, frame="local"),
        )
    )
    door = Assembly().with_part("leaf", _cube(), location=Pos(140, 0, 0))
    return (
        Assembly()
        .with_part("base", _cube(5), location=Pos(0, 0, -50))
        .with_subassembly(
            "stack", stack, joint=RevoluteJoint(axis=Axis.Z, angle_deg=40 * t)
        )
        .with_subassembly(
            "door",
            door,
            joint=RevoluteJoint(
                axis=Axis((100, -80, 0), (0, 0, 1)), angle_deg=-60 * t
            ),
        )
    )


def _matrix(location: Location) -> np.ndarray:
    trsf = location.wrapped.Transformation()
    return np.array(
        [[trsf.Value(r, c) for c in range(1, 5)] for r in range(1, 4)]
        + [[0.0, 0.0, 0.0, 1.0]]
    )


def _trs_matrix(translation, rotation) -> np.ndarray:
    x, y, z, w = rotation
    m = np.eye(4)
    m[:3, :3] = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    m[:3, 3] = translation
    return m


def _slerp(a: np.ndarray, b: np.ndarray, u: float) -> np.ndarray:
    dot = float(np.dot(a, b))
    b, dot = (-b, -dot) if dot < 0 else (b, dot)
    theta = np.arccos(min(dot, 1.0))
    if theta < 1e-9:
        return a
    return (np.sin((1 - u) * theta) * a + np.sin(u * theta) * b) / np.sin(theta)


class _Scene:
    """Just enough of a glTF player: TRS nodes, one animation, LINEAR."""

    def __init__(self, path: Path):
        self.gltf = pygltflib.GLTF2().load(str(path))
        self.blob = self.gltf.binary_blob()
        self.parent = {
            c: i for i, n in enumerate(self.gltf.nodes) for c in (n.children or [])
        }
        self.index = {n.name: i for i, n in enumerate(self.gltf.nodes) if n.name}
        anim = self.gltf.animations[0]
        self.tracks = {
            (ch.target.node, ch.target.path): (
                self._read(anim.samplers[ch.sampler].input),
                self._read(anim.samplers[ch.sampler].output),
            )
            for ch in anim.channels
        }

    def _read(self, accessor_idx: int) -> np.ndarray:
        acc = self.gltf.accessors[accessor_idx]
        bv = self.gltf.bufferViews[acc.bufferView]
        width = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[acc.type]
        start = (bv.byteOffset or 0) + (acc.byteOffset or 0)
        flat = struct.unpack_from(f"<{acc.count * width}f", self.blob, start)
        return np.array(flat).reshape(acc.count, width)

    def channels(self, node_name: str) -> set[str]:
        return {p for (n, p) in self.tracks if n == self.index[node_name]}

    def _sample(self, node_idx: int, path: str, time_s: float, static):
        if (node_idx, path) not in self.tracks:
            return np.array(static)
        times, values = self.tracks[(node_idx, path)]
        times = times[:, 0]
        hi = int(np.clip(np.searchsorted(times, time_s), 1, len(times) - 1))
        u = (time_s - times[hi - 1]) / (times[hi] - times[hi - 1])
        a, b = values[hi - 1], values[hi]
        return _slerp(a, b, u) if path == "rotation" else (1 - u) * a + u * b

    def _local(self, node_idx: int, time_s: float) -> np.ndarray:
        n = self.gltf.nodes[node_idx]
        return _trs_matrix(
            self._sample(node_idx, "translation", time_s, n.translation or [0, 0, 0]),
            self._sample(node_idx, "rotation", time_s, n.rotation or [0, 0, 0, 1]),
        )

    def world(self, node_name: str, time_s: float) -> np.ndarray:
        idx = self.index[node_name]
        m = self._local(idx, time_s)
        while idx in self.parent:
            idx = self.parent[idx]
            m = self._local(idx, time_s) @ m
        return m


def _expected(t: float) -> dict[str, np.ndarray]:
    y_up = Rot(-90, 0, 0)
    return {p.name: _matrix(y_up * p.location) for p in _factory(t).placed_parts}


def _time_s(t: float) -> float:
    return (t - TS[0]) / (TS[-1] - TS[0]) * DURATION_S


@pytest.fixture(scope="module", params=[False, True], ids=["plain", "draco"])
def scene(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> _Scene:
    out = tmp_path_factory.mktemp("animated")
    return _Scene(
        export_animated_glb(
            _factory, TS, out, duration_s=DURATION_S, draco=request.param
        )
    )


@pytest.mark.parametrize("t", TS)
def test_keyframe_poses_match_the_factory(scene: _Scene, t: float):
    for name, want in _expected(t).items():
        assert np.allclose(scene.world(name, _time_s(t)), want, atol=1e-2), name


@pytest.mark.parametrize("t", [0.5, 1.5, 0.25])
def test_poses_between_keyframes_stay_on_the_arc(scene: _Scene, t: float):
    for name, want in _expected(t).items():
        assert np.allclose(scene.world(name, _time_s(t)), want, atol=1e-2), name


def test_revolute_groups_carry_no_translation_channel(scene: _Scene):
    groups = [n.name for n in scene.gltf.nodes if (n.name or "").startswith("animgroup_")]
    assert len(groups) == 3
    assert all(scene.channels(g) == {"rotation"} for g in groups)


def test_joint_group_nodes_nest_like_the_joints(scene: _Scene):
    flap_group = scene.parent[scene.index["stack.trap.flap"]]
    drum_group = scene.parent[scene.index["stack.drum"]]
    assert scene.parent[flap_group] == drum_group
    assert drum_group not in scene.parent


def test_motion_beyond_the_joint_is_kept_exact_at_keyframes(tmp_path: Path):
    """A jointed sub whose placement also slides: the joint can't account
    for the slide, so it survives as the group's translation channel."""

    def sliding(t: float) -> Assembly:
        arm = Assembly().with_part("tip", _cube(), location=Pos(40, 0, 0))
        return Assembly().with_subassembly(
            "arm",
            arm,
            location=Pos(100 + 25 * t, 60, 0),
            joint=RevoluteJoint(axis=Axis.Z, angle_deg=30 * t, frame="local"),
        )

    scene = _Scene(
        export_animated_glb(sliding, TS, tmp_path, duration_s=DURATION_S, draco=False)
    )
    assert scene.channels("animgroup_0") == {"rotation", "translation"}
    y_up = Rot(-90, 0, 0)
    for t in TS:
        want = _matrix(y_up * sliding(t).placed_parts[0].location)
        assert np.allclose(scene.world("arm.tip", _time_s(t)), want, atol=1e-2)
