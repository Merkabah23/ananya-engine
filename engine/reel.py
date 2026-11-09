"""Turn a post's rendered slides into one 9:16 reel: each slide framed for the reel screen and held for a fixed
beat, with a short crossfade between screens.

ffmpeg comes from the imageio-ffmpeg wheel (no system install, same binary locally and in Actions). The reel is
silent with an empty audio track; trending audio, if any, is the owner's call in the Instagram app."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image


REEL = (1080, 1920)
TOP = 220            # the 4:5 slide sits high: Instagram's caption, handle and buttons cover the bottom of a reel
COVER_HOLD = 2.0     # the hook stops the scroll; it is not read slowly (owner: 3s was too slow)
SLIDE_HOLD = 3.0     # owner, 9 Nov 2026: every slide holds 3s (2.5s felt too fast, 4s too slow)
FADE = 0.3
FPS = 30


def holds(alt_texts: list[str], n: int) -> list[float]:
    """Seconds on screen for each of n slides: the cover, then every reading slide and the end card."""
    return [COVER_HOLD] + [SLIDE_HOLD] * (n - 1)


def frame(slide: Path, out: Path) -> Path:
    """The 1080x1350 slide on a 1080x1920 screen, the bands filled with the slide's own edge colour so it reads as one."""
    img = Image.open(slide).convert("RGB")
    screen = Image.new("RGB", REEL, img.getpixel((4, 4)))
    bottom = img.getpixel((4, img.height - 4))
    screen.paste(Image.new("RGB", (REEL[0], REEL[1] - TOP - img.height), bottom), (0, TOP + img.height))
    screen.paste(img, (0, TOP))
    screen.save(out, "JPEG", quality=95)
    return out


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def build(slides: list[Path], alt_texts: list[str], out: Path) -> tuple[Path, float]:
    """Write the reel to `out`; returns the path and its length in seconds."""
    durs = holds(alt_texts, len(slides))
    frames = [frame(s, s.with_name(s.stem + "_reel.jpg")) for s in slides]
    cmd = [ffmpeg(), "-y", "-loglevel", "error"]
    for f, d in zip(frames, durs):
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d + FADE:.2f}", "-i", str(f)]
    cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    chain, last, offset = [], "[0:v]", 0.0
    for k in range(1, len(frames)):
        offset += durs[k - 1]
        chain.append(f"{last}[{k}:v]xfade=transition=fade:duration={FADE}:offset={offset:.2f}[v{k}]")
        last = f"[v{k}]"
    total = round(sum(durs) + FADE, 2)
    graph = ";".join(chain) + (";" if chain else "") + f"{last}scale=out_range=tv,format=yuv420p[v]"
    cmd += ["-filter_complex", graph, "-map", "[v]", "-map", f"{len(frames)}:a", "-t", f"{total:.2f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-color_range", "tv",
            "-r", str(FPS), "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    for f in frames:
        f.unlink(missing_ok=True)
    return out, total
