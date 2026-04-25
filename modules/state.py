from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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

    # ---------------------------------------------------------------
    # Visual-scene tracking (used by SceneDirector / EmotionPortrait)
    # ---------------------------------------------------------------
    # Active visual theme so instant effects can match the current palette
    last_theme: str = "warm"
    # Energy samples (one per turn, 0.0–1.0) for the emotion portrait curve
    energy_samples: List[float] = field(default_factory=list)
    # Notable events logged during the session (arms_up, heart, chorus, …)
    key_events: List[Dict[str, Any]] = field(default_factory=list)
    # Session wall-clock start for elapsed_s calculations
    session_start_time: float = field(default_factory=time.monotonic)
    # Song metadata for emotion portrait
    _last_song_title: str = ""
    _last_song_artist: str = ""
    # Optional QR URL set by an external service after portrait generation
    portrait_qr_url: str = ""

    # ---------------------------------------------------------------
    # Core session methods
    # ---------------------------------------------------------------

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

    # ---------------------------------------------------------------
    # Visual scene helpers
    # ---------------------------------------------------------------

    def record_energy(self, energy_value: float) -> None:
        """Append a normalised 0–1 energy sample (call once per turn)."""
        self.energy_samples.append(max(0.0, min(1.0, energy_value)))
        # Keep at most 120 samples (~10 min at one sample per 5 s)
        if len(self.energy_samples) > 120:
            self.energy_samples = self.energy_samples[-120:]

    def log_key_event(self, event_type: str, label: str) -> None:
        """Record a notable event with elapsed time for the emotion portrait."""
        elapsed = time.monotonic() - self.session_start_time
        self.key_events.append({
            "event_type": event_type,
            "label":      label,
            "elapsed_s":  round(elapsed, 1),
        })

    def update_song(self, title: str, artist: str) -> None:
        self._last_song_title  = title
        self._last_song_artist = artist
        if title:
            self.current_song_key = "{0}|{1}".format(
                title.strip().lower(), artist.strip().lower()
            )


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}

    def get(self, session_id: str, user_id: str = "") -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(
                session_id=session_id,
                user_id=user_id,
            )
        elif user_id and not self._sessions[session_id].user_id:
            self._sessions[session_id].user_id = user_id
        return self._sessions[session_id]
