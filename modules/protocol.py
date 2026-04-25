from __future__ import annotations

import base64
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from .utils import utc_now


ALLOWED_ACTIONS = (
    "idle",
    "wave",
    "mirror_pose",
    "high_five",
    "heart_pose",
    "cheer",
    "clap",
    "sing_along",
    "dance_soft",
    "dance_groove",
    "dance_fast",
)

ALLOWED_EXPRESSIONS = (
    "calm",
    "excited",
    "love",
    "playful",
    "supportive",
    "cool",
    "focused",
)


class ValidationError(ValueError):
    pass


@dataclass
class AudioPayload:
    content_b64: str = ""
    mime_type: str = "audio/wav"
    encoding: str = "base64"
    sample_rate: Optional[int] = None
    text_hint: str = ""

    @classmethod
    def from_value(cls, value: Any) -> "AudioPayload":
        if value is None:
            return cls()
        if isinstance(value, str):
            return cls(content_b64=value)
        if not isinstance(value, dict):
            raise ValidationError("audio must be a base64 string or object")
        return cls(
            content_b64=str(value.get("content_b64") or value.get("data") or ""),
            mime_type=str(value.get("mime_type") or value.get("format") or "audio/wav"),
            encoding=str(value.get("encoding") or "base64"),
            sample_rate=value.get("sample_rate"),
            text_hint=str(value.get("text_hint") or ""),
        )

    def has_audio(self) -> bool:
        return bool(self.content_b64.strip())

    def decode_bytes(self) -> bytes:
        raw_value = self.content_b64.strip()
        if raw_value.startswith("data:") and "," in raw_value:
            raw_value = raw_value.split(",", 1)[1]
        try:
            return base64.b64decode(raw_value)
        except Exception as exc:
            raise ValidationError("audio.content_b64 is not valid base64") from exc

    def suffix(self) -> str:
        mime = self.mime_type.lower()
        if "webm" in mime:
            return ".webm"
        if "mpeg" in mime or "mp3" in mime:
            return ".mp3"
        if "m4a" in mime or "mp4" in mime:
            return ".m4a"
        return ".wav"


@dataclass
class SongPayload:
    title: str = ""
    url: str = ""
    artist: str = ""
    bpm_hint: Optional[float] = None
    emotion_hint: str = ""

    @classmethod
    def from_value(cls, value: Any) -> "SongPayload":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValidationError("song must be an object")
        bpm_hint = value.get("bpm") if value.get("bpm") is not None else value.get("bpm_hint")
        try:
            parsed_bpm = float(bpm_hint) if bpm_hint not in (None, "") else None
        except (TypeError, ValueError):
            parsed_bpm = None
        return cls(
            title=str(value.get("title") or ""),
            url=str(value.get("url") or value.get("path") or ""),
            artist=str(value.get("artist") or ""),
            bpm_hint=parsed_bpm,
            emotion_hint=str(value.get("emotion") or value.get("emotion_hint") or ""),
        )

    def has_context(self) -> bool:
        return bool(self.title or self.url or self.artist or self.bpm_hint or self.emotion_hint)

    def song_key(self) -> str:
        if self.url:
            return self.url
        return "{0}|{1}".format(self.title.strip().lower(), self.artist.strip().lower())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UserSignal:
    request_id: str
    session_id: str
    audio: AudioPayload = field(default_factory=AudioPayload)
    pose_label: str = ""
    touch_event: str = ""
    song: SongPayload = field(default_factory=SongPayload)
    user_text: str = ""
    user_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now)

    @classmethod
    def from_payload(
        cls,
        request_id: str,
        session_id: str,
        payload: Dict[str, Any],
    ) -> "UserSignal":
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        return cls(
            request_id=request_id,
            session_id=session_id,
            audio=AudioPayload.from_value(payload.get("audio")),
            pose_label=str(payload.get("pose_label") or payload.get("pose") or ""),
            touch_event=str(payload.get("touch_event") or payload.get("touch") or ""),
            song=SongPayload.from_value(payload.get("song")),
            user_text=str(payload.get("user_text") or payload.get("text") or ""),
            user_id=str(payload.get("user_id") or ""),
            metadata=metadata,
            timestamp=str(payload.get("timestamp") or utc_now()),
        )


@dataclass
class ClientMessage:
    message_type: str
    request_id: str
    session_id: str
    signal: Optional[UserSignal] = None
    song: Optional[SongPayload] = None


def parse_client_message(raw_text: str, default_session_id: str) -> ClientMessage:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValidationError("message must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValidationError("message root must be an object")

    request_id = str(payload.get("request_id") or "req_" + uuid.uuid4().hex[:10])
    session_id = str(payload.get("session_id") or default_session_id)
    message_type = str(payload.get("type") or "user_signal").strip() or "user_signal"

    reserved = {"type", "request_id", "session_id"}
    body = payload.get("payload")
    if body is None:
        body = {}
    if not body:
        body = dict((key, value) for key, value in payload.items() if key not in reserved)
    if not isinstance(body, dict):
        raise ValidationError("payload must be an object")

    if message_type == "ping":
        return ClientMessage(message_type=message_type, request_id=request_id, session_id=session_id)

    if message_type == "song_context":
        song_value = body.get("song") if "song" in body else body
        return ClientMessage(
            message_type=message_type,
            request_id=request_id,
            session_id=session_id,
            song=SongPayload.from_value(song_value),
        )

    if message_type == "user_signal":
        signal = UserSignal.from_payload(request_id=request_id, session_id=session_id, payload=body)
        return ClientMessage(
            message_type=message_type,
            request_id=request_id,
            session_id=session_id,
            signal=signal,
        )

    return ClientMessage(message_type=message_type, request_id=request_id, session_id=session_id)


def build_server_message(
    message_type: str,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    message = {
        "type": message_type,
        "timestamp": utc_now(),
        "payload": payload or {},
    }
    if request_id:
        message["request_id"] = request_id
    if session_id:
        message["session_id"] = session_id
    return message
