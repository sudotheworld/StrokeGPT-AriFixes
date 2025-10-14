"""Utility helpers for parsing and summarising FunScript files."""

from __future__ import annotations

import hashlib
import json
import statistics
from typing import Any, Dict, Iterable, List

WINDOW_MS = 5000


def _normalise_actions(actions: Iterable[Dict[str, Any]]) -> List[Dict[str, float]]:
    cleaned: List[Dict[str, float]] = []
    for action in actions or []:
        try:
            at = float(action["at"])
            pos = float(action["pos"])
        except (TypeError, ValueError, KeyError):
            continue
        cleaned.append({"at": at, "pos": max(0.0, min(100.0, pos))})

    cleaned.sort(key=lambda item: item["at"])
    if not cleaned:
        return []

    base = cleaned[0]["at"]
    for item in cleaned:
        item["at"] = max(0.0, item["at"] - base)
    return cleaned


def load_actions_from_bytes(raw: bytes) -> List[Dict[str, float]]:
    try:
        data = json.loads(raw.decode("utf-8", errors="ignore"))
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid FunScript JSON") from exc

    if isinstance(data, dict):
        actions = data.get("actions")
    else:
        actions = data
    return _normalise_actions(actions)


def compute_metrics(actions: List[Dict[str, float]]) -> Dict[str, Any]:
    if not actions:
        return {
            "duration_ms": 0,
            "action_count": 0,
            "avg_position": 0,
            "min_position": 0,
            "max_position": 0,
            "avg_speed_per_s": 0,
            "peak_speed_per_s": 0,
            "stroke_count": 0,
            "intensity": 0,
        }

    duration = actions[-1]["at"]
    positions = [a["pos"] for a in actions]
    diffs = []
    speeds = []
    direction_changes = 0
    previous_direction = 0

    for idx in range(1, len(actions)):
        dt = actions[idx]["at"] - actions[idx - 1]["at"]
        if dt <= 0:
            continue
        delta = actions[idx]["pos"] - actions[idx - 1]["pos"]
        diffs.append(delta)
        speed = abs(delta) / dt * 1000.0
        speeds.append(speed)
        if abs(delta) > 3:
            direction = 1 if delta > 0 else -1
            if previous_direction and direction != previous_direction:
                direction_changes += 1
            previous_direction = direction

    avg_speed = statistics.fmean(speeds) if speeds else 0.0
    peak_speed = max(speeds) if speeds else 0.0
    stroke_count = max(1, direction_changes) if speeds else 0
    depth_range = max(positions) - min(positions)
    intensity = min(100, int((avg_speed * 0.6 + peak_speed * 0.4) * (depth_range / 100)))

    return {
        "duration_ms": int(duration),
        "action_count": len(actions),
        "avg_position": round(statistics.fmean(positions), 2),
        "min_position": round(min(positions), 2),
        "max_position": round(max(positions), 2),
        "avg_speed_per_s": round(avg_speed, 2),
        "peak_speed_per_s": round(peak_speed, 2),
        "stroke_count": stroke_count,
        "intensity": intensity,
        "depth_range": round(depth_range, 2),
    }


def _segment_stats(segment: List[Dict[str, float]]) -> Dict[str, Any]:
    if not segment:
        return {
            "avg_depth": 0,
            "depth_range": 0,
            "avg_speed_per_s": 0,
            "stroke_count": 0,
            "dominant_direction": "neutral",
        }

    positions = [a["pos"] for a in segment]
    speeds = []
    up = 0.0
    down = 0.0
    turns = 0
    previous_direction = 0

    for idx in range(1, len(segment)):
        dt = segment[idx]["at"] - segment[idx - 1]["at"]
        if dt <= 0:
            continue
        delta = segment[idx]["pos"] - segment[idx - 1]["pos"]
        speed = abs(delta) / dt * 1000.0
        speeds.append(speed)
        if delta > 0:
            up += delta
        else:
            down += abs(delta)
        if abs(delta) > 3:
            direction = 1 if delta > 0 else -1
            if previous_direction and direction != previous_direction:
                turns += 1
            previous_direction = direction

    direction = "surging" if up > down * 1.2 else "descending" if down > up * 1.2 else "balanced"

    return {
        "avg_depth": round(statistics.fmean(positions), 2),
        "depth_range": round(max(positions) - min(positions), 2),
        "avg_speed_per_s": round(statistics.fmean(speeds) if speeds else 0.0, 2),
        "stroke_count": max(1, turns) if speeds else 0,
        "dominant_direction": direction,
    }


def compute_segments(actions: List[Dict[str, float]], window_ms: int = WINDOW_MS) -> List[Dict[str, Any]]:
    if not actions:
        return []

    duration = actions[-1]["at"]
    segments: List[Dict[str, Any]] = []
    start = 0.0
    while start < duration:
        end = min(duration, start + window_ms)
        bucket = [a for a in actions if start <= a["at"] <= end]
        stats = _segment_stats(bucket)
        stats.update({
            "index": len(segments),
            "start_ms": int(start),
            "end_ms": int(end),
        })
        segments.append(stats)
        start += window_ms
    return segments


def hash_funscript(raw: bytes) -> str:
    return hashlib.sha1(raw).hexdigest()


__all__ = [
    "WINDOW_MS",
    "compute_metrics",
    "compute_segments",
    "hash_funscript",
    "load_actions_from_bytes",
]
