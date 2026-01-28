from __future__ import annotations
import os
from functools import wraps
from typing import Any, Callable, Dict, Tuple

from flask import Flask, redirect, url_for, request, flash
from flask_login import current_user

from extensions import db
from models import User
from services.bank_payments import create_bank_payment_request, bank_info

DEFAULT_PRICE_JPY = 550

def init_billing(app: Flask) -> None:
    # expose helpers
    app.billing = {"bank_info": bank_info()}  # type: ignore[attr-defined]

def plan_config() -> Dict[str, Any]:
    """Beta fixed plan: 550 JPY / month. Trial: 5 analyses."""
    return {
        "beta": {"name": "β版", "price_jpy": int(os.getenv("PRICE_JPY", str(DEFAULT_PRICE_JPY))), "monthly_quota": 9999},
        "free": {"name": "無料", "price_jpy": 0, "monthly_quota": int(os.getenv("FREE_MONTHLY_QUOTA", "5"))},
    }

def get_plan_info() -> Dict[str, Any]:
    cfg = plan_config()
    return {
        "price_jpy": cfg["beta"]["price_jpy"],
        "trial_count": cfg["free"]["monthly_quota"],
        "bank": bank_info(),
        "pay_methods": ["bank", "paypal", "stripe", "paypay"],
        "note": "β版は月額固定です。決済の実装は順次追加。",
    }

def _ensure_month_rollover(u: User) -> None:
    from datetime import datetime
    month = datetime.utcnow().strftime("%Y-%m")
    if u.quota_month != month:
        u.quota_month = month
        u.quota_used_month = 0
        db.session.commit()

def can_use_feature(u: User) -> Tuple[bool, str]:
    _ensure_month_rollover(u)
    cfg = plan_config()
    if u.plan not in cfg:
        u.plan = "free"
        db.session.commit()
    limit = cfg[u.plan]["monthly_quota"]
    if u.quota_used_month >= limit:
        return False, f"今月の無料枠（{limit}回）を使い切りました。アップグレードしてください。"
    return True, "OK"

def consume_quota(u: User, n: int = 1) -> None:
    _ensure_month_rollover(u)
    u.quota_used_total += n
    u.quota_used_month += n
    db.session.commit()

def require_active_subscription(fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not getattr(current_user, "is_authenticated", False):
            return redirect(url_for("auth_login"))
        ok, msg = can_use_feature(current_user)  # type: ignore[arg-type]
        if not ok:
            flash(msg)
            return redirect(url_for("pricing"))
        return fn(*args, **kwargs)
    return wrapper

def request_bank_upgrade(plan: str = "beta") -> Tuple[bool, str, str]:
    if not getattr(current_user, "is_authenticated", False):
        return False, "not_logged_in", ""
    pr = create_bank_payment_request(current_user, plan)  # type: ignore[arg-type]
    return True, "OK", pr.reference_code
