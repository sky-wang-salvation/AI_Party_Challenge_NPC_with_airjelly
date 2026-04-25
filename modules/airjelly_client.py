"""
AirJelly Desktop Python client.

Reads runtime.json auto-discovered from the local AirJelly Desktop app,
then calls the JSON-RPC HTTP API at 127.0.0.1:{port}.

All public methods degrade gracefully: if AirJelly is not running or returns
an error, they return empty results instead of raising.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

LOGGER = logging.getLogger("ktv_ai_server.airjelly")

# Platform-specific paths for runtime.json
_RUNTIME_PATHS = [
    Path.home() / "Library" / "Application Support" / "AirJelly" / "runtime.json",  # macOS
    Path(os.environ.get("APPDATA", "")) / "AirJelly" / "runtime.json",               # Windows
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "AirJelly" / "runtime.json",  # Linux
]

_MUSIC_APP_NAMES = {
    "网易云音乐", "neteasemusic", "spotify", "apple music", "music",
    "qqmusic", "qq音乐", "酷狗音乐", "kugou", "酷我音乐", "kuwo",
}


def _load_runtime() -> Optional[Dict[str, Any]]:
    for path in _RUNTIME_PATHS:
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "port" in data and "token" in data:
                    return data
        except Exception:
            continue
    return None


class AirJellyClient:
    """Lightweight Python wrapper around the AirJelly local HTTP API."""

    def __init__(self, timeout_s: float = 2.0) -> None:
        self._timeout = timeout_s
        self._runtime: Optional[Dict[str, Any]] = None
        self._runtime_loaded_at: float = 0.0
        self._available: Optional[bool] = None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        runtime = self._get_runtime()
        return runtime is not None

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    async def search_memory(
        self,
        query: str,
        limit: int = 5,
        memory_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Semantic search over AirJelly memories. Returns [] on any failure."""
        options: Dict[str, Any] = {"limit": limit}
        if memory_types:
            options["memory_types"] = memory_types
        result = await self._rpc("searchMemory", [query, options])
        if isinstance(result, list):
            return result
        return []

    async def list_memories(
        self,
        limit: int = 10,
        memory_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        options: Dict[str, Any] = {"limit": limit}
        if memory_types:
            options["memory_types"] = memory_types
        result = await self._rpc("listMemories", [options])
        if isinstance(result, list):
            return result
        return []

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def get_open_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch open tasks. Returns [] on failure."""
        result = await self._rpc("listOpenTasks", [limit])
        if isinstance(result, list):
            return result
        return []

    async def create_task(
        self,
        title: str,
        description: str = "",
        due_date_ms: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a task in AirJelly. Returns None on failure."""
        input_data: Dict[str, Any] = {"title": title}
        if description:
            input_data["description"] = description
        if due_date_ms is not None:
            input_data["due_date"] = due_date_ms
        result = await self._rpc("createTask", [input_data])
        if isinstance(result, dict):
            return result
        return None

    # ------------------------------------------------------------------
    # App usage (mood inference)
    # ------------------------------------------------------------------

    async def get_daily_app_usage(self, date: str) -> List[Dict[str, Any]]:
        """date: YYYY-MM-DD. Returns [] on failure."""
        result = await self._rpc("getDailyAppUsage", [date])
        if isinstance(result, list):
            return result
        return []

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def get_events_by_date(
        self, start_ms: int, end_ms: int
    ) -> List[Dict[str, Any]]:
        result = await self._rpc("listEvents", [start_ms, end_ms])
        if isinstance(result, list):
            return result
        return []

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        runtime = self._get_runtime()
        if not runtime:
            return False
        try:
            url = "http://127.0.0.1:{port}/health".format(**runtime)
            req = Request(url, headers={"Authorization": "Bearer " + runtime["token"]})
            with urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return bool(data.get("ok"))
        except Exception as exc:
            LOGGER.debug("AirJelly health check failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Higher-level helpers used by orchestrator
    # ------------------------------------------------------------------

    async def build_music_context(self, artist_hint: str = "") -> str:
        """
        Returns a short prose summary of the user's music preferences,
        derived from AirJelly memories and today's app usage.
        Falls back to "" if AirJelly is unavailable.
        """
        if not self.is_available():
            return ""

        parts: List[str] = []

        # Semantic memory search for music/KTV context
        query = "KTV 唱歌 音乐 歌曲" + (" " + artist_hint if artist_hint else "")
        memories = await self.search_memory(query, limit=4)
        if memories:
            snippets = []
            for m in memories[:3]:
                title = str(m.get("title") or "").strip()
                content = str(m.get("content") or "").strip()
                if title:
                    snippets.append(title + ("：" + content[:40] if content else ""))
            if snippets:
                parts.append("【历史记忆】" + "；".join(snippets))

        # Today's music app usage → mood/energy signal
        today = _today_str()
        usage = await self.get_daily_app_usage(today)
        music_apps = [
            u for u in usage
            if any(name in (u.get("app_name") or "").lower() for name in _MUSIC_APP_NAMES)
        ]
        if music_apps:
            top = sorted(music_apps, key=lambda u: u.get("total_seconds", 0), reverse=True)
            app_name = top[0].get("app_name", "音乐App")
            mins = int(top[0].get("total_seconds", 0) // 60)
            if mins > 0:
                parts.append("【今日音乐App】{0}（{1}分钟）".format(app_name, mins))

        return "\n".join(parts) if parts else ""

    async def build_task_context(self) -> str:
        """
        Returns a short prose list of the user's open KTV/music-related tasks.
        Falls back to "" if AirJelly is unavailable.
        """
        if not self.is_available():
            return ""

        tasks = await self.get_open_tasks(limit=10)
        music_keywords = ("唱", "歌", "ktv", "练", "音乐", "song", "music", "sing")
        relevant = [
            t for t in tasks
            if any(kw in (t.get("title") or "").lower() for kw in music_keywords)
        ]
        if not relevant:
            return ""

        lines = []
        for t in relevant[:3]:
            title = str(t.get("title") or "").strip()
            steps = t.get("next_steps") or []
            if title:
                suffix = "（下一步：{0}）".format(steps[0]) if steps else ""
                lines.append("- " + title + suffix)
        return "【练歌待办】\n" + "\n".join(lines) if lines else ""

    async def maybe_create_ktv_task(self, transcript: str, song_title: str) -> bool:
        """
        If the transcript contains task-creation intent, create a task in AirJelly.
        Returns True if a task was created.
        """
        if not self.is_available():
            return False
        triggers = ("帮我记住", "提醒我", "下次要唱", "要练", "想学", "记一下", "别忘了")
        if not any(t in transcript for t in triggers):
            return False
        title = "练习《{0}》".format(song_title) if song_title else "KTV 练歌任务"
        desc = "来自 KTV 包厢记录：" + transcript[:80]
        task = await self.create_task(title=title, description=desc)
        if task:
            LOGGER.info("AirJelly task created: %s", task.get("id"))
            return True
        return False

    # ------------------------------------------------------------------
    # Internal RPC transport
    # ------------------------------------------------------------------

    def _get_runtime(self) -> Optional[Dict[str, Any]]:
        now = time.monotonic()
        # Re-read runtime.json at most every 30 s (token rotates on Desktop restart)
        if self._runtime is None or now - self._runtime_loaded_at > 30:
            self._runtime = _load_runtime()
            self._runtime_loaded_at = now
        return self._runtime

    async def _rpc(self, method: str, args: Optional[List[Any]] = None) -> Any:
        """Call an AirJelly RPC method. Returns None on any error."""
        from .utils import run_blocking
        try:
            return await run_blocking(self._rpc_sync, method, args or [])
        except Exception as exc:
            LOGGER.debug("AirJelly RPC %s failed: %s", method, exc)
            return None

    def _rpc_sync(self, method: str, args: List[Any]) -> Any:
        runtime = self._get_runtime()
        if not runtime:
            return None
        url = "http://127.0.0.1:{port}/rpc".format(**runtime)
        body = json.dumps({"method": method, "args": args}, ensure_ascii=False).encode("utf-8")
        req = Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + runtime["token"],
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                if isinstance(payload, dict) and "data" in payload:
                    return payload["data"]
                return payload
        except URLError as exc:
            LOGGER.debug("AirJelly RPC %s URLError: %s", method, exc)
            return None


def _today_str() -> str:
    from datetime import date
    return date.today().isoformat()
