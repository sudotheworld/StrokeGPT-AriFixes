import json
from pathlib import Path

import pytest

from funscript_catalog import FunScriptCatalog, FunScriptError


def _write_funscript(tmp_path: Path, name: str, actions):
    payload = {"actions": actions, "metadata": {"title": name}}
    path = tmp_path / f"{name}.funscript"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_ingest_and_lookup(tmp_path):
    catalog_path = tmp_path / "catalog.jsonl"
    catalog = FunScriptCatalog(catalog_path=catalog_path)

    script_path = _write_funscript(
        tmp_path,
        "teaser",
        [
            {"at": 0, "pos": 0},
            {"at": 500, "pos": 80},
            {"at": 1000, "pos": 20},
            {"at": 1500, "pos": 95},
        ],
    )

    result = catalog.ingest("uuid-123", script_path)
    assert result["ok"]
    entry = catalog.get("uuid-123")
    assert entry is not None
    assert entry["metrics"]["duration_seconds"] == pytest.approx(1.5)
    assert entry["metrics"]["stroke_count"] >= 1
    assert catalog.lookup_by_path(script_path) == entry

    summary = catalog.aggregated_summary()
    assert summary["count"] == 1
    assert summary["total_duration_seconds"] == pytest.approx(entry["metrics"]["duration_seconds"])


def test_invalid_funscript(tmp_path):
    catalog = FunScriptCatalog(catalog_path=tmp_path / "catalog.jsonl")
    bad_path = tmp_path / "bad.funscript"
    bad_path.write_text("{not json}", encoding="utf-8")

    result = catalog.ingest("bad", bad_path)
    assert not result["ok"]

    with pytest.raises(FunScriptError):
        catalog._normalise_actions([])

