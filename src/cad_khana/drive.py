"""Drive a viewer page that is open in a host: ask what it shows, and
change it.

`khana view` writes the page; the owner opens it in a host that frames
it. Shala is the host there is, and its ``shala tell`` carries one JSON
body to the page and prints the page's answer. Everything here but
``ask`` is pure: the bodies, and the reading of what came back.

Only ``ask`` and ``parse`` know the host. Another carrier is another
pair of them returning the same ``Answer``: the bodies, the page and the
commands do not change.

The bodies are the page's own (``viewer/src/page.ts``). ``PROTOCOL`` is
the number both sides carry: a page built for another refuses the body
and says to write the page again.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cad_khana.selection import paths

PROTOCOL = 2
CARRIER = "shala"
DIRECTIONS = ("iso", "front", "rear", "left", "right", "top", "bottom")
GETS = ("parts", "picked", "view", "frame")

Body = dict[str, object]
Run = Callable[..., "subprocess.CompletedProcess[str]"]

_BUILD = re.compile(r"\(build of (.*)\)")


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
    """``shala tell``'s output: a `told` line naming the build, then a
    ``message:`` and a ``result:`` line when the page sent them."""
    lines = stdout.splitlines()
    fields = dict(line.split(": ", 1) for line in lines[1:] if ": " in line)
    build = _BUILD.search(lines[0]) if lines else None
    return Answer(
        result=json.loads(fields.get("result", "{}")),
        message=fields.get("message"),
        build=build.group(1) if build else None,
    )


def ask(project: str, body: Body, run: Run = subprocess.run) -> Answer:
    """Carries ``body`` to the page open for ``project`` and returns its
    answer. The carrier exits 1 for a page that refused or is not open,
    and 2 when the host is not running."""
    try:
        done = run(
            [CARRIER, "tell", project, json.dumps(body, separators=(",", ":"))],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise Unreachable(
            f"`{CARRIER}` is not on the PATH: it is what reaches the page"
        ) from None
    said = done.stderr.strip() or done.stdout.strip()
    if done.returncode == 1:
        raise Refused(said)
    if done.returncode:
        raise Unreachable(said)
    return parse(done.stdout)
