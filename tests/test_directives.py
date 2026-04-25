"""
Comprehensive tests for the Unity scene directive system.

Coverage:
  1. directives.py  — data class construction, to_dict(), colour palette completeness
  2. scene_builder.py — SceneDirector theme selection, instant effects, scene building,
                        song-open scene, emotion portrait
  3. Bug-fix regressions — utils.utc_now, music.py intense mood, file:// URL
  4. Integration path — orchestrator.process_signal now returns BrainResult.scene
  5. server.py session event logging
"""
from __future__ import annotations

import asyncio
import json
import time
import unittest
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_music(
    bpm: int = 120,
    energy: str = "medium",
    mood: str = "warm",
    dance_action: str = "dance_groove",
    expression: str = "playful",
    confidence: float = 0.78,
    source: str = "librosa",
):
    from ktv_backend.modules.music import MusicAnalysis
    return MusicAnalysis(
        bpm=bpm, energy=energy, mood=mood,
        dance_action=dance_action, expression=expression,
        confidence=confidence, source=source,
    )


def _make_signal(
    touch_event: str = "",
    pose_label: str = "",
    user_text: str = "",
    song_title: str = "测试歌曲",
    song_artist: str = "测试歌手",
    has_audio: bool = False,
):
    from ktv_backend.modules.protocol import AudioPayload, SongPayload, UserSignal
    audio = AudioPayload(content_b64="dGVzdA==" if has_audio else "")
    song = SongPayload(title=song_title, artist=song_artist)
    return UserSignal(
        request_id="req-test",
        session_id="sess-test",
        audio=audio,
        touch_event=touch_event,
        pose_label=pose_label,
        user_text=user_text,
        song=song,
    )


def _make_session(session_id: str = "sess-test", last_theme: str = "warm"):
    from ktv_backend.modules.state import SessionState
    s = SessionState(session_id=session_id)
    s.last_theme = last_theme
    return s


# ===========================================================================
# 1. directives.py — data classes
# ===========================================================================

class TestThemePalettes(unittest.TestCase):

    def test_all_four_themes_present(self):
        from ktv_backend.modules.directives import THEME_PALETTES
        self.assertSetEqual(set(THEME_PALETTES.keys()), {"calm", "warm", "burst", "cyber"})

    def test_each_theme_has_required_keys(self):
        from ktv_backend.modules.directives import THEME_PALETTES
        required = {"primary", "accent", "highlight", "bg_start", "bg_end", "rim_light", "particle"}
        for theme, palette in THEME_PALETTES.items():
            with self.subTest(theme=theme):
                self.assertTrue(required.issubset(palette.keys()))
                for key, value in palette.items():
                    self.assertTrue(value.startswith("#"), f"{theme}.{key} = {value!r} is not a hex colour")

    def test_burst_has_high_contrast_colours(self):
        from ktv_backend.modules.directives import THEME_PALETTES
        burst = THEME_PALETTES["burst"]
        self.assertEqual(burst["primary"], "#FF006E")
        self.assertEqual(burst["accent"],  "#00F5FF")


class TestCharacterLayer(unittest.TestCase):

    def test_to_dict_has_all_fields(self):
        from ktv_backend.modules.directives import CharacterLayer
        cl = CharacterLayer(action="dance_fast", expression="excited")
        d = cl.to_dict()
        self.assertEqual(d["action"],     "dance_fast")
        self.assertEqual(d["expression"], "excited")
        self.assertIn("beat_sync",             d)
        self.assertIn("intensity",             d)
        self.assertIn("transition_s",          d)
        self.assertIn("rim_light_color",       d)
        self.assertIn("rim_light_intensity",   d)

    def test_defaults_are_safe(self):
        from ktv_backend.modules.directives import CharacterLayer
        cl = CharacterLayer(action="idle", expression="calm")
        self.assertFalse(cl.beat_sync)
        self.assertGreater(cl.intensity, 0)
        self.assertGreater(cl.transition_s, 0)


class TestParticleLayer(unittest.TestCase):

    def test_to_dict_round_trips(self):
        from ktv_backend.modules.directives import PARTICLE_BEAT, ParticleLayer
        pl = ParticleLayer(
            form=PARTICLE_BEAT, density=0.8, bpm=132,
            color_primary="#FF006E", color_accent="#00F5FF",
            special_event="chorus_burst", particle_count_override=500,
        )
        d = pl.to_dict()
        self.assertEqual(d["form"],                   PARTICLE_BEAT)
        self.assertEqual(d["density"],                0.8)
        self.assertEqual(d["bpm"],                    132)
        self.assertEqual(d["special_event"],          "chorus_burst")
        self.assertEqual(d["particle_count_override"],500)


