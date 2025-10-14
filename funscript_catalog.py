"""Utilities for analysing and cataloguing FunScript patterns.

This module normalises FunScript action timelines, computes coarse
metrics, and persists enriched metadata into a JSONL catalogue stored in
the same memory directory used by :mod:`memory_manager`.  It provides a
small API that backend routes and the LLM layer can leverage to ingest
new patterns, look them up by UUID or filename, and surface aggregate
summaries.  Malformed or incompatible FunScripts are handled gracefully
with descriptive errors so ingestion never interrupts the main
application.
"""

from __future__ import annotations

import json
import math
import os
import pathlib
import statistics
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = ["FunScriptCatalog", "FunScriptCatalogError", "FunScriptValidationError"]


class FunScriptCatalogError(Exception):
    """Base exception for catalogue operations."""


class FunScriptValidationError(FunScriptCatalogError):
    """Raised when the supplied FunScript payload cannot be analysed."""


# Re-use the same memory directory as memory_manager by default.
_BASE_DIR = pathlib.Path(os.environ.get("STROKEGPT_DATA", ".")) / "memory"
_BASE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class _AnalysisResult:
    uuid: str
    file_name: str | None
    source_path: str | None
    action_count: int
    normalized_actions: List[Dict[str, float]]
    metrics: Dict[str, Any]

    def to_record(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "file_name": self.file_name,
            "source_path": self.source_path,
            "action_count": self.action_count,
            "normalized_actions": self.normalized_actions,
            "metrics": self.metrics,
            "imported_at": time.time(),
        }


