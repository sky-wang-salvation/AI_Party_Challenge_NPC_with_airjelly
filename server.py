from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Set

if __package__ in {None, ""}:
    PACKAGE_DIR = Path(__file__).resolve().parent
    PROJECT_ROOT = PACKAGE_DIR.parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from ktv_backend.modules.config import ServerConfig
    from ktv_backend.modules.orchestrator import KtvBrain
    from ktv_backend.modules.protocol import (
        SongPayload,
        ValidationError,
        build_server_message,
        parse_client_message,
    )
else:
    from .modules.config import ServerConfig
    from .modules.orchestrator import KtvBrain
    from .modules.protocol import SongPayload, ValidationError, build_server_message, parse_client_message


LOGGER = logging.getLogger("ktv_ai_server")


class ConnectionContext:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.send_lock = asyncio.Lock()
        self.tasks = set()  # type: Set[asyncio.Task]


class KtvWebSocketServer:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.brain = KtvBrain(config)

    async def handler(self, websocket: Any) -> None:
        connection = ConnectionContext(session_id="session_" + uuid.uuid4().hex[:10])
        LOGGER.info("client connected session=%s", connection.session_id)

        airjelly_available = (
            self.brain.airjelly is not None and self.brain.airjelly.is_available()
        )
        await self._send_json(
            websocket,
            connection,
            build_server_message(
                "hello",
                session_id=connection.session_id,
                payload={
                    "service": "ktv-ai-server",
                    "protocol_version": 1,
                    "llm_provider": self.brain.llm.provider_name,
                    "capabilities": {
                        "asr": self.brain.asr.is_available(),
                        "llm": self.brain.llm.is_available(),
                        "tts": self.brain.tts.is_available(),
                        "music_analysis": True,
                        "airjelly": airjelly_available,
                        "proactive_nudge": airjelly_available,
                        "scene_directive": True,
                        "instant_effect": True,
                        "emotion_portrait": True,
                    },
                },
            ),
        )

        # Start proactive nudge loop
        proactive_task = asyncio.create_task(
            self._proactive_loop(websocket, connection)
        )
        self._track_task(connection, proactive_task)

        try:
            async for raw_message in websocket:
                raw_text = raw_message.decode("utf-8") if isinstance(raw_message, bytes) else raw_message
                try:
                    client_message = parse_client_message(raw_text, connection.session_id)
                except ValidationError as exc:
                    await self._send_error(
                        websocket,
                        connection,
                        request_id=None,
                        code="bad_request",
                        message=str(exc),
                    )
                    continue

                if client_message.message_type == "ping":
                    await self._send_json(
                        websocket,
                        connection,
                        build_server_message(
                            "pong",
                            request_id=client_message.request_id,
                            session_id=client_message.session_id,
                            payload={"ok": True},
                        ),
                    )
                    continue

                if client_message.message_type == "song_context":
                    task = asyncio.create_task(
                        self._handle_song_context(websocket, connection, client_message)
                    )
                    self._track_task(connection, task)
                    continue

                if client_message.message_type == "user_signal":
                    task = asyncio.create_task(
                        self._handle_user_signal(websocket, connection, client_message)
                    )
                    self._track_task(connection, task)
                    continue

                if client_message.message_type == "song_end":
                    task = asyncio.create_task(
                        self._handle_song_end(websocket, connection, client_message)
                    )
                    self._track_task(connection, task)
                    continue

                await self._send_error(
                    websocket,
                    connection,
                    request_id=client_message.request_id,
                    code="unsupported_type",
                    message="Unsupported message type: {0}".format(client_message.message_type),
                )
        finally:
            tasks_to_cancel = list(connection.tasks)
            for task in tasks_to_cancel:
                task.cancel()
            if tasks_to_cancel:
                await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            LOGGER.info("client disconnected session=%s", connection.session_id)

    def _track_task(self, connection: ConnectionContext, task: asyncio.Task) -> None:
        connection.tasks.add(task)
        task.add_done_callback(connection.tasks.discard)

    async def _handle_song_context(
        self,
        websocket: Any,
        connection: ConnectionContext,
        client_message: Any,
    ) -> None:
        try:
            analysis = await self.brain.prewarm_song(client_message.song)
            # Build opening scene directive for this song
            open_scene = self.brain.build_song_open_scene(client_message.song, analysis)
            # Update session theme to the song's opening theme
            session = self.brain.sessions.get(connection.session_id)
            session.last_theme = open_scene.theme
            session.update_song(client_message.song.title, client_message.song.artist)
            await self._send_json(
                websocket,
                connection,
                build_server_message(
                    "song_ready",
                    request_id=client_message.request_id,
                    session_id=client_message.session_id,
                    payload={
                        "song": client_message.song.to_dict(),
                        "music": analysis.to_dict(),
                        "scene": open_scene.to_dict(),
                    },
                ),
            )
        except Exception as exc:  # pragma: no cover - runtime dependent
            LOGGER.exception("song_context failed")
            await self._send_error(
                websocket,
                connection,
                request_id=client_message.request_id,
                code="song_context_failed",
                message=str(exc),
            )

    async def _handle_user_signal(
        self,
        websocket: Any,
        connection: ConnectionContext,
        client_message: Any,
    ) -> None:
        # Compute instant effect immediately (rule-based, no LLM wait → <100 ms)
        session = self.brain.sessions.get(connection.session_id)
        instant_effect = self.brain.scene_director.build_instant_effect_for_signal(
            client_message.signal, session.last_theme
        )
        ack_payload: Dict[str, Any] = {"accepted": True}
        if instant_effect is not None:
            ack_payload["instant_effect"] = instant_effect.to_dict()

        await self._send_json(
            websocket,
            connection,
            build_server_message(
                "ack",
                request_id=client_message.request_id,
                session_id=client_message.session_id,
                payload=ack_payload,
            ),
        )

        try:
            result = await self.brain.process_signal(client_message.signal)
            await self._send_json(
                websocket,
                connection,
                build_server_message(
                    "agent_response",
                    request_id=client_message.request_id,
                    session_id=client_message.session_id,
                    payload=result.to_payload(),
                ),
            )

            chunk_count = 0
            async for sequence, chunk in self.brain.stream_tts(result.reply_text):
                chunk_count += 1
                await self._send_json(
                    websocket,
                    connection,
                    build_server_message(
                        "tts_chunk",
                        request_id=client_message.request_id,
                        session_id=client_message.session_id,
                        payload={
                            "seq": sequence,
                            "format": "audio/mpeg",
                            "audio_b64": base64.b64encode(chunk).decode("ascii"),
                            "is_final": False,
                        },
                    ),
                )

            await self._send_json(
                websocket,
                connection,
                build_server_message(
                    "tts_done",
                    request_id=client_message.request_id,
                    session_id=client_message.session_id,
                    payload={
                        "format": "audio/mpeg",
                        "chunk_count": chunk_count,
                        "available": chunk_count > 0,
                    },
                ),
            )
        except Exception as exc:  # pragma: no cover - runtime dependent
            LOGGER.exception("user_signal failed")
            await self._send_error(
                websocket,
                connection,
                request_id=client_message.request_id,
                code="processing_failed",
                message=str(exc),
            )

    async def _handle_song_end(
        self,
        websocket: Any,
        connection: ConnectionContext,
        client_message: Any,
    ) -> None:
        """Handle song_end from Unity: build and send the emotion_portrait."""
        session = self.brain.sessions.get(connection.session_id)
        # Retrieve last cached music analysis, falling back to heuristic estimate
        dummy_song = SongPayload(
            title=session._last_song_title,
            artist=session._last_song_artist,
        )
        cached_music = (
            self.brain.music.get_cached(dummy_song)
            or self.brain.music.estimate(dummy_song)
        )
        portrait = self.brain.build_emotion_portrait(session, cached_music)
        await self._send_json(
            websocket,
            connection,
            build_server_message(
                "emotion_portrait",
                request_id=client_message.request_id,
                session_id=client_message.session_id,
                payload=portrait.to_dict(),
            ),
        )
        LOGGER.info(
            "emotion_portrait sent session=%s theme=%s events=%d",
            connection.session_id,
            portrait.theme,
            len(portrait.key_events),
        )

    async def _proactive_loop(
        self,
        websocket: Any,
        connection: ConnectionContext,
    ) -> None:
        """
        Runs in the background for each connection.
        Periodically checks AirJelly context and pushes a proactive_nudge to Unity
        when there is something worth saying (e.g. a pending practice task).
        """
        interval = self.config.airjelly_proactive_interval_s
        # Wait before the first check so the user has time to settle in
        await asyncio.sleep(min(interval, 10.0))
        while True:
            try:
                session = self.brain.sessions.get(connection.session_id)
                msg = await self.brain.generate_proactive_message(session)
                if msg:
                    await self._send_json(
                        websocket,
                        connection,
                        build_server_message(
                            "proactive_nudge",
                            session_id=connection.session_id,
                            payload={
                                "text": msg,
                                "action": "wave",
                                "expression": "playful",
                                "trigger": "airjelly_task",
                            },
                        ),
                    )
                    LOGGER.info(
                        "proactive_nudge sent session=%s text=%r",
                        connection.session_id,
                        msg,
                    )
            except Exception as exc:
                LOGGER.debug("proactive_loop error: %s", exc)
            await asyncio.sleep(interval)

    async def _send_json(
        self,
        websocket: Any,
        connection: ConnectionContext,
        message: Dict[str, Any],
    ) -> None:
        encoded = json.dumps(message, ensure_ascii=False)
        async with connection.send_lock:
            await websocket.send(encoded)

    async def _send_error(
        self,
        websocket: Any,
        connection: ConnectionContext,
        request_id: Optional[str],
        code: str,
        message: str,
    ) -> None:
        await self._send_json(
            websocket,
            connection,
            build_server_message(
                "error",
                request_id=request_id,
                session_id=connection.session_id,
                payload={"code": code, "message": message},
            ),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KTV multimodal AI websocket server")
    parser.add_argument("--host", help="Host interface to bind.")
    parser.add_argument("--port", type=int, help="Port to bind.")
    parser.add_argument("--log-level", help="Logging level.")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug payloads.")
    return parser


async def serve(config: ServerConfig) -> None:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "Missing optional dependency 'websockets'. Install ktv_backend/requirements.txt first."
        ) from exc

    server = KtvWebSocketServer(config)
    LOGGER.info("starting server at ws://%s:%s", config.host, config.port)
    async with websockets.serve(server.handler, config.host, config.port, max_size=8 * 1024 * 1024):
        await asyncio.Future()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = ServerConfig.from_env()
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.log_level:
        config.log_level = args.log_level
    if args.debug:
        config.send_debug_events = True
        config.log_level = "DEBUG"

    logging.basicConfig(
        level=getattr(logging, str(config.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    asyncio.run(serve(config))


if __name__ == "__main__":
    main()
