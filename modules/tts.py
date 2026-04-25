from __future__ import annotations

import asyncio
import base64
import importlib
import importlib.util
import json
from typing import AsyncIterator, Tuple

from .config import ServerConfig


class StepFunTTSAdapter:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config

    def _api_key(self) -> str:
        return self.config.step_asr_api_key.strip() or self.config.step_api_key.strip()

    def is_available(self) -> bool:
        return bool(self._api_key()) and (
            importlib.util.find_spec("websockets") is not None
        )

    async def iter_audio(self, text: str) -> AsyncIterator[Tuple[int, bytes]]:
        if not text.strip() or not self.is_available():
            return

        websockets = importlib.import_module("websockets")
        endpoint = "{0}?model={1}".format(
            self.config.step_tts_ws_url,
            self.config.step_tts_model,
        )
        headers = {"Authorization": "Bearer " + self._api_key()}

        async with websockets.connect(endpoint, additional_headers=headers, max_size=8 * 1024 * 1024) as websocket:
            session_event = await self._wait_for_event(
                websocket,
                allowed_types={"tts.connection.done"},
                timeout_s=self.config.llm_timeout_s + 4.0,
            )
            session_id = str((session_event.get("data") or {}).get("session_id") or "")
            if not session_id:
                raise RuntimeError("StepFun TTS did not return session_id")

            create_payload = {
                "type": "tts.create",
                "data": {
                    "session_id": session_id,
                    "response_format": self.config.step_tts_response_format,
                    "sample_rate": self.config.step_tts_sample_rate,
                    "voice_id": self.config.step_tts_voice_id,
                    "speed_ratio": self.config.step_tts_speed_ratio,
                    "volume_ratio": self.config.step_tts_volume_ratio,
                    "mode": self.config.step_tts_mode,
                },
            }

            await websocket.send(json.dumps(create_payload))
            await self._wait_for_event(
                websocket,
                allowed_types={"tts.response.created"},
                timeout_s=self.config.llm_timeout_s + 4.0,
            )

            await websocket.send(
                json.dumps(
                    {
                        "type": "tts.text.delta",
                        "data": {
                            "session_id": session_id,
                            "text": text,
                        },
                    }
                )
            )
            await websocket.send(
                json.dumps(
                    {
                        "type": "tts.text.flush",
                        "data": {
                            "session_id": session_id,
                        },
                    }
                )
            )
            await websocket.send(
                json.dumps(
                    {
                        "type": "tts.text.done",
                        "data": {
                            "session_id": session_id,
                        },
                    }
                )
            )

            sequence = 0
            while True:
                event = await self._wait_for_event(
                    websocket,
                    allowed_types={
                        "tts.response.audio.delta",
                        "tts.response.audio.done",
                        "error",
                    },
                    timeout_s=self.config.llm_timeout_s + 8.0,
                )
                event_type = event.get("type")
                if event_type == "tts.response.audio.delta":
                    payload = event.get("data") or {}
                    audio_data = base64.b64decode(str(payload.get("audio") or ""))
                    if audio_data:
                        yield sequence, audio_data
                        sequence += 1
                    continue
                if event_type == "tts.response.audio.done":
                    return
                payload = event.get("data") or {}
                raise RuntimeError(
                    str(payload.get("message") or event.get("message") or event.get("error") or "StepFun TTS error")
                )

    async def _wait_for_event(self, websocket, allowed_types, timeout_s: float):
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for StepFun TTS event")
            raw_message = await asyncio.wait_for(websocket.recv(), timeout=remaining)
            event = json.loads(raw_message)
            event_type = event.get("type")
            if event_type in allowed_types:
                return event
            if event_type in {"error", "tts.response.error"}:
                payload = event.get("data") or {}
                raise RuntimeError(
                    str(payload.get("message") or event.get("message") or event.get("error") or "StepFun TTS error")
                )
