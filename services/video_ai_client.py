# services/video_ai_client.py
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

import requests

from .gait_features import extract_gait_features


@dataclass(frozen=True)
class Timeouts:
    connect: float
    read: float


def _get_base_url() -> str:
    # Prefer VIDEO_AI_URL for backward compatibility; accept VIDEO_AI_BASE_URL too.
    base = (os.getenv("VIDEO_AI_URL") or os.getenv("VIDEO_AI_BASE_URL") or "").strip()
    return base.rstrip("/")


def _timeouts_from_env() -> Timeouts:
    # Default: fail-fast connect, generous read, hard cap via AI_TOTAL_TIMEOUT_SECONDS.
    connect = float(os.getenv("AI_CONNECT_TIMEOUT_SECONDS", "10") or "10")
    read = float(os.getenv("AI_READ_TIMEOUT_SECONDS", "180") or "180")
    total = float(os.getenv("AI_TOTAL_TIMEOUT_SECONDS", "220") or "220")

    # Ensure connect+read does not exceed total (best effort)
    try:
        connect = max(0.5, connect)
        read = max(1.0, read)
        total = max(connect + 1.0, total)
        if connect + read > total:
            read = max(1.0, total - connect)
    except Exception:
        pass
    return Timeouts(connect=connect, read=read)


def _retry_policy_from_env() -> tuple[int, List[float]]:
    tries = int(os.getenv("AI_MAX_RETRIES", "1") or "1")
    backoff_raw = (os.getenv("AI_RETRY_BACKOFF_SECONDS", "") or "").strip()
    backoffs: List[float] = []
    if backoff_raw:
        for x in backoff_raw.split(","):
            x = x.strip()
            if not x:
                continue
            try:
                backoffs.append(float(x))
            except Exception:
                continue
    return max(1, tries), backoffs


def _async_mode() -> bool:
    return (os.getenv("AI_ASYNC_MODE", "0") or "0").strip() in ("1", "true", "True", "yes", "on")


def _max_concurrency() -> int:
    try:
        return max(1, int(os.getenv("AI_MAX_CONCURRENCY", "1") or "1"))
    except Exception:
        return 1


# NOTE: Very small deployment typically runs with 1 gunicorn worker.
# Concurrency guard here is best-effort per-process.
_SEM = None
def _acquire():
    global _SEM
    if _SEM is None:
        import threading
        _SEM = threading.Semaphore(_max_concurrency())
    _SEM.acquire()

def _release():
    global _SEM
    try:
        if _SEM is not None:
            _SEM.release()
    except Exception:
        pass


def _post_json(url: str, payload: Dict[str, Any], timeout: Timeouts) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    tries, backoffs = _retry_policy_from_env()
    last_err: Optional[str] = None

    for i in range(tries):
        if i > 0 and backoffs:
            time.sleep(max(0.0, backoffs[min(i - 1, len(backoffs) - 1)]))
        try:
            r = requests.post(
                url,
                json=payload,
                timeout=(timeout.connect, timeout.read),
                headers={"Accept": "application/json"},
            )
            if 200 <= r.status_code < 300:
                try:
                    return r.json(), None
                except Exception:
                    return None, f"invalid json from video ai (status={r.status_code})"
            last_err = f"video ai http {r.status_code}: {r.text[:200]}"
        except requests.Timeout:
            last_err = "video ai timeout"
        except Exception as e:
            last_err = f"video ai error: {type(e).__name__}: {e}"
    return None, last_err or "video ai request failed"


