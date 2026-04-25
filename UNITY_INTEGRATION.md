# KTV AI 后端 · Unity 对接文档

> 后端版本：基于 WebSocket，Python 3.9+  
> 协议版本：1  
> 测试通过：97 / 97 单元测试全绿 ✅

---

## 一、连接

```
ws://127.0.0.1:8766
```

连上后服务端立刻推送 `hello`，包含能力声明：

```json
{
  "type": "hello",
  "payload": {
    "service": "ktv-ai-server",
    "protocol_version": 1,
    "llm_provider": "openai",
    "capabilities": {
      "asr": true,
      "llm": true,
      "tts": true,
      "music_analysis": true,
      "airjelly": false,
      "proactive_nudge": false,
      "scene_directive": true,
      "instant_effect": true,
      "emotion_portrait": true
    }
  }
}
```

---

## 二、Unity → Python（输入消息）

### 2-1  `song_context`（歌曲预热，歌曲切换时发）

```json
{
  "type": "song_context",
  "request_id": "song-001",
  "session_id": "booth-a",
  "payload": {
    "song": {
      "title": "孤勇者",
      "artist": "陈奕迅",
      "url": "C:/music/gu_yong_zhe.mp3",
      "bpm": 132,
      "emotion": "uplifting"
    }
  }
}
```

| 字段 | 说明 |
|---|---|
| `url` | 本地文件路径或 HTTP URL，空字符串也行（走启发式分析）|
| `bpm` | 可选，已知 BPM 直接传，跳过音频分析 |
| `emotion` | 可选提示：`uplifting / melancholy / warm / tender` |

---

### 2-2  `user_signal`（每次用户互动发）

```json
{
  "type": "user_signal",
  "request_id": "turn-007",
  "session_id": "booth-a",
  "payload": {
    "audio": {
      "content_b64": "BASE64_WAV",
      "mime_type": "audio/wav",
      "sample_rate": 16000
    },
    "user_text": "",
    "pose_label": "arms_up",
    "touch_event": "give_me_5",
    "song": { "title": "孤勇者", "artist": "陈奕迅" }
  }
}
```

**`audio`**：16-bit PCM WAV，base64 编码。没有麦克风时传 `null` 或省略。  
**`user_text`**：ASR 已经在 Unity 侧完成时可直接传文字，后端跳过 ASR。  
**`pose_label`** 枚举：

| 值 | 含义 |
|---|---|
| `arms_up` | 双手举起 |
| `jumping` | 跳动 |
| `scream` | 尖叫/高能 |

**`touch_event`** 枚举：

| 值 | 含义 |
|---|---|
| `give_me_5` | 击掌/拍屏幕 |
| `heart` | 比心 |
| `fist_bump` | 碰拳 |

---

### 2-3  `song_end`（歌曲唱完时发，触发情绪画像）

```json
{
  "type": "song_end",
  "request_id": "end-001",
  "session_id": "booth-a"
}
```

---

### 2-4  `ping`（心跳保活，可选）

```json
{ "type": "ping", "request_id": "ping-001", "session_id": "booth-a" }
```

---

## 三、Python → Unity（输出消息）

### 3-1  `ack`（收到 user_signal 后 **立刻** 发，<100ms）

```json
{
  "type": "ack",
  "request_id": "turn-007",
  "session_id": "booth-a",
  "payload": {
    "accepted": true,
    "instant_effect": {
      "effect_type": "light_pillar",
      "color": "#FFD700",
      "duration_ms": 1500,
      "intensity": 1.0,
      "params": {
        "top_effect": "fireworks",
        "top_color": "#00F5FF",
        "width": 0.08,
        "fade_out_s": 1.2
      }
    }
  }
}
```

**`instant_effect` 是纯规则输出，不等 LLM，Unity 拿到就立刻播。**  
`instant_effect` 可能为 `null`（无 touch/pose 时）。

---

### 3-2  `agent_response`（LLM 处理完后发，约 0.5-2s）