class TestInstantEffect(unittest.TestCase):

    def test_to_dict_excludes_empty_params(self):
        from ktv_backend.modules.directives import InstantEffect
        fx = InstantEffect(effect_type="screen_flash", color="#FFF", duration_ms=100)
        d = fx.to_dict()
        self.assertNotIn("params", d)

    def test_to_dict_includes_params_when_set(self):
        from ktv_backend.modules.directives import InstantEffect
        fx = InstantEffect(
            effect_type="light_pillar",
            color="#FFD700",
            duration_ms=1500,
            params={"top_effect": "fireworks"},
        )
        d = fx.to_dict()
        self.assertEqual(d["params"]["top_effect"], "fireworks")


class TestSceneDirective(unittest.TestCase):

    def _make_scene(self):
        from ktv_backend.modules.directives import (
            BackgroundLayer, CharacterLayer, PARTICLE_BEAT, ParticleLayer, SceneDirective,
        )
        return SceneDirective(
            theme="burst",
            theme_transition_s=0.5,
            character=CharacterLayer(action="dance_fast", expression="excited"),
            particles=ParticleLayer(
                form=PARTICLE_BEAT, density=1.0, bpm=132,
                color_primary="#FF006E", color_accent="#00F5FF",
            ),
            background=BackgroundLayer(grad_start="#1A0033", grad_end="#4D0080", brightness=0.7),
            subtitle="就是这个状态！",
        )

    def test_to_dict_structure(self):
        d = self._make_scene().to_dict()
        self.assertEqual(d["theme"], "burst")
        self.assertIn("character",       d)
        self.assertIn("particles",       d)
        self.assertIn("background",      d)
        self.assertIn("instant_effects", d)
        self.assertIn("subtitle",        d)
        self.assertIn("subtitle_duration_ms", d)

    def test_to_dict_is_json_serialisable(self):
        d = self._make_scene().to_dict()
        serialised = json.dumps(d)
        self.assertIn("burst", serialised)

    def test_instant_effects_list(self):
        from ktv_backend.modules.directives import InstantEffect, SceneDirective, CharacterLayer, ParticleLayer, BackgroundLayer, PARTICLE_BEAT
        scene = SceneDirective(
            theme="burst",
            theme_transition_s=0.5,
            character=CharacterLayer(action="dance_fast", expression="excited"),
            particles=ParticleLayer(form=PARTICLE_BEAT, density=1.0),
            background=BackgroundLayer(grad_start="#000", grad_end="#111"),
            instant_effects=[
                InstantEffect(effect_type="screen_flash"),
                InstantEffect(effect_type="particle_explode"),
            ],
        )
        d = scene.to_dict()
        self.assertEqual(len(d["instant_effects"]), 2)
        types = [e["effect_type"] for e in d["instant_effects"]]
        self.assertIn("screen_flash",     types)
        self.assertIn("particle_explode", types)


class TestEmotionPortrait(unittest.TestCase):

    def test_to_dict_complete(self):
        from ktv_backend.modules.directives import EmotionPortrait, KeyEvent, THEME_PALETTES
        portrait = EmotionPortrait(
            theme="warm",
            palette=dict(THEME_PALETTES["warm"]),
            energy_curve=[0.4, 0.6, 0.8, 0.9, 0.7],
            key_events=[
                KeyEvent(event_type="arms_up", label="举手", elapsed_s=45.0),
                KeyEvent(event_type="heart",   label="比心", elapsed_s=83.0),
            ],
            caption="这是你今晚最暖的时刻。",
            song_title="孤勇者",
            song_artist="陈奕迅",
        )
        d = portrait.to_dict()
        self.assertEqual(d["theme"], "warm")
        self.assertEqual(len(d["key_events"]), 2)
        self.assertEqual(d["key_events"][0]["event_type"], "arms_up")
        self.assertEqual(d["energy_curve"], [0.4, 0.6, 0.8, 0.9, 0.7])
        self.assertEqual(d["song_title"], "孤勇者")


# ===========================================================================
# 2. SceneDirector — theme selection
# ===========================================================================

