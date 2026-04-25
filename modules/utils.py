from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from functools import partial
from typing import Any, Callable, Dict


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z"


async def run_blocking(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    loop = asyncio.get_running_loop()
    bound = partial(func, *args, **kwargs)
    return await loop.run_in_executor(None, bound)


def compact_text(text: str, limit: int) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"


def extract_json_object(text: str) -> Dict[str, Any]:
    clean = (text or "").strip()
    if not clean:
        raise ValueError("Empty JSON payload")
    if clean.startswith("```"):
        clean = clean.strip("`")
        clean = clean.replace("json", "", 1).strip()
    if clean.startswith("{") and clean.endswith("}"):
        return json.loads(clean)

    start = clean.find("{")
    end = clean.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model output")
    return json.loads(clean[start : end + 1])