```json
{
  "type": "agent_response",
  "request_id": "turn-007",
  "session_id": "booth-a",
  "payload": {
    "text": "副歌要到了，我们一起把气氛顶上去。",
    "action": "dance_fast",
    "expression": "excited",
    "transcript": "小K我们一起唱副歌",
    "source": "llm",
    "timings_ms": { "asr": 320, "llm": 780, "music": 0, "total": 1100 },
    "music": {
      "bpm": 132,
      "energy": "high",
      "mood": "uplifting",
      "dance_action": "dance_fast",
      "expression": "excited",
      "confidence": 0.78,
      "source": "librosa"
    },
    "scene": { }
  }
}
```

**`scene` 子对象** 是核心视觉指令，结构见第四节。

---

### 3-3  `tts_chunk` + `tts_done`（TTS 音频分块流式发送）

```json
{
  "type": "tts_chunk",
  "request_id": "turn-007",
  "payload": {
    "seq": 0,
    "format": "audio/mpeg",
    "audio_b64": "BASE64_MP3_CHUNK",
    "is_final": false
  }
}
```

```json
{
  "type": "tts_done",
  "payload": { "format": "audio/mpeg", "chunk_count": 3, "available": true }
}
```

`chunk_count=0` 表示 TTS 不可用（未配置 API Key）。

---

### 3-4  `song_ready`（歌曲预热完成）

```json
{
  "type": "song_ready",
  "request_id": "song-001",
  "payload": {
    "song": { "title": "孤勇者", "artist": "陈奕迅" },
    "music": { "bpm": 132, "energy": "high", "mood": "uplifting", ... },
    "scene": { }
  }
}
```

`scene` 是这首歌的**开场氛围**，小人处于 `idle`，低亮度，粒子刚刚开始漂浮。

---

### 3-5  `emotion_portrait`（歌曲结束后发）

```json
{
  "type": "emotion_portrait",
  "payload": {
    "theme": "burst",
    "palette": {
      "primary": "#FF006E",
      "accent": "#00F5FF",
      "highlight": "#FFFF00",
      "bg_start": "#1A0033",
      "bg_end": "#4D0080",
      "rim_light": "#FF006E",
      "particle": "#00F5FF"
    },
    "energy_curve": [0.55, 0.55, 0.85, 0.85, 0.85, 0.55],
    "key_events": [
      { "event_type": "chorus_start", "label": "副歌爆发", "elapsed_s": 83.0 },
      { "event_type": "arms_up",      "label": "举手",     "elapsed_s": 95.5 },
      { "event_type": "heart",        "label": "比心",     "elapsed_s": 110.2 }
    ],
    "caption": "这首歌点燃了整个包厢。",
    "qr_code_url": "",
    "song_title": "孤勇者",
    "song_artist": "陈奕迅"
  }
}
```

---

### 3-6  `proactive_nudge`（后台定时主动推送，AirJelly 启用时）

```json
{
  "type": "proactive_nudge",
  "session_id": "booth-a",
  "payload": {
    "text": "你有一个练歌待办还没完成哦。",
    "action": "wave",
    "expression": "playful",
    "trigger": "airjelly_task"
  }
}
```

---

### 3-7  `error`

```json
{
  "type": "error",
  "payload": { "code": "bad_request", "message": "..." }
}
```

---

## 四、`scene` 对象详解（视觉导演层）

每次 `agent_response` 和 `song_ready` 都携带 `scene`，Unity 按此渲染所有 5 层视觉。

```json
{
  "theme": "burst",
  "theme_transition_s": 0.5,
  "character": {
    "action": "dance_fast",
    "expression": "excited",
    "beat_sync": true,
    "intensity": 1.0,
    "transition_s": 0.15,
    "rim_light_color": "#FF006E",
    "rim_light_intensity": 1.0
  },
  "particles": {
    "form": "beat",
    "density": 1.0,
    "bpm": 132,
    "color_primary": "#00F5FF",
    "color_accent": "#00F5FF",
    "special_event": "chorus_burst",
    "particle_count_override": 500
  },
  "background": {
    "grad_start": "#1A0033",
    "grad_end": "#4D0080",
    "brightness": 0.80,
    "fluid_speed": 0.98,
    "transition_s": 0.45
  },
  "instant_effects": [
    {
      "effect_type": "screen_flash",
      "color": "#FFFFFF",
      "duration_ms": 50,
      "intensity": 1.0,
      "params": { "follow_up": "particle_explode", "particle_count": 500, "pre_darken_ms": 80 }
    }
  ],
  "subtitle": "副歌要到了，我们一",
  "subtitle_duration_ms": 2200
}
```