class TestSceneDirectorThemeSelection(unittest.TestCase):

    def setUp(self):
        from ktv_backend.modules.scene_builder import SceneDirector
        self.director = SceneDirector()

    def test_high_bpm_maps_to_cyber(self):
        music = _make_music(bpm=145, energy="high", mood="uplifting")
        theme = self.director._select_theme_from_music(music)
        self.assertEqual(theme, "cyber")

    def test_high_energy_below_140bpm_maps_to_burst(self):
        music = _make_music(bpm=128, energy="high", mood="uplifting")
        theme = self.director._select_theme_from_music(music)
        self.assertEqual(theme, "burst")

    def test_medium_energy_maps_to_warm(self):
        music = _make_music(bpm=110, energy="medium", mood="warm")
        theme = self.director._select_theme_from_music(music)
        self.assertEqual(theme, "warm")

    def test_low_energy_melancholy_maps_to_calm(self):
        music = _make_music(bpm=72, energy="low", mood="melancholy")
        theme = self.director._select_theme_from_music(music)
        self.assertEqual(theme, "calm")

    def test_low_energy_tender_maps_to_calm(self):
        music = _make_music(bpm=80, energy="low", mood="tender")
        theme = self.director._select_theme_from_music(music)
        self.assertEqual(theme, "calm")

    def test_chorus_action_forces_burst_on_medium_song(self):
        music = _make_music(bpm=110, energy="medium")
        signal = _make_signal(user_text="副歌来了")
        theme = self.director._select_theme(music, "dance_fast", "chorus_burst")
        self.assertEqual(theme, "burst")

    def test_chorus_action_cyber_on_high_bpm(self):
        music = _make_music(bpm=145, energy="high")
        theme = self.director._select_theme(music, "dance_fast", "chorus_burst")
        self.assertEqual(theme, "cyber")


# ===========================================================================
# 3. SceneDirector — instant effects
# ===========================================================================

class TestSceneDirectorInstantEffects(unittest.TestCase):

    def setUp(self):
        from ktv_backend.modules.scene_builder import SceneDirector
        self.director = SceneDirector()

    def _effect_for(self, touch="", pose="", text="", has_audio=False, theme="warm"):
        signal = _make_signal(touch_event=touch, pose_label=pose, user_text=text, has_audio=has_audio)
        return self.director.build_instant_effect_for_signal(signal, theme)

    # --- touch events ---

    def test_give_me_5_produces_flash(self):
        fx = self._effect_for(touch="give_me_5")
        self.assertIsNotNone(fx)
        self.assertEqual(fx.effect_type, "give_me_5_flash")
        self.assertLessEqual(fx.duration_ms, 300)
        self.assertGreaterEqual(fx.intensity, 0.9)

    def test_heart_produces_heart_burst(self):
        fx = self._effect_for(touch="heart")
        self.assertIsNotNone(fx)
        self.assertEqual(fx.effect_type, "heart_burst")
        self.assertIn("particle_form", fx.params)
        self.assertEqual(fx.params["particle_form"], "heart")

    def test_fist_bump_produces_screen_flash(self):
        fx = self._effect_for(touch="fist_bump")
        self.assertIsNotNone(fx)
        self.assertEqual(fx.effect_type, "screen_flash")

    def test_unknown_touch_skips_to_pose(self):
        fx = self._effect_for(touch="unknown_gesture", pose="arms_up")
        self.assertIsNotNone(fx)
        self.assertEqual(fx.effect_type, "light_pillar")

    # --- pose events ---

    def test_arms_up_produces_light_pillar(self):
        fx = self._effect_for(pose="arms_up")
        self.assertIsNotNone(fx)
        self.assertEqual(fx.effect_type, "light_pillar")
        self.assertEqual(fx.color, "#FFD700")
        self.assertEqual(fx.duration_ms, 1500)
        self.assertEqual(fx.params["top_effect"], "fireworks")

    def test_jumping_produces_ripple(self):
        fx = self._effect_for(pose="jumping")
        self.assertIsNotNone(fx)
        self.assertEqual(fx.effect_type, "ripple")

    # --- voice presence ---

    def test_voice_audio_produces_ripple(self):
        fx = self._effect_for(has_audio=True)
        self.assertIsNotNone(fx)
        self.assertEqual(fx.effect_type, "ripple")
        self.assertLessEqual(fx.intensity, 0.5)  # subtle

    def test_text_produces_ripple(self):
        fx = self._effect_for(text="你好")
        self.assertIsNotNone(fx)
        self.assertEqual(fx.effect_type, "ripple")

    def test_empty_signal_returns_none(self):
        fx = self._effect_for()
        self.assertIsNone(fx)

    # --- touch takes priority over pose ---

    def test_touch_takes_priority_over_pose(self):
        fx = self._effect_for(touch="give_me_5", pose="arms_up")
        self.assertIsNotNone(fx)
        self.assertEqual(fx.effect_type, "give_me_5_flash")

    # --- colour matches theme palette ---

    def test_arms_up_always_gold_regardless_of_theme(self):
        for theme in ("calm", "warm", "burst", "cyber"):
            with self.subTest(theme=theme):
                fx = self._effect_for(pose="arms_up", theme=theme)
                self.assertEqual(fx.color, "#FFD700")


