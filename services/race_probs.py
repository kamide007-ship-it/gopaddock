from __future__ import annotations

from typing import Any, Dict, List

from .race_prob_model import estimate_race_probs
from .racecard_fetcher import build_entrants_with_ratings


def _opponents_from_text(text: str) -> List[str]:
    names: List[str] = []
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        # remove bullet/numbering
        s = s.lstrip("・*-0123456789. ")
        if s:
            names.append(s)
    return names


def montecarlo_race_probs(
    *,
    horse_name: str,
    horse_rating_0_100: float,
    opponents_text: str,
    n_sims: int = 3000,
) -> Dict[str, Any]:
    """Return win/top3/top5 and expected rank probabilities.

    This is deliberately "best effort": if opponents_text is empty, returns a trivial
    single-runner distribution.
    """
    opponents = _opponents_from_text(opponents_text)
    entrants = build_entrants_with_ratings(
        horse_name=horse_name,
        horse_rating=float(horse_rating_0_100),
        opponent_names=opponents,
    )
    return estimate_race_probs(entrants, n_sims=max(500, int(n_sims)))
