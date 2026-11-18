"""Озвучка через Pollinations: Gemini (по умолчанию), ElevenLabs или OpenAI с выбором голоса."""

import hashlib
import subprocess
import wave
import tempfile
from .execution import ThreadPoolExecutor, check_cancelled
from pathlib import Path

from .config import API, CACHE, NET_TTS, VOICES
from .ff import FFMPEG
from .http import post_json
from .files import path_lock, valid_audio


def _one(text: str, provider: str, voice: str) -> Path:
    model = VOICES[provider]["model"]
    h = hashlib.sha1(f"{model}|{voice}|{text}".encode()).hexdigest()[:16]
    d = CACHE / "tts"
    d.mkdir(parents=True, exist_ok=True)
    wav = d / f"{h}.wav"
    with path_lock(wav):
        check_cancelled()
        if valid_audio(wav):
            return wav
        with tempfile.TemporaryDirectory(dir=d) as temporary:
            raw, output = Path(temporary) / "voice.src", Path(temporary) / "voice.wav"
            raw.write_bytes(
                post_json(
                    f"{API}/v1/audio/speech",
                    {"model": model, "input": text, "voice": voice},
                )
            )
            subprocess.run(
                [
                    FFMPEG,
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(raw),
                    "-ar",
                    "44100",
                    "-ac",
                    "1",
                    str(output),
                ],
                check=True,
                timeout=180,
            )
            if not valid_audio(output):
                raise RuntimeError("Провайдер вернул повреждённую озвучку")
            output.replace(wav)
        return wav


def synthesize_all(
    texts: list[str], provider: str = "gemini", voice: str | None = None, log=print
) -> list[tuple[str, float]]:
    """Озвучивает все фразы (параллельно). Возвращает [(wav, длительность)]."""
    voice = voice or VOICES[provider]["default"]
    done = 0

    def one(t):
        nonlocal done
        p = _one(t, provider, voice)
        done += 1
        if done % 5 == 0 or done == len(texts):
            log(f"озвучка {done}/{len(texts)}")
        return p

    with ThreadPoolExecutor(NET_TTS) as ex:
        paths = list(ex.map(one, texts))
    out = []
    for p in paths:
        with wave.open(str(p)) as w:
            out.append((str(p), w.getnframes() / w.getframerate()))
    return out