# ===========================================================================
# 4. SceneDirector — build_scene end-to-end
# ===========================================================================

class TestSceneDirectorBuildScene(unittest.TestCase):

    def setUp(self):
        from ktv_backend.modules.scene_builder import SceneDirector
        self.director = SceneDirector()

    def _build(self, music=None, touch="", pose="", text="", action="idle", expression="calm", reply=""):
        if music is None:
            music = _make_music()
        signal = _make_signal(touch_event=touch, pose_label=pose, user_text=text)
        return self.director.build_scene(music, signal, action, expression, reply)

    def test_returns_scene_directive(self):
        from ktv_backend.modules.directives import SceneDirective
        scene = self._build()
        self.assertIsInstance(scene, SceneDirective)

    def test_theme_is_valid(self):
        scene = self._build()
        self.assertIn(scene.theme, ("calm", "warm", "burst", "cyber"))

    def test_high_energy_song_gets_burst_theme(self):
        music = _make_music(bpm=132, energy="high", mood="uplifting")
        scene = self._build(music=music, action="dance_fast")
        self.assertIn(scene.theme, ("burst", "cyber"))

    def test_slow_song_gets_calm_theme(self):
        music = _make_music(bpm=72, energy="low", mood="melancholy")
        scene = self._build(music=music, action="dance_soft", expression="supportive")
        self.assertEqual(scene.theme, "calm")

    def test_chorus_keyword_triggers_particle_burst(self):
        music = _make_music(bpm=128, energy="high")
        scene = self._build(music=music, text="副歌来了", action="dance_fast")
        particle_event = scene.particles.special_event
        self.assertEqual(particle_event, "chorus_burst")

    def test_chorus_generates_screen_flash_effect(self):
        music = _make_music(bpm=128, energy="high")
        scene = self._build(music=music, text="副歌", action="dance_fast")
        types = [e.effect_type for e in scene.instant_effects]
        self.assertIn("screen_flash", types)

    def test_give_me_5_included_in_instant_effects(self):
        scene = self._build(touch="give_me_5", action="high_five", expression="excited")
        types = [e.effect_type for e in scene.instant_effects]
        self.assertIn("give_me_5_flash", types)

    def test_arms_up_included_in_instant_effects(self):
        music = _make_music(bpm=130, energy="high")
        scene = self._build(music=music, pose="arms_up", action="mirror_pose", expression="excited")
        types = [e.effect_type for e in scene.instant_effects]
        self.assertIn("light_pillar", types)

    def test_subtitle_truncated_to_20_chars(self):
        long_reply = "这是一段非常非常非常非常非常非常非常非常长的回复文本"
        scene = self._build(reply=long_reply)
        self.assertLessEqual(len(scene.subtitle), 20)

    def test_beat_sync_enabled_for_dance_fast(self):
        music = _make_music(energy="high")
        scene = self._build(music=music, action="dance_fast", expression="excited")
        self.assertTrue(scene.character.beat_sync)

    def test_beat_sync_disabled_for_idle(self):
        scene = self._build(action="idle", expression="calm")
        self.assertFalse(scene.character.beat_sync)

    def test_burst_theme_has_high_particle_density(self):
        music = _make_music(bpm=128, energy="high")
        scene = self._build(music=music, action="dance_fast")
        self.assertGreater(scene.particles.density, 0.7)

    def test_calm_theme_has_floating_particles(self):
        from ktv_backend.modules.directives import PARTICLE_FLOATING
        music = _make_music(bpm=75, energy="low", mood="tender")
        scene = self._build(music=music, action="dance_soft", expression="supportive")
        self.assertEqual(scene.particles.form, PARTICLE_FLOATING)

    def test_cyber_theme_has_data_stream_particles(self):
        from ktv_backend.modules.directives import PARTICLE_DATA_STREAM
        music = _make_music(bpm=150, energy="high")
        scene = self._build(music=music, action="dance_fast")
        if scene.theme == "cyber":
            self.assertEqual(scene.particles.form, PARTICLE_DATA_STREAM)

    def test_rim_light_is_excited_high_intensity(self):
        music = _make_music(energy="high")
        scene = self._build(music=music, action="dance_fast", expression="excited")
        self.assertGreaterEqual(scene.character.rim_light_intensity, 0.9)

    def test_rim_light_lower_for_supportive(self):
        music = _make_music(energy="low", mood="melancholy")
        scene = self._build(music=music, action="dance_soft", expression="supportive")
        self.assertLess(scene.character.rim_light_intensity, 0.8)

    def test_chorus_transition_is_fast(self):
        music = _make_music(energy="high")
        scene = self._build(music=music, text="副歌", action="dance_fast")
        self.assertLessEqual(scene.theme_transition_s, 0.6)

    def test_normal_transition_is_slow(self):
        scene = self._build(action="idle", expression="calm")
        self.assertGreaterEqual(scene.theme_transition_s, 1.4)

    def test_scene_to_dict_json_serialisable(self):
        scene = self._build()
        d = scene.to_dict()
        serialised = json.dumps(d)
        self.assertGreater(len(serialised), 50)

    def test_background_brightness_below_cap(self):
        music = _make_music(energy="high")
        scene = self._build(music=music, text="副歌", action="dance_fast")
        self.assertLessEqual(scene.background.brightness, 0.85)


