from __future__ import annotations
import random
from typing import List, Dict, Any

def simulate_finish_probs(
    *,
    our_mu: float,
    entrants: List[Dict[str, Any]],
    n: int = 3000,
    sigma: float = 10.0,
) -> Dict[str, Any]:
    """Monte Carlo rank probability model.

    Performance_i ~ Normal(mu_i, sigma). Higher is better.
    Returns win/top3/top5/expected_rank.
    """
    opp = entrants or []
    mus = [float(our_mu)] + [float(e.get("rating", 50.0)) for e in opp]
    m = len(mus)
    if m <= 1:
        return {"ok": True, "n": int(n), "field_size": 1, "win": 1.0, "top3": 1.0, "top5": 1.0, "expected_rank": 1.0, "sigma": float(sigma)}

    win = 0
    top3 = 0
    top5 = 0
    rank_sum = 0.0

    nn = int(max(200, n))
    for _ in range(nn):
        perf = [random.gauss(mu, sigma) for mu in mus]
        order = sorted(range(m), key=lambda i: perf[i], reverse=True)
        r = order.index(0) + 1
        rank_sum += r
        if r == 1: win += 1
        if r <= 3: top3 += 1
        if r <= 5: top5 += 1

    return {
        "ok": True,
        "n": nn,
        "field_size": m,
        "win": win/nn,
        "top3": top3/nn,
        "top5": top5/nn,
        "expected_rank": rank_sum/nn,
        "sigma": float(sigma),
    }


# Backward-compatible name used by the rest of the app.
def estimate_race_probs(
    *,
    our_mu: float,
    entrants: List[Dict[str, Any]],
    n: int = 3000,
    sigma: float = 10.0,
) -> Dict[str, Any]:
    """Compatibility wrapper.

    The evaluator imports `estimate_race_probs`. Internally we keep the
    implementation in `simulate_finish_probs`.
    """
    return simulate_finish_probs(our_mu=our_mu, entrants=entrants, n=n, sigma=sigma)
