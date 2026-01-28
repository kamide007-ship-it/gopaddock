from __future__ import annotations

import re
from typing import Dict, Any, List, Optional
import requests

def _uniq(seq: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in seq:
        x = (x or "").strip()
        if not x:
            continue
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out

def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x

def _rating_from_poprank(rank: Optional[int], field_size: int) -> float:
    # rank 1 is strongest. Map to 70..40 range (gentle slope)
    if not rank or rank <= 0:
        return 50.0
    base = 70.0 - 1.2*(rank-1)
    # slightly adjust for field size
    if field_size >= 16:
        base -= 2.0
    return float(_clamp(base, 35.0, 80.0))

def parse_racecard_html(html: str) -> Dict[str, Any]:
    """Best-effort extraction of entrants + (optional) popularity/odds from racecard HTML.
    Works as a heuristic for netkeiba/NAR/others. Never raises.
    """
    h = html or ""
    # Horse names: very loose anchor text capture - avoid headers by filtering
    # Candidates: Japanese katakana/hiragana/kanji + alphabets; length >=2
    name_candidates = re.findall(r">\s*([A-Za-z0-9\u3040-\u30FF\u4E00-\u9FFF\u30FC\(\)・\-\s]{2,20})\s*<", h)
    # Filter common non-names
    ban = set(["出馬表","予想","結果","オッズ","馬名","騎手","斤量","調教師","性齢","人気","単勝","複勝","タイム"])
    names = []
    for s in name_candidates:
        s2 = re.sub(r"\s+", " ", s).strip()
        if s2 in ban:
            continue
        if re.fullmatch(r"\d+", s2):
            continue
        # exclude UI labels
        if len(s2) < 2:
            continue
        names.append(s2)
    names = _uniq(names)

    # Popularity ranks: try to find table cells that look like "人気" numeric
    # This is highly site-dependent; we just collect numbers near '人気'
    pop_map = {}
    # Pattern: ...>人気</th> ... <td>3</td> within same row; naive row scanning
    rows = re.split(r"</tr>", h, flags=re.I)
    for row in rows:
        # attempt to find name in row
        row_names = []
        for nm in names[:80]:
            if nm and nm in row:
                row_names.append(nm)
        if not row_names:
            continue
        # find popularity numbers in row
        m = re.search(r"人気[^0-9]{0,20}(\d{1,2})", row)
        rank = None
        if m:
            try: rank = int(m.group(1))
            except Exception: rank = None
        # odds (tansho) numbers e.g. 12.3
        mo = re.search(r"(?:単勝|odds)[^0-9]{0,20}(\d{1,3}(?:\.\d+)?)", row, flags=re.I)
        odds = None
        if mo:
            try: odds = float(mo.group(1))
            except Exception: odds = None

        for nm in row_names:
            if rank is not None and nm not in pop_map:
                pop_map[nm] = {"popularity": rank}
            if odds is not None:
                pop_map.setdefault(nm, {})
                pop_map[nm]["odds"] = odds

    return {
        "ok": True if names else False,
        "names": names,
        "meta": pop_map,
    }

def fetch_racecard(url: str, timeout: int = 10) -> Dict[str, Any]:
    if not url:
        return {"ok": False, "error": "missing_url"}
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent":"Mozilla/5.0 (GoPaddock)"})
        if r.status_code >= 400:
            return {"ok": False, "error": f"http_{r.status_code}"}
        parsed = parse_racecard_html(r.text)
        parsed["source"] = "fetched"
        return parsed
    except Exception as e:
        return {"ok": False, "error": "fetch_failed", "detail": str(e)[:200]}

def build_entrants_with_ratings(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    names = list((parsed or {}).get("names") or [])
    meta = dict((parsed or {}).get("meta") or {})
    field_size = max(1, len(names))
    out: List[Dict[str, Any]] = []
    for nm in names:
        info = meta.get(nm, {}) if isinstance(meta, dict) else {}
        rank = info.get("popularity")
        try:
            rank_i = int(rank) if rank is not None else None
        except Exception:
            rank_i = None
        rating = _rating_from_poprank(rank_i, field_size)
        # If odds exist, nudge: lower odds => up
        odds = info.get("odds")
        try:
            odds_f = float(odds) if odds is not None else None
        except Exception:
            odds_f = None
        if odds_f and odds_f > 0:
            # simple odds adjustment: 2.0 => +6, 20.0 => -4
            adj = 8.0 - 4.0*min(3.0, max(0.0, (odds_f-2.0)/6.0))
            rating = _clamp(rating + adj, 35.0, 85.0)

        out.append({"name": nm, "rating": float(rating)})
    return out