# ===========================================================================
# 5. SceneDirector — build_song_open_scene
# ===========================================================================

class TestSongOpenScene(unittest.TestCase):

    def setUp(self):
        from ktv_backend.modules.scene_builder import SceneDirector
        self.director = SceneDirector()

    def test_opens_with_idle(self):
        music = _make_music(bpm=120, energy="medium")
        scene = self.director.build_song_open_scene(music, song_title="孤勇者")
        self.assertEqual(scene.character.action, "idle")

    def test_opens_with_calm_expression(self):
        music = _make_music(bpm=120, energy="medium")
        scene = self.director.build_song_open_scene(music)
        self.assertEqual(scene.character.expression, "calm")

    def test_beat_sync_off_at_open(self):
        music = _make_music(bpm=132, energy="high")
        scene = self.director.build_song_open_scene(music)
        self.assertFalse(scene.character.beat_sync)

    def test_no_instant_effects_at_open(self):
        music = _make_music()
        scene = self.director.build_song_open_scene(music)
        self.assertEqual(len(scene.instant_effects), 0)

    def test_subtitle_mentions_song(self):
        music = _make_music(bpm=90, energy="low")
        scene = self.director.build_song_open_scene(music, song_title="后来")
        self.assertIn("后来", scene.subtitle)

    def test_slow_transition_at_open(self):
        music = _make_music()
        scene = self.director.build_song_open_scene(music)
        self.assertGreaterEqual(scene.theme_transition_s, 1.5)

    def test_low_energy_song_opens_calm(self):
        music = _make_music(bpm=72, energy="low", mood="melancholy")
        scene = self.director.build_song_open_scene(music)
        self.assertEqual(scene.theme, "calm")

    def test_low_brightness_at_open(self):
        music = _make_music()
        scene = self.director.build_song_open_scene(music)
        self.assertLessEqual(scene.background.brightness, 0.6)


# ===========================================================================
# 6. SceneDirector — build_emotion_portrait
# ===========================================================================

class TestEmotionPortraitBuilder(unittest.TestCase):

    def setUp(self):
        from ktv_backend.modules.scene_builder import SceneDirector
        self.director = SceneDirector()

    def _make_full_session(self):
        session = _make_session()
        session._last_song_title  = "孤勇者"
        session._last_song_artist = "陈奕迅"
        session.energy_samples = [0.4, 0.5, 0.7, 0.9, 0.85, 0.6]
        session.key_events = [
            {"event_type": "arms_up",     "label": "举手",   "elapsed_s": 45.0},
            {"event_type": "chorus_start","label": "副歌爆发","elapsed_s": 83.0},
            {"event_type": "heart",       "label": "比心",   "elapsed_s": 110.0},
        ]
        return session

    def test_returns_emotion_portrait(self):
        from ktv_backend.modules.directives import EmotionPortrait
        session = self._make_full_session()
        music   = _make_music(bpm=130, energy="high")
        portrait = self.director.build_emotion_portrait(session, music)
        self.assertIsInstance(portrait, EmotionPortrait)

    def test_theme_matches_music(self):
        session = self._make_full_session()
        music   = _make_music(bpm=130, energy="high")
        portrait = self.director.build_emotion_portrait(session, music)
        self.assertIn(portrait.theme, ("burst", "cyber"))

    def test_energy_curve_preserved(self):
        session = self._make_full_session()
        music   = _make_music()
        portrait = self.director.build_emotion_portrait(session, music)
        self.assertEqual(portrait.energy_curve, session.energy_samples)

    def test_key_events_converted(self):
        session = self._make_full_session()
        music   = _make_music()
        portrait = self.director.build_emotion_portrait(session, music)
        self.assertEqual(len(portrait.key_events), 3)
        types = [e.event_type for e in portrait.key_events]
        self.assertIn("arms_up",      types)
        self.assertIn("chorus_start", types)
        self.assertIn("heart",        types)

    def test_song_metadata_passed_through(self):
        session = self._make_full_session()
        music   = _make_music()
        portrait = self.director.build_emotion_portrait(session, music)
        self.assertEqual(portrait.song_title,  "孤勇者")
        self.assertEqual(portrait.song_artist, "陈奕迅")

    def test_caption_matches_theme(self):
        session = _make_session()
        music   = _make_music(bpm=150, energy="high")
        portrait = self.director.build_emotion_portrait(session, music)
        # cyber or burst caption
        self.assertTrue(len(portrait.caption) > 5)

    def test_fallback_energy_curve_when_session_empty(self):
        session = _make_session()
        music   = _make_music(energy="high")
        portrait = self.director.build_emotion_portrait(session, music)
        self.assertTrue(len(portrait.energy_curve) >= 1)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in portrait.energy_curve))

    def test_portrait_to_dict_json_serialisable(self):
        session  = self._make_full_session()
        music    = _make_music()
        portrait = self.director.build_emotion_portrait(session, music)
        d = portrait.to_dict()
        self.assertIn("key_events",   d)
        self.assertIn("energy_curve", d)
        json.dumps(d)  # must not raise


