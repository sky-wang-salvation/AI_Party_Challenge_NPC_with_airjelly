"""
Unity visual directive system.

Defines all data structures for driving the 5-layer visual scene described in
"AI情绪可视化陪伴系统 - 呈现效果设计":

  Layer 1: Background     — color gradients + slow fluid
  Layer 2: Particles      — rhythm particle system (3 forms)
  Layer 3: Character 小人  — VRM animation + rim light
  Layer 4: Instant FX     — one-shot effects (<100 ms response)
  Layer 5: UI             — subtitle bubbles, QR code (Unity-owned)

Python → Unity message types produced by this system:

  agent_response  — includes ``scene`` sub-object (SceneDirective)
  ack             — includes ``instant_effect`` for touch/pose events
  song_ready      — includes ``scene`` for the opening atmosphere
  emotion_portrait — end-of-song portrait (EmotionPortrait)
  proactive_nudge — already existed, unchanged
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Theme palettes  (4 visual themes, all colors as #RRGGBB hex strings)
# ---------------------------------------------------------------------------
# Design reference from PDF section 2 + section 8
THEME_PALETTES: Dict[str, Dict[str, str]] = {
    # 🌙 calm — slow songs, intro, tender moments
    "calm": {
        "primary":   "#2D3561",   # deep blue
        "accent":    "#A084DC",   # soft purple
        "highlight": "#E8F0FF",   # moonlight white
        "bg_start":  "#0A0E27",
        "bg_end":    "#1A1F4A",
        "rim_light": "#A084DC",
        "particle":  "#E8F0FF",
    },
    # 🌅 warm — pop / mid-tempo, comfortable KTV vibe
    "warm": {
        "primary":   "#FF6B6B",   # warm pink
        "accent":    "#FFD93D",   # gold yellow
        "highlight": "#FFFFFF",
        "bg_start":  "#3D1F1F",
        "bg_end":    "#6B2E2E",
        "rim_light": "#FF6B6B",
        "particle":  "#FFD93D",
    },
    # 🔥 burst — chorus / climax / fast songs
    "burst": {
        "primary":   "#FF006E",   # fluorescent pink
        "accent":    "#00F5FF",   # electric blue
        "highlight": "#FFFF00",   # acid yellow
        "bg_start":  "#1A0033",
        "bg_end":    "#4D0080",
        "rim_light": "#FF006E",
        "particle":  "#00F5FF",
    },
    # 🌐 cyber — electronic / DJ / BPM ≥ 140
    "cyber": {
        "primary":   "#00FFC6",   # cyan-green
        "accent":    "#B026FF",   # electric violet
        "highlight": "#FF003C",   # alert red
        "bg_start":  "#000000",
        "bg_end":    "#001A33",
        "rim_light": "#00FFC6",
        "particle":  "#B026FF",
    },
}

# ---------------------------------------------------------------------------
# Particle form constants (Layer 2)
# ---------------------------------------------------------------------------
PARTICLE_FLOATING    = "floating"     # calm: sparse white dots drifting up
PARTICLE_BEAT        = "beat"         # warm/burst: burst on every downbeat
PARTICLE_DATA_STREAM = "data_stream"  # cyber: continuous flow, speed ∝ BPM

# ---------------------------------------------------------------------------
# Instant effect type constants (Layer 4, all <100 ms on Unity side)
# ---------------------------------------------------------------------------
EFFECT_SCREEN_FLASH     = "screen_flash"      # full-screen white flash frame
EFFECT_LIGHT_PILLAR     = "light_pillar"      # gold column shooting to top
EFFECT_HEART_BURST      = "heart_burst"       # particles morph into hearts
EFFECT_PARTICLE_EXPLODE = "particle_explode"  # 500 particles outward (chorus)
EFFECT_FIREWORKS        = "fireworks"         # firework burst at pillar tip
EFFECT_RIPPLE           = "ripple"            # ring ripple from character
EFFECT_SCATTER          = "particle_scatter"  # particles shocked-scatter (scream)
EFFECT_CROWD_CHEER      = "crowd_cheer"       # confetti rain + color flash
EFFECT_GIVE_ME_5_FLASH  = "give_me_5_flash"   # high-five: white pop + confetti

# ---------------------------------------------------------------------------
# Data classes — Layer 3: Character
# ---------------------------------------------------------------------------

@dataclass
class CharacterLayer:
    """Controls the VRM 小人 animation state (Layer 3).

    Fields sent to Unity so the animator can set the correct state:
    - action / expression: directly map to animator parameter names
    - beat_sync: if True, Unity pulses/jumps the character on each downbeat
    - intensity: 0.0–1.0 scale for animation energy (mapped to blend-tree weight)
    - transition_s: cross-fade duration from previous animation state
    - rim_light_color / rim_light_intensity: edge glow so 小人 pops against
      any background (PDF section 4: "轮廓光")
    """
    action: str
    expression: str
    beat_sync: bool = False
    intensity: float = 0.7
    transition_s: float = 0.3
    rim_light_color: str = "#FFFFFF"
    rim_light_intensity: float = 0.6

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Data classes — Layer 2: Particles
# ---------------------------------------------------------------------------

@dataclass
class ParticleLayer:
    """Controls the rhythm particle system (Layer 2).

    form selects which of the 3 PDF particle modes Unity activates:
      PARTICLE_FLOATING    – calm: sparse, self-lit white dots drifting upward
      PARTICLE_BEAT        – warm/burst: wave of particles from character on
                             each downbeat, shrink on off-beats
      PARTICLE_DATA_STREAM – cyber: directional flow (left→right / bottom→top),
                             speed ∝ BPM, colour spread across spectrum

    special_event triggers one-shot burst states:
      "chorus_burst"  – 500 particles explode outward (section 5)
      "heart_form"    – all particles morph into heart shapes
      "scatter"       – particles violently scatter (simulates scream energy)
      ""              – normal continuous emission
    """
    form: str
    density: float                  # 0.0–1.0 emission intensity
    bpm: Optional[int] = None       # drives particle rate / stream speed
    color_primary: str = "#FFFFFF"
    color_accent: str = "#AAAAFF"
    special_event: str = ""
    particle_count_override: int = 0  # 0 = auto from density

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Data classes — Layer 1: Background
# ---------------------------------------------------------------------------

@dataclass
class BackgroundLayer:
    """Controls the background gradient + fluid simulation (Layer 1).

    PDF visual law: keep ≥30 % screen dark. We enforce this by capping
    brightness at 0.85 everywhere.

    transition_s: slow cross-fade (1-3 s for background per PDF guidelines).
    fluid_speed: 0.1 (very slow, calm) → 1.0 (fast, cyber/burst).
    """
    grad_start: str
    grad_end: str
    brightness: float = 0.55        # 0.0–0.85  (never go full bright)
    fluid_speed: float = 0.3        # slow=0.1, fast=1.0
    transition_s: float = 1.5       # lerp time on theme change

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Data classes — Layer 4: Instant effects
# ---------------------------------------------------------------------------

@dataclass
class InstantEffect:
    """A one-shot visual event that Unity plays and discards.

    Must resolve in <100 ms per PDF section 3 requirements.

    params dict is effect-type-specific:
      light_pillar  : {"top_effect": "fireworks", "top_color": "#FFD700"}
      screen_flash  : {"follow_up": "particle_explode", "particle_count": 500}
      ripple        : {"origin": "character"}
    """
    effect_type: str
    color: str = "#FFFFFF"
    duration_ms: int = 300
    intensity: float = 1.0
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "effect_type": self.effect_type,
            "color": self.color,
            "duration_ms": self.duration_ms,
            "intensity": self.intensity,
        }
        if self.params:
            d["params"] = self.params
        return d


# ---------------------------------------------------------------------------
# Combined scene directive
# ---------------------------------------------------------------------------

@dataclass
class SceneDirective:
    """Complete visual state for all layers, sent with every agent_response.

    Unity interprets this as a target state and transitions smoothly:
    - Background lerps in transition_s (Layer 1)
    - Particles switch form / density (Layer 2)
    - Character blends into new action/expression (Layer 3, transition_s)
    - instant_effects fire immediately on receipt (Layer 4)
    - subtitle bubble appears then fades (Layer 5)

    theme_transition_s: how fast to cross-fade colour palette (1.5 s default
    per PDF section 8, 0.5 s for chorus bursts).
    """
    theme: str                                          # calm/warm/burst/cyber
    theme_transition_s: float                           # colour-lerp duration
    character: CharacterLayer
    particles: ParticleLayer
    background: BackgroundLayer
    instant_effects: List[InstantEffect] = field(default_factory=list)
    subtitle: str = ""              # hand-written particle text, max ~20 chars
    subtitle_duration_ms: int = 2000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "theme": self.theme,
            "theme_transition_s": self.theme_transition_s,
            "character": self.character.to_dict(),
            "particles": self.particles.to_dict(),
            "background": self.background.to_dict(),
            "instant_effects": [e.to_dict() for e in self.instant_effects],
            "subtitle": self.subtitle,
            "subtitle_duration_ms": self.subtitle_duration_ms,
        }


# ---------------------------------------------------------------------------
# Emotion portrait (end-of-song, section 6)
# ---------------------------------------------------------------------------

@dataclass
class KeyEvent:
    """A timestamped notable event recorded during the session."""
    event_type: str     # "chorus_start" | "arms_up" | "heart" | "give_me_5" | "voice_peak"
    label: str          # human-readable, displayed in portrait
    elapsed_s: float    # seconds since session start

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EmotionPortrait:
    """End-of-song emotion portrait data, sent as 'emotion_portrait' message.

    Unity uses this to:
    1. Compose the abstract art image (60% screen) using palette + energy_curve
    2. Render the energy bar chart and key_events timeline
    3. Show the 小人's caption bubble
    4. Display the QR code (content served by a separate H5 service)

    energy_curve: list of 0.0–1.0 floats, one per ~5 s of song, representing
    the user's emotional energy (derived from BPM, pose, and touch events).
    """
    theme: str
    palette: Dict[str, str]
    energy_curve: List[float]
    key_events: List[KeyEvent]
    caption: str = "这是你刚才唱出来的颜色。"
    qr_code_url: str = ""
    song_title: str = ""
    song_artist: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "theme": self.theme,
            "palette": self.palette,
            "energy_curve": self.energy_curve,
            "key_events": [e.to_dict() for e in self.key_events],
            "caption": self.caption,
            "qr_code_url": self.qr_code_url,
            "song_title": self.song_title,
            "song_artist": self.song_artist,
        }
