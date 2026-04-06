
import sqlite3
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, send_file, flash
import csv
import io

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "signals_web.db"

app = Flask(__name__)
app.secret_key = "change-this-secret-key"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    trade_time TEXT NOT NULL,
    assistant_name TEXT NOT NULL,
    instrument TEXT NOT NULL,
    direction TEXT NOT NULL,
    structure_type TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    screenshot_link TEXT,
    moved_as_expected TEXT,
    mfe_r REAL,
    mae_r REAL,
    achieved_rr REAL,
    notes TEXT,
    created_at TEXT NOT NULL
);
"""

STRUCTURE_OPTIONS = ["前高/压力", "前低/支撑", "趋势回调点", "趋势反弹点", "区间上沿", "区间下沿"]
DIRECTION_OPTIONS = ["Long", "Short"]
SIGNAL_OPTIONS = ["阳吞没阴（看涨）", "阴吞没阳（看跌）"]
EXPECTED_OPTIONS = ["Yes", "No", "Unknown"]

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
def init_db():
    conn = sqlite3.connect("signals.db")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_date TEXT,
        trade_time TEXT,
        assistant_name TEXT,
        instrument TEXT,
        direction TEXT,
        structure_type TEXT,
        signal_type TEXT,
        screenshot_link TEXT,
        moved_as_expected TEXT,
        mfe_r REAL,
        mae_r REAL,
        achieved_rr REAL,
        notes TEXT,
        created_at TEXT
    )
    """)
    conn.commit()
    conn.close()
def init_db():
    with get_conn() as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()

def parse_float(value):
    if value is None or str(value).strip() == "":
        return None
    return float(value)

def get_filter_options():
    with get_conn() as conn:
        assistants = [r[0] for r in conn.execute("SELECT DISTINCT assistant_name FROM signals ORDER BY assistant_name").fetchall()]
        instruments = [r[0] for r in conn.execute("SELECT DISTINCT instrument FROM signals ORDER BY instrument").fetchall()]
        structures = [r[0] for r in conn.execute("SELECT DISTINCT structure_type FROM signals ORDER BY structure_type").fetchall()]
    return {
        "assistants": assistants,
        "instruments": instruments,
        "structures": structures,
    }

def build_query(filters):
    sql = """
        SELECT id, trade_date, trade_time, assistant_name, instrument, direction,
               structure_type, signal_type, screenshot_link, moved_as_expected,
               mfe_r, mae_r, achieved_rr, notes, created_at
        FROM signals
    """
    conditions = []
    params = []
    if filters.get("assistant") and filters["assistant"] != "全部":
        conditions.append("assistant_name = ?")
        params.append(filters["assistant"])
    if filters.get("instrument") and filters["instrument"] != "全部":
        conditions.append("instrument = ?")
        params.append(filters["instrument"])
    if filters.get("structure") and filters["structure"] != "全部":
        conditions.append("structure_type = ?")
        params.append(filters["structure"])
    if filters.get("direction") and filters["direction"] != "全部":
        conditions.append("direction = ?")
        params.append(filters["direction"])
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY trade_date DESC, trade_time DESC, id DESC"
    return sql, params

def get_rows(filters=None):
    filters = filters or {}
    sql, params = build_query(filters)
    with get_conn() as conn:
        return conn.execute(sql, params).fetchall()

def compute_stats(rows):
    total = len(rows)
    moved_yes = sum(1 for r in rows if r["moved_as_expected"] == "Yes")
    moved_no = sum(1 for r in rows if r["moved_as_expected"] == "No")
    mfe_values = [r["mfe_r"] for r in rows if r["mfe_r"] is not None]
    mae_values = [r["mae_r"] for r in rows if r["mae_r"] is not None]
    rr_values = [r["achieved_rr"] for r in rows if r["achieved_rr"] is not None]

    by_structure = {}
    by_assistant = {}

    for r in rows:
        by_structure.setdefault(r["structure_type"], []).append(r)
        by_assistant.setdefault(r["assistant_name"], []).append(r)

    structure_counts = {k: len(v) for k, v in by_structure.items()}
    assistant_hit_rates = {
        k: round(100 * sum(1 for x in v if x["moved_as_expected"] == "Yes") / len(v), 2)
        for k, v in by_assistant.items() if len(v) > 0
    }

    return {
        "total": total,
        "moved_yes": moved_yes,
        "moved_no": moved_no,
        "hit_rate": round(100 * moved_yes / total, 2) if total else 0,
        "avg_mfe": round(sum(mfe_values) / len(mfe_values), 2) if mfe_values else None,
        "avg_mae": round(sum(mae_values) / len(mae_values), 2) if mae_values else None,
        "avg_rr": round(sum(rr_values) / len(rr_values), 2) if rr_values else None,
        "structure_counts": structure_counts,
        "assistant_hit_rates": assistant_hit_rates,
    }