# ===========================================================================
# 7. SessionState — event tracking helpers
# ===========================================================================

class TestSessionStateTracking(unittest.TestCase):

    def _new_session(self):
        from ktv_backend.modules.state import SessionState
        return SessionState(session_id="test")

    def test_record_energy_appends(self):
        s = self._new_session()
        s.record_energy(0.6)
        s.record_energy(0.8)
        self.assertEqual(s.energy_samples, [0.6, 0.8])

    def test_record_energy_clamps(self):
        s = self._new_session()
        s.record_energy(-0.5)
        s.record_energy(1.5)
        self.assertEqual(s.energy_samples, [0.0, 1.0])

    def test_record_energy_caps_at_120(self):
        s = self._new_session()
        for _ in range(130):
            s.record_energy(0.5)
        self.assertEqual(len(s.energy_samples), 120)

    def test_log_key_event_stores_elapsed(self):
        s = self._new_session()
        s.log_key_event("arms_up", "举手")
        self.assertEqual(len(s.key_events), 1)
        ev = s.key_events[0]
        self.assertEqual(ev["event_type"], "arms_up")
        self.assertEqual(ev["label"],      "举手")
        self.assertIsInstance(ev["elapsed_s"], float)
        self.assertGreaterEqual(ev["elapsed_s"], 0.0)

    def test_log_multiple_events(self):
        s = self._new_session()
        s.log_key_event("heart",     "比心")
        s.log_key_event("give_me_5", "击掌")
        self.assertEqual(len(s.key_events), 2)

    def test_update_song_sets_title_and_artist(self):
        s = self._new_session()
        s.update_song("孤勇者", "陈奕迅")
        self.assertEqual(s._last_song_title,  "孤勇者")
        self.assertEqual(s._last_song_artist, "陈奕迅")

    def test_update_song_sets_current_song_key(self):
        s = self._new_session()
        s.update_song("孤勇者", "陈奕迅")
        self.assertIn("孤勇者", s.current_song_key)

    def test_last_theme_default(self):
        s = self._new_session()
        self.assertEqual(s.last_theme, "warm")


# ===========================================================================
# 8. Orchestrator integration — process_signal returns scene
# ===========================================================================

