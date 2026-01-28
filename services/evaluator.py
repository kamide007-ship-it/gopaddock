from __future__ import annotations

import os
import re
from dataclasses import asdict
from typing import Any, Dict, Optional, Tuple

from .gait_features_v2 import extract_gait_features
from .pedigree_ai_strict import analyze_pedigree_strict
from .scoring_v2 import score_v2
from .race_match_v2 import compute_match_M
from .racecard_fetcher import fetch_racecard, build_entrants_with_ratings
from .entrants_parser import parse_entrants
from .race_prob_model import estimate_race_probs


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _safe_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _infer_track_profile(*, notes: str, race_url: str) -> Dict[str, Any]:
    """Best-effort track profile inference.

    We avoid hard scraping rules here and instead parse user-provided notes
    and any obvious keywords in the URL.
    """
    t = (notes or "")
    u = (race_url or "")
    direction: Optional[str] = None
    if "右" in t:
        direction = "right"
    if "左" in t:
        # if both mentioned, set unknown
        direction = "left" if direction is None else "unknown"

    corner: Optional[str] = None
    if any(k in t for k in ["小回り", "タイト", "コーナーきつ"]):
        corner = "tight"
    elif any(k in t for k in ["大回り", "ゆるい", "コーナー緩"]):
        corner = "wide"

    surface_hint: Optional[str] = None
    if any(k in t for k in ["芝", "turf", "grass"]):
        surface_hint = "turf"
    if any(k in t for k in ["ダ", "ダート", "dirt", "sand"]):
        surface_hint = "dirt"

    # track name hints from URL (very light)
    track_name: Optional[str] = None
    for name in ["sapporo","hakodate","fukushima","niigata","tokyo","nakayama","chukyo","kyoto","hanshin","kokura",
                 "saga","morioka","mizusawa","ooi","funabashi","urawa","kawasaki","nagoya","kanazawa","sonoda","himeji"]:
        if name in u.lower():
            track_name = name
            break

    return {
        "direction": direction or "unknown",
        "corner": corner or "unknown",
        "surface_hint": surface_hint or "unknown",
        "track_name": track_name or "unknown",
        "source": "notes/url-best-effort",
    }


def _extract_opponents_from_text(opponents_text: str) -> list[str]:
    text = opponents_text or ""
    # commas / newlines / Japanese commas
    parts = re.split(r"[\n,、]+", text)
    out: list[str] = []
    for p in parts:
        p = _normalize_text(p)
        if not p:
            continue
        out.append(p[:40])
    return out[:40]


def _build_entrants_from_text(opponent_text: str) -> list[dict[str, Any]]:
    """Parse user-provided opponent list (best-effort)."""
    parsed = parse_entrants(opponent_text or "")
    out: list[dict[str, Any]] = []
    for it in parsed:
        nm = _normalize_text(str(it.get("name") or ""))
        if not nm:
            continue
        rating = _safe_float(it.get("rating"), 50.0)
        out.append({"name": nm[:40], "rating": float(_clamp(rating, 30.0, 90.0))})
    return out[:40]