---

### 4-1  主题（`theme`）

| 值 | 场景 | 主色 | 背景 |
|---|---|---|---|
| `calm` | 慢歌 / 抒情 / 开场 | `#2D3561` 深蓝 | `#0A0E27 → #1A1F4A` |
| `warm` | 流行 / 中速 | `#FF6B6B` 暖粉 | `#3D1F1F → #6B2E2E` |
| `burst` | 副歌 / 快歌 | `#FF006E` 荧光粉 | `#1A0033 → #4D0080` |
| `cyber` | 电音 / BPM≥140 | `#00FFC6` 青绿 | `#000000 → #001A33` |

`theme_transition_s`：颜色 lerp 时长（普通 1.5s，副歌 0.5s）。**必须 lerp，不要硬切。**

---

### 4-2  小人（`character`，Layer 3）

**`action`** 枚举及对应动画：

| action | 动画描述 |
|---|---|
| `idle` | 站立呼吸，眨眼，轻微摇摆 |
| `wave` | 右手挥手 |
| `mirror_pose` | 双手举起，镜像用户 |
| `high_five` | 右手前伸击掌 |
| `heart_pose` | 双手在胸前比心形 |
| `cheer` | 双手举高欢呼，原地弹跳 |
| `clap` | 双手拍掌 |
| `sing_along` | 手持麦克风姿势，头随节拍摇 |
| `dance_soft` | 慢节拍左右晃动 |
| `dance_groove` | 中节拍，臀部律动 |
| `dance_fast` | 快节拍，全身弹跳，BPM 同步 |

**`expression`** 枚举：

| expression | 含义 |
|---|---|
| `calm` | 平静，微笑 |
| `excited` | 兴奋，眼睛放大 |
| `love` | 爱心眼，嘴角上扬 |
| `playful` | 俏皮，歪头 |
| `supportive` | 温柔鼓励 |
| `cool` | 酷，微微侧脸 |
| `focused` | 专注，眉头轻皱 |

**`beat_sync`**：`true` 时小人要在每个强拍（downbeat）做一次弹跳/脉冲，频率由 `particles.bpm` 计算。  
**`intensity`**：0–1，映射到动画幅度 blend weight。  
**`transition_s`**：从上一个动作淡入的时长，高能状态下 0.15s，抒情 0.35s。  
**轮廓光（rim_light）**：小人背面始终保留一圈光勾边，让它在复杂背景下清晰可辨。

---

### 4-3  粒子层（`particles`，Layer 2）

**`form`** 枚举：

| form | 行为 |
|---|---|
| `floating` | calm 用：稀疏白色光点，随机向上漂移，自带柔光 |
| `beat` | warm/burst 用：每个强拍从小人脚底散开一波，弱拍缩小变暗 |
| `data_stream` | cyber 用：从左→右 / 下→上持续流动，速度 ∝ BPM，颜色按频谱分布 |

**`special_event`** 枚举（一次性爆发状态）：

| 值 | 效果 |
|---|---|
| `chorus_burst` | **副歌起**：单帧生成 500 颗粒子向外爆射，与 `screen_flash` 联动 |
| `heart_form` | 粒子全部变成爱心形状，密度 0.75 |
| `scatter` | 粒子被"震散"后缓慢聚回（用户尖叫场景）|
| `""` | 正常连续发射，无特殊事件 |

**`particle_count_override`**：`0` 表示由 density 自动计算；`500` 表示副歌强制 500 颗。  
**`density`**：0–1，calm=0.22，warm=0.52，burst/chorus=1.0。

---

### 4-4  背景层（`background`，Layer 1）

