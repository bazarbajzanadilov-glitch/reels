"""Путь к ffmpeg: системный, если есть, иначе встроенный из пакета imageio-ffmpeg."""

import shutil

FFMPEG = shutil.which("ffmpeg")
if not FFMPEG:
    import imageio_ffmpeg

    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
