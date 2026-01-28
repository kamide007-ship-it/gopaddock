from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None  # type: ignore


def summarize_pedigree(*, sire: str, dam: str, damsire: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Summarize pedigree traits using OpenAI text model (no browsing).

    Safe behavior:
      - If OPENAI_API_KEY missing => returns (None, reason)
      - Never raises
    """
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        return None, "OPENAI_API_KEY not set"

    if OpenAI is None:
        return None, "openai package not installed"

    model = (os.getenv("GPT_TEXT_MODEL") or "gpt-4.1-mini").strip()
    client = OpenAI(api_key=key)

    prompt = f"""You are an equine analyst. Based ONLY on general, widely-known pedigree tendencies (no browsing), summarize likely traits.

Sire: {sire}
Dam: {dam}
Dam-sire: {damsire}

Return JSON with keys:
- temperament (short)
- speed (short)
- stamina (short)
- durability (short)
- surface (short)
- notes (short)

Avoid definitive claims; use probabilistic language.
"""

    try:
        resp = client.responses.create(
            model=model,
            input=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        txt = getattr(resp, "output_text", None) or ""
        if not txt:
            # fallback if SDK returns structured blocks
            try:
                txt = resp.output[0].content[0].text  # type: ignore[attr-defined]
            except Exception:
                txt = ""
        import json as _json
        data = _json.loads(txt) if txt else {}
        return data, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
