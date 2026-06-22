"""
Tiny sound-effect module for Desktop Cat.

Synthesizes short WAV files on first run (no asset files to ship) and
plays them via QSoundEffect. Respects the global `sound_effects`
toggle from world_settings.json. Failures are silent — audio is a
polish layer, never required for the game to run.
"""

from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path
from typing import Callable, Iterable

try:
    from PyQt6.QtCore      import QUrl
    from PyQt6.QtMultimedia import QSoundEffect
    _HAVE_QT_AUDIO = True
except Exception:  # pragma: no cover — missing optional dep
    _HAVE_QT_AUDIO = False


_SOUND_DIR = Path(__file__).parent / 'sprites' / 'sounds'
_RATE      = 22050

# Bumped whenever any synth function changes so cached WAVs are replaced.
_SYNTH_VERSION = 3

_effects: dict[str, 'QSoundEffect'] = {}
_ambient_effect: 'QSoundEffect | None' = None
_enabled: bool = True


# ── Low-level WAV writer ──────────────────────────────────────────────────────

def _write_wav(path: Path, samples: Iterable[float], rate: int = _RATE) -> None:
    data = b''.join(struct.pack('<h', max(-32767, min(32767, int(s * 32767))))
                    for s in samples)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data)


def _lowpass(signal: list[float], alpha: float = 0.15) -> list[float]:
    """Very cheap one-pole low-pass filter; alpha smaller = more filtering."""
    out: list[float] = []
    y = 0.0
    for x in signal:
        y += alpha * (x - y)
        out.append(y)
    return out


# ── Synth functions ──────────────────────────────────────────────────────────

def _synth_plop(rate: int = _RATE) -> list[float]:
    """Cute little water-drop bloop — short, pitched, warm.

    Onset click + pitched sine with a small downward pitch envelope and
    very quick exponential decay. No long sweep (which would sound like
    a laser), just a brief percussive "bup".
    """
    dur = 0.090                 # 90 ms total
    n   = int(rate * dur)
    out: list[float] = [0.0] * n
    # Base frequency slides 280 → 170 Hz over ~50 ms then holds
    for i in range(n):
        t = i / rate
        slide = min(t / 0.050, 1.0)
        f = 280 - (280 - 170) * slide
        # Envelope: instant attack, exponential decay (~35 ms settle)
        env = math.exp(-t * 38) * (1.0 - math.exp(-t * 2400))
        s = math.sin(2 * math.pi * f * t) * env * 0.80
        # A touch of 2nd harmonic for a rounder timbre
        s += math.sin(2 * math.pi * f * 2 * t) * env * 0.12
        out[i] = s
    # Brief onset click (first 3 ms of mild noise) for percussive snap
    click_n = int(rate * 0.003)
    for i in range(click_n):
        out[i] += (random.random() * 2 - 1) * 0.25 * math.exp(-i / click_n * 5)
    return out


def _synth_drop(rate: int = _RATE) -> list[float]:
    """Soft whoosh → tiny landing thump for Sao falling in.

    A pitched whoosh (falling sine + filtered noise) followed by a low
    rounded thud at the end. Softer and shorter than the old version.
    """
    dur = 0.38
    n   = int(rate * dur)
    out: list[float] = [0.0] * n
    # Whoosh: filtered noise, fading in then tapering
    noise: list[float] = []
    for i in range(n):
        t = i / rate
        if t < 0.22:
            env = math.sin(math.pi * (t / 0.22)) * 0.30
        else:
            env = 0.0
        noise.append((random.random() * 2 - 1) * env)
    whoosh = _lowpass(noise, alpha=0.10)
    # Falling sine layered over the whoosh (from 420 → 180 Hz)
    for i in range(n):
        t = i / rate
        if t < 0.22:
            f = 420 - (420 - 180) * (t / 0.22)
            env = math.sin(math.pi * (t / 0.22)) * 0.22
            whoosh[i] += math.sin(2 * math.pi * f * t) * env
    # Thud: low sine at the end with a short exponential decay
    thud_start = 0.22
    thud_n = int(rate * 0.14)
    for i in range(thud_n):
        t = i / rate
        f = 130 - 20 * (t / 0.14)
        env = math.exp(-t * 22) * 0.85
        pos = int(rate * thud_start) + i
        if pos < n:
            whoosh[pos] += math.sin(2 * math.pi * f * t) * env
    return [max(-1.0, min(1.0, x)) for x in whoosh]


