"""
SceneDirector — stateless builder that converts KTV context into
rich Unity visual directives (SceneDirective / InstantEffect / EmotionPortrait).

Design rules implemented here (from PDF "AI情绪可视化陪伴系统"):

Theme selection:
  BPM ≥ 140 + high energy          → cyber
  BPM ≥ 126 + high energy          → burst   (chorus / fast song)
  medium energy OR BPM 95-125      → warm    (pop / standard KTV)
  low energy + melancholy/tender   → calm    (ballad / intro)

Theme transition timing:
  Normal state change              → 1.5 s lerp  (section 8)
  Chorus burst / give_me_5         → 0.5 s snap
  Song open                        → 2.0 s ease-in

Instant effects (section 3 input→visual table):
  arms_up   → gold light pillar + fireworks at top
  give_me_5 → screen flash white (50ms) → crowd_cheer confetti
  heart     → particles morph into hearts
  jumping   → ripple ring from character
  voice     → subtle ripple (always-on for presence feedback)

  chorus keywords → screen_flash → particle_explode 500 pcs
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .directives import (
    EFFECT_CROWD_CHEER,
    EFFECT_FIREWORKS,
    EFFECT_GIVE_ME_5_FLASH,
    EFFECT_HEART_BURST,
    EFFECT_LIGHT_PILLAR,
    EFFECT_PARTICLE_EXPLODE,
    EFFECT_RIPPLE,
    EFFECT_SCATTER,
    EFFECT_SCREEN_FLASH,
    PARTICLE_BEAT,
    PARTICLE_DATA_STREAM,
    PARTICLE_FLOATING,
    THEME_PALETTES,
    BackgroundLayer,
    CharacterLayer,
    EmotionPortrait,
    InstantEffect,
    KeyEvent,
    ParticleLayer,
    SceneDirective,
)
from .music import MusicAnalysis
from .protocol import UserSignal

# ---------------------------------------------------------------------------
# Chorus trigger keywords (section 5: "副歌起: 单帧生成500+粒子")
# ---------------------------------------------------------------------------
_CHORUS_KEYWORDS = frozenset(("副歌", "高潮", "chorus", "燥起来", "爆发", "高音", "冲", "一起冲"))

# ---------------------------------------------------------------------------
# Touch → instant effect factories
# ---------------------------------------------------------------------------
def _fx_give_me_5(palette: Dict[str, str]) -> InstantEffect:
    return InstantEffect(
        effect_type=EFFECT_GIVE_ME_5_FLASH,
        color="#FFFFFF",
        duration_ms=120,
        intensity=1.0,
        params={"follow_up": EFFECT_CROWD_CHEER, "confetti_color": palette.get("accent", "#FFD93D")},
    )


def _fx_heart(palette: Dict[str, str]) -> InstantEffect:
    return InstantEffect(
        effect_type=EFFECT_HEART_BURST,
        color="#FF6B6B",
        duration_ms=1400,
        intensity=0.9,
        params={"particle_form": "heart", "spread_radius": 0.6},
    )


def _fx_fist_bump(palette: Dict[str, str]) -> InstantEffect:
    return InstantEffect(
        effect_type=EFFECT_SCREEN_FLASH,
        color=palette.get("accent", "#FFD93D"),
        duration_ms=150,
        intensity=0.75,
    )


_TOUCH_EFFECT_MAP = {
    "give_me_5": _fx_give_me_5,
    "heart":     _fx_heart,
    "fist_bump": _fx_fist_bump,
}

# ---------------------------------------------------------------------------
# Pose → instant effect factories
# ---------------------------------------------------------------------------
def _fx_arms_up(palette: Dict[str, str]) -> InstantEffect:
    """Gold light pillar with fireworks at the top (section 10 demo ④)."""
    return InstantEffect(
        effect_type=EFFECT_LIGHT_PILLAR,
        color="#FFD700",
        duration_ms=1500,
        intensity=1.0,
        params={
            "top_effect":   EFFECT_FIREWORKS,
            "top_color":    palette.get("accent", "#FFD700"),
            "width":        0.08,       # pillar width as fraction of screen
            "fade_out_s":   1.2,
        },
    )


def _fx_jumping(palette: Dict[str, str]) -> InstantEffect:
    return InstantEffect(
        effect_type=EFFECT_RIPPLE,
        color=palette.get("accent", "#FFFFFF"),
        duration_ms=700,
        intensity=0.65,
        params={"origin": "feet", "rings": 2},
    )


def _fx_scream(palette: Dict[str, str]) -> InstantEffect:
    """High-energy scream → particles scatter then regather (section 5)."""
    return InstantEffect(
        effect_type=EFFECT_SCATTER,
        color=palette.get("primary", "#FF006E"),
        duration_ms=1000,
        intensity=0.85,
        params={"regather_s": 0.8},
    )


_POSE_EFFECT_MAP = {
    "arms_up": _fx_arms_up,
    "jumping": _fx_jumping,
    "scream":  _fx_scream,
}

# ---------------------------------------------------------------------------
# SceneDirector
# ---------------------------------------------------------------------------

class SceneDirector:
    """
    Stateless builder — create once on KtvBrain, call freely from any coroutine.
    All methods are synchronous (no I/O) so they never block the event loop.
    """

    # ------------------------------------------------------------------
    # Primary scene build (called after LLM response is ready)
    # ------------------------------------------------------------------

    def build_scene(
        self,
        music: MusicAnalysis,
        signal: UserSignal,
        action: str,
        expression: str,
        reply_text: str,
    ) -> SceneDirective:
        """Build a full SceneDirective from all available context.

        This drives layers 1–4 for the agent_response message.
        """
        special = self._detect_special_event(signal, music, action)
        theme = self._select_theme(music, action, special)
        palette = THEME_PALETTES[theme]

        is_chorus = special == "chorus_burst"
        transition_s = 0.5 if is_chorus else 1.5

        character = self._build_character(action, expression, music, theme)
        particles = self._build_particles(theme, music, special)
        background = self._build_background(theme, music.energy, is_chorus)
        instant_effects = self._collect_instant_effects(signal, palette, special)

        # Trim subtitle to 20 chars (PDF section 4: "一次最多10个字，多了换两条")
        subtitle = (reply_text or "").strip()[:20]

        return SceneDirective(
            theme=theme,
            theme_transition_s=transition_s,
            character=character,
            particles=particles,
            background=background,
            instant_effects=instant_effects,
            subtitle=subtitle,
            subtitle_duration_ms=2200 if len(subtitle) > 10 else 1800,
        )

    # ------------------------------------------------------------------
    # Instant-effect-only build (called from ack, before LLM returns)
    # ------------------------------------------------------------------

    def build_instant_effect_for_signal(
        self,
        signal: UserSignal,
        current_theme: str = "warm",
    ) -> Optional[InstantEffect]:
        """Rule-based instant effect, must resolve in <100 ms (section 3).

        Called as soon as a user_signal is received, before any LLM call.
        Uses current_theme from the session so the effect colour matches
        the live palette.
        """
        palette = THEME_PALETTES.get(current_theme, THEME_PALETTES["warm"])
        touch = (signal.touch_event or "").lower()
        pose  = (signal.pose_label  or "").lower()

        if touch in _TOUCH_EFFECT_MAP:
            return _TOUCH_EFFECT_MAP[touch](palette)
        if pose in _POSE_EFFECT_MAP:
            return _POSE_EFFECT_MAP[pose](palette)

        # Voice / text detected → subtle presence ripple
        if signal.audio.has_audio() or signal.user_text:
            return InstantEffect(
                effect_type=EFFECT_RIPPLE,
                color=palette.get("accent", "#A084DC"),
                duration_ms=500,
                intensity=0.35,
                params={"origin": "character", "rings": 1},
            )
        return None

    # ------------------------------------------------------------------
    # Song open scene (called from song_ready message)
    # ------------------------------------------------------------------

    def build_song_open_scene(
        self,
        music: MusicAnalysis,
        song_title: str = "",
    ) -> SceneDirective:
        """Opening atmosphere when a song is prewarmed (section 10 demo ①②).

        Starts in idle / calm state so the first verse feels like it grows
        into the scene rather than starting at full intensity.
        """
        theme = self._select_theme_from_music(music)
        palette = THEME_PALETTES[theme]

        # Open with idle breathing (section 10: "轻轻呼吸")
        character = CharacterLayer(
            action="idle",
            expression="calm",
            beat_sync=False,
            intensity=0.45,
            transition_s=1.2,
            rim_light_color=palette["rim_light"],
            rim_light_intensity=0.45,
        )
        particles = ParticleLayer(
            form=PARTICLE_FLOATING if theme == "calm" else PARTICLE_BEAT,
            density=0.25,
            bpm=music.bpm,
            color_primary=palette["particle"],
            color_accent=palette["accent"],
        )
        background = BackgroundLayer(
            grad_start=palette["bg_start"],
            grad_end=palette["bg_end"],
            brightness=0.45,
            fluid_speed=0.18,
            transition_s=2.0,
        )

        label = (song_title or "这首歌")[:6]
        subtitle = "准备好了吗，{0}要开始了。".format(label)[:20]

        return SceneDirective(
            theme=theme,
            theme_transition_s=2.0,
            character=character,
            particles=particles,
            background=background,
            instant_effects=[],
            subtitle=subtitle,
            subtitle_duration_ms=2600,
        )

    # ------------------------------------------------------------------
    # End-of-song emotion portrait
    # ------------------------------------------------------------------

    def build_emotion_portrait(
        self,
        session: object,
        music: MusicAnalysis,
    ) -> EmotionPortrait:
        """Compose the end-of-song emotion portrait (section 6 + demo ⑤).

        `session` is a SessionState-like object with optional attributes:
          energy_samples  : List[float]
          key_events      : List[dict]  (each: {event_type, label, elapsed_s})
          current_song_key, _last_song_title, _last_song_artist
        """
        theme = self._select_theme_from_music(music)
        palette = THEME_PALETTES[theme]

        energy_curve = list(getattr(session, "energy_samples", None) or [])
        if not energy_curve:
            # Fallback: single flat sample from music energy
            default_e = {"high": 0.85, "medium": 0.55, "low": 0.3}.get(music.energy, 0.5)
            energy_curve = [default_e]

        raw_events = getattr(session, "key_events", None) or []
        key_events: List[KeyEvent] = []
        for ev in raw_events:
            try:
                key_events.append(KeyEvent(**ev))
            except TypeError:
                pass

        caption_by_theme = {
            "burst": "这首歌点燃了整个包厢。",
            "warm":  "这是你今晚最暖的时刻。",
            "calm":  "这是你刚才唱出来的颜色。",
            "cyber": "你的声音变成了数据流。",
        }

        return EmotionPortrait(
            theme=theme,
            palette=dict(palette),
            energy_curve=energy_curve,
            key_events=key_events,
            caption=caption_by_theme.get(theme, "这是你刚才唱出来的颜色。"),
            qr_code_url=getattr(session, "portrait_qr_url", ""),
            song_title=getattr(session, "_last_song_title", ""),
            song_artist=getattr(session, "_last_song_artist", ""),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_theme(
        self,
        music: MusicAnalysis,
        action: str,
        special: str,
    ) -> str:
        # Chorus / explicit high-energy action forces burst or cyber
        if special == "chorus_burst" or action in {"dance_fast", "cheer", "clap"}:
            bpm = music.bpm or 120
            return "cyber" if bpm >= 140 else "burst"
        return self._select_theme_from_music(music)

    def _select_theme_from_music(self, music: MusicAnalysis) -> str:
        bpm = music.bpm or 104
        if music.energy == "high":
            return "cyber" if bpm >= 140 else "burst"
        if music.energy == "medium":
            return "warm"
        # low energy
        if music.mood in {"melancholy", "tender", "neutral"}:
            return "calm"
        return "warm"

    def _detect_special_event(
        self,
        signal: UserSignal,
        music: MusicAnalysis,
        action: str,
    ) -> str:
        text  = (signal.user_text   or "").lower()
        touch = (signal.touch_event or "").lower()
        pose  = (signal.pose_label  or "").lower()

        # Chorus triggers (section 5: "副歌起: 单帧生成500+粒子向外抛射")
        if any(kw in text for kw in _CHORUS_KEYWORDS):
            return "chorus_burst"
        if pose == "arms_up" and music.energy == "high":
            return "chorus_burst"
        if action in {"dance_fast", "cheer"} and music.energy == "high":
            return "chorus_burst"

        if touch == "heart":
            return "heart_form"

        return ""

    def _build_character(
        self,
        action: str,
        expression: str,
        music: MusicAnalysis,
        theme: str,
    ) -> CharacterLayer:
        palette = THEME_PALETTES[theme]

        # Beat-sync animations (jump on each downbeat)
        beat_sync_actions = {"dance_fast", "cheer", "clap", "sing_along", "dance_groove"}
        beat_sync = action in beat_sync_actions and music.energy in {"high", "medium"}

        intensity_by_theme: Dict[str, float] = {
            "burst": 1.0,
            "cyber": 0.95,
            "warm":  0.72,
            "calm":  0.50,
        }
        intensity = intensity_by_theme.get(theme, 0.7)

        # Faster blend-in for high-energy transitions
        transition_s = 0.15 if beat_sync else 0.35

        # Rim light intensity by emotional state
        rim_intensity_by_expr: Dict[str, float] = {
            "excited":    1.00,
            "love":       0.90,
            "playful":    0.85,
            "surprised":  0.80,
            "cool":       0.70,
            "supportive": 0.65,
            "focused":    0.60,
            "calm":       0.50,
            "sleepy":     0.35,
        }
        rim_intensity = rim_intensity_by_expr.get(expression, 0.65)

        return CharacterLayer(
            action=action,
            expression=expression,
            beat_sync=beat_sync,
            intensity=intensity,
            transition_s=transition_s,
            rim_light_color=palette["rim_light"],
            rim_light_intensity=rim_intensity,
        )

    def _build_particles(
        self,
        theme: str,
        music: MusicAnalysis,
        special: str,
    ) -> ParticleLayer:
        palette = THEME_PALETTES[theme]

        form_by_theme = {
            "calm":  PARTICLE_FLOATING,
            "warm":  PARTICLE_BEAT,
            "burst": PARTICLE_BEAT,
            "cyber": PARTICLE_DATA_STREAM,
        }
        density_by_theme: Dict[str, float] = {
            "calm":  0.22,
            "warm":  0.52,
            "burst": 0.82,
            "cyber": 0.70,
        }

        form    = form_by_theme.get(theme, PARTICLE_BEAT)
        density = density_by_theme.get(theme, 0.5)
        count   = 0

        if special == "chorus_burst":
            density = 1.0
            count   = 500
        elif special == "heart_form":
            density = 0.75
        elif special == "scatter":
            density = 0.90

        return ParticleLayer(
            form=form,
            density=density,
            bpm=music.bpm,
            color_primary=palette["particle"],
            color_accent=palette["accent"],
            special_event=special,
            particle_count_override=count,
        )

    def _build_background(
        self,
        theme: str,
        energy: str,
        is_chorus: bool,
    ) -> BackgroundLayer:
        palette = THEME_PALETTES[theme]

        base_brightness: Dict[str, float] = {
            "burst": 0.68,
            "cyber": 0.62,
            "warm":  0.52,
            "calm":  0.42,
        }
        brightness = base_brightness.get(theme, 0.55)
        if is_chorus:
            # Darken one frame then brighten (section 10 demo ③: "蓄力")
            brightness = min(brightness + 0.12, 0.85)

        fluid_by_theme: Dict[str, float] = {
            "burst": 0.78,
            "cyber": 0.92,
            "warm":  0.38,
            "calm":  0.14,
        }
        fluid_speed = fluid_by_theme.get(theme, 0.4)
        if energy == "high":
            fluid_speed = min(fluid_speed * 1.25, 1.0)

        return BackgroundLayer(
            grad_start=palette["bg_start"],
            grad_end=palette["bg_end"],
            brightness=brightness,
            fluid_speed=fluid_speed,
            transition_s=0.45 if is_chorus else 1.5,
        )

    def _collect_instant_effects(
        self,
        signal: UserSignal,
        palette: Dict[str, str],
        special: str,
    ) -> List[InstantEffect]:
        effects: List[InstantEffect] = []

        touch = (signal.touch_event or "").lower()
        pose  = (signal.pose_label  or "").lower()

        if touch in _TOUCH_EFFECT_MAP:
            effects.append(_TOUCH_EFFECT_MAP[touch](palette))
        if pose in _POSE_EFFECT_MAP:
            effects.append(_POSE_EFFECT_MAP[pose](palette))

        # Chorus burst: screen pre-darken + massive particle explosion (demo ③)
        if special == "chorus_burst":
            # Insert at front so Unity fires it first
            effects.insert(
                0,
                InstantEffect(
                    effect_type=EFFECT_SCREEN_FLASH,
                    color="#FFFFFF",
                    duration_ms=50,
                    intensity=1.0,
                    params={
                        "follow_up":     EFFECT_PARTICLE_EXPLODE,
                        "particle_count": 500,
                        "pre_darken_ms":  80,   # "蓄力" micro-darkness before pop
                    },
                ),
            )

        return effects
