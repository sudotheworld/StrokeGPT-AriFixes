"""Utilities for loading and cataloguing FunScript files.

This module provides a lightweight catalog that keeps enriched metadata
about uploaded FunScript files inside the existing StrokeGPT memory
directory.  Each entry in the catalog stores the normalised timeline,
basic metrics (duration, stroke counts, tempo, climax cues) and any
metadata present in the original file.  Entries are persisted as JSON
lines so they can be appended or updated efficiently by file UUID.

In addition to ingestion helpers, the catalog offers lookup routines for
backend routes as well as summary helpers that can be fed to the LLM
layer when it needs to describe or label a script.
"""

from __future__ import annotations

import json
import os
import pathlib
import statistics
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


class FunScriptError(Exception):
    """Raised when a FunScript file cannot be parsed or normalised."""


def _memory_base_dir() -> pathlib.Path:
    """Return the shared memory directory used across the application."""

    try:
        # Import lazily so we do not create circular imports at module load.
        from memory_manager import _base_dir as shared_base_dir  # type: ignore

        return shared_base_dir
    except Exception:
        base = pathlib.Path(os.environ.get("STROKEGPT_DATA", ".")) / "memory"
        base.mkdir(parents=True, exist_ok=True)
        return base


@dataclass(slots=True)
class FunScriptMetrics:
    """Aggregated metrics derived from a normalised FunScript timeline."""

    duration_seconds: float
    action_count: int
    stroke_count: int
    tempo_spm: Dict[str, float]
    climax_cues: List[float]
    average_depth: float
    average_speed: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "duration_seconds": self.duration_seconds,
            "action_count": self.action_count,
            "stroke_count": self.stroke_count,
            "tempo_spm": self.tempo_spm,
            "climax_cues": self.climax_cues,
            "average_depth": self.average_depth,
            "average_speed": self.average_speed,
        }