class FunScriptCatalog:
    """Analyse FunScripts and persist derived metadata to JSONL storage."""

    def __init__(self, catalog_path: pathlib.Path | None = None, *, max_actions: int = 500) -> None:
        self.catalog_path = catalog_path or (_BASE_DIR / "funscript_catalog.jsonl")
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self.catalog_path.touch(exist_ok=True)
        self._max_actions = max_actions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def ingest(self, file_uuid: str, funscript: Any, *, file_name: str | None = None,
               source_path: str | None = None) -> Dict[str, Any]:
        """Analyse a FunScript payload and persist the resulting metadata.

        Parameters
        ----------
        file_uuid:
            Stable identifier for the pattern.  Used as the primary key in
            the catalogue.
        funscript:
            Either a dict already parsed from JSON, a JSON string, or a
            filesystem path pointing to a `.funscript`/`.json` file.
        file_name:
            Optional friendly name for the file (e.g. uploaded filename).
        source_path:
            Optional absolute/relative path where the file originated.
        """

        record: Dict[str, Any]
        try:
            data = self._load_funscript(funscript)
            analysis = self._analyse(file_uuid, data, file_name=file_name, source_path=source_path)
            record = analysis.to_record()
        except FunScriptCatalogError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # pragma: no cover - defensive guard
            return {"ok": False, "error": f"unexpected error: {exc}"}

        self._upsert_record(record)
        return {"ok": True, "metadata": record}

    def get(self, file_uuid: str) -> Optional[Dict[str, Any]]:
        """Return metadata for the supplied UUID if present."""
        file_uuid = (file_uuid or "").strip()
        if not file_uuid:
            return None
        for record in self._iter_records():
            if record.get("uuid") == file_uuid:
                return record
        return None

    def find_by_filename(self, file_name: str) -> List[Dict[str, Any]]:
        """Return all catalogue entries that match a filename (case-insensitive)."""
        needle = (file_name or "").strip().lower()
        if not needle:
            return []
        return [rec for rec in self._iter_records() if str(rec.get("file_name", "")).lower() == needle]

    def list_all(self) -> List[Dict[str, Any]]:
        """Return the full catalogue as a list of metadata records."""
        return list(self._iter_records())

    def aggregate_summary(self) -> Dict[str, Any]:
        """Produce aggregate statistics across the catalogue."""
        records = self.list_all()
        if not records:
            return {
                "total_files": 0,
                "average_duration_s": 0.0,
                "average_stroke_count": 0.0,
                "tempo_spm": {"min": None, "max": None, "avg": None},
            }

        durations = [rec.get("metrics", {}).get("duration_s", 0.0) for rec in records]
        strokes = [rec.get("metrics", {}).get("stroke_count", 0) for rec in records]
        tempo_samples: List[float] = []
        for rec in records:
            tempo = rec.get("metrics", {}).get("tempo_spm", {})
            for key in ("min", "max", "avg"):
                value = tempo.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    tempo_samples.append(value)

        def _safe_mean(values: Iterable[float]) -> float:
            try:
                return round(statistics.fmean(values), 2)
            except (statistics.StatisticsError, ZeroDivisionError):
                return 0.0

        summary = {
            "total_files": len(records),
            "average_duration_s": _safe_mean([v for v in durations if isinstance(v, (int, float))]),
            "average_stroke_count": _safe_mean([v for v in strokes if isinstance(v, (int, float))]),
        }
        if tempo_samples:
            summary["tempo_spm"] = {
                "min": round(min(tempo_samples), 2),
                "max": round(max(tempo_samples), 2),
                "avg": round(statistics.fmean(tempo_samples), 2),
            }
        else:
            summary["tempo_spm"] = {"min": None, "max": None, "avg": None}
        return summary

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _load_funscript(self, funscript: Any) -> Dict[str, Any]:
        if isinstance(funscript, dict):
            return funscript
        if isinstance(funscript, (str, bytes, bytearray)):
            text = funscript.decode("utf-8") if isinstance(funscript, (bytes, bytearray)) else funscript
            path = pathlib.Path(text)
            if path.exists():
                try:
                    with path.open("r", encoding="utf-8") as handle:
                        return json.load(handle)
                except Exception as exc:
                    raise FunScriptCatalogError(f"failed to load FunScript from {path}: {exc}") from exc
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise FunScriptValidationError("FunScript payload is not valid JSON") from exc
        raise FunScriptValidationError("Unsupported FunScript payload type")

    def _analyse(self, file_uuid: str, funscript: Dict[str, Any], *, file_name: str | None,
                 source_path: str | None) -> _AnalysisResult:
        uuid_clean = (file_uuid or "").strip()
        if not uuid_clean:
            raise FunScriptValidationError("file_uuid is required")
        actions_raw = funscript.get("actions") if isinstance(funscript, dict) else None
        if not isinstance(actions_raw, list) or not actions_raw:
            raise FunScriptValidationError("FunScript is missing an actions array")

        filtered: List[Tuple[float, float]] = []
        for action in actions_raw:
            if not isinstance(action, dict):
                continue
            try:
                at = float(action.get("at"))
                pos = float(action.get("pos"))
            except (TypeError, ValueError):
                continue
            filtered.append((at, max(0.0, min(100.0, pos))))
        if len(filtered) < 2:
            raise FunScriptValidationError("FunScript has fewer than two valid actions")

        filtered.sort(key=lambda item: item[0])

        # Collapse duplicate timestamps, keeping the last position for that time.
        deduped: List[Tuple[float, float]] = []
        for at, pos in filtered:
            if not deduped or at != deduped[-1][0]:
                deduped.append((at, pos))
            else:
                deduped[-1] = (at, pos)

        start_time = deduped[0][0]
        end_time = deduped[-1][0]
        duration_s = max(0.0, (end_time - start_time) / 1000.0)
        normalized = [
            {"t": round((at - start_time) / 1000.0, 6), "p": round(pos, 3)}
            for at, pos in deduped
        ]

        if len(normalized) > self._max_actions:
            stride = math.ceil(len(normalized) / self._max_actions)
            normalized = [normalized[i] for i in range(0, len(normalized), stride)]
            if normalized[-1]["t"] != round((end_time - start_time) / 1000.0, 6):
                normalized.append({"t": round((end_time - start_time) / 1000.0, 6), "p": round(deduped[-1][1], 3)})

        metrics = self._compute_metrics(deduped, duration_s)
        metrics["duration_s"] = round(duration_s, 3)

        return _AnalysisResult(
            uuid=uuid_clean,
            file_name=file_name,
            source_path=source_path,
            action_count=len(deduped),
            normalized_actions=normalized,
            metrics=metrics,
        )

    def _compute_metrics(self, actions: List[Tuple[float, float]], duration_s: float) -> Dict[str, Any]:
        if len(actions) < 2:
            return {
                "duration_s": round(duration_s, 3),
                "stroke_count": 0,
                "tempo_spm": {"min": None, "max": None, "avg": None},
                "climax_cues": [],
            }

        stroke_changes = 0
        last_dir = 0
        last_change_time = actions[0][0]
        tempo_samples: List[float] = []
        speed_samples: List[Tuple[float, float]] = []  # (time, speed)

        for idx in range(1, len(actions)):
            prev_at, prev_pos = actions[idx - 1]
            curr_at, curr_pos = actions[idx]
            dt = (curr_at - prev_at) / 1000.0
            if dt <= 0:
                continue
            delta = curr_pos - prev_pos
            direction = 0
            if abs(delta) > 1e-6:
                direction = 1 if delta > 0 else -1
            if direction and last_dir and direction != last_dir:
                stroke_changes += 1
                cycle = (prev_at - last_change_time) / 1000.0
                if cycle > 0.05:  # ignore extremely small jitter
                    tempo_samples.append(60.0 / (cycle * 2.0))
                last_change_time = prev_at
            if direction:
                last_dir = direction
            speed = abs(delta) / dt
            normalized_time = (prev_at - actions[0][0]) / 1000.0
            speed_samples.append((normalized_time, speed))

        if stroke_changes:
            stroke_count = max(1, stroke_changes // 2)
        else:
            stroke_count = max(0, len(actions) - 1)

        tempo_summary: Dict[str, Optional[float]]
        if tempo_samples:
            tempo_summary = {
                "min": round(min(tempo_samples), 2),
                "max": round(max(tempo_samples), 2),
                "avg": round(statistics.fmean(tempo_samples), 2),
            }
        else:
            tempo_summary = {"min": None, "max": None, "avg": None}

        climax_cues: List[str] = []
        if speed_samples:
            overall_avg = statistics.fmean(speed for _, speed in speed_samples)
            cutoff = duration_s * 0.9 if duration_s > 0 else speed_samples[-1][0]
            tail_speeds = [speed for time_t, speed in speed_samples if time_t >= cutoff]
            if tail_speeds:
                tail_avg = statistics.fmean(tail_speeds)
                if overall_avg > 0 and tail_avg >= overall_avg * 1.2:
                    climax_cues.append("high_tempo_finish")
            tail_positions = [pos for at, pos in actions if (at - actions[0][0]) / 1000.0 >= cutoff]
            if tail_positions and max(tail_positions) >= 85:
                climax_cues.append("deep_finish")

        return {
            "duration_s": round(duration_s, 3),
            "stroke_count": stroke_count,
            "tempo_spm": tempo_summary,
            "climax_cues": climax_cues,
        }

    def _upsert_record(self, record: Dict[str, Any]) -> None:
        records = self.list_all()
        replaced = False
        for idx, existing in enumerate(records):
            if existing.get("uuid") == record.get("uuid"):
                records[idx] = record
                replaced = True
                break
        if not replaced:
            records.append(record)
        with self.catalog_path.open("w", encoding="utf-8") as handle:
            for rec in records:
                handle.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _iter_records(self) -> Iterable[Dict[str, Any]]:
        try:
            with self.catalog_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            return
