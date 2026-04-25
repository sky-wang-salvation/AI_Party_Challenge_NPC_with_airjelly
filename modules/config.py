from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8766
    log_level: str = "INFO"
    send_debug_events: bool = False
    overall_timeout_s: float = 1.5
    llm_timeout_s: float = 0.9
    llm_provider: str = "auto"
    step_api_key: str = ""
    step_base_url: str = "https://api.stepfun.com/v1"
    step_llm_model: str = "step-2-mini"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5.4-mini"
    openai_reasoning_effort: str = "low"
    step_asr_model: str = "stepaudio-2.5-asr-stream"
    step_asr_ws_url: str = "wss://api.stepfun.com/v1/realtime/asr/stream"
    step_asr_language: str = "zh"
    step_asr_timeout_s: float = 8.0
    step_tts_model: str = "step-tts-mini"
    step_tts_ws_url: str = "wss://api.stepfun.com/v1/realtime/audio"
    step_tts_voice_id: str = "cixingnansheng"
    step_tts_response_format: str = "mp3"
    step_tts_sample_rate: int = 24000
    step_tts_speed_ratio: float = 1.0
    step_tts_volume_ratio: float = 1.0
    step_tts_mode: str = "sentence"
    step_tts_instruction: str = ""
    max_history_turns: int = 6
    music_download_timeout_s: float = 4.0
    music_analysis_duration_s: float = 45.0
    song_cache_dir: Path = field(default_factory=lambda: PACKAGE_ROOT / ".ktv_cache" / "songs")

    @classmethod
    def from_env(cls) -> "ServerConfig":
        cache_dir = os.getenv("KTV_SONG_CACHE_DIR")
        return cls(
            host=os.getenv("KTV_WS_HOST", "127.0.0.1"),
            port=_env_int("KTV_WS_PORT", 8766),
            log_level=os.getenv("KTV_LOG_LEVEL", "INFO"),
            send_debug_events=_env_bool("KTV_DEBUG_EVENTS", False),
            overall_timeout_s=_env_float("KTV_OVERALL_TIMEOUT_S", 1.5),
            llm_timeout_s=_env_float("KTV_LLM_TIMEOUT_S", 0.9),
            llm_provider=os.getenv("KTV_LLM_PROVIDER", "auto"),
            step_api_key=os.getenv("STEP_API_KEY", ""),
            step_base_url=os.getenv("STEP_BASE_URL", "https://api.stepfun.com/v1"),
            step_llm_model=os.getenv("STEP_LLM_MODEL", "step-2-mini"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
            openai_reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "low"),
            step_asr_model=os.getenv("STEP_ASR_MODEL", "stepaudio-2.5-asr-stream"),
            step_asr_ws_url=os.getenv(
                "STEP_ASR_WS_URL",
                "wss://api.stepfun.com/v1/realtime/asr/stream",
            ),
            step_asr_language=os.getenv("STEP_ASR_LANGUAGE", "zh"),
            step_asr_timeout_s=_env_float("STEP_ASR_TIMEOUT_S", 8.0),
            step_tts_model=os.getenv("STEP_TTS_MODEL", "step-tts-mini"),
            step_tts_ws_url=os.getenv(
                "STEP_TTS_WS_URL",
                "wss://api.stepfun.com/v1/realtime/audio",
            ),
            step_tts_voice_id=os.getenv("STEP_TTS_VOICE_ID", "cixingnansheng"),
            step_tts_response_format=os.getenv("STEP_TTS_RESPONSE_FORMAT", "mp3"),
            step_tts_sample_rate=_env_int("STEP_TTS_SAMPLE_RATE", 24000),
            step_tts_speed_ratio=_env_float("STEP_TTS_SPEED_RATIO", 1.0),
            step_tts_volume_ratio=_env_float("STEP_TTS_VOLUME_RATIO", 1.0),
            step_tts_mode=os.getenv("STEP_TTS_MODE", "sentence"),
            step_tts_instruction=os.getenv("STEP_TTS_INSTRUCTION", ""),
            max_history_turns=_env_int("KTV_MAX_HISTORY_TURNS", 6),
            music_download_timeout_s=_env_float("KTV_MUSIC_DOWNLOAD_TIMEOUT_S", 4.0),
            music_analysis_duration_s=_env_float("KTV_MUSIC_ANALYSIS_DURATION_S", 45.0),
            song_cache_dir=Path(cache_dir) if cache_dir else PACKAGE_ROOT / ".ktv_cache" / "songs",
        )