def _post_multipart(url: str, file_path: str, timeout: Timeouts) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    tries, backoffs = _retry_policy_from_env()
    last_err: Optional[str] = None

    for i in range(tries):
        if i > 0 and backoffs:
            time.sleep(max(0.0, backoffs[min(i - 1, len(backoffs) - 1)]))
        try:
            with open(file_path, "rb") as f:
                files = {"file": (os.path.basename(file_path), f, "video/mp4")}
                r = requests.post(url, files=files, timeout=(timeout.connect, timeout.read))
            if 200 <= r.status_code < 300:
                try:
                    return r.json(), None
                except Exception:
                    return None, f"invalid json from video ai (status={r.status_code})"
            last_err = f"video ai http {r.status_code}: {r.text[:200]}"
        except requests.Timeout:
            last_err = "video ai timeout"
        except Exception as e:
            last_err = f"video ai error: {type(e).__name__}: {e}"
    return None, last_err or "video ai request failed"


def _poll_job(base: str, job_id: str, timeout: Timeouts) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    # Poll until done or until total timeout window roughly elapses.
    t0 = time.time()
    total = float(os.getenv("AI_TOTAL_TIMEOUT_SECONDS", "220") or "220")
    poll = float(os.getenv("AI_JOB_POLL_SECONDS", "2") or "2")
    last_err: Optional[str] = None

    while True:
        if time.time() - t0 > total:
            return None, "video ai job timeout"
        try:
            r = requests.get(f"{base}/jobs/{job_id}", timeout=(timeout.connect, min(30.0, timeout.read)))
            if 200 <= r.status_code < 300:
                j = r.json()
                if bool(j.get("ok")) and j.get("status") in ("done", "succeeded", "success"):
                    return j.get("result") or j, None
                if j.get("status") in ("failed", "error"):
                    return None, str(j.get("detail") or j.get("error") or "job failed")
                # pending/running
                time.sleep(max(0.5, poll))
                continue
            last_err = f"job poll http {r.status_code}"
            time.sleep(max(0.5, poll))
        except requests.Timeout:
            last_err = "job poll timeout"
            time.sleep(max(0.5, poll))
        except Exception as e:
            last_err = f"job poll error: {type(e).__name__}: {e}"
            time.sleep(max(0.5, poll))


def analyze_video(
    video_abs_path: str,
    *,
    timeout_s: int = 40,
    video_public_url: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Call external Video-AI service (optional).

    Priority:
      1) If VIDEO_AI_URL/BASE_URL set and video_public_url is given:
           - AI_ASYNC_MODE=1 -> POST {base}/analyze_async_url, then poll /jobs/{id}
           - else            -> POST {base}/analyze_url
      2) Else if VIDEO_AI_URL/BASE_URL set:
           - POST {base}/analyze (multipart)
      3) Else:
           - local CV fallback (always available)

    This function NEVER raises; safe for production pipeline.
    """
    base = _get_base_url()
    timeout = _timeouts_from_env()

    # Local fallback
    if not base:
        try:
            gf = extract_gait_features(video_abs_path)
            return {
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
            }, None
        except Exception as e:
            return None, f"local cv failed: {type(e).__name__}: {e}"

    _acquire()
    try:
        # URL mode if available
        if video_public_url:
            if _async_mode():
                j, err = _post_json(f"{base}/analyze_async_url", {"video_url": video_public_url}, timeout)
                if j is None:
                    return None, err or "video ai async submit failed"
                job_id = j.get("job_id") or j.get("id")
                if not job_id:
                    return None, "video ai async: missing job_id"
                return _poll_job(base, str(job_id), timeout)
            else:
                j, err = _post_json(f"{base}/analyze_url", {"video_url": video_public_url}, timeout)
                if j is not None:
                    return j, None
                # If analyze_url not supported, fall back to multipart below.
                # Continue to multipart.

        # Multipart mode
        j, err = _post_multipart(f"{base}/analyze", video_abs_path, timeout)
        return j, err
    finally:
        _release()


# Backward-compatible helper name used by services/video_ai.py
def post_to_video_ai(video_abs_path: str, *, timeout_s: int = 40, video_public_url: Optional[str] = None) -> Dict[str, Any]:
    payload, err = analyze_video(video_abs_path, timeout_s=timeout_s, video_public_url=video_public_url)
    if payload is not None:
        return payload
    return {"ok": False, "error": "video_ai_failed", "detail": err or "unknown"}