class FunScriptCatalog:
    """Manage an on-disk catalog of FunScript metadata."""

    def __init__(self, catalog_path: Optional[pathlib.Path] = None) -> None:
        base_dir = _memory_base_dir()
        self.catalog_path = catalog_path or (base_dir / "funscript_catalog.jsonl")
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Optional[List[Dict[str, Any]]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def ingest(self, file_uuid: str, funscript_path: pathlib.Path | str) -> Dict[str, Any]:
        """Load a FunScript, compute metrics and persist the catalog entry."""

        path = pathlib.Path(funscript_path)
        try:
            raw_data = self._load_json(path)
            normalised_actions = self._normalise_actions(raw_data.get("actions"))
            metrics = self._compute_metrics(normalised_actions)
        except FunScriptError as exc:
            return {"ok": False, "error": str(exc), "uuid": file_uuid}

        entry = {
            "uuid": file_uuid,
            "source_path": str(path.resolve()),
            "updated_at": time.time(),
            "metadata": raw_data.get("metadata", {}),
            "actions": normalised_actions,
            "metrics": metrics.as_dict(),
        }
        self._upsert(entry)
        return {"ok": True, "entry": entry}

    def get(self, file_uuid: str) -> Optional[Dict[str, Any]]:
        """Return the catalog entry for the given UUID, if present."""

        for entry in self._load_catalog():
            if entry.get("uuid") == file_uuid:
                return entry
        return None

    def lookup_by_path(self, funscript_path: pathlib.Path | str) -> Optional[Dict[str, Any]]:
        """Return the entry that references the provided filesystem path."""

        target = str(pathlib.Path(funscript_path).resolve())
        for entry in self._load_catalog():
            if entry.get("source_path") == target:
                return entry
        return None

    def entries(self) -> List[Dict[str, Any]]:
        """Return all catalog entries (cached in memory)."""

        return list(self._load_catalog())

    def aggregated_summary(self) -> Dict[str, Any]:
        """Compute aggregated metrics across all stored FunScripts."""

        entries = self._load_catalog()
        metrics: List[Dict[str, Any]] = [e.get("metrics", {}) for e in entries if isinstance(e.get("metrics"), dict)]
        summary: Dict[str, Any] = {
            "count": len(metrics),
            "total_duration_seconds": 0.0,
            "average_duration_seconds": 0.0,
            "average_stroke_count": 0.0,
            "tempo_spm": {"min": 0.0, "max": 0.0, "avg": 0.0},
            "total_climax_cues": 0,
        }
        if not metrics:
            return summary

        durations = [m.get("duration_seconds", 0.0) for m in metrics]
        stroke_counts = [m.get("stroke_count", 0) for m in metrics]
        avg_spm_values = []
        min_spm_values = []
        max_spm_values = []
        total_climax_cues = 0
        for m in metrics:
            tempo = m.get("tempo_spm") or {}
            if tempo:
                avg_spm_values.append(tempo.get("avg", 0.0))
                min_spm_values.append(tempo.get("min", 0.0))
                max_spm_values.append(tempo.get("max", 0.0))
            cues = m.get("climax_cues") or []
            total_climax_cues += len(cues)

        summary["total_duration_seconds"] = float(sum(durations))
        summary["average_duration_seconds"] = float(statistics.fmean(durations))
        summary["average_stroke_count"] = float(statistics.fmean(stroke_counts)) if stroke_counts else 0.0
        if min_spm_values:
            summary["tempo_spm"] = {
                "min": float(min(min_spm_values)),
                "max": float(max(max_spm_values)),
                "avg": float(statistics.fmean(avg_spm_values)),
            }
        summary["total_climax_cues"] = total_climax_cues
        return summary

    def llm_context(self, file_uuid: str) -> Optional[str]:
        """Render a compact textual summary for prompt injection."""

        entry = self.get(file_uuid)
        if not entry:
            return None
        metrics = entry.get("metrics", {})
        if not metrics:
            return None
        duration = metrics.get("duration_seconds", 0)
        tempo = metrics.get("tempo_spm", {})
        climax = metrics.get("climax_cues", [])
        avg_depth = metrics.get("average_depth", 0)
        avg_speed = metrics.get("average_speed", 0)
        return (
            f"FunScript '{entry.get('metadata', {}).get('title') or entry.get('uuid')}'\n"
            f"- Duration: {duration:.1f}s\n"
            f"- Actions: {metrics.get('action_count', 0)}\n"
            f"- Strokes: {metrics.get('stroke_count', 0)}\n"
            f"- Avg depth: {avg_depth:.1f}% | Avg speed: {avg_speed:.1f}%\n"
            f"- Tempo SPM: {tempo.get('min', 0):.1f}-{tempo.get('max', 0):.1f} (avg {tempo.get('avg', 0):.1f})\n"
            f"- Climax cues @ {', '.join(f'{c:.1f}s' for c in climax) if climax else 'none'}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _load_catalog(self) -> List[Dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        items: List[Dict[str, Any]] = []
        if not self.catalog_path.exists():
            self._cache = items
            return items
        try:
            with self.catalog_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        self._cache = items
        return items

    def _upsert(self, entry: Dict[str, Any]) -> None:
        entries = self._load_catalog()
        replaced = False
        for idx, existing in enumerate(entries):
            if existing.get("uuid") == entry.get("uuid"):
                entries[idx] = entry
                replaced = True
                break
        if not replaced:
            entries.append(entry)
        try:
            with self.catalog_path.open("w", encoding="utf-8") as handle:
                for record in entries:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            # If persisting fails we drop the cache so a later attempt reloads
            self._cache = None
            raise
        else:
            self._cache = entries

    def _load_json(self, path: pathlib.Path) -> Dict[str, Any]:
        if not path.exists():
            raise FunScriptError(f"FunScript file does not exist: {path}")
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError as exc:
            raise FunScriptError(f"Invalid FunScript JSON: {exc}") from exc
        except OSError as exc:
            raise FunScriptError(f"Unable to read FunScript: {exc}") from exc

    def _normalise_actions(self, actions: Any) -> List[Dict[str, float]]:
        if not isinstance(actions, Iterable):
            raise FunScriptError("FunScript missing 'actions' list")

        cleaned: List[Dict[str, float]] = []
        for item in actions:  # type: ignore
            if not isinstance(item, dict):
                continue
            at = item.get("at")
            pos = item.get("pos")
            if at is None or pos is None:
                continue
            try:
                at_val = max(0, float(at))
                pos_val = float(pos)
            except (TypeError, ValueError):
                continue
            pos_val = min(100.0, max(0.0, pos_val))
            cleaned.append({"at": at_val, "pos": pos_val})

        if len(cleaned) < 2:
            raise FunScriptError("FunScript contains fewer than two valid actions")

        cleaned.sort(key=lambda x: x["at"])
        deduped: List[Dict[str, float]] = []
        for item in cleaned:
            if deduped and abs(item["at"] - deduped[-1]["at"]) < 1e-6:
                deduped[-1] = item
            else:
                deduped.append(item)

        start = deduped[0]["at"]
        normalised = [{"at": round(item["at"] - start, 3), "pos": round(item["pos"], 3)} for item in deduped]
        return normalised

    def _compute_metrics(self, actions: List[Dict[str, float]]) -> FunScriptMetrics:
        duration_ms = actions[-1]["at"]
        duration_seconds = round(duration_ms / 1000.0, 3)
        action_count = len(actions)

        stroke_durations: List[float] = []
        direction: Optional[int] = None
        stroke_start = actions[0]["at"]
        prev = actions[0]
        total_depth = prev["pos"]
        total_speed = 0.0
        movement_samples = 0

        for current in actions[1:]:
            delta_pos = current["pos"] - prev["pos"]
            delta_time = max(0.001, current["at"] - prev["at"])
            total_depth += current["pos"]
            total_speed += abs(delta_pos) / delta_time * 1000.0  # convert to percentage change per second
            movement_samples += 1

            if delta_pos != 0:
                new_direction = 1 if delta_pos > 0 else -1
                if direction is None:
                    direction = new_direction
                    stroke_start = prev["at"]
                elif new_direction != direction:
                    stroke_duration = max(1.0, prev["at"] - stroke_start)
                    stroke_durations.append(stroke_duration)
                    stroke_start = prev["at"]
                    direction = new_direction
            prev = current

        if direction is not None:
            stroke_durations.append(max(1.0, actions[-1]["at"] - stroke_start))

        stroke_count = len(stroke_durations)
        tempo = self._tempo_from_strokes(stroke_durations)
        climax = self._detect_climax(actions)
        average_depth = total_depth / action_count if action_count else 0.0
        average_speed = total_speed / movement_samples if movement_samples else 0.0

        return FunScriptMetrics(
            duration_seconds=duration_seconds,
            action_count=action_count,
            stroke_count=stroke_count,
            tempo_spm=tempo,
            climax_cues=climax,
            average_depth=round(average_depth, 3),
            average_speed=round(average_speed, 3),
        )

    def _tempo_from_strokes(self, stroke_durations: List[float]) -> Dict[str, float]:
        if not stroke_durations:
            return {"min": 0.0, "max": 0.0, "avg": 0.0}
        spm_values = [60000.0 / d for d in stroke_durations if d > 0]
        if not spm_values:
            return {"min": 0.0, "max": 0.0, "avg": 0.0}
        return {
            "min": round(min(spm_values), 3),
            "max": round(max(spm_values), 3),
            "avg": round(statistics.fmean(spm_values), 3),
        }

    def _detect_climax(self, actions: List[Dict[str, float]]) -> List[float]:
        if not actions:
            return []
        duration = actions[-1]["at"] or 1.0
        window_start = duration * 0.7
        cues = []
        for item in actions:
            if item["at"] >= window_start and item["pos"] >= 85.0:
                cues.append(round(item["at"] / 1000.0, 3))
        # Deduplicate while preserving order
        seen = set()
        unique: List[float] = []
        for ts in cues:
            if ts in seen:
                continue
            seen.add(ts)
            unique.append(ts)
        return unique

