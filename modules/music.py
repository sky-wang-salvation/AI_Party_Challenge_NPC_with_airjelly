from __future__ import annotations

import importlib
import importlib.util
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse
from urllib.request import urlopen

from .config import ServerConfig
from .protocol import SongPayload
from .utils import run_blocking


@dataclass
class MusicAnalysis:
    bpm: Optional[int]
    energy: str
    mood: str
    dance_action: str
    expression: str
    confidence: float
    source: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    def short_text(self) -> str:
        bpm_text = str(self.bpm) if self.bpm is not None else "unknown"
        return "bpm={0}, energy={1}, mood={2}, dance={3}, source={4}".format(
            bpm_text,
            self.energy,
            self.mood,
            self.dance_action,
            self.source,
        )


class MusicAnalyzer:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self._cache = {}  # type: Dict[str, MusicAnalysis]
        self._tasks = {}  # type: Dict[str, object]
        self.config.song_cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cached(self, song: SongPayload) -> Optional[MusicAnalysis]:
        key = song.song_key()
        return self._cache.get(key) if key else None

    async def prewarm(self, song: SongPayload) -> MusicAnalysis:
        cached = self.get_cached(song)
        if cached is not None:
            return cached

        key = song.song_key()
        if not key:
            return self.estimate(song)

        task = self._tasks.get(key)
        if task is None:
            task = self._spawn_task(song)
            self._tasks[key] = task
        result = await task
        self._cache[key] = result
        self._tasks.pop(key, None)
        return result

    def ensure_background(self, song: SongPayload) -> None:
        key = song.song_key()
        if not key or key in self._cache or key in self._tasks:
            return
        self._tasks[key] = self._spawn_task(song)

    def estimate(self, song: SongPayload) -> MusicAnalysis:
        title = (song.title or "").lower()
        emotion = (song.emotion_hint or "").lower()
        bpm = int(song.bpm_hint) if song.bpm_hint is not None else None

        mood = "neutral"
        if any(keyword in title for keyword in ("爱", "love", "sweet", "告白", "心动")):
            mood = "warm"
        elif any(keyword in title for keyword in ("孤独", "失恋", "sad", "雨", "后来", "演员")):
            mood = "melancholy"
        elif any(keyword in title for keyword in ("勇", "光", "fire", "run", "热爱", "逆战")):
            mood = "uplifting"
        elif any(keyword in title for keyword in ("夜", "moon", "海", "slow", "温柔")):
            mood = "tender"

        if emotion:
            if any(keyword in emotion for keyword in ("sad", "伤", "emo", "抒情")):
                mood = "melancholy"
            elif any(keyword in emotion for keyword in ("love", "甜", "浪漫")):
                mood = "warm"
            elif any(keyword in emotion for keyword in ("燃", "high", "热血", "兴奋")):
                mood = "uplifting"

        if bpm is None:
            if mood == "uplifting":
                bpm = 132
            elif mood in {"melancholy", "tender"}:
                bpm = 82
            else:
                bpm = 104

        if bpm >= 126:
            energy = "high"
        elif bpm >= 95:
            energy = "medium"
        else:
            energy = "low"

        dance_action, expression = self._map_dance_and_expression(energy, mood)
        return MusicAnalysis(
            bpm=bpm,
            energy=energy,
            mood=mood,
            dance_action=dance_action,
            expression=expression,
            confidence=0.35,
            source="heuristic",
        )

    def _spawn_task(self, song: SongPayload):
        import asyncio

        return asyncio.create_task(run_blocking(self._analyze_sync, song))

    def _analyze_sync(self, song: SongPayload) -> MusicAnalysis:
        if not importlib.util.find_spec("librosa"):
            return self.estimate(song)

        source_path = None
        temp_download = None
        try:
            source_path, temp_download = self._resolve_audio_source(song)
            if not source_path:
                return self.estimate(song)

            librosa = importlib.import_module("librosa")
            waveform, sample_rate = librosa.load(
                source_path,
                sr=22050,
                mono=True,
                duration=self.config.music_analysis_duration_s,
            )
            if len(waveform) == 0:
                return self.estimate(song)

            tempo, _beats = librosa.beat.beat_track(y=waveform, sr=sample_rate)
            rms = float(librosa.feature.rms(y=waveform).mean())
            centroid = float(librosa.feature.spectral_centroid(y=waveform, sr=sample_rate).mean())
            energy, mood = self._classify_metrics(float(tempo), rms, centroid)
            dance_action, expression = self._map_dance_and_expression(energy, mood)
            return MusicAnalysis(
                bpm=int(round(float(tempo))) if tempo else None,
                energy=energy,
                mood=mood,
                dance_action=dance_action,
                expression=expression,
                confidence=0.78,
                source="librosa",
            )
        except Exception:
            return self.estimate(song)
        finally:
            if temp_download and os.path.exists(temp_download):
                os.unlink(temp_download)

    def _resolve_audio_source(self, song: SongPayload) -> Tuple[Optional[str], Optional[str]]:
        if not song.url:
            return None, None
        raw = song.url.strip()
        parsed = urlparse(raw)

        if parsed.scheme in ("http", "https"):
            suffix = Path(parsed.path).suffix or ".mp3"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                response = urlopen(raw, timeout=self.config.music_download_timeout_s)
                try:
                    temp_file.write(response.read())
                finally:
                    response.close()
                return temp_file.name, temp_file.name

        if parsed.scheme == "file":
            from urllib.request import url2pathname
            file_path = Path(url2pathname(parsed.path))
            return str(file_path), None

        local_path = Path(raw)
        if local_path.exists():
            return str(local_path), None
        return None, None

    def _classify_metrics(self, tempo: float, rms: float, centroid: float):
        normalized_centroid = centroid / 5000.0 if centroid else 0.0
        intensity = tempo / 140.0 + rms * 1.6 + normalized_centroid * 0.4
        if intensity >= 1.5:
            energy = "high"
        elif intensity >= 1.0:
            energy = "medium"
        else:
            energy = "low"

        if energy == "high" and normalized_centroid >= 0.45:
            mood = "uplifting"
        elif energy == "high":
            mood = "uplifting"  # map intense → uplifting so downstream mood handlers always match
        elif energy == "low" and tempo <= 88:
            mood = "tender"
        elif normalized_centroid <= 0.28:
            mood = "melancholy"
        else:
            mood = "warm"
        return energy, mood

    def _map_dance_and_expression(self, energy: str, mood: str):
        if energy == "high":
            return "dance_fast", "excited"
        if energy == "medium":
            if mood in {"warm", "uplifting"}:
                return "dance_groove", "playful"
            return "dance_groove", "focused"
        if mood in {"melancholy", "tender"}:
            return "dance_soft", "supportive"
        return "dance_soft", "calm"
