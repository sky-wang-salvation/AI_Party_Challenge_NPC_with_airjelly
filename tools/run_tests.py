"""
KTV AI Backend — 一键测试脚本

用法：
    python ktv_backend/tools/run_tests.py           # 跑全部测试
    python ktv_backend/tools/run_tests.py --unit    # 只跑单元测试
    python ktv_backend/tools/run_tests.py --airjelly # 只测 AirJelly 连通
    python ktv_backend/tools/run_tests.py --rules   # 只测规则引擎
    python ktv_backend/tools/run_tests.py --prompt  # 只测 Prompt 注入

不需要 Unity，不需要 API Key（单元测试 + 规则引擎）。
AirJelly 测试需要本机运行 AirJelly Desktop。
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import textwrap
import traceback
from pathlib import Path
from typing import Callable, List, Tuple

# 确保从项目根目录导入
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m·\033[0m"


def section(title: str) -> None:
    print(f"\n\033[1m{'─' * 50}\033[0m")
    print(f"\033[1m  {title}\033[0m")
    print(f"\033[1m{'─' * 50}\033[0m")


def ok(msg: str) -> None:
    print(f"  {PASS}  {msg}")


def fail(msg: str) -> None:
    print(f"  {FAIL}  {msg}")


def info(msg: str) -> None:
    print(f"  {INFO}  {msg}")


# ──────────────────────────────────────────────
# Level 1: unittest
# ──────────────────────────────────────────────

def run_unit_tests() -> bool:
    section("Level 1 · 单元测试 (unittest)")
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "ktv_backend/tests", "-v"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    output = result.stderr + result.stdout
    lines = [l for l in output.splitlines() if l.strip()]
    passed = failed = 0
    for line in lines:
        if " ... ok" in line:
            ok(line.split(" ... ")[0].strip())
            passed += 1
        elif "FAIL:" in line or "ERROR:" in line:
            fail(line.strip())
            failed += 1
    if result.returncode == 0:
        ok(f"全部通过 ({passed} 项)")
        return True
    else:
        fail(f"失败 {failed} 项，详情：\n{textwrap.indent(output, '    ')}")
        return False


# ──────────────────────────────────────────────
# Level 2: import + capability check
# ──────────────────────────────────────────────

def run_import_check() -> bool:
    section("Level 2 · 模块导入 & 能力探测")
    try:
        from ktv_backend.modules.config import ServerConfig
        from ktv_backend.modules.orchestrator import KtvBrain
        from ktv_backend.modules.airjelly_client import AirJellyClient
        from ktv_backend.modules.protocol import parse_client_message, build_server_message
        from ktv_backend.modules.persona import build_prompts
        from ktv_backend.modules.state import SessionRegistry
        ok("所有模块 import 成功")

        config = ServerConfig()
        brain = KtvBrain(config)
        aj = AirJellyClient()

        info(f"AirJelly available : {aj.is_available()}")
        info(f"LLM provider       : {brain.llm.provider_name}")
        info(f"LLM available      : {brain.llm.is_available()}")
        info(f"ASR available      : {brain.asr.is_available()}")
        info(f"TTS available      : {brain.tts.is_available()}")
        ok("能力探测完成")
        return True
    except Exception as exc:
        fail(f"导入失败: {exc}")
        traceback.print_exc()
        return False


# ──────────────────────────────────────────────
# Level 3: AirJelly connectivity
# ──────────────────────────────────────────────

async def _run_airjelly_async() -> Tuple[bool, List[str]]:
    from ktv_backend.modules.airjelly_client import AirJellyClient
    from datetime import date

    aj = AirJellyClient()
    notes: List[str] = []
    all_ok = True

    if not aj.is_available():
        return False, ["AirJelly Desktop 未运行，请先启动再测试"]

    # health
    healthy = await aj.health_check()
    if healthy:
        notes.append("health_check: OK")
    else:
        notes.append("health_check: FAIL")
        all_ok = False

    # search_memory
    mems = await aj.search_memory("音乐 KTV 唱歌", limit=3)
    notes.append(f"search_memory: 返回 {len(mems)} 条记忆")

    # open tasks
    tasks = await aj.get_open_tasks(limit=5)
    notes.append(f"get_open_tasks: 返回 {len(tasks)} 个任务")
    for t in tasks[:3]:
        notes.append(f"  - {t.get('title', '')}")

    # app usage
    usage = await aj.get_daily_app_usage(date.today().isoformat())
    notes.append(f"get_daily_app_usage: 今日 {len(usage)} 个 App")
    top = sorted(usage, key=lambda u: u.get("total_seconds", 0), reverse=True)[:3]
    for u in top:
        notes.append(f"  - {u.get('app_name')} {int(u.get('total_seconds', 0)//60)} min")

    # build_music_context
    ctx = await aj.build_music_context()
    notes.append(f"build_music_context: {'有内容' if ctx else '空（无音乐记忆）'}")

    # build_task_context
    tctx = await aj.build_task_context()
    notes.append(f"build_task_context: {'有内容' if tctx else '空（无练歌待办）'}")

    return all_ok, notes


def run_airjelly_tests() -> bool:
    section("Level 3 · AirJelly 连通性")
    try:
        all_ok, notes = asyncio.run(_run_airjelly_async())
        for note in notes:
            if note.startswith("  "):
                info(note.strip())
            elif "FAIL" in note:
                fail(note)
            else:
                ok(note)
        return all_ok
    except Exception as exc:
        fail(f"AirJelly 测试异常: {exc}")
        traceback.print_exc()
        return False


# ──────────────────────────────────────────────
# Level 4: 规则引擎
# ──────────────────────────────────────────────

RULE_CASES = [
    ("touch give_me_5 → high_five",    "give_me_5",  "",        "",                   "high_five",  "excited"),
    ("touch heart → heart_pose",       "heart",      "",        "",                   "heart_pose", "love"),
    ("pose arms_up → mirror_pose",     "",           "arms_up", "",                   "mirror_pose","excited"),
    ("sad keyword → dance_soft",       "",           "",        "好难过想哭",           "dance_soft", "supportive"),
    ("lyrics help → sing_along",       "",           "",        "我忘词了救我",         "sing_along", "playful"),
    ("chorus invite → sing_along",     "",           "",        "副歌来了一起唱",       "sing_along", "excited"),
    ("high-energy song → dance_fast",  "",           "",        "",                   "dance_fast", "excited"),  # 用 uplifting 歌曲
]

async def _run_rules_async() -> Tuple[bool, List[Tuple[str, bool, str]]]:
    from ktv_backend.modules.config import ServerConfig
    from ktv_backend.modules.orchestrator import KtvBrain
    from ktv_backend.modules.protocol import parse_client_message
    import json

    config = ServerConfig()
    brain = KtvBrain(config)
    results = []

    for name, touch, pose, text, exp_action, exp_expr in RULE_CASES:
        song_title = "孤勇者" if "high-energy" in name else "告白气球"
        raw = json.dumps({
            "type": "user_signal",
            "session_id": "rule-test",
            "payload": {
                "user_id": "test-user",
                "touch_event": touch,
                "pose_label": pose,
                "user_text": text,
                "song": {"title": song_title, "artist": "陈奕迅"},
            },
        })
        msg = parse_client_message(raw, "fallback")
        result = await brain.process_signal(msg.signal)
        passed = result.action == exp_action and result.expression == exp_expr
        detail = (
            f"action={result.action!r} expr={result.expression!r} reply={result.reply_text!r}"
        )
        if not passed:
            detail += f" (期望 action={exp_action!r} expr={exp_expr!r})"
        results.append((name, passed, detail))

    return all(p for _, p, _ in results), results


def run_rules_tests() -> bool:
    section("Level 4 · 规则引擎")
    try:
        all_ok, results = asyncio.run(_run_rules_async())
        for name, passed, detail in results:
            if passed:
                ok(f"{name}")
                info(detail)
            else:
                fail(f"{name}")
                info(detail)
        return all_ok
    except Exception as exc:
        fail(f"规则引擎测试异常: {exc}")
        traceback.print_exc()
        return False


# ──────────────────────────────────────────────
# Level 5: Prompt 注入
# ──────────────────────────────────────────────

async def _run_prompt_async() -> Tuple[bool, List[str]]:
    from ktv_backend.modules.airjelly_client import AirJellyClient
    from ktv_backend.modules.persona import build_prompts
    from ktv_backend.modules.protocol import parse_client_message
    from ktv_backend.modules.state import SessionState
    import json

    notes: List[str] = []
    aj = AirJellyClient()

    music_ctx = await aj.build_music_context("周杰伦") if aj.is_available() else ""
    task_ctx = await aj.build_task_context() if aj.is_available() else ""

    raw = json.dumps({
        "type": "user_signal",
        "session_id": "prompt-test",
        "payload": {
            "user_text": "一起唱副歌",
            "song": {"title": "告白气球", "artist": "周杰伦"},
        },
    })
    msg = parse_client_message(raw, "fallback")
    session = SessionState(session_id="prompt-test", user_id="user-001")
    session.update_airjelly(music_ctx, task_ctx)

    _, user_prompt = build_prompts(
        msg.signal,
        "bpm=104, energy=medium, mood=warm, dance=dance_groove, source=heuristic",
        "一起唱副歌",
        session,
        airjelly_music_context=music_ctx,
        airjelly_task_context=task_ctx,
    )

    notes.append("user_prompt 包含歌曲信息: " + ("是" if "告白气球" in user_prompt else "否"))
    notes.append("user_prompt 包含歌手信息: " + ("是" if "周杰伦" in user_prompt else "否"))
    notes.append("user_prompt 包含语音转写: " + ("是" if "一起唱副歌" in user_prompt else "否"))

    if music_ctx:
        notes.append("AirJelly 记忆已注入 prompt: " + ("是" if "AirJelly" in user_prompt else "否"))
    else:
        notes.append("AirJelly 未连接，跳过记忆注入检查")

    if task_ctx:
        notes.append("AirJelly 待办已注入 prompt: " + ("是" if "练歌待办" in user_prompt else "否"))
    else:
        notes.append("AirJelly 无练歌待办，跳过任务注入检查")

    all_ok = all("否" not in n or "跳过" in n for n in notes)
    return all_ok, notes


def run_prompt_tests() -> bool:
    section("Level 5 · Prompt 注入")
    try:
        all_ok, notes = asyncio.run(_run_prompt_async())
        for note in notes:
            if "否" in note and "跳过" not in note:
                fail(note)
            else:
                ok(note)
        return all_ok
    except Exception as exc:
        fail(f"Prompt 测试异常: {exc}")
        traceback.print_exc()
        return False


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="KTV AI Backend 一键测试")
    parser.add_argument("--unit",    action="store_true", help="只跑单元测试")
    parser.add_argument("--airjelly",action="store_true", help="只测 AirJelly 连通")
    parser.add_argument("--rules",   action="store_true", help="只测规则引擎")
    parser.add_argument("--prompt",  action="store_true", help="只测 Prompt 注入")
    args = parser.parse_args()

    run_all = not any([args.unit, args.airjelly, args.rules, args.prompt])

    results: List[Tuple[str, bool]] = []

    if run_all or args.unit:
        results.append(("单元测试", run_unit_tests()))

    if run_all or args.unit:
        results.append(("模块导入", run_import_check()))

    if run_all or args.airjelly:
        results.append(("AirJelly 连通", run_airjelly_tests()))

    if run_all or args.rules:
        results.append(("规则引擎", run_rules_tests()))

    if run_all or args.prompt:
        results.append(("Prompt 注入", run_prompt_tests()))

    section("测试汇总")
    all_passed = True
    for name, passed in results:
        if passed:
            ok(name)
        else:
            fail(name)
            all_passed = False

    print()
    if all_passed:
        print("  \033[92m全部通过 ✓\033[0m")
        sys.exit(0)
    else:
        print("  \033[91m存在失败项 ✗\033[0m")
        sys.exit(1)


if __name__ == "__main__":
    main()
