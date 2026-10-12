"""Phase 2 unit tests for run records, baselines and agent detection plumbing."""

from __future__ import annotations

import time

from sprintwarden import baseline as bl
from sprintwarden import runs
from sprintwarden.config import Paths


def test_S02_run_ids_sort_chronologically_within_a_second():
    ids = []
    for _ in range(5):
        ids.append(runs.new_run_id())
        time.sleep(0.002)
    assert ids == sorted(ids)
    assert len(ids[0]) == len("20261012T103105123Z-3fa2")


def test_S02_run_files_are_sharded_by_month(tmp_path):
    paths = Paths(tmp_path)
    rid = "20261012T103105123Z-3fa2"
    assert runs.run_file(paths, rid) == tmp_path / ".sprint" / "runs" / "2026-10" / f"{rid}.json"


def test_S02_cap_lists_keeps_counts_honest():
    record = {"failing": list(range(250)), "missing": [1], "new_skips": []}
    capped = runs.cap_lists(record, cap=200)
    assert len(capped["failing"]) == 200 and capped["truncated"] == {"failing": 50}
    assert record["failing"] == list(range(250)), "original untouched"


def test_S02_effective_acceptances_follow_the_baseline():
    base = bl.Baseline(created="2026-10-12T10:00:00.500Z", tests={"a": "passed"})
    before = bl.Acceptance("a", "r", "h", "2026-10-12T10:00:00.400Z")
    after = bl.Acceptance("b", "r", "h", "2026-10-12T10:00:00.600Z")
    legacy_fmt = bl.Acceptance("c", "r", "h", "2026-10-12T10:00:01Z")
    eff = bl.effective([before, after, legacy_fmt], base)
    assert set(eff) == {"b", "c"}
    assert set(bl.effective([before], None)) == {"a"}


def test_S02_baseline_file_is_sorted_one_test_per_line(tmp_path):
    paths = Paths(tmp_path)
    bl.write_baseline(
        paths,
        {"z.b": "passed", "a.a": "skipped", "m.x": "failed"},
        reason="t",
        sprint=None,
        git={},
        run=None,
    )
    text = paths.baseline.read_text()
    assert text.index('"a.a"') < text.index('"z.b"') and '"m.x"' not in text
    assert bl.load_baseline(paths).total == 2
