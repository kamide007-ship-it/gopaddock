from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple


def _get_ffmpeg_cmd() -> Optional[str]:
    """Return path to ffmpeg binary if available.

    Render では apt-get で ffmpeg を入れられない構成があるため、
    `imageio-ffmpeg` が入っている場合は同梱バイナリを優先します。
    """

    # Prefer imageio-ffmpeg bundled binary
    try:
        import imageio_ffmpeg  # type: ignore

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except Exception:
        pass

    # Fallback to system ffmpeg
    exe2 = shutil.which("ffmpeg")
    if exe2:
        return exe2

    return None


def _run_ffmpeg(args: list[str], *, timeout_seconds: int = 600) -> Tuple[bool, str]:
    """Run ffmpeg safely and return (ok, stderr_tail)."""
    try:
        p = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        err = (p.stderr or b"").decode("utf-8", errors="ignore")
        return (p.returncode == 0, err[-2000:])
    except subprocess.TimeoutExpired:
        return (False, "ffmpeg timeout")
    except Exception as e:
        return (False, f"ffmpeg failed: {e}")


def transcode_to_mp4_h264(
    input_path: str,
    *,
    output_path: Optional[str] = None,
    timeout_seconds: int = 600,
) -> Tuple[Optional[str], str]:
    """Best-effort transcode to MP4 (H.264/AAC).

    Returns (output_path_or_none, log_message).
    - ffmpeg がない環境では None を返します（アプリは落としません）。
    - 音声が無い/壊れているケースがあるため、AAC 失敗時は -an で再試行します。
    """

    ffmpeg = _get_ffmpeg_cmd()
    if not ffmpeg:
        return None, "ffmpeg not found (install imageio-ffmpeg or provide system ffmpeg)"

    inp = Path(input_path)
    if not inp.exists():
        return None, f"input not found: {input_path}"

    out = Path(output_path) if output_path else inp.with_suffix("").with_name(inp.stem + "_h264.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)

    # Keep output small-ish and fast to decode
    base_cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(inp),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        os.environ.get("FFMPEG_X264_PRESET", "veryfast"),
        "-crf",
        os.environ.get("FFMPEG_X264_CRF", "23"),
        "-movflags",
        "+faststart",
    ]

    # 1) Try with AAC audio
    cmd1 = base_cmd + ["-c:a", "aac", "-b:a", "128k", str(out)]
    ok, tail = _run_ffmpeg(cmd1, timeout_seconds=timeout_seconds)
    if ok and out.exists() and out.stat().st_size > 0:
        return str(out), "transcoded mp4(h264/aac)"

    # 2) Retry without audio (some MOVs have unsupported audio codec)
    cmd2 = base_cmd + ["-an", str(out)]
    ok2, tail2 = _run_ffmpeg(cmd2, timeout_seconds=timeout_seconds)
    if ok2 and out.exists() and out.stat().st_size > 0:
        return str(out), "transcoded mp4(h264) without audio"

    # Cleanup broken output
    try:
        if out.exists():
            out.unlink()
    except Exception:
        pass

    return None, f"transcode failed: {tail2 or tail}"


def maybe_transcode_for_analysis(video_path: Optional[str]) -> Tuple[Optional[str], str]:
    """If input is MOV/HEVC-likely, try to transcode to MP4(H.264).

    Returns (path_to_use, note).
    """

    if not video_path:
        return None, "no video"

    p = Path(video_path)
    ext = p.suffix.lower()

    enabled = os.environ.get("VIDEO_TRANSCODE", "1").strip() not in ("0", "false", "False")
    if not enabled:
        return video_path, "transcode disabled"

    if ext in (".mov", ".m4v"):
        out, note = transcode_to_mp4_h264(video_path, timeout_seconds=int(os.environ.get("VIDEO_TRANSCODE_TIMEOUT_SECONDS", "600")))
        return (out or video_path, note)

    # For .mp4, still accept (some iPhone mp4 are HEVC), but do not force by default.
    # You can force by setting VIDEO_TRANSCODE_FORCE=1
    force = os.environ.get("VIDEO_TRANSCODE_FORCE", "0").strip() in ("1", "true", "True")
    if force:
        out, note = transcode_to_mp4_h264(video_path, timeout_seconds=int(os.environ.get("VIDEO_TRANSCODE_TIMEOUT_SECONDS", "600")))
        return (out or video_path, note)

    return video_path, "no transcode needed"
