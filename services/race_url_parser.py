from __future__ import annotations
import re
from typing import Dict, Any
import requests

def parse_race_conditions_from_text(text: str) -> Dict[str, Any]:
    t = text
    surface = None
    if re.search(r"(芝|turf|grass)", t, re.I):
        surface = "turf"
    if re.search(r"(ダ|ダート|dirt|sand)", t, re.I):
        surface = "dirt"

    dist_m = None
    m = re.search(r"(\d{3,4})\s*m", t)
    if m: dist_m = int(m.group(1))
    m = re.search(r"(\d{3,4})\s*メートル", t)
    if m: dist_m = int(m.group(1))

    turn = None
    if re.search(r"(右|right)", t, re.I): turn = "right"
    if re.search(r"(左|left)", t, re.I): turn = "left"

    klass = None
    if re.search(r"(g1|g2|g3|重賞)", t, re.I):
        klass = "graded"
    elif re.search(r"(c1|c2|c3|1勝|2勝|3勝|条件)", t, re.I):
        klass = "class"
    elif re.search(r"(新馬|未勝利)", t, re.I):
        klass = "maiden"

    return {"surface": surface, "distance_m": dist_m, "turn": turn, "class": klass}

def fetch_and_parse(url: str, timeout: int = 8) -> Dict[str, Any]:
    if not url:
        return {"ok": False, "error": "missing_url"}
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent":"Mozilla/5.0 (GoPaddock)"})
        if r.status_code >= 400:
            return {"ok": False, "error": f"http_{r.status_code}"}
        cond = parse_race_conditions_from_text(r.text)
        cond["ok"] = True
        cond["source"] = "fetched"
        return cond
    except Exception as e:
        return {"ok": False, "error": "fetch_failed", "detail": str(e)[:200]}
