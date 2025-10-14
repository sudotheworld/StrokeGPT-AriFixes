from __future__ import annotations

import json
import os
import pathlib
import threading
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Sequence

from llm_service import LLMService
from memory_manager import MemoryManager


def _slugify(value: str) -> str:
    """Return a filesystem safe slug for ``value``."""
    cleaned = ''.join(ch.lower() if ch.isalnum() else '-' for ch in value.strip())
    cleaned = '-'.join(part for part in cleaned.split('-') if part)
    return cleaned or 'agent'


class MultiLomMemoryStore:
    """Append-only per-agent memory store used by the multi-LOM chat manager."""

    def __init__(self, base_dir: Optional[str | pathlib.Path] = None) -> None:
        root = pathlib.Path(base_dir) if base_dir is not None else pathlib.Path(os.environ.get("STROKEGPT_DATA", ".")) / "memory" / "multi_lom"
        root.mkdir(parents=True, exist_ok=True)
        self._root = root
        self._lock = threading.Lock()

    def _path(self, agent_key: str) -> pathlib.Path:
        return self._root / f"{_slugify(agent_key)}.jsonl"

    def append_event(self, agent_key: str, event_type: str, payload: Dict[str, object]) -> Dict[str, object]:
        record: Dict[str, object] = {
            "ts": time.time(),
            "type": event_type,
        }
        record.update(payload)
        path = self._path(agent_key)
        with self._lock:
            with path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def recent(self, agent_key: str, limit: int = 50) -> List[Dict[str, object]]:
        path = self._path(agent_key)
        if not path.exists():
            return []
        out: List[Dict[str, object]] = []
        with self._lock:
            try:
                with path.open('r', encoding='utf-8') as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            out.append(json.loads(line))
                        except Exception:
                            continue
            except Exception:
                return []
        return out[-limit:]

    def context_block(self, agent_key: str, limit: int = 20) -> str:
        events = self.recent(agent_key, limit)
        if not events:
            return ""
        lines: List[str] = []
        for event in events:
            etype = event.get("type")
            if etype == "memory" and event.get("text"):
                lines.append(f"- {event['text']}")
            elif etype == "agenda" and event.get("agenda"):
                lines.append(f"Agenda focus: {event['agenda']}")
            elif etype == "message" and event.get("text"):
                lines.append(f"Said: {event['text']}")
        return "\n".join(lines[-limit:])


@dataclass
class MultiLomAgent:
    name: str
    persona: str
    memory_key: str
    agenda: str = "Discover a personal agenda through conversation and pursue it with nuance."

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class MultiLomChatManager:
    """Coordinate a never-ending multi-agent chat using the shared LLM service."""

    def __init__(self,
                 llm_service: LLMService,
                 memory_store: MultiLomMemoryStore,
                 persona_memory: Optional[MemoryManager] = None) -> None:
        self._llm = llm_service
        self._memory_store = memory_store
        self._persona_memory = persona_memory
        self._agents: List[MultiLomAgent] = []
        self._history: List[Dict[str, object]] = []
        self._history_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.turn_delay = 4.0
        self.max_history = 120

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def configure_agents(self, agents: Sequence[MultiLomAgent]) -> None:
        if self.is_running:
            self.stop(wait=True)
        with self._history_lock:
            self._agents = [MultiLomAgent(a.name, a.persona, a.memory_key, a.agenda or MultiLomAgent.agenda) for a in agents]
            self._history.clear()
        # prime the memory with their agendas
        for agent in self._agents:
            if agent.agenda:
                self._memory_store.append_event(agent.memory_key, "agenda", {"agenda": agent.agenda})

    def start(self, turn_delay: Optional[float] = None) -> None:
        if not self._agents:
            raise ValueError("Configure at least two agents before starting the multi-LOM chat.")
        if len(self._agents) < 2:
            raise ValueError("At least two agents are required for the multi-LOM chat.")
        if self.is_running:
            if turn_delay is not None:
                self.turn_delay = max(0.5, float(turn_delay))
            return
        if turn_delay is not None:
            self.turn_delay = max(0.5, float(turn_delay))
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="MultiLomChat", daemon=True)
        self._thread.start()

    def stop(self, wait: bool = False) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and wait:
            thread.join(timeout=5)
        if not wait:
            # Allow background loop to finish naturally, but clear reference when done
            if thread and not thread.is_alive():
                self._thread = None
        else:
            self._thread = None

    def status(self) -> Dict[str, object]:
        with self._history_lock:
            agents = [agent.to_dict() for agent in self._agents]
            history_count = len(self._history)
        return {
            "running": self.is_running,
            "agents": agents,
            "turn_delay": self.turn_delay,
            "history_count": history_count,
        }

    def history(self, limit: int = 50) -> List[Dict[str, object]]:
        with self._history_lock:
            return list(self._history[-limit:])

    def _run_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                for agent in list(self._agents):
                    if self._stop_event.is_set():
                        break
                    try:
                        self._execute_turn(agent)
                    except Exception as exc:
                        print(f"Multi-LOM agent turn failed: {exc}")
                    if self._stop_event.wait(self.turn_delay):
                        break
        finally:
            self._thread = None

    def _execute_turn(self, agent: MultiLomAgent) -> None:
        with self._history_lock:
            transcript = [
                f"{entry['speaker']}: {entry['text']}" for entry in self._history[-40:]
            ]
        convo = "\n".join(transcript)
        persona_context = self._memory_store.context_block(agent.memory_key, limit=30)
        response = self._llm.generate_multi_agent_turn(
            agent_name=agent.name,
            persona_description=agent.persona,
            agenda=agent.agenda,
            conversation_so_far=convo,
            memory_context=persona_context,
        )
        if not isinstance(response, dict):
            return
        chat_text = str(response.get("chat") or "").strip()
        if not chat_text:
            return
        new_agenda = str(response.get("agenda") or "").strip()
        if new_agenda:
            agent.agenda = new_agenda
            self._memory_store.append_event(agent.memory_key, "agenda", {"agenda": new_agenda})
        memories = response.get("memory") or []
        if isinstance(memories, str):
            memories = [memories]
        memories = [str(m).strip() for m in memories if str(m).strip()]

        timestamp = time.time()
        record = {
            "ts": timestamp,
            "speaker": agent.name,
            "text": chat_text,
            "agenda": agent.agenda,
        }
        with self._history_lock:
            self._history.append(record)
            if len(self._history) > self.max_history:
                self._history = self._history[-self.max_history:]
        self._memory_store.append_event(agent.memory_key, "message", {"text": chat_text})
        if self._persona_memory is not None:
            try:
                self._persona_memory.add_event(f"lom:{agent.memory_key}", f"{agent.name}: {chat_text}", tags=["multi_lom", "chat"])
            except Exception:
                pass
        for memo in memories:
            self._memory_store.append_event(agent.memory_key, "memory", {"text": memo})
            if self._persona_memory is not None:
                try:
                    self._persona_memory.add_event(f"lom:{agent.memory_key}", memo, tags=["multi_lom", "memory"])
                except Exception:
                    pass

