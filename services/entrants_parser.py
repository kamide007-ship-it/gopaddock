from __future__ import annotations
import re
from typing import List, Dict, Any, Optional

def parse_entrants(text: str) -> List[Dict[str, Any]]:
    """Parse entrants from free text.

    Supported per line:
      - '馬名' (name only; rating defaults 50)
      - '馬名: 62' or '馬名 62'
      - '馬名,62'
    Returns list of {name, rating}.
    """
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines()]
    out: List[Dict[str, Any]] = []
    for ln in lines:
        if not ln:
            continue
        ln = ln.replace("，", ",").replace("：", ":")
        ln = re.sub(r"^[\-\*\•\s]+", "", ln)

        name = ln
        rating: Optional[float] = None

        if "," in ln:
            parts = [p.strip() for p in ln.split(",") if p.strip()]
            if len(parts) >= 2:
                name = parts[0]
                rating = _try_float(parts[1])

        if ":" in ln:
            parts = [p.strip() for p in ln.split(":") if p.strip()]
            if len(parts) >= 2:
                name = parts[0]
                rating = _try_float(parts[1])

        m = re.search(r"^(.*?)[\s]+(\d{1,3}(?:\.\d+)?)$", ln)
        if m:
            name = m.group(1).strip()
            rating = _try_float(m.group(2))

        name = (name or "").strip()
        if not name:
            continue

        if rating is None:
            rating = 50.0

        rating = max(0.0, min(100.0, float(rating)))
        out.append({"name": name, "rating": rating})
    return out

def _try_float(s: str) -> Optional[float]:
    try:
        return float(re.sub(r"[^0-9\.\-]", "", s))
    except Exception:
        return None
