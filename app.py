import logging
import os
import sys
import base64
import csv
import io
import sqlite3
import tempfile
import traceback
from datetime import datetime

from flask import Flask, make_response, redirect, render_template, request, url_for
from fpdf import FPDF


def resource_path(relative):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def data_dir():
    # Cloud: set DATA_DIR env var (e.g. /data on Railway volume)
    # Local Mac: uses Application Support
    # Local dev: uses project folder
    if os.environ.get("DATA_DIR"):
        path = os.environ["DATA_DIR"]
    elif sys.platform == "darwin" and not os.environ.get("RAILWAY_ENVIRONMENT"):
        path = os.path.expanduser("~/Library/Application Support/Beechwood Golf Course")
    else:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(path, exist_ok=True)
    return path


_data_dir = data_dir()
LOG_PATH = os.path.join(_data_dir, "app.log")
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)
# Also log to stdout so Railway's log viewer works
logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

app = Flask(__name__, template_folder=resource_path("templates"), static_folder=resource_path("static"))
app.secret_key = "beechwood-golf-course"
DB_PATH = os.path.join(_data_dir, "waivers.db")
logging.info("App starting. DB=%s Templates=%s", DB_PATH, resource_path("templates"))

WAIVER_TEXT = """\
GOLF CART LIABILITY WAIVER AND RELEASE OF LIABILITY

By signing below, I, the undersigned ("Participant"), acknowledge, understand, and voluntarily agree to the following terms and conditions:

1. ASSUMPTION OF RISK
I understand and acknowledge that operating or riding in a golf cart involves inherent risks, including but not limited to: tipping or rolling over on uneven terrain, collisions with other golf carts, vehicles, pedestrians, or fixed objects, loss of control, personal injury, and property damage. I voluntarily and knowingly assume ALL risks associated with operating or riding in a golf cart at Beechwood Golf Course.

2. RELEASE AND WAIVER OF LIABILITY
I hereby release, waive, discharge, and covenant not to sue Beechwood Golf Course, its owners, operators, officers, employees, agents, volunteers, and representatives (collectively "Released Parties") from any and all liability, claims, demands, actions, and causes of action — whether known or unknown — arising out of or related to any loss, damage, injury (including death) that may be sustained by me, whether caused by the negligence of the Released Parties or otherwise, while operating or riding in a golf cart on the premises.

3. RESPONSIBILITY FOR DAMAGE TO THE GOLF CART
I accept full financial responsibility for any and all damage sustained to the golf cart assigned to me during my use, including damage resulting from collision, rollover, improper use, off-path operation, failure to follow instructions, or any other cause attributable to my actions or negligence. I agree to reimburse Beechwood Golf Course for the full cost of repairs or replacement if necessary.

4. RESPONSIBILITY FOR INJURY AND DAMAGE TO THIRD PARTIES
I accept full personal and financial responsibility for any bodily injury, death, or property damage caused to any third party as a result of my operation of a golf cart. I agree to indemnify, defend, and hold harmless the Released Parties from any and all claims, damages, losses, costs, and expenses (including reasonable attorney's fees) arising out of or resulting from third-party injury or property damage caused by my operation of a golf cart.

5. GOLF COURSE RULES AND REGULATIONS
I agree to operate the golf cart in strict accordance with all rules and regulations of Beechwood Golf Course, including but not limited to: posted speed limits, designated cart paths, cart-free zones, and any verbal or written instructions provided by course staff. I understand that failure to comply may result in immediate suspension of cart privileges.

6. ACKNOWLEDGMENT OF LEGAL CAPACITY
I certify that I am at least 18 years of age, legally competent to enter into this agreement, and that I have read this Waiver carefully, understand its contents and legal consequences, and sign it freely and voluntarily without inducement.
"""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS waivers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                signature_data TEXT NOT NULL
            )
        """)


init_db()


def pdf_safe(text):
    """Replace characters unsupported by fpdf's built-in Helvetica font."""
    return (text
        .replace("—", "--")   # em dash
        .replace("–", "-")    # en dash
        .replace("‘", "'")    # left single quote
        .replace("’", "'")    # right single quote
        .replace("“", '"')    # left double quote
        .replace("”", '"')    # right double quote
        .replace("…", "...")  # ellipsis
    )


