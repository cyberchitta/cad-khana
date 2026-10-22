import json
import re
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

from cad_khana import drive
from cad_khana.selection import SelectionError

PAGE = Path(__file__).parents[1] / "viewer" / "src" / "page.ts"


def _carrier(
    code: int, stdout: str = "", stderr: str = ""
) -> tuple[list[list[str]], drive.Run]:
    calls: list[list[str]] = []

    def run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, code, stdout, stderr)

    return calls, run


def test_the_command_and_the_page_carry_the_same_protocol_number():
    """The page refuses a body with another number, so the two must be
    changed together."""
    found = re.search(r"^const PROTOCOL = (\d+);", PAGE.read_text(), re.M)
    assert found is not None
    assert int(found.group(1)) == drive.PROTOCOL


def test_the_page_takes_every_direction_and_get_the_command_offers():
    source = PAGE.read_text()
    for name, offered in (("DIRECTIONS", drive.DIRECTIONS), ("GETS", drive.GETS)):
        found = re.search(rf"^const {name} = \[(.*)\] as const;", source, re.M)
        assert found is not None
        assert tuple(json.loads(f"[{found.group(1)}]")) == offered


def test_show_carries_only_what_was_asked():
    assert drive.show("unit.cube") == {
        "khana": drive.PROTOCOL,
        "show": {"part": "unit.cube"},
    }
    assert drive.show(None, direction="top", hidden=[], ortho=None) == {
        "khana": drive.PROTOCOL,
        "show": {"view": {"direction": "top", "hidden": []}},
    }
    assert drive.show(None, ortho=None)["show"] == {}


def test_panes_leaves_out_the_ones_not_named():
    assert drive.panes(False, None, True)["set"] == {"tree": False, "toolbar": True}


def test_hidden_is_every_part_the_selection_leaves_out():
    parts = ("lid", "unit.cube", "unit.rod", "unit10.cube")
    assert drive.hidden(parts, (), ("unit",)) == ["unit.cube", "unit.rod"]
    assert drive.hidden(parts, ("unit",), ("unit.rod",)) == [
        "lid",
        "unit.rod",
        "unit10.cube",
    ]
    with pytest.raises(SelectionError):
        drive.hidden(parts, (), ("units",))


def test_parse_reads_the_build_the_message_and_the_result():
    answer = drive.parse(
        "told sorted-studs (build of 2026-10-12 19:02)\n"
        "message: toolbar hidden\n"
        'result: {"target": "cad/a.py:build", "parts": ["lid: a"]}\n'
    )
    assert answer.build == "2026-10-12 19:02"
    assert answer.message == "toolbar hidden"
    assert answer.result["parts"] == ["lid: a"]
    assert answer.page == "cad/a.py:build (build of 2026-10-12 19:02)"
    assert drive.parse("told p (build of now)\n").result == {}


def test_ask_sends_one_line_of_json_to_the_carrier():
    calls, run = _carrier(0, 'told p (build of now)\nresult: {"target": "a.py"}\n')
    answer = drive.ask("p", drive.get("parts"), run)
    assert answer.target == "a.py"
    assert calls == [["shala", "tell", "p", '{"khana":2,"get":["parts"]}']]


def test_ask_tells_a_refusal_from_no_answer():
    _, refusing = _carrier(1, stderr="shala: no part lidd\n")
    with pytest.raises(drive.Refused, match="no part lidd"):
        drive.ask("p", drive.show("lidd"), refusing)
    _, down = _carrier(2, stderr="shala: Shala is not running\n")
    with pytest.raises(drive.Unreachable, match="not running"):
        drive.ask("p", drive.get("parts"), down)

    def absent(_args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("shala")

    with pytest.raises(drive.Unreachable, match="PATH"):
        drive.ask("p", drive.get("parts"), absent)


def test_project_is_the_repository_folder(tmp_path: Path):
    (tmp_path / "studs" / ".git").mkdir(parents=True)
    (tmp_path / "studs" / "cad" / "m1").mkdir(parents=True)
    assert drive.project(tmp_path / "studs" / "cad" / "m1") == "studs"
    assert drive.project(tmp_path / "studs") == "studs"


def test_the_pair_socket_is_where_pair_ui_puts_it():
    assert drive.pair_socket(
        "studs", {"XDG_RUNTIME_DIR": "/run/u", "TMPDIR": "/t"}
    ) == Path("/run/u/pair-ui/studs.sock")
    assert drive.pair_socket("studs", {"TMPDIR": "/t/"}) == Path(
        "/t/pair-ui/studs.sock"
    )
    assert drive.pair_socket("studs", {}) == Path("/tmp/pair-ui/studs.sock")


def test_a_socket_counts_only_while_a_host_answers_on_it():
    # A short directory: a Unix socket's path has a length limit.
    with tempfile.TemporaryDirectory(dir="/tmp") as where:
        path = Path(where) / "p.sock"
        assert not drive.listening(path)
        with socket.socket(socket.AF_UNIX) as host:
            host.bind(str(path))
            host.listen()
            assert drive.listening(path)
        assert path.exists()
        assert not drive.listening(path)


def test_ask_through_pair_ui_sends_what_shala_would():
    calls, run = _carrier(0, 'told p\nmessage: \nresult: {"target": "a.py"}\n')
    answer = drive.ask("p", drive.get("parts"), run, via=drive.PAIR_UI)
    assert answer.target == "a.py"
    assert answer.message is None
    assert calls == [["pair-ui", "tell", "p", '{"khana":2,"get":["parts"]}']]


def test_reveal_puts_the_state_where_each_carrier_takes_it():
    moniker = "khana://p/a.py#part=lid"
    calls, run = _carrier(0, f"revealed {moniker}\nmessage: a.py: put back part lid\n")
    answer = drive.reveal(moniker, "p", '{"ortho":true}', run, via=drive.PAIR_UI)
    assert answer.message == "a.py: put back part lid"
    shala = f"revealed {moniker} in the app: a.py: put back part lid (build of now)\n"
    later, run = _carrier(0, shala)
    answer = drive.reveal(moniker, "p", '{"ortho":true}', run, via=drive.SHALA)
    assert (answer.message, answer.build) == ("a.py: put back part lid", "now")
    assert calls + later == [
        ["pair-ui", "reveal", moniker, "--state", '{"ortho":true}'],
        ["shala", "reveal", "--state", '{"ortho":true}', moniker],
    ]
