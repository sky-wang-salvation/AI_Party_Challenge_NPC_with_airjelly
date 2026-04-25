from __future__ import annotations

import argparse
import asyncio
import base64
import json
import mimetypes
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke test client for ktv_backend websocket API")
    parser.add_argument("--url", default="ws://127.0.0.1:8766", help="Backend websocket URL.")
    parser.add_argument("--session-id", default="smoke-test", help="Session id to send.")
    parser.add_argument("--song-title", default="孤勇者", help="Song title in song_context/user_signal.")
    parser.add_argument("--song-artist", default="陈奕迅", help="Song artist in song_context/user_signal.")
    parser.add_argument("--song-url", default="", help="Optional song URL or local path.")
    parser.add_argument(
        "--text",
        default="副歌来了，带我一起跳。",
        help="User text for LLM test. Use an empty string to force ASR from --audio.",
    )
    parser.add_argument("--pose", default="arms_up", help="Optional pose_label.")
    parser.add_argument("--touch", default="", help="Optional touch_event.")
    parser.add_argument("--audio", default="", help="Optional audio file path for ASR test.")
    parser.add_argument("--sample-rate", type=int, default=16000, help="Sample rate to report with audio.")
    parser.add_argument("--timeout", type=float, default=12.0, help="Per-stage timeout in seconds.")
    return parser


def configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        stream.reconfigure(encoding="utf-8", errors="replace")


def build_song_payload(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "title": args.song_title,
        "artist": args.song_artist,
        "url": args.song_url,
    }


def build_audio_payload(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    if not args.audio:
        return None

    audio_path = Path(args.audio).expanduser().resolve()
    raw = audio_path.read_bytes()
    mime_type = mimetypes.guess_type(audio_path.name)[0] or "audio/wav"
    return {
        "content_b64": base64.b64encode(raw).decode("ascii"),
        "mime_type": mime_type,
        "sample_rate": args.sample_rate,
    }


def build_message(message_type: str, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": message_type,
        "request_id": f"{message_type}-{uuid.uuid4().hex[:8]}",
        "session_id": session_id,
        "payload": payload,
    }


def print_send(message: Dict[str, Any]) -> None:
    print("→ " + json.dumps(message, ensure_ascii=False))


def print_recv(message: Dict[str, Any]) -> None:
    print("← " + json.dumps(message, ensure_ascii=False))

    message_type = message.get("type")
    payload = message.get("payload") or {}
    if message_type == "hello":
        print(
            "  hello:"
            f" provider={payload.get('llm_provider', 'unknown')}"
            f" capabilities={json.dumps(payload.get('capabilities', {}), ensure_ascii=False)}"
        )
    elif message_type == "agent_response":
        print(
            "  agent_response:"
            f" source={payload.get('source', '-')}"
            f" action={payload.get('action', '-')}"
            f" expression={payload.get('expression', '-')}"
        )
        if payload.get("text"):
            print("  text: " + str(payload["text"]))
        if payload.get("transcript"):
            print("  transcript: " + str(payload["transcript"]))
    elif message_type == "tts_done":
        print(
            "  tts_done:"
            f" available={payload.get('available')}"
            f" chunk_count={payload.get('chunk_count')}"
        )
    elif message_type == "error":
        print(
            "  error:"
            f" code={payload.get('code', '-')}"
            f" message={payload.get('message', '-')}"
        )


async def wait_for_terminal_message(
    websocket: Any,
    request_id: str,
    timeout_s: float,
    terminal_types: set[str],
) -> None:
    while True:
        raw = await asyncio.wait_for(websocket.recv(), timeout=timeout_s)
        message = json.loads(raw)
        print_recv(message)

        if message.get("request_id") != request_id:
            continue
        if message.get("type") in terminal_types:
            return


async def main_async(args: argparse.Namespace) -> None:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("Missing dependency 'websockets'. Install requirements.txt first.") from exc

    async with websockets.connect(args.url, max_size=8 * 1024 * 1024) as websocket:
        hello = json.loads(await asyncio.wait_for(websocket.recv(), timeout=args.timeout))
        print_recv(hello)

        song_message = build_message(
            "song_context",
            args.session_id,
            {"song": build_song_payload(args)},
        )
        print_send(song_message)
        await websocket.send(json.dumps(song_message, ensure_ascii=False))
        await wait_for_terminal_message(
            websocket,
            song_message["request_id"],
            args.timeout,
            {"song_ready", "error"},
        )

        user_message = build_message(
            "user_signal",
            args.session_id,
            {
                "audio": build_audio_payload(args),
                "pose_label": args.pose,
                "touch_event": args.touch,
                "song": build_song_payload(args),
                "user_text": args.text,
            },
        )
        print_send(user_message)
        await websocket.send(json.dumps(user_message, ensure_ascii=False))
        await wait_for_terminal_message(
            websocket,
            user_message["request_id"],
            args.timeout,
            {"tts_done", "error"},
        )


def main() -> None:
    configure_stdio()
    args = build_parser().parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
