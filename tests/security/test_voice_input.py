import json
import os
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.voice import Voice


@pytest.mark.asyncio
async def test_tts_is_offloaded_bounded_and_validates_output(monkeypatch):
    voice = Voice()
    voice._espeak = "fake-espeak"
    voice._sox = None
    wav_files = []

    def fake_run(command, **kwargs):
        assert kwargs["timeout"] == 60
        path = command[command.index("-w") + 1]
        wav_files.append(path)
        Path(path).write_bytes(b"RIFF-audio")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("app.voice.subprocess.run", fake_run)
    result = await voice.speak("hello")
    assert result == wav_files[0]
    assert os.path.getsize(result) > 0
    os.unlink(result)

    assert await voice.speak("x" * 2_001) is None


@pytest.mark.asyncio
async def test_tts_failure_removes_partial_audio(monkeypatch):
    voice = Voice()
    voice._espeak = "fake-espeak"
    generated = []

    def fake_run(command, **kwargs):
        path = command[command.index("-w") + 1]
        generated.append(path)
        Path(path).write_bytes(b"partial")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr("app.voice.subprocess.run", fake_run)
    assert await voice.speak("hello") is None
    assert len(generated) == 1
    assert not os.path.exists(generated[0])


@pytest.mark.parametrize("seconds", [0, -1, 16, True, "5"])
def test_microphone_transcription_rejects_unbounded_duration(seconds):
    voice = Voice()
    voice.stt_available = lambda: pytest.fail("invalid duration must be rejected first")
    assert voice.transcribe_mic(seconds=seconds) is None


def test_vosk_transcription_finalizes_audio_and_cleans_up(monkeypatch, tmp_path):
    voice = Voice()
    voice._vosk_model = str(tmp_path)
    monkeypatch.setattr(voice, "stt_available", lambda: True)
    resources = {"stopped": False, "closed": False, "terminated": False}
    recognizer_calls = []
    wav_files = []
    real_mkstemp = tempfile.mkstemp

    def fake_mkstemp(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        wav_files.append(path)
        return fd, path

    class FakeStream:
        def read(self, frame_count, exception_on_overflow):
            return b"\x00\x00" * frame_count

        def stop_stream(self):
            resources["stopped"] = True

        def close(self):
            resources["closed"] = True

    class FakeAudio:
        def open(self, **kwargs):
            return FakeStream()

        def terminate(self):
            resources["terminated"] = True

    class FakeRecognizer:
        def AcceptWaveform(self, data):
            recognizer_calls.append(("accept", len(data)))

        def FinalResult(self):
            recognizer_calls.append(("final",))
            return json.dumps({"text": "transcribed"})

    pyaudio = types.ModuleType("pyaudio")
    pyaudio.paInt16 = 8
    pyaudio.PyAudio = FakeAudio
    vosk = types.ModuleType("vosk")
    vosk.Model = lambda path: object()
    vosk.KaldiRecognizer = lambda model, rate: FakeRecognizer()
    monkeypatch.setitem(sys.modules, "pyaudio", pyaudio)
    monkeypatch.setitem(sys.modules, "vosk", vosk)
    monkeypatch.setattr("app.voice.tempfile.mkstemp", fake_mkstemp)

    assert voice.transcribe_mic(seconds=1) == "transcribed"
    assert recognizer_calls[-1] == ("final",)
    assert resources == {"stopped": True, "closed": True, "terminated": True}
    assert len(wav_files) == 1
    assert not os.path.exists(wav_files[0])
