"""tests/AC_MATRIX.md stays complete and true (AGENTS.md: every AC maps to a test layer).

Checks the matrix against the repo, not against itself: every spec §9 AC has a row, every row
says where each layer stands in the agreed words, every test it cites exists, and every EL
agent test in backend/agent/tests/ is cited.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MATRIX = (ROOT / "tests" / "AC_MATRIX.md").read_text()
SPEC = (ROOT / "docs" / "product-specification.md").read_text()
STATUSES = ("done", "written-not-run", "deferred")


def _rows() -> list[list[str]]:
    rows = []
    for line in MATRIX.split("\n## Exceptions")[0].splitlines():
        if line.startswith("| ") and not line.startswith(("| AC |", "| Rule |", "|---")):
            rows.append([cell.strip() for cell in line.strip().strip("|").split(" | ")])
    return rows


def _cited() -> list[tuple[str, str | None]]:
    """(path, test name or None) for every backticked repo path in the matrix."""
    cited: list[tuple[str, str | None]] = []
    for row in _rows():
        last: str | None = None
        for token in re.findall(r"`([^`]+)`", " | ".join(row)):
            path, _, name = token.partition("::")
            if path:
                if "/" not in path or not re.search(r"\.\w+$", path):
                    continue
                if path.endswith(".py"):
                    last = path  # a bare `::name` after it names a test in this file
            elif last is None:
                continue
            else:
                path = last
            cited.append((path, name or None))
    return cited


def test_every_spec_ac_has_a_row() -> None:
    spec_acs = re.findall(r"^- (AC\d\.\d|ACX\.\d) ", SPEC, flags=re.M)
    matrix_acs = {row[0] for row in _rows()}

    assert len(spec_acs) == 35
    assert [ac for ac in spec_acs if ac not in matrix_acs] == []


@pytest.mark.parametrize("row", _rows(), ids=lambda r: r[0][:30])
def test_every_row_states_each_layer_as_done_written_not_run_or_deferred(row: list[str]) -> None:
    status = row[4]
    assert not re.search(r"\b(defined|planned)\b", status), (row[0], status)
    segments = [s.strip() for s in re.sub(r"\([^)]*\)", "", status).split(";") if s.strip()]

    assert segments, row[0]
    for segment in segments:
        assert segment.split()[-1] in STATUSES, (row[0], segment)


@pytest.mark.parametrize(("path", "name"), _cited(), ids=lambda v: str(v))
def test_every_cited_test_exists(path: str, name: str | None) -> None:
    file = ROOT / path
    assert file.exists(), path
    if name is None:
        return
    source = file.read_text()
    if name.endswith("*"):
        assert re.search(rf"def {re.escape(name[:-1])}\w*\(", source), f"{path}::{name}"
    else:
        assert re.search(rf"def {re.escape(name)}\(", source), f"{path}::{name}"


def test_every_el_agent_test_is_cited() -> None:
    cited = {path for path, _ in _cited()}
    el_tests = {
        str(p.relative_to(ROOT)) for p in (ROOT / "backend" / "agent" / "tests").glob("*.json")
    }

    assert sorted(el_tests - cited) == []
