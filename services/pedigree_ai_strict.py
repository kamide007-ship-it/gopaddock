from __future__ import annotations

import os, json, re
from typing import Any, Dict

def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x

def _fallback(pedigree_text: str) -> Dict[str, Any]:
    t = (pedigree_text or "").lower()
    stamina_hint = 50.0
    speed_hint = 50.0
    turfiness = 0.5
    stamina_kw = ["sadler","galileo","deep impact","sunday silence","stamina","stay"]
    speed_kw = ["mr. prospector","storm cat","speightstown","danzig","speed","sprint","fast"]
    turf_kw = ["turf","grass","sadler","galileo","deep impact","montjeu"]
    dirt_kw = ["dirt","mud","a.p. indy","tapit","smart strike","unbridled","fappiano"]
    for k in stamina_kw:
        if k in t: stamina_hint += 5
    for k in speed_kw:
        if k in t: speed_hint += 5
    for k in turf_kw:
        if k in t: turfiness += 0.05
    for k in dirt_kw:
        if k in t: turfiness -= 0.05

    stamina_hint = _clamp(stamina_hint, 35, 80)
    speed_hint = _clamp(speed_hint, 35, 80)
    turfiness = _clamp(turfiness, 0.0, 1.0)

    ped_score = _clamp(0.5*speed_hint + 0.5*stamina_hint, 0, 100)
    ped_surfacefit = _clamp(50.0 + 30.0*(turfiness-0.5), 0, 100)

    return {
        "ok": False,
        "ped_score": float(ped_score),
        "ped_speed": float(speed_hint),
        "ped_stamina": float(stamina_hint),
        "ped_surfacefit": float(ped_surfacefit),
        "ped_turfiness_0_1": float(turfiness),
        "notes": "OPENAI_API_KEY未設定のため、血統はヒューリスティック推定（暫定）です。",
        "confidence_0_1": 0.25
    }

def analyze_pedigree_strict(*, pedigree_text: str) -> Dict[str, Any]:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return _fallback(pedigree_text)

    try:
        from openai import OpenAI

        # 長時間ハングを避けるため、タイムアウト/リトライを env から制御
        # 例:
        #   AI_TOTAL_TIMEOUT_SECONDS=220
        #   AI_MAX_RETRIES=3
        timeout_s = float(os.getenv("AI_TOTAL_TIMEOUT_SECONDS", "220") or "220")
        max_retries = int(os.getenv("AI_MAX_RETRIES", "3") or "3")
        client = OpenAI(api_key=api_key, timeout=timeout_s, max_retries=max_retries)

        system = (
            "あなたは競走馬血統の解析者。必ずJSONのみで返答。"
            "キー: ok,ped_score,ped_speed,ped_stamina,ped_surfacefit,ped_turfiness_0_1,notes,confidence_0_1"
            "数値はped_*は0-100、turfinessは0-1。"
        )
        user = f"""血統テキストを解析し、指定キーでJSONを返してください。
血統テキスト:
{pedigree_text}
"""
        resp = client.responses.create(
            model=os.getenv("GPT_TEXT_MODEL","gpt-4.1-mini"),
            input=[{"role":"system","content":system},{"role":"user","content":user}],
            response_format={"type":"json_object"},
            temperature=0.2,
        )
        obj = json.loads(resp.output_text)

        def g(k, d):
            try: return float(obj.get(k, d))
            except Exception: return float(d)

        turf = _clamp(g("ped_turfiness_0_1", 0.5), 0.0, 1.0)
        return {
            "ok": True,
            "ped_score": _clamp(g("ped_score", 50.0), 0, 100),
            "ped_speed": _clamp(g("ped_speed", 50.0), 0, 100),
            "ped_stamina": _clamp(g("ped_stamina", 50.0), 0, 100),
            "ped_surfacefit": _clamp(g("ped_surfacefit", 50.0), 0, 100),
            "ped_turfiness_0_1": turf,
            "notes": str(obj.get("notes","")).strip()[:400],
            "confidence_0_1": _clamp(g("confidence_0_1", 0.5), 0.0, 1.0),
        }
    except Exception:
        return _fallback(pedigree_text)
