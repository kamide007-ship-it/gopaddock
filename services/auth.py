from __future__ import annotations
import os
from functools import wraps
from typing import Callable, Any, Tuple

from flask import Flask, redirect, url_for, request, flash
from flask_login import LoginManager, login_user, logout_user, login_required as _login_required, current_user
from extensions import db, login_manager
from models import User

def init_auth(app: Flask) -> None:
    """Initialize authentication + DB.

    IMPORTANT:
      Flask-SQLAlchemy requires SQLALCHEMY_DATABASE_URI to be set
      BEFORE calling db.init_app(app), otherwise it raises:
      'SQLALCHEMY_DATABASE_URI or SQLALCHEMY_BINDS must be set.'
    """
    # Determine DB URL (prefer DATABASE_URL; also accept SQLALCHEMY_DATABASE_URI)
    db_url = (
        os.getenv("DATABASE_URL")
        or os.getenv("SQLALCHEMY_DATABASE_URI")
        or app.config.get("SQLALCHEMY_DATABASE_URI")
    )

    if not db_url:
        # Default local sqlite
        db_url = "sqlite:///app.db"

    # Render Postgres legacy scheme
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Now we can init extensions safely
    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        db.create_all()

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        try:
            return db.session.get(User, int(user_id))
        except Exception:
            return None
def ensure_admin_seeded() -> None:
    """Seed admin user from env vars if provided. Soft (no crash)."""
    email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    pw = (os.getenv("ADMIN_PASSWORD") or "").strip()
    if not email or not pw:
        print("ADMIN seed skipped: ADMIN_EMAIL / ADMIN_PASSWORD not set")
        return
    try:
        u = User.query.filter_by(email=email).first()  # type: ignore[attr-defined]
        if not u:
            u = User(email=email, is_admin=True, plan=os.getenv("ADMIN_PLAN","pro"))
            u.set_password(pw)
            db.session.add(u)
            db.session.commit()
            print(f"Admin seeded: {email}")
        else:
            # ensure admin flag
            changed = False
            if not u.is_admin:
                u.is_admin = True
                changed = True
            if changed:
                db.session.commit()
            print(f"Admin exists: {email}")
    except Exception as e:
        print(f"Admin seed failed (soft): {e}")

def is_admin() -> bool:
    try:
        return bool(getattr(current_user, "is_authenticated", False) and getattr(current_user, "is_admin", False))
    except Exception:
        return False

def login_required(fn: Callable[..., Any]) -> Callable[..., Any]:
    return _login_required(fn)

def handle_login(email: str, password: str) -> Tuple[bool, str]:
    email = (email or "").strip().lower()
    password = (password or "").strip()
    if not email or not password:
        return False, "Email とパスワードを入力してください"
    u = User.query.filter_by(email=email).first()  # type: ignore[attr-defined]
    if not u or not u.check_password(password):
        return False, "Email またはパスワードが違います"
    login_user(u)
    return True, "OK"

def handle_logout() -> None:
    logout_user()

def create_user(email: str, password: str) -> Tuple[bool, str]:
    email = (email or "").strip().lower()
    password = (password or "").strip()
    if not email or not password:
        return False, "Email とパスワードが必要です"
    if len(password) < 6:
        return False, "パスワードは6文字以上にしてください"
    if User.query.filter_by(email=email).first():  # type: ignore[attr-defined]
        return False, "このEmailは既に登録されています"
    u = User(email=email, plan="free", is_admin=False)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return True, "OK"

def list_users():
    return User.query.order_by(User.created_at.desc()).all()  # type: ignore[attr-defined]
