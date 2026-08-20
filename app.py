import os
import time
import traceback
import shutil

try:
    import pyodbc
except ImportError:
    pyodbc = None

from datetime import datetime, timezone

from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    send_from_directory,
    g,
)

from audio_analysis import analyze_audio


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")


# ---------------------------------------------------------------------------
# FFmpeg Configuration
# ---------------------------------------------------------------------------

# Your installed FFmpeg directory
FFMPEG_DIR = (
    r"C:\Users\prash\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg.Shared_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-9.0.1-full_build-shared"
    r"\bin"
)

FFMPEG_PATH = os.path.join(FFMPEG_DIR, "ffmpeg.exe")
FFPROBE_PATH = os.path.join(FFMPEG_DIR, "ffprobe.exe")


# Add FFmpeg directory to PATH for this Python process
if os.path.isdir(FFMPEG_DIR):
    os.environ["PATH"] = (
        FFMPEG_DIR
        + os.pathsep
        + os.environ.get("PATH", "")
    )


# ---------------------------------------------------------------------------
# SQL Server Configuration
# ---------------------------------------------------------------------------

SQL_SERVER = r"PRASHANT\SQLEXPRESS"
SQL_DATABASE = "ConsultBaeDB"

# IMPORTANT:
# Change these to your SQL Server login credentials.
CONNECTION_STRING = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={SQL_SERVER};"
    f"DATABASE={SQL_DATABASE};"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)


# ---------------------------------------------------------------------------
# Create upload directory
# ---------------------------------------------------------------------------

os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Flask Application
# ---------------------------------------------------------------------------

app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


# ---------------------------------------------------------------------------
# Allowed Audio Extensions
# ---------------------------------------------------------------------------

ALLOWED_EXT = {
    "wav",
    "mp3",
    "m4a",
    "webm",
    "ogg",
    "flac",
    "aac",
    "mp4",
    "3gp",
    "caf",
}


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class _database:
    """Small request-scoped wrapper around the SQL Server connection."""

    def __init__(self, connection_string):
        self.connection_string = connection_string
        self._connection = None

    def _get_connection(self):
        if self._connection is None:

            if pyodbc is None:
                raise RuntimeError(
                    "pyodbc is required to connect to the database"
                )

            self._connection = pyodbc.connect(
                self.connection_string
            )

        return self._connection

    def cursor(self):
        return self._get_connection().cursor()

    def commit(self):
        self._get_connection().commit()

    def rollback(self):
        if self._connection is not None:
            self._connection.rollback()

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None


# ---------------------------------------------------------------------------
# Get Database
# ---------------------------------------------------------------------------

def get_db():

    db = getattr(g, "_database", None)

    if db is None:
        db = g._database = _database(
            CONNECTION_STRING
        )

    return db


# ---------------------------------------------------------------------------
# Close Database Connection
# ---------------------------------------------------------------------------

@app.teardown_appcontext
def close_connection(exception):

    db = getattr(g, "_database", None)

    if db is not None:
        db.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def allowed_file(filename):

    return (
        "."
        in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXT
    )


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------

def _wants_json():

    return request.path.startswith("/api/")


@app.errorhandler(404)
def handle_404(e):

    if _wants_json():

        return jsonify({
            "error": "Not found: " + request.path
        }), 404

    return e


@app.errorhandler(405)
def handle_405(e):

    if _wants_json():

        return jsonify({
            "error": "Method not allowed on " + request.path
        }), 405

    return e


@app.errorhandler(413)
def handle_413(e):

    return jsonify({
        "error": "Audio file is too large (max 50MB)."
    }), 413


@app.errorhandler(500)
def handle_500(e):

    traceback.print_exc()

    if _wants_json():

        return jsonify({
            "error": "Server error: " + str(e)
        }), 500

    return e


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():

    return render_template(
        "index.html"
    )


@app.route("/submissions")
def submissions_view():

    return render_template(
        "submissions.html"
    )


# ---------------------------------------------------------------------------
# API - List Audio Records
# ---------------------------------------------------------------------------

