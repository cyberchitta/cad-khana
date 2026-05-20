from __future__ import annotations

import platform
import socket
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as _pkg_version

from cad_khana.mechanism.diagnostics import SCHEMA_VERSION

_VIEWER_DEFAULT_PORT = 3939
_VIEWER_PROBE_TIMEOUT_S = 0.2


@dataclass(frozen=True)
class ViewerStatus:
    importable: bool
    reachable: bool
    error: str | None


@dataclass(frozen=True)
class EnvironmentReport:
    cad_khana: str
    python: str
    build123d: str
    bd_warehouse: str | None
    ocp_vscode: ViewerStatus
    schema_version: str
    status: str


def _pkg(name: str, default: str | None) -> str | None:
    try:
        return _pkg_version(name)
    except PackageNotFoundError:
        return default


def _is_listening(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_viewer() -> ViewerStatus:
    try:
        from ocp_vscode import get_port
    except ImportError as exc:
        return ViewerStatus(importable=False, reachable=False, error=str(exc))
    try:
        port = get_port() or _VIEWER_DEFAULT_PORT
    except Exception as exc:
        port = _VIEWER_DEFAULT_PORT
        port_err: str | None = str(exc)
    else:
        port_err = None
    if not _is_listening("localhost", int(port), _VIEWER_PROBE_TIMEOUT_S):
        return ViewerStatus(
            importable=True,
            reachable=False,
            error=port_err or f"no listener on port {port}",
        )
    return ViewerStatus(importable=True, reachable=True, error=None)


def probe() -> EnvironmentReport:
    viewer = _probe_viewer()
    return EnvironmentReport(
        cad_khana=_pkg("cad-khana", "unknown") or "unknown",
        python=platform.python_version(),
        build123d=_pkg("build123d", "unknown") or "unknown",
        bd_warehouse=_pkg("bd-warehouse", None),
        ocp_vscode=viewer,
        schema_version=SCHEMA_VERSION,
        status="ok" if viewer.reachable else "degraded",
    )