def evaluate_horse(
    *,
    horse_name: str = "",
    race_url: str = "",
    sire: str = "",
    dam: str = "",
    damsire: str = "",
    notes: str = "",
    opponent_text: str = "",
    video_path: str | None = None,
    ai_state: PaddockAIState | None = None,
) -> Dict[str, Any]:
    """Main evaluation pipeline (v2 locked).

    - Works without OPENAI_API_KEY and without VIDEO_AI_URL (no crash).
    - Produces a stable JSON output with all key sections always present.
    """
    horse_name_n = _normalize_text(horse_name) or "(no_name)"
    race_url_n = _normalize_text(race_url)
    notes_n = (notes or "").strip()

    # 1) Video -> gait features (local CV) + optional external AI (best-effort)
    gait: Dict[str, Any] = {
        "ok": False,
        "quality": {"score_0_100": 0, "issues": ["no_video"], "re_shoot_tips": ["歩様動画を追加すると精度が上がります。"]},
        "motion": {"ok": False},
        "asymmetry": {"asym_ok": False},
        "signals": {},
    }
    if video_path:
        try:
            gait = extract_gait_features(video_path)
        except Exception as e:
            gait = {
                "ok": False,
                "quality": {"score_0_100": 0, "issues": ["cv_error"], "re_shoot_tips": ["動画が破損している可能性があります。別の動画で再試行してください。"]},
                "motion": {"ok": False},
                "asymmetry": {"asym_ok": False},
                "signals": {"error": str(e)[:200]},
            }

    q = _safe_float(((gait.get("quality") or {}).get("score_0_100")), 0.0)
    sig = gait.get("signals") or {}
    pitch_hz = _safe_float(sig.get("pitch_hz"), 2.0)
    stride_index = _safe_float(sig.get("stride_index"), 0.55)
    wobble = _safe_float(sig.get("wobble"), 0.30)
    asym = _safe_float(sig.get("lr_asymmetry_ratio"), 0.10)
    speed_proxy = sig.get("speed_proxy")
    try:
        speed_proxy_f = float(speed_proxy) if speed_proxy is not None else None
    except Exception:
        speed_proxy_f = None
    roi_asym = sig.get("roi_asym") if isinstance(sig.get("roi_asym"), dict) else None
    headbob_ratio = sig.get("headbob_ratio") if sig.get("headbob_ratio") is not None else None
    try:
        headbob_ratio_f = float(headbob_ratio) if headbob_ratio is not None else None
    except Exception:
        headbob_ratio_f = None

    # 2) Pedigree (strict JSON, safe fallback)
    pedigree_text = _normalize_text(" ".join([p for p in [sire, dam, damsire] if p]))
    ped = analyze_pedigree_strict(pedigree_text=pedigree_text)
    ped_score = _safe_float(ped.get("ped_score"), 50.0)
    ped_stamina = _safe_float(ped.get("ped_stamina"), 50.0)
    ped_surfacefit = _safe_float(ped.get("ped_surfacefit"), 50.0)

    # 3) Race conditions (best-effort from URL + manual opponents)
    opponents = _extract_opponents_from_text(opponent_text)
    racecard = None
    entrants = None
    if race_url_n and not opponents:
        # If URL provided but opponents not, try best-effort extraction.
        try:
            racecard = fetch_racecard(race_url_n)
            if isinstance(racecard, dict) and racecard.get("entrants"):
                opponents = [str(x.get("name") or "").strip() for x in (racecard.get("entrants") or [])]
            elif isinstance(racecard, dict) and racecard.get("html"):
                parsed = parse_entrants(str(racecard.get("html") or ""))
                opponents = [str(x.get("name") or "").strip() for x in parsed]
        except Exception:
            racecard = None

    # 4) Match (track correction hybrid)
    track_profile = _infer_track_profile(notes=notes_n, race_url=race_url_n)
    M = compute_match_M(
        gait_item_scores={
            "P": 100.0 * (1.0 - _clamp((pitch_hz - 1.8) / max(0.001, (2.8 - 1.8)), 0.0, 1.0)),
            "S": 100.0 * _clamp((stride_index - 0.35) / max(0.001, (0.75 - 0.35)), 0.0, 1.0),
            "W": 100.0 * (1.0 - _clamp((wobble - 0.12) / max(0.001, (0.40 - 0.12)), 0.0, 1.0)),
            "A": 100.0 * (1.0 - _clamp((asym - 0.03) / max(0.001, (0.20 - 0.03)), 0.0, 1.0)),
            "V": 50.0 if speed_proxy_f is None else 100.0 * _clamp((speed_proxy_f - 0.8) / max(0.001, (1.6 - 0.8)), 0.0, 1.0),
        },
        ped={
            "ped_stamina": ped_stamina,
            "ped_surfacefit": ped_surfacefit,
            "ped_turfiness_0_1": _safe_float(ped.get("ped_turfiness_0_1"), 0.5),
        },
        track_profile=track_profile,
    )

    # 5) Score
    state = ai_state or PaddockAIState()
    v2 = score_v2(
        q=q,
        pitch_hz=pitch_hz,
        stride_index=stride_index,
        wobble=wobble,
        asym=asym,
        speed_proxy=speed_proxy_f,
        roi_asym=roi_asym,
        headbob_ratio=headbob_ratio_f,
        ai_state=state,
        ped_score=ped_score,
        ped_stamina=ped_stamina,
        ped_surfacefit=ped_surfacefit,
        race_match_override=M,
    )

    # 6) Race probabilities (only meaningful if opponents exist)
    probs = estimate_race_probs(
        total_score=_safe_float((v2.get("total") or {}).get("Total"), 50.0),
        opponents=opponents,
    )

    return {
        "ok": True,
        "version": "v2.11.0",
        "horse": {
            "name": horse_name_n,
            "sire": _normalize_text(sire),
            "dam": _normalize_text(dam),
            "damsire": _normalize_text(damsire),
        },
        "inputs": {
            "race_url": race_url_n,
            "notes": notes_n,
            "opponents_count": len(opponents),
            "track_profile": track_profile,
            "ai_state": asdict(state),
        },
        "cv_metrics": gait,
        "pedigree": ped,
        "match": {"M": M},
        "scores": v2,
        "race": {
            "opponents": opponents,
            "racecard": {"ok": bool(racecard and racecard.get("ok")), "source": racecard.get("source") if isinstance(racecard, dict) else None},
            "entrants": entrants if isinstance(entrants, dict) else None,
        },
        "race_probs": probs,
        "notes": {
            "ai_env": {
                "OPENAI_API_KEY": bool((os.getenv("OPENAI_API_KEY") or "").strip()),
                "VIDEO_AI_URL": bool((os.getenv("VIDEO_AI_URL") or "").strip()),
            },
            "safety": "AI未設定時は自動スキップ。失敗してもアプリは落ちません。",
        },
    }