def build_pdf(entry):
    pdf = FPDF()
    pdf.set_margins(20, 20, 20)
    pdf.add_page()
    effective_width = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(effective_width, 10, pdf_safe("Beechwood Golf Course"), ln=True, align="C")
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(effective_width, 8, pdf_safe("Golf Cart Liability Waiver"), ln=True, align="C")
    pdf.ln(4)

    pdf.set_draw_color(34, 85, 34)
    pdf.set_line_width(0.5)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(5)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(35, 7, "Full Name:", ln=False)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, pdf_safe(entry["name"]), ln=True)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(35, 7, "Phone:", ln=False)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, pdf_safe(entry["phone"]), ln=True)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(35, 7, "Date & Time:", ln=False)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, pdf_safe(entry["timestamp"]), ln=True)
    pdf.ln(4)

    pdf.set_draw_color(34, 85, 34)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(5)

    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(effective_width, 5.5, pdf_safe(WAIVER_TEXT))
    pdf.ln(6)

    pdf.set_draw_color(34, 85, 34)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(5)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Participant Signature:", ln=True)
    pdf.ln(2)

    sig_data = entry["signature_data"]
    if sig_data.startswith("data:image/png;base64,"):
        sig_data = sig_data[len("data:image/png;base64,"):]

    sig_bytes = base64.b64decode(sig_data)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    try:
        tmp.write(sig_bytes)
        tmp.close()
        pdf.image(tmp.name, x=pdf.l_margin, w=90, h=35)
    finally:
        os.unlink(tmp.name)

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 6, pdf_safe(f"Signed electronically on {entry['timestamp']} -- Beechwood Golf Course"), ln=True)

    return bytes(pdf.output())


@app.route("/")
def index():
    return render_template("index.html", waiver_text=WAIVER_TEXT)


@app.route("/submit", methods=["POST"])
def submit():
    try:
        data = request.get_json(force=True, silent=True) or {}
        name = data.get("name", "").strip()
        phone = data.get("phone", "").strip()
        signature_data = data.get("signature", "").strip()

        logging.debug("Submit: name=%r phone=%r sig_len=%d", name, phone, len(signature_data))

        if not name or not phone or not signature_data or signature_data == "data:,":
            return "Please fill in all fields and provide a signature.", 400

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            conn.execute(
                "INSERT INTO waivers (timestamp, name, phone, signature_data) VALUES (?, ?, ?, ?)",
                (timestamp, name, phone, signature_data),
            )
        logging.info("Waiver saved for %s", name)
        return render_template("success.html", name=name)
    except Exception:
        err = traceback.format_exc()
        logging.error("Submit failed:\n%s", err)
        return err, 500


@app.route("/admin")
def admin():
    with get_db() as conn:
        entries = conn.execute(
            "SELECT id, timestamp, name, phone FROM waivers ORDER BY timestamp DESC"
        ).fetchall()
    return render_template("admin.html", entries=entries, count=len(entries))


@app.route("/admin/export/csv")
def export_csv():
    with get_db() as conn:
        entries = conn.execute(
            "SELECT id, timestamp, name, phone FROM waivers ORDER BY timestamp DESC"
        ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Date & Time", "Name", "Phone"])
    for e in entries:
        writer.writerow([e["id"], e["timestamp"], e["name"], e["phone"]])
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = (
        f"attachment; filename=beechwood_waivers_{datetime.now().strftime('%Y%m%d')}.csv"
    )
    return response


@app.route("/admin/export/pdf/<int:entry_id>")
def export_pdf(entry_id):
    with get_db() as conn:
        entry = conn.execute("SELECT * FROM waivers WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        return "Entry not found", 404
    pdf_bytes = build_pdf(entry)
    safe_name = "".join(c for c in entry["name"] if c.isalnum() or c in (" ", "-", "_")).strip().replace(" ", "_")
    filename = f"waiver_{safe_name}_{entry['timestamp'][:10]}.pdf"
    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@app.route("/admin/delete/<int:entry_id>", methods=["POST"])
def delete_entry(entry_id):
    with get_db() as conn:
        conn.execute("DELETE FROM waivers WHERE id = ?", (entry_id,))
    return redirect(url_for("admin"))


if __name__ == "__main__":
    import threading
    import time

    # When running on a server (Railway etc.) just serve normally
    if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("PORT"):
        port = int(os.environ.get("PORT", 8080))
        app.run(host="0.0.0.0", port=port, debug=False)
    else:
        import webview

        def run_flask():
            app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)

        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        time.sleep(0.8)

        webview.create_window(
            "Beechwood Golf Course",
            "http://127.0.0.1:5000",
            width=820,
            height=920,
            min_size=(600, 700),
            resizable=True,
        )
        webview.start()
