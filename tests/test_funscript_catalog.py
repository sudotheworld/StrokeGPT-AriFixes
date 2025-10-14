from pathlib import Path

import pytest

from funscript_catalog import FunScriptCatalog


@pytest.fixture()
def catalog(tmp_path: Path) -> FunScriptCatalog:
    catalogue_path = tmp_path / "memory" / "funscript_catalog.jsonl"
    return FunScriptCatalog(catalog_path=catalogue_path)


def test_ingest_and_lookup(catalog: FunScriptCatalog):
    sample = {
        "actions": [
            {"at": 0, "pos": 0},
            {"at": 500, "pos": 100},
            {"at": 1000, "pos": 0},
            {"at": 1500, "pos": 100},
            {"at": 2000, "pos": 0},
        ]
    }

    result = catalog.ingest("abc123", sample, file_name="test.funscript")
    assert result["ok"] is True

    stored = catalog.get("abc123")
    assert stored is not None
    assert stored["file_name"] == "test.funscript"
    assert stored["metrics"]["duration_s"] == pytest.approx(2.0, abs=0.01)
    assert stored["metrics"]["stroke_count"] >= 1
    assert stored["action_count"] == len(sample["actions"])

    # The normalized list should not exceed the configured maximum
    assert len(stored["normalized_actions"]) <= catalog._max_actions


def test_summary_and_filename_lookup(catalog: FunScriptCatalog):
    first = {
        "actions": [
            {"at": 0, "pos": 10},
            {"at": 1000, "pos": 90},
            {"at": 2000, "pos": 20},
            {"at": 3000, "pos": 80},
        ]
    }
    second = {
        "actions": [
            {"at": 0, "pos": 0},
            {"at": 750, "pos": 100},
            {"at": 1500, "pos": 0},
        ]
    }

    catalog.ingest("one", first, file_name="alpha.funscript")
    catalog.ingest("two", second, file_name="beta.funscript")

    matches = catalog.find_by_filename("alpha.funscript")
    assert len(matches) == 1
    assert matches[0]["uuid"] == "one"

    summary = catalog.aggregate_summary()
    assert summary["total_files"] == 2
    assert summary["average_duration_s"] > 0
    assert summary["tempo_spm"]["min"] is None or summary["tempo_spm"]["min"] >= 0


def test_ingest_rejects_bad_payload(catalog: FunScriptCatalog):
    bad = {"actions": [{"at": "nan", "pos": "nan"}]}
    result = catalog.ingest("bad", bad)
    assert result["ok"] is False
    assert "error" in result