`brightness` 上限 **0.85**（设计规定：整屏保留 ≥30% 暗区）。  
`fluid_speed`：0.14（calm 极慢）→ 0.98（burst/cyber 快速流动）。  
`transition_s`：背景过渡时间，副歌 0.45s，平时 1.5s。

---

### 4-5  即时特效（`instant_effects`，Layer 4）

来自两处：
- **`ack.instant_effect`**：touch/pose 触发，**收到即播，不等 agent_response**
- **`scene.instant_effects`**：LLM 处理完后的补充特效（如副歌 screen_flash）

**`effect_type`** 枚举：

| effect_type | 描述 | 关键参数 |
|---|---|---|
| `give_me_5_flash` | 击掌：白色弹出 + 彩带雨 | `params.confetti_color` |
| `light_pillar` | 金色光柱从小人脚底冲顶 | `params.top_effect="fireworks"`, `fade_out_s`, `width` |
| `fireworks` | 光柱顶端烟花炸开 | 由 `light_pillar` 触发 |
| `heart_burst` | 粒子变爱心向外扩散 | `params.spread_radius`, `params.particle_form="heart"` |
| `screen_flash` | 全屏闪白一帧 | `params.follow_up`, `params.pre_darken_ms` |
| `particle_explode` | 500 颗粒子向外爆射 | `params.particle_count` |
| `ripple` | 从小人位置向外扩散的圆环 | `params.rings`, `params.origin` |
| `particle_scatter` | 粒子被震散后缓慢聚回 | `params.regather_s` |
| `crowd_cheer` | 彩带雨 + 颜色闪烁 | `params.confetti_color` |

所有特效 **`duration_ms`** 之后自动结束，Unity 不需要手动清理。

---

### 4-6  字幕气泡（`subtitle`，Layer 5）

- 最多 20 个字（LLM 回复的前 20 字）
- 以**手写体粒子**从小人嘴边浮出 → 飘 `subtitle_duration_ms` 毫秒 → 散开消失
- TTS 同步播放，字幕和语音一起出现
- 空字符串时不显示气泡

---

## 五、完整交互时序

```
Unity                          Python 后端
  |                                |
  |--- song_context -------------->|  切歌
  |<-- song_ready (+ scene) -------|  开场氛围，小人 idle
  |                                |
  |--- user_signal (touch=heart) ->|  用户比心
  |<-- ack (instant_effect) -------|  ★ <100ms，立刻播 heart_burst
  |<-- agent_response (+ scene) ---|  ~1s，小人 heart_pose + love 表情 + warm 主题
  |<-- tts_chunk × N --------------|  语音分块流式
  |<-- tts_done -------------------|
  |                                |
  |--- user_signal (pose=arms_up) ->|  用户举手，副歌
  |<-- ack (instant_effect) --------|  ★ <100ms，立刻播 light_pillar
  |<-- agent_response (+ scene) ----|  burst 主题，dance_fast，500 粒子
  |<-- tts_chunk × N --------------|
  |<-- tts_done -------------------|
  |                                |
  |--- song_end ------------------>|  歌曲结束
  |<-- emotion_portrait -----------|  情绪画像数据
```

---

## 六、环境变量（部署时配置）

```bash
# StepFun（ASR + TTS）
STEP_API_KEY=your_key
STEP_LLM_MODEL=step-2-mini
STEP_ASR_MODEL=stepaudio-2.5-asr-stream
STEP_TTS_MODEL=step-tts-mini
STEP_TTS_VOICE_ID=cixingnansheng

# 或切换 OpenAI LLM（ASR/TTS 仍用 StepFun）
KTV_LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini

# 服务器
KTV_WS_HOST=127.0.0.1
KTV_WS_PORT=8766
```

**无 API Key 时后端正常启动**，LLM/ASR/TTS 降级为规则引擎，`scene` 指令照常发出。

---

## 七、启动

```bash
pip install -r ktv_backend/requirements.txt
cd /path/to/project_root
python -m ktv_backend.server --debug
```

---

## 八、快速验证（无 Unity）

```bash
# 另开终端
python ktv_backend/tools/smoke_test_client.py
```

输出中能看到 `hello` → `ack + instant_effect` → `agent_response + scene` → `tts_done` 的完整链路。
