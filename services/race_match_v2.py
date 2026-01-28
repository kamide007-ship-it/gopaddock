from __future__ import annotations

from typing import Dict, Optional, Tuple


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _get(d: Dict[str, float], key: str, default: float = 50.0) -> float:
    try:
        v = float(d.get(key, default))
        if v != v:  # NaN
            return default
        return v
    except Exception:
        return default


def _infer_surface_from_track(track_profile: Optional[dict]) -> Optional[str]:
    if not track_profile:
        return None
    s = (track_profile.get("surface") or "").strip().lower()
    if s in ("turf", "grass", "芝"):
        return "turf"
    if s in ("dirt", "sand", "ダート", "砂"):
        return "dirt"
    return None


def _infer_turn_from_track(track_profile: Optional[dict]) -> Optional[str]:
    if not track_profile:
        return None
    t = (track_profile.get("turn") or "").strip().lower()
    if t in ("left", "右回り", "right"):
        # NOTE: Japanese terms are reversed in wording; we treat explicit English.
        return "left" if t == "left" else "right" if t == "right" else None
    if t in ("right",):
        return "right"
    if t in ("left",):
        return "left"
    if t in ("右", "右回り"):
        return "right"
    if t in ("左", "左回り"):
        return "left"
    return None


def compute_match_M(
    gait_item_scores: Dict[str, float],
    pedigree: Optional[dict],
    race: Optional[dict],
    track_profile: Optional[dict] = None,
) -> Dict[str, float]:
    """Compute match score (0-100) between current horse state and race conditions.

    This is a deterministic, locked rule-based layer (not AI) so clinicians can audit it.
    Inputs are already normalized to 0-100 sub-scores in gait_item_scores.

    Returns:
      {
        "match_0_100": float,
        "components": { ... },
      }
    """

    race = race or {}
    surface = (race.get("surface") or _infer_surface_from_track(track_profile) or "unknown").lower()
    dist_m = float(race.get("distance_m") or 0.0)
    turn = (race.get("turn") or _infer_turn_from_track(track_profile) or "unknown").lower()
    corner = ((track_profile or {}).get("corner") or "unknown").lower()
    going = ((track_profile or {}).get("going") or "unknown").lower()

    # Core gait signals (0..100)
    stride = _get(gait_item_scores, "S", 50.0)
    pitch = _get(gait_item_scores, "P", 50.0)
    stability = _get(gait_item_scores, "W", 50.0)
    symmetry = _get(gait_item_scores, "A", 50.0)
    fatigue = _get(gait_item_scores, "F", 50.0)
    speed = _get(gait_item_scores, "V", 50.0)

    ped_speed = 50.0
    ped_stamina = 50.0
    ped_durable = 50.0
    try:
        if pedigree and isinstance(pedigree, dict):
            ps = pedigree.get("scores", {}) if isinstance(pedigree.get("scores"), dict) else {}
            ped_speed = float(ps.get("speed", ped_speed))
            ped_stamina = float(ps.get("stamina", ped_stamina))
            ped_durable = float(ps.get("durability", ped_durable))
    except Exception:
        pass

    # Distance preference proxy
    if dist_m <= 0:
        dist_pref = 50.0
    elif dist_m <= 1400:
        dist_pref = 0.65 * ped_speed + 0.35 * speed
    elif dist_m <= 1800:
        dist_pref = 0.45 * ped_speed + 0.55 * ped_stamina
    else:
        dist_pref = 0.25 * ped_speed + 0.75 * ped_stamina

    # Surface suitability proxy
    if surface == "turf":
        surf_pref = 0.45 * ped_speed + 0.25 * stability + 0.30 * symmetry
    elif surface == "dirt":
        surf_pref = 0.35 * ped_durable + 0.25 * fatigue + 0.20 * stability + 0.20 * symmetry
    else:
        surf_pref = 0.5 * ped_durable + 0.5 * stability

    # Corner / turn demands
    corner_adj = 0.0
    if corner in ("tight", "small", "小回り"):
        # Tight corners punish wobble and low stability; also favor shorter (not too long) stride.
        corner_adj += 0.18 * (stability - 50.0)
        corner_adj += 0.10 * (symmetry - 50.0)
        corner_adj += 0.06 * (_clamp(70.0 - stride, -50.0, 50.0))  # too long stride -> slight penalty
    elif corner in ("wide", "large", "大回り"):
        # Wide tracks reward stride efficiency.
        corner_adj += 0.12 * (stride - 50.0)
        corner_adj += 0.06 * (stability - 50.0)

    # Going / footing
    going_adj = 0.0
    if going in ("heavy", "soft", "mud", "sloppy", "不良", "重"):
        # Bad going punishes fatigue risk and low durability.
        going_adj += 0.14 * (fatigue - 50.0)
        going_adj += 0.10 * (ped_durable - 50.0)
        going_adj += 0.06 * (symmetry - 50.0)

    # Turn direction: we cannot know inside/outside limb without multi-angle,
    # so we only apply a very small penalty if asymmetry is poor and direction is known.
    turn_adj = 0.0
    if turn in ("left", "right") and symmetry < 45.0:
        turn_adj -= (45.0 - symmetry) * 0.12

    base = 0.42 * dist_pref + 0.38 * surf_pref + 0.10 * stability + 0.10 * symmetry
    match = _clamp(base + corner_adj + going_adj + turn_adj, 0.0, 100.0)

    return {
        "match_0_100": round(match, 2),
        "components": {
            "dist_pref": round(_clamp(dist_pref, 0.0, 100.0), 2),
            "surf_pref": round(_clamp(surf_pref, 0.0, 100.0), 2),
            "corner_adj": round(corner_adj, 2),
            "going_adj": round(going_adj, 2),
            "turn_adj": round(turn_adj, 2),
            "surface": surface,
            "distance_m": dist_m,
            "turn": turn,
            "corner": corner,
            "going": going,
        },
    }
