"""Drive a viewer page that is open in a host: ask what it shows, and
change it.

`khana view` writes the page; the owner opens it in a host. Two hosts
carry pair-ui's messages to it: the pair-ui host, which serves the page
to a plain browser and listens on a socket per project, and Shala, which
frames it. Each has a command that carries one JSON body to the page and
prints its answer, in the same form: ``pair-ui tell`` and ``shala
tell``, and ``reveal`` for a moniker. A pair-ui host listening for the
project is the one used; otherwise Shala. Everything here but ``ask``,
``reveal`` and ``carrier`` is pure: the bodies, and the reading of what
came back.

The bodies are the page's own (``viewer/src/page.ts``). ``PROTOCOL`` is
the number both sides carry: a page built for another refuses the body
and says to write the page again.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cad_khana.selection import paths

PROTOCOL = 2
SHALA = "shala"
PAIR_UI = "pair-ui"
DIRECTIONS = ("iso", "front", "rear", "left", "right", "top", "bottom")
GETS = ("parts", "picked", "view", "frame")

Body = dict[str, object]
Run = Callable[..., "subprocess.CompletedProcess[str]"]

_BUILD = re.compile(r"\s*\(build of (.*)\)")


class Refused(Exception):
    """The page, or its host, said no: nothing changed."""


class Unreachable(Exception):
    """No answer could be had: no carrier, or no host running."""


@dataclass(frozen=True)
class Answer:
    """What the page said. ``target`` is the assembly it was written
    from, ``build`` when its files were written."""

    result: dict[str, object]
    message: str | None = None
    build: str | None = None

    @property
    def target(self) -> str:
        return str(self.result.get("target") or "an unnamed target")

    @property
    def page(self) -> str:
        return self.target + (f" (build of {self.build})" if self.build else "")


def project(cwd: Path) -> str | None:
    """The name a host knows this directory's project by: its
    repository's folder."""
    here = cwd.resolve()
    return next((p.name for p in (here, *here.parents) if (p / ".git").exists()), None)


def pair_socket(project: str, env: dict[str, str] | None = None) -> Path:
    """Where a pair-ui host serving ``project`` listens: pair-ui's own
    ``socket_path``."""
    found = os.environ if env is None else env
    base = found.get("XDG_RUNTIME_DIR") or found.get("TMPDIR") or "/tmp"
    return Path(base) / "pair-ui" / f"{project}.sock"


def listening(path: Path) -> bool:
    """Whether a host answers on the socket: a file left behind by a
    stopped one does not."""
    with socket.socket(socket.AF_UNIX) as probe:
        try:
            probe.connect(str(path))
        except OSError:
            return False
    return True


def carrier(project: str) -> str:
    """The command that reaches ``project``'s page: pair-ui's when its
    host is listening, else Shala's."""
    return PAIR_UI if listening(pair_socket(project)) else SHALA


def get(*keys: str) -> Body:
    return {"khana": PROTOCOL, "get": list(keys)}


def panes(tree: bool | None, info: bool | None, toolbar: bool | None) -> Body:
    """Only the panes named: one left out keeps its state."""
    named = {"tree": tree, "info": info, "toolbar": toolbar}
    return {
        "khana": PROTOCOL,
        "set": {k: v for k, v in named.items() if v is not None},
    }


def show(part: str | None = None, **view: object) -> Body:
    """Select ``part`` and set whichever view keys are not ``None``."""
    given = {k: v for k, v in view.items() if v is not None}
    return {
        "khana": PROTOCOL,
        "show": {
            **({} if part is None else {"part": part}),
            **({"view": given} if given else {}),
        },
    }


def hidden(
    parts: tuple[str, ...], only: tuple[str, ...], hide: tuple[str, ...]
) -> list[str]:
    """Every part the selection leaves out. The page takes the whole
    list, so a part not in it is shown."""
    kept = frozenset(paths(parts, only, hide))
    return [p for p in parts if p not in kept]


def parse(stdout: str) -> Answer:
    """A carrier's output: a `told` or `revealed` line, then a
    ``message:`` and a ``result:`` line when the page sent them. Shala
    names the build on the first line, and puts a reveal's message there
    after ``in the app:``."""
    lines = stdout.splitlines()
    first = lines[0] if lines else ""
    fields = dict(line.split(": ", 1) for line in lines[1:] if ": " in line)
    build = _BUILD.search(first)
    _, inline, said = _BUILD.sub("", first).partition(" in the app: ")
    return Answer(
        result=json.loads(fields.get("result", "{}")),
        message=fields.get("message") or (said if inline else None),
        build=build.group(1) if build else None,
    )


def _carry(via: str, args: list[str], run: Run) -> Answer:
    """Runs the carrier. Each exits 1 for a page that refused or none
    that answered, and Shala 2 when it is not running."""
    try:
        done = run([via, *args], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise Unreachable(
            f"`{via}` is not on the PATH: it is what reaches the page"
        ) from None
    said = done.stderr.strip() or done.stdout.strip()
    if done.returncode == 1:
        raise Refused(said)
    if done.returncode:
        raise Unreachable(said)
    return parse(done.stdout)


def ask(
    project: str, body: Body, run: Run = subprocess.run, via: str | None = None
) -> Answer:
    """Carries ``body`` to the page open for ``project`` and returns its
    answer."""
    text = json.dumps(body, separators=(",", ":"))
    return _carry(via or carrier(project), ["tell", project, text], run)


def reveal(
    moniker: str,
    project: str,
    state: str | None = None,
    run: Run = subprocess.run,
    via: str | None = None,
) -> Answer:
    """Asks the page open for ``project`` to put back what ``moniker``
    names, and the view in ``state`` (JSON) when given."""
    given = [] if state is None else ["--state", state]
    chosen = via or carrier(project)
    args = (
        ["reveal", moniker, *given]
        if chosen == PAIR_UI
        else ["reveal", *given, moniker]
    )
    return _carry(chosen, args, run)
