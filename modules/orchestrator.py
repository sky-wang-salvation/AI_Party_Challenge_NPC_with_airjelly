from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict

from .asr import StepFunASR
from .config import ServerConfig
from .llm import KtvLlmClient, LlmDirective
from .music import MusicAnalysis, MusicAnalyzer
from .persona import build_prompts
from .protocol import ALLOWED_ACTIONS, ALLOWED_EXPRESSIONS, SongPayload, UserSignal
from .state import DialogueTurn, SessionRegistry
from .tts import StepFunTTSAdapter
from .utils import compact_text


@dataclass
class BrainResult:
    reply_text: str
    action: str
    expression: str
    transcript: str
    music: MusicAnalysis
    source: str
    timings_ms: Dict[str, int]
    debug: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "text": self.reply_text,
            "action": self.action,
            "expression": self.expression,
            "transcript": self.transcript,
            "music": self.music.to_dict(),
            "source": self.source,
            "timings_ms": self.timings_ms,
        }
        if self.debug:
            payload["debug"] = self.debug
        return payload


class KtvBrain:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.sessions = SessionRegistry()
        self.asr = StepFunASR(config)
        self.llm = KtvLlmClient(config)
        self.tts = StepFunTTSAdapter(config)
        self.music = MusicAnalyzer(config)

    async def prewarm_song(self, song: SongPayload) -> MusicAnalysis:
        if not song or not song.has_context():
            return self.music.estimate(song)
        return await self.music.prewarm(song)

    async def process_signal(self, signal: UserSignal) -> BrainResult:
        stage_start = time.perf_counter()
        session = self.sessions.get(signal.session_id)

        music_stage = time.perf_counter()
        music = await self._resolve_music(signal.song)
        music_ms = int((time.perf_counter() - music_stage) * 1000)

        transcript_stage = time.perf_counter()
        transcript = compact_text(signal.user_text or "", 80)
        if not transcript and signal.audio.has_audio():
            transcript = compact_text(await self.asr.transcribe(signal.audio), 80)
        asr_ms = int((time.perf_counter() - transcript_stage) * 1000)

        fallback = self._build_rule_response(signal, transcript, music)
        response = fallback
        source = "rules"
        llm_error = ""

        if self.llm.is_available():
            llm_stage = time.perf_counter()
            try:
                system_prompt, user_prompt = build_prompts(signal, music.short_text(), transcript, session)
                remaining_budget = max(
                    0.2,
                    self.config.overall_timeout_s - (time.perf_counter() - stage_start) - 0.2,
                )
                directive = await asyncio.wait_for(
                    self.llm.generate_directive(system_prompt, user_prompt),
                    timeout=min(self.config.llm_timeout_s, remaining_budget),
                )
                response = self._sanitize_directive(directive, fallback)
                source = "llm"
            except Exception as exc:
                llm_error = str(exc)
            llm_ms = int((time.perf_counter() - llm_stage) * 1000)
        else:
            llm_ms = 0

        session.last_pose_label = signal.pose_label
        session.last_touch_event = signal.touch_event
        session.current_song_key = signal.song.song_key()
        session.add_turn(
            DialogueTurn(
                user_text=transcript or self._describe_nonverbal(signal),
                reply_text=response.reply_text,
                action=response.action,
                expression=response.expression,
                song_title=signal.song.title,
            ),
            max_history_turns=self.config.max_history_turns,
        )

        total_ms = int((time.perf_counter() - stage_start) * 1000)
        timings_ms = {
            "music": music_ms,
            "asr": asr_ms,
            "llm": llm_ms,
            "total": total_ms,
        }
        debug = {}
        if self.config.send_debug_events:
            debug = {
                "pose_label": signal.pose_label,
                "touch_event": signal.touch_event,
                "llm_error": llm_error,
                "model_status": {
                    "asr": self.asr.is_available(),
                    "llm": self.llm.is_available(),
                    "tts": self.tts.is_available(),
                },
                "llm_provider": self.llm.provider_name,
            }
        return BrainResult(
            reply_text=response.reply_text,
            action=response.action,
            expression=response.expression,
            transcript=transcript,
            music=music,
            source=source,
            timings_ms=timings_ms,
            debug=debug,
        )

    async def stream_tts(self, text: str):
        async for sequence, chunk in self.tts.iter_audio(text):
            yield sequence, chunk

    async def _resolve_music(self, song: SongPayload) -> MusicAnalysis:
        if not song or not song.has_context():
            return self.music.estimate(song)

        cached = self.music.get_cached(song)
        if cached is not None:
            return cached

        self.music.ensure_background(song)
        return self.music.estimate(song)

    def _sanitize_directive(self, directive: LlmDirective, fallback: LlmDirective) -> LlmDirective:
        action = directive.action if directive.action in ALLOWED_ACTIONS else fallback.action
        expression = (
            directive.expression if directive.expression in ALLOWED_EXPRESSIONS else fallback.expression
        )
        reply = compact_text(directive.reply_text or fallback.reply_text, 40) or fallback.reply_text
        return LlmDirective(reply_text=reply, action=action, expression=expression)

    def _build_rule_response(
        self,
        signal: UserSignal,
        transcript: str,
        music: MusicAnalysis,
    ) -> LlmDirective:
        text = (transcript or "").lower()
        touch = (signal.touch_event or "").lower()
        pose = (signal.pose_label or "").lower()

        if touch == "give_me_5":
            return LlmDirective(
                reply_text="啪，击掌成功，副歌一起冲。",
                action="high_five",
                expression="excited",
            )
        if touch == "heart":
            return LlmDirective(
                reply_text="爱心收到，今天这首甜度拉满。",
                action="heart_pose",
                expression="love",
            )
        if any(keyword in text for keyword in ("失恋", "难过", "伤心", "emo", "想哭")):
            return LlmDirective(
                reply_text="这段我陪你稳稳唱，情绪我接住。",
                action="dance_soft",
                expression="supportive",
            )
        if any(keyword in text for keyword in ("忘词", "不会唱", "救我")):
            return LlmDirective(
                reply_text="别慌，我给你垫一句，继续接上。",
                action="sing_along",
                expression="playful",
            )
        if any(keyword in text for keyword in ("一起唱", "副歌", "来", "燥起来", "高音")):
            return LlmDirective(
                reply_text="副歌要到了，我们一起把气氛顶上去。",
                action="sing_along",
                expression="excited",
            )
        if pose == "jumping":
            return LlmDirective(
                reply_text="跳起来了，这段气氛已经点着了。",
                action="cheer",
                expression="excited",
            )
        if pose == "arms_up":
            return LlmDirective(
                reply_text="手都举起来了，包厢热起来了。",
                action="mirror_pose",
                expression="excited",
            )
        if music.energy == "high":
            return LlmDirective(
                reply_text="这节奏起来了，跟我一起炸场。",
                action="dance_fast",
                expression="excited",
            )
        if music.mood in {"melancholy", "tender"}:
            return LlmDirective(
                reply_text="这一段我陪你轻轻唱，情绪很到位。",
                action="dance_soft",
                expression="supportive",
            )
        return LlmDirective(
            reply_text="我在，下一句我们继续接上。",
            action=music.dance_action,
            expression=music.expression,
        )

    def _describe_nonverbal(self, signal: UserSignal) -> str:
        parts = []
        if signal.pose_label:
            parts.append("pose=" + signal.pose_label)
        if signal.touch_event:
            parts.append("touch=" + signal.touch_event)
        if signal.song.title:
            parts.append("song=" + signal.song.title)
        return ", ".join(parts) or "nonverbal"
