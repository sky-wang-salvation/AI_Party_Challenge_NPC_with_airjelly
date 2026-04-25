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
    history: List[DialogueTurn] = field(default_factory=list)
    last_pose_label: str = ""
    last_touch_event: str = ""
    current_song_key: str = ""

    def add_turn(self, turn: DialogueTurn, max_history_turns: int) -> None:
        self.history.append(turn)
        if len(self.history) > max_history_turns:
            self.history = self.history[-max_history_turns:]

    def recent_turns(self, limit: int) -> List[DialogueTurn]:
        return self.history[-limit:]


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions = {}  # type: Dict[str, SessionState]

    def get(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id)
        return self._sessions[session_id]