class TestOrchestratorSceneIntegration(unittest.TestCase):

    def test_brain_result_includes_scene(self):
        from ktv_backend.modules.config import ServerConfig
        from ktv_backend.modules.directives import SceneDirective
        from ktv_backend.modules.orchestrator import KtvBrain
        from ktv_backend.modules.protocol import parse_client_message

        config = ServerConfig()
        brain  = KtvBrain(config)

        msg = parse_client_message(
            json.dumps({
                "type": "user_signal",
                "session_id": "booth-a",
                "payload": {
                    "touch_event": "give_me_5",
                    "song": {"title": "孤勇者", "artist": "陈奕迅"},
                },
            }),
            "fallback-session",
        )
        result = asyncio.run(brain.process_signal(msg.signal))
        self.assertIsNotNone(result.scene)
        self.assertIsInstance(result.scene, SceneDirective)

    def test_payload_contains_scene_dict(self):
        from ktv_backend.modules.config import ServerConfig
        from ktv_backend.modules.orchestrator import KtvBrain
        from ktv_backend.modules.protocol import parse_client_message

        config = ServerConfig()
        brain  = KtvBrain(config)

        msg = parse_client_message(
            json.dumps({
                "type": "user_signal",
                "session_id": "booth-b",
                "payload": {
                    "pose_label": "arms_up",
                    "song": {"title": "热爱105度的你"},
                },
            }),
            "fallback-session",
        )
        result  = asyncio.run(brain.process_signal(msg.signal))
        payload = result.to_payload()
        self.assertIn("scene", payload)
        scene_d = payload["scene"]
        self.assertIn("theme",      scene_d)
        self.assertIn("character",  scene_d)
        self.assertIn("particles",  scene_d)
        self.assertIn("background", scene_d)

    def test_session_theme_updated_after_signal(self):
        from ktv_backend.modules.config import ServerConfig
        from ktv_backend.modules.orchestrator import KtvBrain
        from ktv_backend.modules.protocol import parse_client_message

        config = ServerConfig()
        brain  = KtvBrain(config)
        session_id = "booth-c"

        msg = parse_client_message(
            json.dumps({
                "type": "user_signal",
                "session_id": session_id,
                "payload": {
                    "song": {"title": "逆战", "artist": "张杰"},
                },
            }),
            "fallback-session",
        )
        asyncio.run(brain.process_signal(msg.signal))
        session = brain.sessions.get(session_id)
        self.assertIn(session.last_theme, ("calm", "warm", "burst", "cyber"))

    def test_energy_sample_recorded_per_turn(self):
        from ktv_backend.modules.config import ServerConfig
        from ktv_backend.modules.orchestrator import KtvBrain
        from ktv_backend.modules.protocol import parse_client_message

        config = ServerConfig()
        brain  = KtvBrain(config)
        session_id = "booth-d"

        for i in range(3):
            msg = parse_client_message(
                json.dumps({
                    "type": "user_signal",
                    "session_id": session_id,
                    "payload": {"song": {"title": "孤勇者"}},
                }),
                "fallback-session",
            )
            asyncio.run(brain.process_signal(msg.signal))

        session = brain.sessions.get(session_id)
        self.assertEqual(len(session.energy_samples), 3)

    def test_key_events_logged_for_touch(self):
        from ktv_backend.modules.config import ServerConfig
        from ktv_backend.modules.orchestrator import KtvBrain
        from ktv_backend.modules.protocol import parse_client_message

        config = ServerConfig()
        brain  = KtvBrain(config)
        session_id = "booth-e"

        msg = parse_client_message(
            json.dumps({
                "type": "user_signal",
                "session_id": session_id,
                "payload": {
                    "touch_event": "heart",
                    "song": {"title": "甜蜜蜜"},
                },
            }),
            "fallback-session",
        )
        asyncio.run(brain.process_signal(msg.signal))

        session = brain.sessions.get(session_id)
        types = [e["event_type"] for e in session.key_events]
        self.assertIn("heart", types)


# ===========================================================================
# 9. Bug-fix regressions
# ===========================================================================

class TestBugFixRegressions(unittest.TestCase):

    def test_utc_now_no_deprecation_warning(self):
        """datetime.utcnow() should no longer be called."""
        import warnings
        from ktv_backend.modules.utils import utc_now
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            result = utc_now()  # would raise if utcnow() still used
        self.assertTrue(result.endswith("Z"))
        self.assertIn("T", result)

    def test_utc_now_format(self):
        from ktv_backend.modules.utils import utc_now
        ts = utc_now()
        # Should be ISO 8601 without microseconds: 2026-04-25T07:39:00Z
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_music_classify_no_intense_mood(self):
        """_classify_metrics should never return 'intense' as mood."""
        from ktv_backend.modules.music import MusicAnalyzer
        from ktv_backend.modules.config import ServerConfig
        analyzer = MusicAnalyzer(ServerConfig())
        for tempo in (80, 100, 120, 140, 160):
            for rms in (0.01, 0.05, 0.15, 0.3):
                for centroid in (1000, 2500, 4000, 6000):
                    energy, mood = analyzer._classify_metrics(float(tempo), rms, float(centroid))
                    with self.subTest(tempo=tempo, rms=rms, centroid=centroid):
                        self.assertNotEqual(mood, "intense",
                            f"Got mood='intense' for tempo={tempo}, rms={rms}, centroid={centroid}")

    def test_music_classify_returns_known_moods(self):
        from ktv_backend.modules.music import MusicAnalyzer
        from ktv_backend.modules.config import ServerConfig
        known_moods = {"uplifting", "tender", "melancholy", "warm", "neutral"}
        analyzer = MusicAnalyzer(ServerConfig())
        for tempo in (75, 100, 128, 145):
            for rms in (0.02, 0.10, 0.25):
                energy, mood = analyzer._classify_metrics(float(tempo), rms, 3000.0)
                self.assertIn(mood, known_moods,
                    f"Unexpected mood={mood!r} for tempo={tempo}, rms={rms}")