@app.route(
    "/api/submissions",
    methods=["GET"]
)
def api_list_submissions():

    db = get_db()

    cursor = db.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            phone,
            filename,
            original_filename,
            file_path,
            duration_sec,
            sample_rate_hz,
            sample_rate_khz,
            bitrate_kbps,
            channels,
            loudness_dbfs,
            peak_dbfs,
            noise_floor_dbfs,
            snr_db,
            quality_label,
            created_at
        FROM Audio
        ORDER BY id DESC
    """)

    columns = [
        column[0]
        for column in cursor.description
    ]

    rows = [
        dict(zip(columns, row))
        for row in cursor.fetchall()
    ]

    cursor.close()

    return jsonify(rows)


# ---------------------------------------------------------------------------
# Serve Uploaded Audio
# ---------------------------------------------------------------------------

@app.route(
    "/uploads/<path:filename>"
)
def uploaded_file(filename):

    return send_from_directory(
        UPLOAD_DIR,
        filename
    )


# ---------------------------------------------------------------------------
# Submit Audio
# ---------------------------------------------------------------------------

@app.route(
    "/api/submit",
    methods=["POST"]
)
def submit():

    filepath = None

    try:

        # ---------------------------------------------------------------
        # Get Form Data
        # ---------------------------------------------------------------

        name = request.form.get(
            "name",
            ""
        ).strip()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        audio_file = request.files.get(
            "audio"
        )


        # ---------------------------------------------------------------
        # Validate Name
        # ---------------------------------------------------------------

        if not name:

            return jsonify({
                "error": "Name is required"
            }), 400


        # ---------------------------------------------------------------
        # Validate Phone
        # ---------------------------------------------------------------

        if not phone:

            return jsonify({
                "error": "Phone number is required"
            }), 400


        # ---------------------------------------------------------------
        # Validate Audio
        # ---------------------------------------------------------------

        if (
            not audio_file
            or not audio_file.filename
        ):

            return jsonify({
                "error": "Audio (recorded or uploaded) is required"
            }), 400


        # ---------------------------------------------------------------
        # Original File Name
        # ---------------------------------------------------------------

        orig_name = (
            audio_file.filename
            or "recording.webm"
        )


        # ---------------------------------------------------------------
        # Get Extension
        # ---------------------------------------------------------------

        ext = (
            orig_name.rsplit(".", 1)[-1].lower()
            if "." in orig_name
            else ""
        )


        if ext not in ALLOWED_EXT:

            ext = "webm"


        # ---------------------------------------------------------------
        # Generate Safe File Name
        # ---------------------------------------------------------------

        timestamp = int(
            time.time() * 1000
        )

        safe_stub = "".join(
            c
            for c in name
            if c.isalnum()
            or c in (" ", "_", "-")
        ).strip().replace(
            " ",
            "_"
        )

        safe_stub = safe_stub or "anon"

        safe_name = (
            f"{timestamp}_{safe_stub}.{ext}"
        )


        # ---------------------------------------------------------------
        # Full File Path
        # ---------------------------------------------------------------

        filepath = os.path.join(
            UPLOAD_DIR,
            safe_name
        )


        # ---------------------------------------------------------------
        # Save Uploaded File
        # ---------------------------------------------------------------

        audio_file.save(filepath)


        # ---------------------------------------------------------------
        # Verify Uploaded File
        # ---------------------------------------------------------------

        if not os.path.exists(filepath):

            return jsonify({
                "error": "Uploaded file could not be saved."
            }), 500


        print()
        print("=" * 70)
        print("AUDIO FILE DEBUG")
        print("=" * 70)

        print(
            "Audio file:",
            filepath
        )

        print(
            "File exists:",
            os.path.exists(filepath)
        )

        print(
            "File size:",
            os.path.getsize(filepath),
            "bytes"
        )

        print(
            "FFmpeg path:",
            shutil.which("ffmpeg")
        )

        print(
            "FFprobe path:",
            shutil.which("ffprobe")
        )

        print(
            "FFmpeg exists:",
            os.path.exists(FFMPEG_PATH)
        )

        print(
            "FFprobe exists:",
            os.path.exists(FFPROBE_PATH)
        )

        print("=" * 70)
        print()


        # ---------------------------------------------------------------
        # Analyze Audio
        # ---------------------------------------------------------------

        try:

            analysis = analyze_audio(
                filepath
            )

        except Exception as e:

            traceback.print_exc()

            return jsonify({
                "error": (
                    f"Could not analyze audio file: {e}"
                ),
                "file": safe_name,
                "filepath": filepath,
                "ffmpeg": shutil.which("ffmpeg"),
                "ffprobe": shutil.which("ffprobe"),
            }), 400


        # ---------------------------------------------------------------
        # Insert Into SQL Server Audio Table
        # ---------------------------------------------------------------

        db = get_db()

        cursor = db.cursor()


        cursor.execute("""
            INSERT INTO Audio (
                name,
                phone,
                filename,
                original_filename,
                file_path,
                duration_sec,
                sample_rate_hz,
                sample_rate_khz,
                bitrate_kbps,
                channels,
                loudness_dbfs,
                peak_dbfs,
                noise_floor_dbfs,
                snr_db,
                quality_label,
                created_at
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )
        """, (

            name,

            phone,

            safe_name,

            orig_name,

            filepath,

            analysis["duration_sec"],

            analysis["sample_rate_hz"],

            analysis["sample_rate_khz"],

            analysis["bitrate_kbps"],

            analysis["channels"],

            analysis["loudness_dbfs"],

            analysis["peak_dbfs"],

            analysis["noise_floor_dbfs"],

            analysis["snr_db"],

            analysis["quality_label"],

            datetime.now(timezone.utc),
        ))


        # ---------------------------------------------------------------
        # Commit Database
        # ---------------------------------------------------------------

        db.commit()

        cursor.close()


        # ---------------------------------------------------------------
        # Success
        # ---------------------------------------------------------------

        return jsonify({

            "success": True,

            "message": (
                "Audio saved successfully"
            ),

            "filename": safe_name,

            "analysis": analysis

        })


    # -------------------------------------------------------------------
    # Unexpected Error
    # -------------------------------------------------------------------

    except Exception as e:

        traceback.print_exc()

        return jsonify({

            "error": (
                f"Unexpected server error: {e}"
            )

        }), 500


# ---------------------------------------------------------------------------
# Run Flask
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    debug = (
        os.environ.get(
            "FLASK_DEBUG",
            "0"
        ) == "1"
    )


    print()
    print("=" * 70)
    print("AUDIO APPLICATION")
    print("=" * 70)

    print(
        "FFmpeg:",
        shutil.which("ffmpeg")
    )

    print(
        "FFprobe:",
        shutil.which("ffprobe")
    )

    print(
        "Upload directory:",
        UPLOAD_DIR
    )

    print(
        "Upload directory exists:",
        os.path.exists(UPLOAD_DIR)
    )

    print("=" * 70)
    print()


    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug
    )