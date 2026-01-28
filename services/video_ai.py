# services/video_ai.py
from __future__ import annotations

import os
import tempfile
from dataclasses import asdict
from typing import Any, Dict, Optional, Tuple

from .video_ai_client import post_to_video_ai
from .video_transcode import maybe_transcode_for_analysis
from .gait_features import extract_gait_features


def analyze_video_best_effort(
    video_path: str,
    *,
    video_public_url: Optional[str] = None,
    timeout_s: int = 40,
) -> Tuple[Dict[str, Any], list[str]]:
    """Analyze gait video with layered fallbacks.

    - If external VIDEO_AI service is configured, try it first.
      - If video_public_url is provided, URL-mode is attempted (and async if enabled).
      - Else, multipart upload is used (with optional MOV->MP4 transcode).
    - If external AI fails or isn't configured, fall back to local CV metrics.
    - Always returns (result_json, logs) and never raises.
    """
    logs: list[str] = []
    use_remote = bool((os.getenv("VIDEO_AI_URL") or os.getenv("VIDEO_AI_BASE_URL") or "").strip())

    # If URL-mode is available, prefer it (small payload, stable).
    if use_remote and video_public_url:
        payload = post_to_video_ai(video_path, timeout_s=timeout_s, video_public_url=video_public_url)
        if payload.get("ok"):
            logs.append("video_ai:url_mode:ok")
            return payload, logs
        logs.append(f"video_ai:url_mode:fail:{payload.get('detail') or payload.get('error')}")

    # Multipart mode: transcode MOV/HEVC -> MP4(H.264/AAC) if possible
    trans_path = None
    if use_remote and not video_public_url:
        try:
            trans_path = maybe_transcode_for_analysis(video_path)
            if trans_path and trans_path != video_path:
                logs.append("video_ai:transcoded_to_mp4")
            payload = post_to_video_ai(trans_path or video_path, timeout_s=timeout_s)
            if payload.get("ok"):
                logs.append("video_ai:multipart:ok")
                return payload, logs
            logs.append(f"video_ai:multipart:fail:{payload.get('detail') or payload.get('error')}")
        except Exception as e:
            logs.append(f"video_ai:multipart:exception:{type(e).__name__}:{e}")

    # Local CV fallback
    try:
        gf = extract_gait_features(video_path)
        payload = {
            "ok": True,
            "cv_metrics": {
                "quality": {"score_0_100": gf.quality_score_0_100, "issues": gf.quality_issues},
                "gait": {
                    "pitch_hz": gf.pitch_hz,
                    "stride_index": gf.stride_index,
                    "wobble_ratio_0_1": gf.wobble_ratio_0_1,
                    "speed_proxy": gf.speed_proxy,
                    "headbob_ratio": gf.headbob_ratio,
                },
                "asymmetry": {"lr_asymmetry_ratio": gf.lr_asym_0_1},
            },
            "detail": "local_cv_fallback",
        }
        logs.append("local_cv:ok")
        return payload, logs
    except Exception as e:
        logs.append(f"local_cv:fail:{type(e).__name__}:{e}")
        return {"ok": False, "error": "cv_failed", "detail": str(e)}, logs
