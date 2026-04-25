from __future__ import annotations

from typing import Tuple

from .protocol import ALLOWED_ACTIONS, ALLOWED_EXPRESSIONS, UserSignal
from .state import SessionState


SYSTEM_PROMPT = """你是“小K”，一个站在KTV触摸屏前的陪唱虚拟偶像。
你要像现场气氛担当一样回应用户：快、短、自然、会接梗，但不要阴阳怪气。

你必须同时理解四类输入：
1. 用户说了什么
2. 用户当前姿态
3. 触摸屏互动事件
4. 当前歌曲的节奏和情绪

输出时遵守这些规则：
- 只能输出 JSON，不要解释，不要 markdown
- JSON 结构固定为 {{"reply":"...","action":"...","expression":"..."}}
- reply 用口语化中文，1 到 2 句，总长度控制在 8 到 36 个字
- 如果正在唱歌，优先陪唱、打气、接梗，不要长篇问答
- touch_event 是 give_me_5 时优先 high_five
- touch_event 是 heart 时优先 heart_pose
- 高能量歌曲优先 dance_fast 或 cheer
- 抒情歌曲优先 dance_soft
- 动作只能从这个列表里选：{actions}
- 表情只能从这个列表里选：{expressions}
""".format(
    actions=", ".join(ALLOWED_ACTIONS),
    expressions=", ".join(ALLOWED_EXPRESSIONS),
)


def build_prompts(signal: UserSignal, music_summary: str, transcript: str, session: SessionState) -> Tuple[str, str]:
    history_lines = []
    for turn in session.recent_turns(3):
        history_lines.append(
            "用户: {0} | 小K: {1} | 动作:{2} | 表情:{3}".format(
                turn.user_text or "（无语音）",
                turn.reply_text,
                turn.action,
                turn.expression,
            )
        )
    history_text = "\n".join(history_lines) if history_lines else "无历史"
    prompt = """
请根据现场上下文输出一条最合适的回应。

用户语音转写：
{transcript}

姿态标签：
{pose}

触摸事件：
{touch}

当前歌曲：
标题={title}
歌手={artist}
音乐分析={music_summary}

最近互动历史：
{history}
""".strip().format(
        transcript=transcript or "（本轮没有清晰语音）",
        pose=signal.pose_label or "none",
        touch=signal.touch_event or "none",
        title=signal.song.title or "未知",
        artist=signal.song.artist or "未知",
        music_summary=music_summary,
        history=history_text,
    )
    return SYSTEM_PROMPT, prompt
