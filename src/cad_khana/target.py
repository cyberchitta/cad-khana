"""Resolve a ``<module-path>[:<factory>]`` target to an ``Assembly``.

The import-model commands (``check``, ``export``, ``view``, ``draw``)
consume a module's real public surface — its named, parameterized
factories returning ``Assembly`` — the same surface a parent module
consumes. A *member* is a (factory, argument binding) pair; the CLI
names a factory and calls it with its defaults, so a factory's defaults
are the master design.

With no ``:factory``, the name ``assembly`` is resolved: a callable is
called, a bare ``Assembly`` value is accepted as the **degenerate**
form. Anything else is a boundary error that lists the module's public
factories — the error message is the discovery mechanism, which is why
the ``-> Assembly`` return annotation mandated by the code style is
load-bearing here.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from cad_khana.mechanism.assembly import Assembly

DEFAULT_MEMBER = "assembly"
ROOT_STEM = "assembly"

_MISSING = object()


class TargetError(Exception):
    """A target that names no resolvable assembly — a boundary error."""


@dataclass(frozen=True)
class Target:
    path: Path
    factory: str | None = None

    @staticmethod
    def parse(spec: str) -> Target:
        head, sep, tail = spec.rpartition(":")
        return (
            Target(Path(head), tail)
            if sep and tail.isidentifier()
            else Target(Path(spec))
        )

    @property
    def slug(self) -> str:
        stem = self.path.stem
        return stem if self.factory is None else f"{stem}-{self.factory}"

    @property
    def default_out(self) -> Path:
        """``<module-dir>/outputs`` for a unit's ``assembly.py``, and a
        per-slug subdirectory for every other target, so co-located
        targets (``assembly.py`` beside ``check_cones.py``) never
        overwrite each other's ``mechanism.json``."""
        outputs = self.path.resolve().parent / "outputs"
        return outputs if self.slug == ROOT_STEM else outputs / self.slug


def package_module_spec(path: Path) -> tuple[str, Path] | None:
    """Dotted module name + ``sys.path`` root for a file that is a
    package member (its directory and every ancestor up to the package
    root carry an ``__init__.py``). ``None`` for plain scripts."""
    path = path.resolve()
    if not (path.parent / "__init__.py").exists():
        return None
    root = path.parent
    while (root.parent / "__init__.py").exists():
        root = root.parent
    parts = path.relative_to(root.parent).with_suffix("").parts
    if not all(p.isidentifier() for p in parts):
        return None
    return ".".join(parts), root.parent


def load(path: Path) -> ModuleType:
    """Import ``path`` as a module — with ``python -m`` semantics when it
    is a package member, so its relative imports resolve. Plain
    ``importlib``: no caching layer of our own, so consumers that evict
    ``sys.modules`` entries to re-import under different globals keep
    working."""
    spec = package_module_spec(path)
    if spec is None:
        return _load_standalone(path)
    module, root = spec
    _ensure_importable(root)
    return importlib.import_module(module)


def _ensure_importable(root: Path) -> None:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _load_standalone(path: Path) -> ModuleType:
    path = path.resolve()
    _ensure_importable(path.parent)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def factories(module: ModuleType) -> tuple[str, ...]:
    """Public callables defined in ``module`` and annotated ``-> Assembly``."""
    return tuple(
        name
        for name, obj in vars(module).items()
        if not name.startswith("_")
        and getattr(obj, "__module__", None) == module.__name__
        and _returns_assembly(obj)
    )


def _returns_assembly(obj: object) -> bool:
    if not callable(obj):
        return False
    try:
        annotation = inspect.signature(obj).return_annotation
    except (TypeError, ValueError):
        return False
    return annotation is Assembly or (
        isinstance(annotation, str)
        and annotation.rpartition(".")[2] == Assembly.__name__
    )


def _discovery_hint(module: ModuleType, target: Target) -> str:
    names = factories(module)
    return (
        f"public factories returning Assembly: {', '.join(names)} — "
        f"address one as '{target.path}:{names[0]}'"
        if names
        else "and no public factory returning Assembly was found "
        "(a factory is a function annotated '-> Assembly')"
    )


def resolve(target: Target) -> Assembly:
    module = load(target.path)
    name = target.factory or DEFAULT_MEMBER
    obj = getattr(module, name, _MISSING)
    if obj is _MISSING:
        raise TargetError(
            f"{target.path} has no '{name}'; {_discovery_hint(module, target)}"
        )
    if callable(obj):
        return _returned(obj(), name, target)
    if target.factory is None and isinstance(obj, Assembly):
        return obj
    raise TargetError(
        f"{target.path}: '{name}' is a {type(obj).__name__}, not "
        f"{'a factory' if target.factory else 'a factory or an Assembly'}; "
        f"{_discovery_hint(module, target)}"
    )


def _returned(value: object, name: str, target: Target) -> Assembly:
    if isinstance(value, Assembly):
        return value
    raise TargetError(
        f"{target.path}: '{name}()' returned {type(value).__name__}, "
        "expected an Assembly"
    )