def _synth_step(rate: int = _RATE) -> list[float]:
    """Soft footstep tap — very short lowpass-filtered noise burst."""
    dur = 0.045
    n   = int(rate * dur)
    raw: list[float] = []
    for i in range(n):
        t = i / rate
        env = math.exp(-t * 90) * (1.0 - math.exp(-t * 2500))
        raw.append((random.random() * 2 - 1) * env * 0.55)
    # Heavy lowpass so it sounds like a muffled pad, not a click
    out = _lowpass(_lowpass(raw, alpha=0.11), alpha=0.18)
    # Tiny pitched thud at 90 Hz for a touch of warmth
    for i in range(n):
        t = i / rate
        env = math.exp(-t * 60) * 0.30
        out[i] += math.sin(2 * math.pi * 90 * t) * env
    return out


def _synth_jump(rate: int = _RATE) -> list[float]:
    """Light upward whoop — rising sine with a soft envelope."""
    dur = 0.18
    n   = int(rate * dur)
    out: list[float] = []
    for i in range(n):
        t = i / rate
        # Rising pitch 220 → 360 Hz over the first 80 ms, then held
        slide = min(t / 0.08, 1.0)
        f = 220 + (360 - 220) * slide
        # Envelope: gentle attack, smooth decay
        env = (1 - math.exp(-t * 60)) * math.exp(-t * 11) * 0.55
        s  = math.sin(2 * math.pi * f * t) * env
        s += math.sin(2 * math.pi * f * 2 * t) * env * 0.18
        out.append(s)
    return out


def _synth_ambient(rate: int = _RATE) -> list[float]:
    """Soft airy hum + breeze layer for a quiet, cosy background.

    Produces a seamlessly loopable ~6-second buffer: heavily filtered
    noise modulated by a slow LFO, plus a very low drone. Fades at the
    seam so that a perfect loop joins without a click.
    """
    dur  = 6.0
    n    = int(rate * dur)
    # Brownish noise (integrated white noise, rescaled)
    white = [random.random() * 2 - 1 for _ in range(n)]
    # One-pole integrator for brown noise
    brown: list[float] = []
    y = 0.0
    for x in white:
        y = 0.98 * y + 0.02 * x
        brown.append(y)
    # Normalize-ish
    peak = max((abs(v) for v in brown), default=1.0) or 1.0
    brown = [v / peak for v in brown]
    # Extra lowpass for softness
    brown = _lowpass(brown, alpha=0.08)
    # Modulate with slow LFO (0.18 Hz) so it breathes
    out: list[float] = []
    for i, v in enumerate(brown):
        t   = i / rate
        lfo = 0.55 + 0.45 * math.sin(2 * math.pi * 0.18 * t)
        # Very low drone, quiet
        drone = math.sin(2 * math.pi * 78 * t) * 0.04 \
              + math.sin(2 * math.pi * 117 * t) * 0.025
        out.append(v * 0.22 * lfo + drone)
    # Crossfade the last 0.5 s with the first 0.5 s so the loop is seamless
    fade = int(rate * 0.5)
    for i in range(fade):
        a = i / fade
        blended = out[i] * a + out[n - fade + i] * (1 - a)
        out[i] = blended
        out[n - fade + i] = blended
    # Final taper at the seam to kill any residual click
    for i in range(32):
        out[n - 1 - i] *= i / 32.0
    # Keep overall very quiet (ambient should be felt, not heard)
    return [max(-1.0, min(1.0, v)) * 0.55 for v in out]


def _synth_softbell(rate: int = _RATE) -> list[float]:
    """Soft, warm two-note bell for the Pomodoro work↔break switch.

    A gentle rising fifth (D5 → A5) on mellow sine voices with a slow
    attack and a long, soft decay — calm and rounded, nothing like a
    sharp alarm 'ding'.
    """
    dur = 0.95
    n   = int(rate * dur)
    out: list[float] = [0.0] * n
    for f, start in ((587.33, 0.0), (880.0, 0.17)):     # D5, then A5
        s0 = int(rate * start)
        for i in range(s0, n):
            t = (i - s0) / rate
            env = (1.0 - math.exp(-t * 38)) * math.exp(-t * 3.0) * 0.45
            s  = math.sin(2 * math.pi * f * t) * env
            s += math.sin(2 * math.pi * f * 2 * t) * env * 0.16   # faint shimmer
            out[i] += s
    return [max(-1.0, min(1.0, v)) for v in out]


_SYNTHS: dict[str, Callable[[int], list[float]]] = {
    'plop':     _synth_plop,
    'drop':     _synth_drop,
    'step':     _synth_step,
    'jump':     _synth_jump,
    'softbell': _synth_softbell,
    'ambient':  _synth_ambient,
}


