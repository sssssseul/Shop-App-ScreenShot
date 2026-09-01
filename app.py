import os
import re
import uuid
import mimetypes
import calendar as pycalendar
from datetime import datetime, date
from io import BytesIO
from zipfile import ZipFile

import psycopg2
import psycopg2.extras
from flask import (
    Flask, request, redirect, url_for, render_template,
    send_file, abort, flash, jsonify
)

app = Flask(__name__, template_folder=".")
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS captures (
            id SERIAL PRIMARY KEY,
            session_id TEXT NOT NULL,
            label TEXT NOT NULL,
            sequence INTEGER NOT NULL DEFAULT 1,
            captured_at TIMESTAMP NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'image/png',
            image_data BYTEA NOT NULL,
            uploaded_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_captured_at ON captures (captured_at);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_session ON captures (session_id);")
    conn.commit()
    cur.close()
    conn.close()


@app.route("/")
def index():
    return redirect(url_for("calendar_view"))


MONTH_NAMES_KO = ["1월", "2월", "3월", "4월", "5월", "6월",
                  "7월", "8월", "9월", "10월", "11월", "12월"]


@app.route("/calendar")
def calendar_view():
    today = date.today()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT DISTINCT EXTRACT(YEAR FROM captured_at)::int AS y FROM captures ORDER BY y")
    years = [r["y"] for r in cur.fetchall()]
    if today.year not in years:
        years.append(today.year)
    years = sorted(set(years))

    cur.execute(
        "SELECT DISTINCT EXTRACT(MONTH FROM captured_at)::int AS m FROM captures "
        "WHERE EXTRACT(YEAR FROM captured_at) = %s", (year,),
    )
    months_with_data = {r["m"] for r in cur.fetchall()}

    def shift(y, m, offset):
        idx = (y * 12 + (m - 1)) + offset
        return idx // 12, (idx % 12) + 1

    panels = {}
    month_blocks = []
    center_default_day = None

    for offset in (-1, 0, 1):
        y_m, m_m = shift(year, month, offset)
        cur.execute(
            """SELECT id, session_id, label, sequence, captured_at
               FROM captures
               WHERE EXTRACT(YEAR FROM captured_at) = %s
                 AND EXTRACT(MONTH FROM captured_at) = %s
               ORDER BY captured_at ASC, sequence ASC""",
            (y_m, m_m),
        )
        rows = cur.fetchall()
        by_day = {}
        for r in rows:
            by_day.setdefault(r["captured_at"].day, []).append(r)

        days_in_month = pycalendar.monthrange(y_m, m_m)[1]
        first_weekday = date(y_m, m_m, 1).weekday()
        lead_blanks = (first_weekday + 1) % 7
        cells = [{"day": d, "has": d in by_day} for d in range(1, days_in_month + 1)]
        trail_blanks = 42 - lead_blanks - len(cells)

        month_blocks.append({
            "year": y_m, "month": m_m, "label": f"{y_m}년 {m_m}월",
            "lead_blanks": lead_blanks, "trail_blanks": trail_blanks, "cells": cells,
            "is_center": offset == 0,
        })

        for d, shots in by_day.items():
            sessions = {}
            for s in shots:
                sessions.setdefault(s["session_id"], []).append(s)
            session_list = [
                {"time_str": grp[0]["captured_at"].strftime("%H:%M"), "shots": grp}
                for grp in sessions.values()
            ]
            session_list.sort(key=lambda g: g["shots"][0]["captured_at"])

            panels[f"{m_m}-{d}"] = {
                "date_str": f"{y_m}-{m_m:02d}-{d:02d}",
                "year": y_m, "month": m_m, "day": d,
                "sessions": session_list,
            }
            if offset == 0:
                if center_default_day is None or d > center_default_day:
                    center_default_day = d

    cur.close()
    conn.close()

    if center_default_day is not None:
        default_panel = f"{month}-{center_default_day}"
    else:
        default_panel = None

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)

    month_tabs = [
        {"num": m, "name": MONTH_NAMES_KO[m - 1], "has_data": m in months_with_data}
        for m in range(1, 13)
    ]

    return render_template(
        "calendar.html",
        year=year, month=month, years=years, month_tabs=month_tabs,
        month_blocks=month_blocks,
        panels=panels, default_panel=default_panel,
        prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month,
    )


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        label = "Shop App"
        captured_date = request.form.get("captured_date")
        captured_time = request.form.get("captured_time") or "00:00"
        files = request.files.getlist("images")
        files = [f for f in files if f and f.filename]

        if not files:
            flash("이미지를 최소 1장 선택해주세요.")
            return redirect(url_for("upload"))

        try:
            captured_at = datetime.strptime(
                f"{captured_date} {captured_time}", "%Y-%m-%d %H:%M"
            )
        except (ValueError, TypeError):
            captured_at = datetime.now()

        session_id = uuid.uuid4().hex

        conn = get_db()
        cur = conn.cursor()
        for i, f in enumerate(files, start=1):
            data = f.read()
            content_type = f.mimetype or "image/png"
            cur.execute(
                """INSERT INTO captures
                   (session_id, label, sequence, captured_at, content_type, image_data)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (session_id, label, i, captured_at, content_type, psycopg2.Binary(data)),
            )
        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for("view_session", session_id=session_id))

    return render_template("upload.html", today=date.today().isoformat())


@app.route("/download/<int:year>/<int:month>/<int:day>")
def download_day(year, month, day):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """SELECT label, sequence, content_type, image_data, captured_at
           FROM captures
           WHERE EXTRACT(YEAR FROM captured_at) = %s
             AND EXTRACT(MONTH FROM captured_at) = %s
             AND EXTRACT(DAY FROM captured_at) = %s
           ORDER BY captured_at ASC, sequence ASC""",
        (year, month, day),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        abort(404)

    buf = BytesIO()
    used_names = set()
    with ZipFile(buf, "w") as zf:
        for r in rows:
            ext = mimetypes.guess_extension(r["content_type"]) or ".png"
            safe_label = re.sub(r"[^\w\-가-힣]+", "_", r["label"]).strip("_") or "capture"
            time_folder = r["captured_at"].strftime("%H-%M")
            fname = f"{time_folder}/{safe_label}_{r['sequence']:02d}{ext}"
            while fname in used_names:
                fname = f"{time_folder}/{safe_label}_{r['sequence']:02d}_{uuid.uuid4().hex[:4]}{ext}"
            used_names.add(fname)
            zf.writestr(fname, r["image_data"])
    buf.seek(0)

    zip_name = f"{year}-{month:02d}-{day:02d}.zip"
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=zip_name)


@app.route("/delete", methods=["POST"])
def delete_captures():
    ids = [int(i) for i in request.form.getlist("capture_ids") if i.isdigit()]
    year = request.form.get("year", type=int)
    month = request.form.get("month", type=int)

    if ids:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM captures WHERE id = ANY(%s)", (ids,))
        conn.commit()
        cur.close()
        conn.close()
        flash(f"{len(ids)}개 삭제했습니다.")

    return redirect(url_for("calendar_view", year=year, month=month))


def _fetch_day_shots(cur, date_str):
    try:
        y, m, d = (int(x) for x in date_str.split("-"))
    except (ValueError, AttributeError):
        return None
    cur.execute(
        """SELECT id, session_id, label, sequence, captured_at
           FROM captures
           WHERE DATE(captured_at) = %s
           ORDER BY captured_at ASC, sequence ASC""",
        (date(y, m, d),),
    )
    shots = cur.fetchall()

    sessions = {}
    for s in shots:
        sessions.setdefault(s["session_id"], []).append(s)
    session_list = [
        {"time_str": grp[0]["captured_at"].strftime("%H:%M"), "shots": grp}
        for grp in sessions.values()
    ]
    session_list.sort(key=lambda g: g["shots"][0]["captured_at"])

    return {"date_str": date_str, "sessions": session_list}


@app.route("/compare_data")
def compare_data():
    date_a = request.args.get("a")
    date_b = request.args.get("b")

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    day_a = _fetch_day_shots(cur, date_a)
    day_b = _fetch_day_shots(cur, date_b)
    cur.close()
    conn.close()

    if not day_a or not day_b:
        abort(404)

    def serialize(day):
        return {
            "date_str": day["date_str"],
            "sessions": [
                {
                    "time_str": grp["time_str"],
                    "shots": [
                        {
                            "id": s["id"],
                            "label": s["label"],
                            "sequence": s["sequence"],
                            "image_url": url_for("image", capture_id=s["id"]),
                        }
                        for s in grp["shots"]
                    ],
                }
                for grp in day["sessions"]
            ],
        }

    return jsonify({"a": serialize(day_a), "b": serialize(day_b)})


@app.route("/session/<session_id>")
def view_session(session_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """SELECT id, label, sequence, captured_at FROM captures
           WHERE session_id = %s ORDER BY sequence ASC""",
        (session_id,),
    )
    shots = cur.fetchall()
    cur.close()
    conn.close()

    if not shots:
        abort(404)

    return render_template("session.html", shots=shots, session_id=session_id,
                            label=shots[0]["label"], captured_at=shots[0]["captured_at"])


@app.route("/image/<int:capture_id>")
def image(capture_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT image_data, content_type FROM captures WHERE id = %s",
        (capture_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        abort(404)

    image_data, content_type = row
    return send_file(BytesIO(image_data), mimetype=content_type)


with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
