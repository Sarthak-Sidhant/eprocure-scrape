import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orgs  # noqa: E402
from seed import remap_counts  # noqa: E402


def test_ids_are_rekeyed_by_name():
    counts = {"222": {"name": "DG,BSF,MHA", "tenders_count": 3592}, "160": {"name": "Delhi Development Authority", "tenders_count": 5}}
    live = {"160": "Delhi Development Authority", "223": "DG,BSF,MHA", "222": "Development Monitoring and Evaluation Office"}
    out, moved, skipped = remap_counts(counts, live)
    assert set(out) == {"223", "160"} and moved == 1 and skipped == []


def test_zero_count_orgs_are_dropped():
    out, _, _ = remap_counts({"1": {"name": "A", "tenders_count": 0}}, {"1": "A"})
    assert out == {}


def test_ambiguous_and_missing_names_are_skipped_not_guessed():
    counts = {"1": {"name": "Dup", "tenders_count": 3}, "2": {"name": "Gone", "tenders_count": 4}}
    out, _, skipped = remap_counts(counts, {"10": "Dup", "11": "Dup"})
    assert out == {} and {s[0] for s in skipped} == {"1", "2"}


def test_name_matching_ignores_case_and_spacing():
    assert orgs.norm("  Ministry  of Railways ") == orgs.norm("ministry of railways")