def _manifest_path() -> Path:
    return _SOUND_DIR / '.synth_version'


def _ensure_files() -> None:
    """Synthesize WAVs if missing, or re-synthesize when the synth
    version has changed. Cached effects are cleared so the new WAVs
    are actually loaded."""
    global _effects, _ambient_effect
    try:
        _SOUND_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    # Check manifest
    mani = _manifest_path()
    current = None
    try:
        if mani.exists():
            current = int(mani.read_text().strip() or '0')
    except (OSError, ValueError):
        current = None

    needs_rebuild = current != _SYNTH_VERSION

    for name, synth in _SYNTHS.items():
        path = _SOUND_DIR / f'{name}.wav'
        if needs_rebuild or not path.exists():
            try:
                _write_wav(path, synth())
            except OSError:
                pass

    if needs_rebuild:
        try:
            mani.write_text(str(_SYNTH_VERSION))
        except OSError:
            pass
        # Drop cached effects so new files are picked up
        _effects.clear()
        if _ambient_effect is not None:
            try:
                _ambient_effect.stop()
            except Exception:
                pass
            _ambient_effect = None


def _get(name: str) -> 'QSoundEffect | None':
    if not _HAVE_QT_AUDIO:
        return None
    if name in _effects:
        return _effects[name]
    path = _SOUND_DIR / f'{name}.wav'
    if not path.exists():
        return None
    eff = QSoundEffect()
    eff.setSource(QUrl.fromLocalFile(str(path)))
    eff.setVolume(0.55)
    _effects[name] = eff
    return eff


# ── Public API ────────────────────────────────────────────────────────────────

def _preload() -> None:
    """Create every QSoundEffect up front so its WAV is loaded BEFORE the
    first play.  QSoundEffect loads asynchronously, so a rarely-played sound
    (like the timer bell — first heard ~25 min in) would otherwise drop its
    very first play because the buffer wasn't ready yet."""
    if not _HAVE_QT_AUDIO:
        return
    for name in _SYNTHS:
        if name != 'ambient':
            _get(name)


def init() -> None:
    """Synthesize sound files if missing / out of date, then preload them."""
    _ensure_files()
    _preload()


def set_enabled(on: bool) -> None:
    """Global mute switch. Also pauses or resumes the ambient layer."""
    global _enabled
    _enabled = bool(on)
    if _ambient_effect is None:
        return
    try:
        if _enabled and _ambient_effect.loopsRemaining() != QSoundEffect.Infinite:
            _ambient_effect.setLoopCount(QSoundEffect.Loop.Infinite)
        if _enabled:
            _ambient_effect.play()
        else:
            _ambient_effect.stop()
    except Exception:
        pass


def is_enabled() -> bool:
    return _enabled


# By user request, Sao is silent except the timer ding.  Footsteps, jumps,
# plops, drops and the ambient bed are all suppressed here so the (many) call
# sites don't each need touching.  The task-complete chime is separate — it's
# Web Audio inside the hub UI, not this module.
_ALLOWED_SOUNDS = {'softbell'}


def play(name: str, volume: float = 0.55, pitch_jitter: float = 0.0) -> None:
    """Fire-and-forget playback. No-op when disabled, not allow-listed, or any
    error occurs."""
    if not _enabled or name not in _ALLOWED_SOUNDS:
        return
    try:
        eff = _get(name)
        if eff is None:
            return
        if pitch_jitter:
            # QSoundEffect doesn't expose pitch — approximate by varying volume
            volume = max(0.0, min(1.0, volume * (1 + random.uniform(
                -pitch_jitter, pitch_jitter))))
        eff.setVolume(volume)
        eff.play()
    except Exception:
        pass


def start_ambient(volume: float = 0.18) -> None:
    """Disabled by request — the ambient background bed was removed (Sao is
    silent except the timer ding)."""
    return


def _start_ambient_unused(volume: float = 0.18) -> None:
    global _ambient_effect
    if not _HAVE_QT_AUDIO:
        return
    try:
        path = _SOUND_DIR / 'ambient.wav'
        if not path.exists():
            return
        if _ambient_effect is None:
            _ambient_effect = QSoundEffect()
            _ambient_effect.setSource(QUrl.fromLocalFile(str(path)))
            _ambient_effect.setLoopCount(QSoundEffect.Loop.Infinite)
        _ambient_effect.setVolume(volume)
        if _enabled:
            _ambient_effect.play()
    except Exception:
        pass


def stop_ambient() -> None:
    if _ambient_effect is None:
        return
    try:
        _ambient_effect.stop()
    except Exception:
        pass
