# KTV AI Backend

这套后端现在已经单独收进 `ktv_backend/`，不再和根目录里的 `memory_system` 混在一起。

## 目录

- [server.py](/c:/Users/kichi/Desktop/我和你们爆了/coding/记忆飞升/ktv_backend/server.py:1)：WebSocket 服务入口
- [modules/config.py](/c:/Users/kichi/Desktop/我和你们爆了/coding/记忆飞升/ktv_backend/modules/config.py:1)：配置和环境变量
- [modules/protocol.py](/c:/Users/kichi/Desktop/我和你们爆了/coding/记忆飞升/ktv_backend/modules/protocol.py:1)：Unity / Python 消息协议
- [modules/orchestrator.py](/c:/Users/kichi/Desktop/我和你们爆了/coding/记忆飞升/ktv_backend/modules/orchestrator.py:1)：多模态编排主流程
- [modules/asr.py](/c:/Users/kichi/Desktop/我和你们爆了/coding/记忆飞升/ktv_backend/modules/asr.py:1)：StepFun ASR
- [modules/llm.py](/c:/Users/kichi/Desktop/我和你们爆了/coding/记忆飞升/ktv_backend/modules/llm.py:1)：LLM 适配层（StepFun / OpenAI）
- [modules/tts.py](/c:/Users/kichi/Desktop/我和你们爆了/coding/记忆飞升/ktv_backend/modules/tts.py:1)：StepFun TTS
- [tests/test_ktv_backend.py](/c:/Users/kichi/Desktop/我和你们爆了/coding/记忆飞升/ktv_backend/tests/test_ktv_backend.py:1)：基础测试
- [requirements.txt](/c:/Users/kichi/Desktop/我和你们爆了/coding/记忆飞升/ktv_backend/requirements.txt:1)：依赖清单

## 当前模型方案

- ASR：`stepaudio-2.5-asr-stream`
- LLM：可切 `step-2-mini` / `gpt-5.4-mini`
- TTS：`step-tts-mini`

## 安装依赖

```powershell
pip install -r ktv_backend/requirements.txt
```

## 环境变量

```powershell
$env:STEP_API_KEY="your_key"
$env:STEP_LLM_MODEL="step-2-mini"
$env:STEP_ASR_MODEL="stepaudio-2.5-asr-stream"
$env:STEP_TTS_MODEL="step-tts-mini"
$env:STEP_TTS_VOICE_ID="cixingnansheng"
$env:KTV_WS_HOST="127.0.0.1"
$env:KTV_WS_PORT="8766"
```

默认缓存目录已经改到 `ktv_backend/.ktv_cache/`，不会再往项目根目录继续堆 KTV 运行缓存。

## 启动

```powershell
python -m ktv_backend.server
```

默认地址：

```text
ws://127.0.0.1:8766
```

## Unity -> Python

推荐固定两类输入消息。

### `song_context`

```json
{
  "type": "song_context",
  "request_id": "song-001",
  "session_id": "booth-a",
  "payload": {
    "song": {
      "title": "孤勇者",
      "artist": "陈奕迅",
      "url": "C:/music/gu_yong_zhe.mp3"
    }
  }
}
```

### `user_signal`

当前 ASR 适配层最稳的是 `16-bit PCM wav`：

```json
{
  "type": "user_signal",
  "request_id": "turn-007",
  "session_id": "booth-a",
  "payload": {
    "audio": {
      "content_b64": "BASE64_WAV",
      "mime_type": "audio/wav",
      "sample_rate": 16000,
      "text_hint": ""
    },
    "pose_label": "arms_up",
    "touch_event": "give_me_5",
    "song": {
      "title": "孤勇者",
      "artist": "陈奕迅",
      "url": "C:/music/gu_yong_zhe.mp3"
    }
  }
}
```

## Python -> Unity

服务会返回这些消息：

- `hello`
- `ack`
- `song_ready`
- `agent_response`
- `tts_chunk`
- `tts_done`
- `error`

`agent_response` 的关键字段仍然是：

```json
{
  "text": "啪，击掌成功，副歌一起冲。",
  "action": "high_five",
  "expression": "excited",
  "transcript": "",
  "music": {
    "bpm": 132,
    "energy": "high",
    "mood": "uplifting",
    "dance_action": "dance_fast",
    "expression": "excited",
    "confidence": 0.35,
    "source": "heuristic"
  }
}
```

## 测试

```powershell
python -m unittest discover -s ktv_backend/tests
```

## OpenAI LLM Switch

ASR and TTS can keep using StepFun. Only the LLM layer needs to switch.

```powershell
$env:KTV_LLM_PROVIDER="openai"
$env:OPENAI_API_KEY="your_openai_key"
$env:OPENAI_MODEL="gpt-5.4-mini"
$env:OPENAI_REASONING_EFFORT="low"
```

Provider modes:

- `KTV_LLM_PROVIDER="auto"`: prefer OpenAI when `OPENAI_API_KEY` exists, otherwise fall back to StepFun LLM
- `KTV_LLM_PROVIDER="stepfun"`: force StepFun LLM
- `KTV_LLM_PROVIDER="openai"`: force OpenAI LLM

Recommended mixed setup for this project:

```powershell
$env:KTV_LLM_PROVIDER="openai"
$env:OPENAI_API_KEY="your_openai_key"
$env:OPENAI_MODEL="gpt-5.4-mini"
$env:OPENAI_REASONING_EFFORT="low"
$env:STEP_API_KEY="your_step_key"
$env:STEP_ASR_MODEL="stepaudio-2.5-asr-stream"
$env:STEP_TTS_MODEL="step-tts-mini"
$env:STEP_TTS_VOICE_ID="cixingnansheng"
```

## Smoke Test

You can validate the websocket protocol and current LLM provider without Unity.

From `D:\桌面`, start the backend:

```powershell
python -m ktv_backend.server --debug
```

In another terminal:

```powershell
python D:\桌面\ktv_backend\tools\smoke_test_client.py
```

The script prints the backend `hello`, current `llm_provider`, `agent_response`, and `tts_done`.

- To test OpenAI LLM with typed text: keep `--text` as default.
- To force ASR from StepFun: pass `--text "" --audio your_sample.wav`.
