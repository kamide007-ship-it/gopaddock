from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

from extensions import db
from models import Evaluation, User
from services.auth import (
    handle_login,
    handle_logout,
    init_auth,
    login_required,
    current_user,
    create_user,
)
from services.evaluator import evaluate_horse
from services.race_probs import montecarlo_race_probs
from services.video_ai import analyze_video_best_effort
from services.legal import get_tokusho, get_privacy_meta


APP_VERSION = "v2.9.6-stable"


def _env_int(name: str, default: int) -> int:
    try:
        v = os.getenv(name, "").strip()
        if not v:
            return default
        return int(v)
    except Exception:
        return default


def _get_db_url() -> str:
    # Render: DATABASE_URL is standard. If no disk is attached, fall back to /tmp.
    if os.getenv("SQLALCHEMY_DATABASE_URI"):
        return os.getenv("SQLALCHEMY_DATABASE_URI", "")
    if os.getenv("DATABASE_URL"):
        return os.getenv("DATABASE_URL", "")
    base = Path("/var/data") if Path("/var/data").exists() else Path("/tmp")
    return f"sqlite:///{base}/gopaddock.sqlite3"


def _upload_dir() -> Path:
    # On Render, /var/data exists only if you attached a disk; /tmp always exists.
    base = Path(os.getenv("UPLOAD_DIR", "/tmp/gopaddock_uploads"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY") or "dev-secret"
    app.config["APP_VERSION"] = os.getenv("APP_VERSION", APP_VERSION)

    # DB: never hard-crash on missing env var
    app.config["SQLALCHEMY_DATABASE_URI"] = _get_db_url()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Trial / billing knobs (UI only in this version)
    app.config["FREE_TRIAL_LIMIT"] = _env_int("FREE_TRIAL_LIMIT", 5)
    app.config["MONTHLY_PRICE_JPY"] = _env_int("MONTHLY_PRICE_JPY", 550)

    # Business / legal
    app.config["BUSINESS_NAME"] = os.getenv("BUSINESS_NAME", "Equine Vet Synapse")
    app.config["CONTACT_EMAIL"] = os.getenv("CONTACT_EMAIL", "equinevet.owners@gmail.com")
    app.config["BUSINESS_URL"] = os.getenv("BUSINESS_URL", "https://www.minamisoma-vet.com/")

    # Init auth/db
    init_auth(app)


# Public access to uploaded files (for URL-mode video AI).
@app.get("/uploads/<path:filename>")
def uploaded_file(filename: str):
    from flask import send_from_directory, abort
    up = _upload_dir()
    # Basic traversal protection
    if ".." in filename or filename.startswith("/"):
        abort(404)
    return send_from_directory(up, filename, as_attachment=False)

    @app.context_processor
    def inject_globals():
        return {
            "APP_VERSION": app.config["APP_VERSION"],
            "BUSINESS_NAME": app.config["BUSINESS_NAME"],
            "CONTACT_EMAIL": app.config["CONTACT_EMAIL"],
            "BUSINESS_URL": app.config["BUSINESS_URL"],
            "MONTHLY_PRICE_JPY": app.config["MONTHLY_PRICE_JPY"],
            "FREE_TRIAL_LIMIT": app.config["FREE_TRIAL_LIMIT"],
            "current_user": current_user,
        }

    # ----------------
    # Health / version
    # ----------------
    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "version": app.config["APP_VERSION"]})

    @app.get("/version")
    def version():
        return jsonify({"version": app.config["APP_VERSION"]})

    @app.get("/robots.txt")
    def robots():
        return "User-agent: *\nDisallow:\n", 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.get("/favicon.ico")
    def favicon():
        # avoid 404 spam
        return ("", 204)

    # -------------
    # Auth routes
    # -------------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            ok, err = handle_login(request.form.get("email", ""), request.form.get("password", ""))
            if ok:
                nxt = request.args.get("next") or url_for("app_page")
                return redirect(nxt)
            flash(err or "ログインに失敗しました", "error")
        return render_template("login.html", next=request.args.get("next", "/"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            invite = request.form.get("invite_code", "").strip()

            req_invite = os.getenv("CLIENT_INVITE_CODE", "").strip()
            if req_invite and invite != req_invite:
                flash("招待コードが正しくありません。", "error")
                return render_template("register.html")

            ok, err = create_user(email=email, password=password)
            if ok:
                flash("登録しました。ログインしてください。", "success")
                return redirect(url_for("login"))
            flash(err or "登録に失敗しました", "error")
        return render_template("register.html")

    @app.route("/logout", methods=["GET","POST"])
    @login_required
    def logout():
        handle_logout()
        return redirect(url_for("login"))

    # -------------
    # Pages
    # -------------
    @app.get("/")
    def root():
        # If logged in, go to app. Else login.
        if current_user.is_authenticated:
            return redirect(url_for("app_page"))
        return redirect(url_for("login"))

    @app.get("/index")
    def index():
        return redirect(url_for("root"))

    @app.route("/app", methods=["GET", "POST"])
    @login_required
    def app_page():
        result: Optional[Dict[str, Any]] = None
        if request.method == "POST":
            horse_name = (request.form.get("horse_name") or "").strip()
            race_url = (request.form.get("race_url") or "").strip()
            sire = (request.form.get("sire") or "").strip()
            dam = (request.form.get("dam") or "").strip()
            damsire = (request.form.get("damsire") or "").strip()
            notes = (request.form.get("notes") or "").strip()
            opponent_text = (request.form.get("opponents") or "").strip()

            # video upload (optional)
            video_path = None
            f = request.files.get("video")
            if f and f.filename:
                fn = secure_filename(f.filename)
                out = _upload_dir() / f"{uuid.uuid4().hex}_{fn}"
                f.save(out)
                video_path = str(out)

            # best-effort video metrics (never crash)
            cv_metrics = analyze_video_best_effort(video_path)

            # core evaluation (hybrid)
            report = evaluate_horse(
                horse_name=horse_name or "unknown",
                race_url=race_url or None,
                sire=sire or None,
                dam=dam or None,
                damsire=damsire or None,
                notes=notes or None,
                opponent_text=opponent_text or None,
                video_path=video_path,
                cv_metrics=cv_metrics,
            )

            # persist
            ev = Evaluation(
                user_id=current_user.id,
                horse_name=horse_name or "unknown",
                race_url=race_url or None,
                sire=sire or None,
                dam=dam or None,
                damsire=damsire or None,
                notes=notes or None,
                report_json=json.dumps(report, ensure_ascii=False),
                created_at=datetime.utcnow(),
            )
            db.session.add(ev)
            db.session.commit()

            result = report
            flash("解析が完了しました。", "success")

        return render_template("app.html", result=result)

    @app.get("/history")
    @login_required
    def history():
        rows = Evaluation.query.filter_by(user_id=current_user.id).order_by(Evaluation.id.desc()).limit(100).all()
        return render_template("history.html", evaluations=rows)

    @app.get("/evaluation/<int:eval_id>")
    @login_required
    def view_evaluation(eval_id: int):
        ev = Evaluation.query.filter_by(id=eval_id, user_id=current_user.id).first()
        if not ev:
            abort(404)
        report = {}
        try:
            report = json.loads(ev.report_json or "{}")
        except Exception:
            report = {"ok": False, "error": "invalid_report_json"}
        return render_template("evaluation.html", ev=ev, report=report)

    @app.get("/pricing")
    def pricing():
        return render_template("pricing.html")

    @app.get("/checkout")
    @login_required
    def checkout():
        # Placeholder: Stripe/PayPal/PayPay can be integrated later
        return render_template("upgrade.html")

    # -----------------
    # APIs (best-effort)
    # -----------------
    @app.post("/api/video_analyze")
    @login_required
    def api_video_analyze():
        f = request.files.get("video")
        if not f or not f.filename:
            return jsonify({"ok": False, "error": "no_video"}), 400

        fn = secure_filename(f.filename)
        out = _upload_dir() / f"{uuid.uuid4().hex}_{fn}"
        f.save(out)
        # Build public URL for URL-mode Video-AI (small payload, stable).
        video_url = None
        try:
            video_url = url_for("uploaded_file", filename=os.path.basename(str(out)), _external=True)
        except Exception:
            video_url = None

        payload, logs = analyze_video_best_effort(str(out), video_public_url=video_url)
        payload = payload or {"ok": False, "error": "video_analyze_failed"}
        payload["video_url"] = video_url
        payload["_log"] = (payload.get("_log") or []) + logs
        return jsonify(payload)

    @app.post("/api/race_probs")
    @login_required
    def api_race_probs():
        data = request.get_json(silent=True) or {}
        participants = data.get("participants") or []
        if not isinstance(participants, list) or len(participants) < 2:
            return jsonify({"ok": False, "error": "need_participants"}), 400
        res = montecarlo_race_probs(participants)
        return jsonify({"ok": True, "result": res})

    # ----------
    # Legal pages
    # ----------
    @app.get("/legal/tokusho")
    def legal_tokusho():
        return render_template("tokusho.html", tokusho=get_tokusho())

    @app.get("/legal/terms")
    def legal_terms():
        return render_template("terms.html", tokusho=get_tokusho())

    @app.get("/legal/privacy")
    def legal_privacy():
        return render_template(
            "privacy.html",
            tokusho=get_tokusho(),
            meta=get_privacy_meta(),
        )

    @app.get("/legal/refund")
    def legal_refund():
        return render_template("refund.html", tokusho=get_tokusho())

    # -------------
    # DB bootstrap
    # -------------
    with app.app_context():
        db.create_all()

    return app
