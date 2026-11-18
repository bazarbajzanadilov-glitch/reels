"""Звук: озвучка + фоновый гул (или своя музыка) + звуковые эффекты. Всё сводится через ffmpeg."""

import random
import subprocess
import wave
from array import array
from pathlib import Path

from .config import ASSETS, CACHE
from .ff import FFMPEG

# Эффекты синтезируются ffmpeg-ом — никаких авторских прав.
SFX = {
    "boom": "aevalsrc='0.95*sin(2*PI*(70-45*t)*t)*exp(-5*t)+0.25*(random(0)*2-1)*exp(-14*t)':d=1.2:s=44100",
    "whoosh": "anoisesrc=d=0.7:c=pink:a=0.6:r=44100,highpass=f=500,lowpass=f=4000,afade=t=in:d=0.35,afade=t=out:st=0.35:d=0.35",
    "heartbeat": "aevalsrc='0.9*sin(2*PI*48*t)*exp(-22*t)+0.7*sin(2*PI*44*(t-0.28))*exp(-22*(t-0.28))*gte(t,0.28)':d=0.9:s=44100",
    "alarm": "aevalsrc='0.28*sin(2*PI*880*t)*lt(mod(t,0.4),0.2)':d=1.6:s=44100",
    "hit": "aevalsrc='0.7*sin(2*PI*160*t)*exp(-28*t)+0.15*(random(0)*2-1)*exp(-40*t)':d=0.35:s=44100",
    "rise": "aevalsrc='0.25*sin(2*PI*(120+260*t*t)*t)*min(1,t*2)':d=1.5:s=44100",
}


def sfx_file(name: str) -> str | None:
    if name not in SFX:
        return None
    d = CACHE / "sfx"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.wav"
    if not path.exists():
        subprocess.run(
            [
                FFMPEG,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                SFX[name],
                "-ac",
                "1",
                str(path),
            ],
            check=True,
        )
    return str(path)


RATE = 44100


def _read_mono16(path: str) -> array:
    with wave.open(path) as w:
        assert (
            w.getframerate() == RATE and w.getnchannels() == 1 and w.getsampwidth() == 2
        ), path
        a = array("h")
        a.frombytes(w.readframes(w.getnframes()))
        return a


def _build_track(
    events: list[tuple[str, float, float]], total: float, out: str
) -> None:
    """Раскладывает WAV-файлы по времени в одну дорожку. events: (wav, начало, громкость).
    Фразы озвучки не пересекаются — копируются блоком; эффекты могут накладываться — складываются."""
    buf = array("h", bytes(2 * int(total * RATE + RATE)))
    used = []  # занятые отрезки
    cache: dict[tuple[str, float], array] = {}
    for path, start, gain in events:
        key = (path, gain)
        if key not in cache:
            src = _read_mono16(path)
            if gain != 1.0:
                src = array("h", (max(-32768, min(32767, int(s * gain))) for s in src))
            cache[key] = src
        src = cache[key]
        o = int(start * RATE)
        n = min(len(src), len(buf) - o)
        if n <= 0:
            continue
        if not any(a < o + n and o < b for a, b in used):
            buf[o : o + n] = src[:n]  # место свободно — просто копируем
        else:
            for i in range(n):  # наложение — складываем с ограничением
                v = buf[o + i] + src[i]
                buf[o + i] = 32767 if v > 32767 else (-32768 if v < -32768 else v)
        used.append((o, o + n))
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(buf.tobytes())


def mix(
    voice_parts: list[tuple[str, float]],
    sfx_events: list[tuple[str, float]],
    total: float,
    out: str,
    music_volume: float = 0.18,
) -> None:
    """voice_parts: (wav, время начала); sfx_events: (имя эффекта, время начала).
    Озвучка и эффекты собираются в две дорожки, затем ffmpeg сводит их с гулом или музыкой."""
    voice_wav, sfx_wav = out + ".voice.wav", out + ".sfx.wav"
    _build_track([(w, s, 1.0) for w, s in voice_parts], total, voice_wav)
    _build_track(
        [(f, s, 0.55) for name, s in sfx_events if (f := sfx_file(name))],
        total,
        sfx_wav,
    )

    inputs = ["-i", voice_wav, "-i", sfx_wav]
    music = sorted((ASSETS / "music").glob("*.mp3")) + sorted(
        (ASSETS / "music").glob("*.wav")
    )
    fade = f"afade=t=out:st={max(0, total - 1.5):.2f}:d=1.5"
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(random.choice(music))]
        bg = f"[2:a]aresample={RATE},aformat=channel_layouts=mono,volume={music_volume},atrim=0:{total:.2f},{fade}[bg]"
    else:  # тревожный низкий гул
        drone = (
            "aevalsrc='0.09*sin(2*PI*55*t)+0.06*sin(2*PI*82.4*t)+0.04*sin(2*PI*110.6*t)"
            f"*(0.6+0.4*sin(2*PI*0.25*t))':d={total:.2f}:s={RATE}"
        )
        inputs += ["-f", "lavfi", "-i", drone]
        bg = f"[2:a]lowpass=f=400,afade=t=in:d=1,{fade}[bg]"
    graph = (
        f"{bg};[0:a][1:a][bg]amix=inputs=3:normalize=0:duration=first,"
        f"atrim=0:{total:.2f},alimiter=limit=0.95[out]"
    )
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            *inputs,
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            "-ac",
            "2",
            "-ar",
            str(RATE),
            out,
        ],
        check=True,
    )
    for f in (voice_wav, sfx_wav):
        Path(f).unlink(missing_ok=True)
