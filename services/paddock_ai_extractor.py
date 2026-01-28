from __future__ import annotations
import os
from .scoring_v2 import PaddockAIState

def extract_paddock_state_from_video(*, video_path: str, thumb_path: str | None = None) -> PaddockAIState:
    # Robust: if OPENAI_API_KEY missing, return defaults (never crash / never 500)
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        return PaddockAIState()
    # TODO: wire vision model call. For now keep defaults to lock schema.
    return PaddockAIState()
