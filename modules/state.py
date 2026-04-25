from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class DialogueTurn:
    user_text: str
    reply_text: str
    action: str
    expression: str
    song_title: str = ""


@dataclass
class SessionState:
    session_id: str
    user_id: str = ""
    history: List[DialogueTurn] = field(default_factory=list)
    last_pose_label: str = ""
    last_touch_event: str = ""
    current_song_key: str = ""
    # AirJelly-enriched context, refreshed at session start and on each turn
    airjelly_music_context: str = ""
    airjelly_task_context: str = ""
    # Track whether we've done the initial AirJelly prefetch for this session
    airjelly_prefetched: bool = False

    def add_turn(self, turn: DialogueTurn, max_history_turns: int) -> None:
        self.history.append(turn)
        if len(self.history) > max_history_turns:
            self.history = self.history[-max_history_turns:]

    def recent_turns(self, limit: int) -> List[DialogueTurn]:
        return self.history[-limit:]

    def update_airjelly(self, music_context: str, task_context: str) -> None:
        self.airjelly_music_context = music_context
        self.airjelly_task_context = task_context
        self.airjelly_prefetched = True


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions = {}  # type: Dict[str, SessionState]

    def get(self, session_id: str, user_id: str = "") -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(
                session_id=session_id,
                user_id=user_id,
            )
        elif user_id and not self._sessions[session_id].user_id:
            self._sessions[session_id].user_id = user_id
        return self._sessions[session_id]