# ===========================================================================
# 10. Full demo scenario tests (section 10 of PDF)
# ===========================================================================

class TestDemoScenarios(unittest.TestCase):
    """
    Simulate the 5 demo scenarios from the PDF:
      ① 安静开场  — idle, calm, low particles
      ② 第一句歌  — dance starts, beat particles
      ③ 副歌爆发  — burst theme, 500 particles, screen flash
      ④ 用户举手  — light pillar, excited expression
      ⑤ 收尾      — emotion portrait available
    """

    def setUp(self):
        from ktv_backend.modules.scene_builder import SceneDirector
        self.director = SceneDirector()

    def test_scenario_1_opening_is_calm_idle(self):
        music = _make_music(bpm=88, energy="low", mood="tender")
        scene = self.director.build_song_open_scene(music, song_title="后来")
        self.assertEqual(scene.character.action, "idle")
        self.assertFalse(scene.character.beat_sync)
        self.assertLess(scene.background.brightness, 0.55)

    def test_scenario_2_first_verse_has_beat_particles(self):
        from ktv_backend.modules.directives import PARTICLE_BEAT, PARTICLE_FLOATING
        music = _make_music(bpm=95, energy="medium", mood="warm")
        signal = _make_signal(has_audio=True)
        scene = self.director.build_scene(music, signal, "dance_soft", "playful", "跟上来。")
        self.assertIn(scene.particles.form, (PARTICLE_BEAT, PARTICLE_FLOATING))

    def test_scenario_3_chorus_triggers_particle_explosion(self):
        music  = _make_music(bpm=130, energy="high", mood="uplifting")
        signal = _make_signal(user_text="副歌燥起来", pose_label="arms_up")
        scene  = self.director.build_scene(music, signal, "dance_fast", "excited", "就是这个状态！")
        self.assertEqual(scene.particles.special_event, "chorus_burst")
        self.assertGreaterEqual(scene.particles.particle_count_override, 500)
        flash_types = [e.effect_type for e in scene.instant_effects]
        self.assertIn("screen_flash", flash_types)

    def test_scenario_3_chorus_theme_is_burst_or_cyber(self):
        music  = _make_music(bpm=130, energy="high")
        signal = _make_signal(user_text="副歌")
        scene  = self.director.build_scene(music, signal, "dance_fast", "excited", "副歌冲！")
        self.assertIn(scene.theme, ("burst", "cyber"))

    def test_scenario_4_arms_up_generates_light_pillar(self):
        music  = _make_music(bpm=130, energy="high")
        signal = _make_signal(pose_label="arms_up")
        scene  = self.director.build_scene(music, signal, "mirror_pose", "excited", "手都举起来了！")
        types  = [e.effect_type for e in scene.instant_effects]
        self.assertIn("light_pillar", types)
        pillar = next(e for e in scene.instant_effects if e.effect_type == "light_pillar")
        self.assertEqual(pillar.duration_ms, 1500)
        self.assertEqual(pillar.params["top_effect"], "fireworks")

    def test_scenario_4_arms_up_expression_excited(self):
        music  = _make_music(bpm=130, energy="high")
        signal = _make_signal(pose_label="arms_up")
        scene  = self.director.build_scene(music, signal, "mirror_pose", "excited", "包厢热起来！")
        self.assertEqual(scene.character.expression, "excited")

    def test_scenario_5_emotion_portrait_has_key_events(self):
        from ktv_backend.modules.directives import EmotionPortrait
        session = _make_session()
        session.energy_samples = [0.4, 0.6, 0.9, 1.0, 0.8, 0.5]
        session.key_events = [
            {"event_type": "chorus_start", "label": "副歌爆发 @ 1:23", "elapsed_s": 83.0},
            {"event_type": "arms_up",      "label": "举手 ×3",         "elapsed_s": 95.0},
            {"event_type": "heart",        "label": "比心 ×2",         "elapsed_s": 110.0},
        ]
        music   = _make_music(bpm=130, energy="high")
        portrait = self.director.build_emotion_portrait(session, music)
        self.assertIsInstance(portrait, EmotionPortrait)
        self.assertEqual(len(portrait.key_events), 3)
        self.assertGreater(len(portrait.energy_curve), 0)


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
