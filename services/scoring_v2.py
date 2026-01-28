from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, Any

from .scoring_config import (
    P0,P1,S0,S1,W0,W1,A0,A1,PR0,PR1,SR0,SR1,WR0,WR1,AR0,AR1,V0,V1,
    HB0,HIND_ASYM0,FORE_ASYM0,
    DELTA_MAX, CAL_A0, CAL_A1, CAL_A2
)

def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x

def sat(x: float, a: float, b: float) -> float:
    if b <= a:
        return 0.0
    return clamp((x - a) / (b - a), 0.0, 1.0)

def rev(u: float) -> float:
    return 1.0 - u

def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)

@dataclass
class PaddockAIState:
    T: float = 50.0
    X: float = 50.0
    SW: float = 50.0
    BR: float = 50.0
    CO: float = 50.0
    F: float = 50.0
    AiConf: float = 0.3

def score_v2(
    *,
    q: float,
    pitch_hz: float,
    stride_index: float,
    wobble: float,
    asym: float,
    speed_proxy: float | None,
    roi_asym: Dict[str, float] | None,
    headbob_ratio: float | None,
    ai_state: PaddockAIState,
    ped_score: float = 50.0,
    ped_stamina: float = 50.0,
    ped_surfacefit: float = 50.0,
    race_match_override: float | None = None,
) -> Dict[str, Any]:
    # Confidence
    C_vid = 0.65 + 0.35 * clamp(q/100.0, 0.0, 1.0)

    # Item scores
    P = 100.0 * rev(sat(pitch_hz, P0, P1))
    S = 100.0 * sat(stride_index, S0, S1)
    W = 100.0 * rev(sat(wobble, W0, W1))
    A = 100.0 * rev(sat(asym, A0, A1))
    V = 50.0 if speed_proxy is None else 100.0 * sat(speed_proxy, V0, V1)

    # A) speed proxy integrated
    G = 0.18*P + 0.30*S + 0.22*W + 0.18*A + 0.12*V

    # Risk parts
    rp = 100.0 * sat(pitch_hz, PR0, PR1)
    rw = 100.0 * sat(wobble, WR0, WR1)
    ra = 100.0 * sat(asym, AR0, AR1)
    rs = 100.0 * rev(sat(stride_index, SR0, SR1))

    # B) clinical flags
    headbob_suspect = bool(headbob_ratio is not None and headbob_ratio > HB0)
    hind_asym_suspect = False
    fore_asym_suspect = False
    if roi_asym:
        hind_asym_suspect = roi_asym.get("hind", 0.0) > HIND_ASYM0
        fore_asym_suspect = roi_asym.get("head", 0.0) > FORE_ASYM0

    R_gait = 0.28*rp + 0.28*ra + 0.22*rw + 0.12*rs
    if headbob_suspect:
        R_gait += 10.0
    if hind_asym_suspect:
        R_gait += 10.0
    R_gait = clamp(R_gait, 0.0, 100.0)

    # AI state integration
    t = clamp(ai_state.T/100.0, 0.0, 1.0)
    x = clamp(ai_state.X/100.0, 0.0, 1.0)
    sw = clamp(ai_state.SW/100.0, 0.0, 1.0)
    br = clamp(ai_state.BR/100.0, 0.0, 1.0)
    co = clamp(ai_state.CO/100.0, 0.0, 1.0)
    f = clamp(ai_state.F/100.0, 0.0, 1.0)
    K_ai = 0.50 + 0.50 * clamp(ai_state.AiConf, 0.0, 1.0)

    PaddockState = 100.0 * clamp(0.30*t + 0.25*f + 0.30*co + 0.15*(1.0-x), 0.0, 1.0)
    PaddockState_ = (1.0-K_ai)*50.0 + K_ai*PaddockState

    Stress = clamp(0.45*x + 0.35*sw + 0.20*br, 0.0, 1.0)
    StressRisk_ = 100.0 * K_ai * Stress

    G_adj = clamp(G + 0.15*(PaddockState_ - 50.0), 0.0, 100.0)
    R_adj = clamp(R_gait + 0.30*StressRisk_, 0.0, 100.0)

    # Combine gait total
    GaitTotal_raw = clamp(G_adj - 0.35*R_adj, 0.0, 100.0)
    GaitTotal = GaitTotal_raw * C_vid

    # Match (simple, locked)
    if race_match_override is None:
        Dm = 0.5*S + 0.5*ped_stamina
        Sm = ped_surfacefit
        Cm = W
        M = clamp(0.45*Dm + 0.35*Sm + 0.20*Cm, 0.0, 100.0)
    else:
        M = clamp(race_match_override, 0.0, 100.0)

    # Total
    Total_raw = 0.65*GaitTotal + 0.20*ped_score + 0.15*M
    Total = clamp(Total_raw - 0.10*R_adj, 0.0, 100.0)

    # C) CI widens with low quality, score unchanged
    U = 1.0 - clamp(q/100.0, 0.0, 1.0)
    Delta = DELTA_MAX * U
    CI = (clamp(Total-Delta, 0.0, 100.0), clamp(Total+Delta, 0.0, 100.0))

    # D) calibrated probabilities (initial coefficients)
    z = CAL_A0 + CAL_A1*((Total-60.0)/8.0) + CAL_A2*((M-60.0)/10.0)
    Place = 100.0 * sigmoid(z) * 0.55
    Contend = 100.0 * sigmoid(z - 0.7) * 0.25

    return {
        "item_scores": {"P":P, "S":S, "W":W, "A":A, "V":V},
        "gait": {"G":G, "G_adj":G_adj, "GaitTotal":GaitTotal},
        "risk": {"R_gait":R_gait, "R_adj":R_adj, "stress_risk":StressRisk_, "paddock_state":PaddockState_},
        "match": {"M":M},
        "total": {"Total":Total, "CI":CI, "C_vid":C_vid},
        "prob": {"PlacePct":Place, "ContendPct":Contend},
        "clinical_flags": {
            "headbob_suspect": headbob_suspect,
            "hind_asym_suspect": hind_asym_suspect,
            "fore_asym_suspect": fore_asym_suspect,
        }
    }
