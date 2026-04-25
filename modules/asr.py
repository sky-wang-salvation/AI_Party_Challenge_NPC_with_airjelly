from __future__ import annotations

import asyncio
import base64
import importlib
import importlib.util
import io
import json
import uuid
import wave
from typing import Tuple

from .config import ServerConfig
from .protocol import AudioPayload


class StepFunASR:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config

    def _api_key(self) -> str:
        return self.config.step_asr_api_key.strip() or self.config.step_api_key.strip()

    def is_available(self) -> bool:
        return bool(self._api_key()) and (
            importlib.util.find_spec("websockets") is not None
        )

    async def transcribe(self, audio: AudioPayload) -> str:
        if not audio.has_audio():
            return (audio.text_hint or "").strip()
        if not self.is_available():
            return (audio.text_hint or "").strip()

        try:
            pcm_audio_b64, sample_rate, channels = self._prepare_pcm(audio)
        except Exception:
            return (audio.text_hint or "").strip()

        websockets = importlib.import_module("websockets")
        headers = {"Authorization": "Bearer " + self._api_key()}

        async with websockets.connect(
            self.config.step_asr_ws_url,
            extra_headers=headers,
            max_size=8 * 1024 * 1024,
        ) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "event_id": "evt_" + uuid.uuid4().hex[:10],
                        "type": "session.update",
                        "session": {
                            "audio": {
                                "input": {
                                    "format": {
                                        "type": "pcm",
                                        "codec": "pcm_s16le",
                                        "rate": sample_rate,
                                        "bits": 16,
                                        "channel": channels,
                                    },
                                    "transcription": {
                                        "model": self.config.step_asr_model,
                                        "language": self.config.step_asr_language,
                                        "full_rerun_on_commit": True,
                                        "enable_itn": True,
                                    },
                                }
                            }
                        },
                    }
                )
            )
            await self._wait_for_event(
                websocket,
                allowed_types={"session.created", "session.updated"},
                timeout_s=self.config.step_asr_timeout_s,
            )

            await websocket.send(
                json.dumps(
                    {
                        "event_id": "evt_" + uuid.uuid4().hex[:10],
                        "type": "input_audio_buffer.append",
                        "audio": pcm_audio_b64,
                    }
                )
            )
            await websocket.send(
                json.dumps(
                    {
                        "event_id": "evt_" + uuid.uuid4().hex[:10],
                        "type": "input_audio_buffer.commit",
                    }
                )
            )

            transcript = await self._collect_transcript(websocket)
            return transcript.strip() or (audio.text_hint or "").strip()

    def _prepare_pcm(self, audio: AudioPayload) -> Tuple[str, int, int]:
        raw_bytes = audio.decode_bytes()
        mime = audio.mime_type.lower()

        if "wav" in mime or "wave" in mime:
            with wave.open(io.BytesIO(raw_bytes), "rb") as wav_file:
                sample_width = wav_file.getsampwidth()
                if sample_width != 2:
                    raise ValueError("Only 16-bit PCM wav is supported for StepFun ASR")
                frame_rate = int(wav_file.getframerate())
                channels = int(wav_file.getnchannels())
                pcm_frames = wav_file.readframes(wav_file.getnframes())
            return (
                base64.b64encode(pcm_frames).decode("ascii"),
                frame_rate,
                channels,
            )

        if "pcm" in mime:
            sample_rate = int(audio.sample_rate or 16000)
            return (
                base64.b64encode(raw_bytes).decode("ascii"),
                sample_rate,
                1,
            )

        raise ValueError("Unsupported audio format for StepFun ASR: {0}".format(audio.mime_type))

    async def _collect_transcript(self, websocket) -> str:
        while True:
            event = await self._wait_for_event(
                websocket,
                allowed_types={
                    "conversation.item.input_audio_transcription.completed",
                    "error",
                },
                timeout_s=self.config.step_asr_timeout_s,
            )
            event_type = event.get("type")
            if event_type == "conversation.item.input_audio_transcription.completed":
                return str(event.get("transcript") or "")
            if event_type == "error":
                raise RuntimeError(str(event.get("message") or event.get("error") or "StepFun ASR error"))

    async def _wait_for_event(self, websocket, allowed_types, timeout_s: float):
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for StepFun ASR event")
            raw_message = await asyncio.wait_for(websocket.recv(), timeout=remaining)
            event = json.loads(raw_message)
            event_type = event.get("type")
            if event_type in allowed_types:
                return event
            if event_type == "error":
                raise RuntimeError(str(event.get("message") or event.get("error") or "StepFun ASR error"))