@app.route("/")
def index():
    filters = {
        "assistant": request.args.get("assistant", "全部"),
        "instrument": request.args.get("instrument", "全部"),
        "structure": request.args.get("structure", "全部"),
        "direction": request.args.get("direction", "全部"),
    }
    rows = get_rows(filters)
    stats = compute_stats(rows)
    options = get_filter_options()
    return render_template(
        "index.html",
        rows=rows,
        stats=stats,
        filters=filters,
        options=options
    )

@app.route("/new", methods=["GET", "POST"])
def new_signal():
    if request.method == "POST":
        try:
            trade_date = request.form["trade_date"].strip()
            trade_time = request.form["trade_time"].strip()
            assistant_name = request.form["assistant_name"].strip()
            instrument = request.form["instrument"].strip()
            direction = request.form["direction"].strip()
            structure_type = request.form["structure_type"].strip()
            signal_type = request.form["signal_type"].strip()
            screenshot_link = request.form.get("screenshot_link", "").strip()
            moved_as_expected = request.form.get("moved_as_expected", "Unknown").strip()
            mfe_r = parse_float(request.form.get("mfe_r"))
            mae_r = parse_float(request.form.get("mae_r"))
            achieved_rr = parse_float(request.form.get("achieved_rr"))
            notes = request.form.get("notes", "").strip()

            datetime.strptime(trade_date, "%Y-%m-%d")
            datetime.strptime(trade_time, "%H:%M")

            if not all([trade_date, trade_time, assistant_name, instrument]):
                raise ValueError("日期、时间、助理姓名、品种不能为空。")

            with get_conn() as conn:
                conn.execute("""
                    INSERT INTO signals (
                        trade_date, trade_time, assistant_name, instrument, direction,
                        structure_type, signal_type, screenshot_link, moved_as_expected,
                        mfe_r, mae_r, achieved_rr, notes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade_date, trade_time, assistant_name, instrument, direction,
                    structure_type, signal_type, screenshot_link, moved_as_expected,
                    mfe_r, mae_r, achieved_rr, notes, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
                conn.commit()

            flash("信号已保存。", "success")
            return redirect(url_for("index"))
        except Exception as e:
            flash(f"保存失败：{e}", "error")

    now = datetime.now()
    return render_template(
        "new_signal.html",
        today=now.strftime("%Y-%m-%d"),
        current_time=now.strftime("%H:%M"),
        structure_options=STRUCTURE_OPTIONS,
        direction_options=DIRECTION_OPTIONS,
        signal_options=SIGNAL_OPTIONS,
        expected_options=EXPECTED_OPTIONS,
    )

@app.route("/delete/<int:signal_id>", methods=["POST"])
def delete_signal(signal_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM signals WHERE id = ?", (signal_id,))
        conn.commit()
    flash("记录已删除。", "success")
    return redirect(url_for("index"))

@app.route("/export")
def export_csv():
    filters = {
        "assistant": request.args.get("assistant", "全部"),
        "instrument": request.args.get("instrument", "全部"),
        "structure": request.args.get("structure", "全部"),
        "direction": request.args.get("direction", "全部"),
    }
    rows = get_rows(filters)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Date", "Time", "Assistant", "Instrument", "Direction",
        "StructureType", "SignalType", "ScreenshotLink", "MovedAsExpected",
        "MFE_R", "MAE_R", "Achieved_RR", "Notes", "CreatedAt"
    ])
    for r in rows:
        writer.writerow([
            r["id"], r["trade_date"], r["trade_time"], r["assistant_name"], r["instrument"],
            r["direction"], r["structure_type"], r["signal_type"], r["screenshot_link"],
            r["moved_as_expected"], r["mfe_r"], r["mae_r"], r["achieved_rr"], r["notes"], r["created_at"]
        ])

    mem = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="signals_export.csv")

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
init_db()
