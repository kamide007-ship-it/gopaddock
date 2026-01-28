from __future__ import annotations

import cv2
import numpy as np
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

@dataclass
class GaitFeatures:
    pitch_hz: float
    stride_index: float
    wobble_ratio_0_1: float
    lr_asym_0_1: float
    speed_proxy: Optional[float]
    roi_asym: Dict[str, float]
    headbob_ratio: Optional[float]
    quality_score_0_100: float
    quality_issues: list[str]

def _safe_div(a: float, b: float, eps: float = 1e-6) -> float:
    return float(a) / float(b + eps)

def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x

def estimate_quality(frame: np.ndarray) -> Tuple[float, list[str]]:
    issues: list[str] = []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    fm = cv2.Laplacian(gray, cv2.CV_64F).var()
    if fm < 80:
        issues.append("blur")
    mean = float(gray.mean())
    if mean < 60:
        issues.append("dark")
    if mean > 210:
        issues.append("overexposed")
    blur_score = _clip01((fm - 40) / 200)
    bright_score = 1.0 - _clip01(abs(mean - 130) / 130)
    score = 100.0 * (0.6*blur_score + 0.4*bright_score)
    return score, issues

def extract_gait_features(video_path: str, max_frames: int = 240) -> GaitFeatures:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("Failed to open video")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    frames = []
    while len(frames) < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    if len(frames) < 10:
        raise RuntimeError("Too few frames")

    q0, issues0 = estimate_quality(frames[0])

    h, w = frames[0].shape[:2]
    x0, y0, x1, y1 = int(w*0.25), int(h*0.15), int(w*0.75), int(h*0.90)

    def roi_rect(part: str):
        bh = y1 - y0
        if part == "head":
            return (x0, y0, x1, y0 + bh//3)
        if part == "trunk":
            return (x0, y0 + bh//3, x1, y0 + 2*bh//3)
        return (x0, y0 + 2*bh//3, x1, y1)

    prev = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)

    flow_mags = []
    drift = []
    head_ud = []
    trunk_ud = []
    lr_energy = []
    roi_lr_energy = {"head": [], "trunk": [], "hind": []}
    speed_norms = []

    for i in range(1, len(frames)):
        curr = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(prev, curr, None, 0.5, 3, 15, 3, 5, 1.2, 0)

        fb = flow[y0:y1, x0:x1]
        mag = np.sqrt(fb[...,0]**2 + fb[...,1]**2)
        flow_mags.append(float(np.mean(mag)))

        dx = float(np.mean(fb[...,0]))
        dy = float(np.mean(fb[...,1]))
        drift.append((dx, dy))

        mid = (x1 - x0)//2
        left = fb[:, :mid]
        right = fb[:, mid:]
        eL = float(np.mean(np.sqrt(left[...,0]**2 + left[...,1]**2)))
        eR = float(np.mean(np.sqrt(right[...,0]**2 + right[...,1]**2)))
        lr_energy.append((eL, eR))

        for part in ("head","trunk","hind"):
            rx0, ry0, rx1, ry1 = roi_rect(part)
            r = flow[ry0:ry1, rx0:rx1]
            midr = (rx1 - rx0)//2
            l = r[:, :midr]
            rr = r[:, midr:]
            eLr = float(np.mean(np.sqrt(l[...,0]**2 + l[...,1]**2)))
            eRr = float(np.mean(np.sqrt(rr[...,0]**2 + rr[...,1]**2)))
            roi_lr_energy[part].append((eLr, eRr))

        hx0, hy0, hx1, hy1 = roi_rect("head")
        tx0, ty0, tx1, ty1 = roi_rect("trunk")
        head_ud.append(float(np.mean(flow[hy0:hy1, hx0:hx1, 1])))
        trunk_ud.append(float(np.mean(flow[ty0:ty1, tx0:tx1, 1])))

        # A) speed proxy: forward flow after removing pan (dx), normalized by bbox height
        fwd = fb[...,0] - dx
        vpx = float(np.median(fwd))
        scale = float(y1 - y0)
        speed_norms.append(vpx / (scale + 1e-6))

        prev = curr

    dxs = np.array([d[0] for d in drift], dtype=np.float32)
    dys = np.array([d[1] for d in drift], dtype=np.float32)
    drift_std = float(np.sqrt(np.var(dxs) + np.var(dys)))
    wobble = _clip01(drift_std / 6.0)

    mags = np.array(flow_mags, dtype=np.float32)
    mags = mags - np.mean(mags)
    if np.allclose(mags, 0):
        pitch_hz = 2.0
    else:
        ac = np.correlate(mags, mags, mode="full")[len(mags)-1:]
        ac[0] = 0
        peak = int(np.argmax(ac[:max(5, len(ac)//2)]))
        period_frames = max(2, peak)
        pitch_hz = float(fps / period_frames)

    motion_mag_mean = float(np.mean(np.abs(flow_mags)))
    stride_index = float(motion_mag_mean / (pitch_hz + 1e-6))

    eLs = np.array([x[0] for x in lr_energy], dtype=np.float32)
    eRs = np.array([x[1] for x in lr_energy], dtype=np.float32)
    lr_asym = float(np.mean(np.abs(eLs - eRs) / (eLs + eRs + 1e-6)))
    lr_asym = _clip01(lr_asym)

    roi_asym: Dict[str, float] = {}
    for part in ("head","trunk","hind"):
        eLr = np.array([x[0] for x in roi_lr_energy[part]], dtype=np.float32)
        eRr = np.array([x[1] for x in roi_lr_energy[part]], dtype=np.float32)
        roi_asym[part] = float(np.mean(np.abs(eLr - eRr) / (eLr + eRr + 1e-6)))
        roi_asym[part] = _clip01(roi_asym[part])

    head_amp = float(np.std(np.array(head_ud, dtype=np.float32)))
    trunk_amp = float(np.std(np.array(trunk_ud, dtype=np.float32)))
    headbob_ratio = _safe_div(head_amp, trunk_amp, 1e-6)

    speed_proxy = float(np.median(np.array(speed_norms, dtype=np.float32))) if speed_norms else None

    issues = list(issues0)
    if wobble > 0.55:
        issues.append("shake")
    quality_score = float(max(0.0, min(100.0, q0 - 30.0*wobble)))

    return GaitFeatures(
        pitch_hz=pitch_hz,
        stride_index=stride_index,
        wobble_ratio_0_1=wobble,
        lr_asym_0_1=lr_asym,
        speed_proxy=speed_proxy,
        roi_asym=roi_asym,
        headbob_ratio=headbob_ratio,
        quality_score_0_100=quality_score,
        quality_issues=issues,
    )
