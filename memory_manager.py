"""
memory_manager.py
-------------------

This module provides a simple, append‑only event store and utility routines
for maintaining a rolling memory of user interactions and persona
preferences.  Each event is persisted to a JSON lines file and can be
retrieved in reverse chronological order or collapsed into a compact
context string.  A naive summarisation helper is also provided which
produces a YAML‑like persona description.  This helper may later be
replaced with a more sophisticated LLM summariser, but for now it
distills repeated lines and recent entries into a succinct form.

Events are keyed by a user identifier (which defaults to the
requester's IP address or "room" if not specified).  Tags may be
attached to events but are currently unused by the summariser.

The default storage directory is governed by the STROKEGPT_DATA
environment variable if set, otherwise a subdirectory named
"memory" within the working directory is created.  All file I/O is
gracefully guarded against exceptions to avoid interrupting the
main application.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
from collections import Counter
from typing import Any, Dict, List, Optional


# Determine a base directory for storing memory files.  This can be
# overridden by setting the STROKEGPT_DATA environment variable.  The
# directory is created on demand.
_base_dir = pathlib.Path(os.environ.get("STROKEGPT_DATA", ".")) / "memory"
_base_dir.mkdir(parents=True, exist_ok=True)


class MemoryManager:
    """Append‑only memory manager with simple summarisation.

    Attributes
    ----------
    mem_path : pathlib.Path
        The file where individual events are recorded as JSON lines.
    profile_path : pathlib.Path
        The file where a YAML‑like persona summary is written when
        `summarise` is called.
    """

    def __init__(self,
                 path_events: pathlib.Path | None = None,
                 path_profile: pathlib.Path | None = None) -> None:
        # Set default file locations within the base memory directory
        self.mem_path = path_events or (_base_dir / "mem.jsonl")
        self.profile_path = path_profile or (_base_dir / "persona.yaml")
        # Ensure the event log exists so reads don't error
        self.mem_path.touch(exist_ok=True)

    # ------------------------------------------------------------------
    # Event API
    #
    def add_event(self, user_id: str, text: str, tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """Append a new event to the log.

        Parameters
        ----------
        user_id : str
            Identifier for the originator of the event.  Typically this is
            the requester's IP address or a room identifier.
        text : str
            The freeform content of the event.  Empty strings are ignored.
        tags : list[str], optional
            Optional tags for future filtering or analysis.  Currently
            unused by the summariser.

        Returns
        -------
        dict
            A dictionary with keys ``ok`` and either ``event`` or
            ``error`` depending on whether the event was recorded.
        """
        rec: Dict[str, Any] = {
            "ts": time.time(),
            "user": user_id or "room",
            "text": (text or "").strip(),
            "tags": tags or []
        }
        if not rec["text"]:
            return {"ok": False, "error": "empty text"}
        try:
            with self.mem_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "event": rec}

    def _load(self) -> List[Dict[str, Any]]:
        """Load all events from the log.

        Returns
        -------
        list[dict]
            A list of event dictionaries.  Invalid lines are skipped.
        """
        out: List[Dict[str, Any]] = []
        try:
            with self.mem_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    out.append(rec)
        except Exception:
            pass
        return out

    def recent(self, n: int = 25) -> List[Dict[str, Any]]:
        """Return the most recent `n` events.

        Parameters
        ----------
        n : int, optional
            Maximum number of events to return (default is 25).

        Returns
        -------
        list[dict]
            A list of the last `n` events, oldest to newest.
        """
        items = self._load()
        return items[-n:]

    def context(self, user_id: str, max_chars: int = 1200) -> str:
        """Produce a compact context string for a given user.

        The context is composed of recent, unique events attributed to
        either the provided ``user_id`` or the default "room" user.  The
        list is traversed in reverse so that the most recent entries are
        considered first.  Duplicate lines (case‑insensitive) are omitted
        to avoid repetition.  The resulting lines are concatenated with
        newlines and prefixed with a header.

        Parameters
        ----------
        user_id : str
            The identifier whose events should be prioritised.
        max_chars : int, optional
            Upper bound on the length of the returned string.  Once the
            accumulated context exceeds this many characters, earlier
            events are truncated (default is 1200).

        Returns
        -------
        str
            A human‑readable context block or an empty string if there are
            no relevant events.
        """
        items = [r for r in self._load() if r.get("user") in (user_id, "room")][-100:]
        seen: set[str] = set()
        folded: List[str] = []
        for rec in reversed(items):  # process most recent first
            text = (rec.get("text") or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            folded.append(f"- {text}")
            # Stop if we exceed the max length
            if sum(len(x) + 1 for x in folded) > max_chars:
                break
        if not folded:
            return ""
        return "Known persona & preferences (rolling):\n" + "\n".join(folded)

    def summarise(self, user_id: str = "room") -> str:
        """Generate a naive YAML summary of the persona.

        The summarisation collects short lines from all events, tallies
        their frequency, and selects the most common (up to a dozen) as
        representative traits.  If there are no repeats, the last ten
        events are used instead.  The summary is written to
        ``self.profile_path`` and returned.

        Parameters
        ----------
        user_id : str, optional
            Identifier used for the profile (default is "room").

        Returns
        -------
        str
            The generated YAML string.
        """
        notes = [r.get("text", "").strip() for r in self._load() if r.get("text")]
        tokens: List[str] = []
        for t in notes:
            # Keep only reasonably short notes for summarisation
            if len(t) <= 120:
                tokens.append(t.rstrip("."))
        # Determine the most common short notes
        common: List[str] = [t for t, _ in Counter(tokens).most_common(12)]
        if not common:
            common = [t.rstrip(".") for t in notes[-10:]]
        body = "- " + "\n- ".join(common)
        out = (
            f"persona:\n"
            f"  user_id: {user_id}\n"
            f"  updated: {int(time.time())}\n"
            f"  traits:\n    " + body.replace("\n", "\n    ") + "\n"
        )
        try:
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            self.profile_path.write_text(out, encoding="utf-8")
        except Exception:
            pass
        return out