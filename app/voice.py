"""voice.py -- MOON-AI's female voice (TTS) + speech-to-text (STT).

Female voice design
-------------------
MOON-AI speaks with a warm, clearly-FEMALE voice. The pipeline:
  1. espeak-ng synthesises with an explicit *female* voice (f5, raised pitch,
     softer intonation) -- espeak's voice 5 is its female preset.
  2. SoX reshapes the timbre into an attractive, intimate tone:
       - `pitch`   : raises overall pitch (female register)
       - `bass -f`  : trims hiss / adds body so it is not thin/robotic
       - `treble`   : gentle air/presence
       - `chorus`   : subtle stereo width for a fuller, "studio" feel
       - `reverb`   : a touch of room so it is not dry
  The exact numbers are tuned in FemaleVoicePresets and can be overridden.

Speech-to-text (dictation)
--------------------------
Optional `vosk` offline model. If unavailable, dictation simply reports it is
disabled -- the rest of MOON-AI keeps working.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_TRANSCRIPTION_SECONDS = 15
_MAX_TTS_TEXT_CHARS = 2_000
_MAX_VOICE_FILE_BYTES = 20 * 1024 * 1024


# Aesthetic "world's most attractive female voice" tuning.
# pitch_hz  : SoX pitch shift in cents-ish Hz (positive = higher = more feminine)
# formant   : `bass` gain (dB) for body/roundness
# air       : `treble` gain (dB) for breathy presence
FEMALE_PRESETS: dict[str, dict] = {
    "seductive":  {"pitch_hz": 280, "formant": 2.5, "air": 2.0, "chorus": True,  "reverb": 0.12},
    "warm":       {"pitch_hz": 220, "formant": 3.0, "air": 1.2, "chorus": True,  "reverb": 0.08},
    "crystal":    {"pitch_hz": 340, "formant": 1.5, "air": 3.0, "chorus": False, "reverb": 0.04},
    "default":    {"pitch_hz": 260, "formant": 2.5, "air": 1.8, "chorus": True,  "reverb": 0.10},
}


class Voice:
    """Female TTS + optional STT wrapper for MOON-AI."""

    def __init__(
        self,
        *,
        preset: str = "default",
        espeak_voice: str = "en+f5",
        rate: int = 175,
    ) -> None:
        self.preset_name = preset if preset in FEMALE_PRESETS else "default"
        self.preset = FEMALE_PRESETS[self.preset_name]
        self.espeak_voice = espeak_voice  # f5 == female voice in espeak
        self.rate = rate
        self._espeak = shutil.which("espeak-ng") or shutil.which("espeak")
        self._sox = shutil.which("sox")
        self._vosk_model: str | None = None
        # locate an optional vosk model directory
        for cand in (os.environ.get("VOSK_MODEL_DIR"), ""):
            if cand and Path(cand).exists():
                self._vosk_model = cand
                break

    # -- TTS -----------------------------------------------------------------
    async def speak(self, text: str) -> str | None:
        """Return a path to a WAV file with MOON-AI's female voice, or None."""
        if not text:
            return None
        if len(text) > _MAX_TTS_TEXT_CHARS:
            logger.warning("voice text exceeds %s characters", _MAX_TTS_TEXT_CHARS)
            return None
        if not self._espeak:
            logger.warning("no TTS engine (espeak) available; cannot speak")
            return None
        try:
            return await asyncio.to_thread(self._female_speak, text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("voice speak failed: %s", exc)
            return None

    def _female_speak(self, text: str) -> str:
        fd, raw = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        output: str | None = None
        try:
            result = subprocess.run(
                [
                    self._espeak,
                    "-v", self.espeak_voice,
                    "-s", str(self.rate),
                    "-p", "60",
                    "-a", "110",
                    "-w", raw,
                    text,
                ],
                check=False,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
            if result.returncode or not Path(raw).is_file() or Path(raw).stat().st_size == 0:
                raise RuntimeError("espeak did not produce a WAV file")
            if Path(raw).stat().st_size > _MAX_VOICE_FILE_BYTES:
                raise RuntimeError("espeak output exceeded the audio file limit")
            if not self._sox:
                return raw

            out_fd, output = tempfile.mkstemp(suffix=".wav")
            os.close(out_fd)
            Path(output).unlink()
            preset = self.preset
            sox_cmd = [self._sox, raw, output]
            sox_cmd += ["pitch", str(preset["pitch_hz"])]
            sox_cmd += ["bass", str(preset["formant"])]
            sox_cmd += ["treble", str(preset["air"])]
            sox_cmd += ["highpass", "80"]
            sox_cmd += ["compand", "0.02,0.2", "-60,-60,-30,-15,-10,-6,0,0", "-6", "0", "0.1"]
            if preset["chorus"]:
                sox_cmd += ["chorus", "0.7", "0.9", "55", "0.4", "0.25", "2.0", "-s"]
            if preset["reverb"]:
                sox_cmd += ["reverb", "-w", str(preset["reverb"])]
            sox_cmd += ["gain", "-1"]
            try:
                sox_result = subprocess.run(
                    sox_cmd,
                    check=False,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                logger.warning("SoX post-processing timed out; using raw TTS audio")
                Path(output).unlink(missing_ok=True)
                return raw
            if (
                sox_result.returncode == 0
                and Path(output).is_file()
                and 0 < Path(output).stat().st_size <= _MAX_VOICE_FILE_BYTES
            ):
                Path(raw).unlink(missing_ok=True)
                return output
            logger.warning("SoX post-processing failed; using raw TTS audio")
            Path(output).unlink(missing_ok=True)
            return raw
        except Exception:
            Path(raw).unlink(missing_ok=True)
            if output:
                Path(output).unlink(missing_ok=True)
            raise

    def available(self) -> bool:
        return bool(self._espeak)

    # -- STT (dictation) -----------------------------------------------------
    def stt_available(self) -> bool:
        if not self._vosk_model:
            return False
        try:
            import vosk  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    def transcribe_mic(self, *, seconds: int = 5, device: int | None = None) -> str | None:
        """Capture `seconds` of microphone audio and return the transcript.

        Requires vosk + a model dir set via VOSK_MODEL_DIR. Returns None if
        dictation is unavailable.
        """
        if (
            not isinstance(seconds, int)
            or isinstance(seconds, bool)
            or not 1 <= seconds <= _MAX_TRANSCRIPTION_SECONDS
        ):
            logger.warning(
                "dictation duration must be between 1 and %s seconds",
                _MAX_TRANSCRIPTION_SECONDS,
            )
            return None
        if (
            device is not None
            and (
                not isinstance(device, int)
                or isinstance(device, bool)
                or device < 0
            )
        ):
            logger.warning("dictation device index must be a non-negative integer")
            return None
        if not self.stt_available():
            logger.info("dictation unavailable (install vosk + VOSK_MODEL_DIR)")
            return None
        try:
            import wave

            import pyaudio  # type: ignore
            import vosk
        except Exception as exc:  # noqa: BLE001
            logger.warning("dictation deps missing: %s", exc)
            return None
        # capture
        rec_fd, rec = tempfile.mkstemp(suffix=".wav")
        os.close(rec_fd)
        pa = None
        stream = None
        try:
            pa = pyaudio.PyAudio()
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000,
                             input=True, frames_per_buffer=8000,
                             input_device_index=device)
            frames = []
            for _ in range(int(16000 / 8000 * seconds)):
                frames.append(stream.read(8000, exception_on_overflow=False))
            stream.stop_stream()
            stream.close()
            stream = None
            pa.terminate()
            pa = None
            with wave.open(rec, "wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
                wf.writeframes(b"".join(frames))
            recog = vosk.KaldiRecognizer(vosk.Model(self._vosk_model), 16000)
            with wave.open(rec, "rb") as wf:
                data = wf.readframes(wf.getnframes())
            recog.AcceptWaveform(data)
            res = recog.FinalResult()
            import json
            return json.loads(res).get("text", "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("dictation failed: %s", exc)
            return None
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("dictation stream stop failed: %s", exc)
                try:
                    stream.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("dictation stream close failed: %s", exc)
            if pa is not None:
                try:
                    pa.terminate()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("dictation audio cleanup failed: %s", exc)
            Path(rec).unlink(missing_ok=True)
