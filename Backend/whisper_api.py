"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    WHISPER TRANSCRIPTION API (FastAPI)                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                            ║
║  A production-ready REST API for speech-to-text transcription.             ║
║  Designed to be called by Relay.app, Activepieces, n8n, or any HTTP client.║
║                                                                            ║
║  SETUP                                                                     ║
║  ─────                                                                     ║
║  1. Install dependencies:                                                  ║
║     pip install fastapi uvicorn python-multipart faster-whisper             ║
║                 pydub requests python-dotenv                               ║
║                                                                            ║
║  2. (Optional) Create a .env file:                                         ║
║     WHISPER_MODEL=base        # tiny | base | small | medium | large-v3    ║
║     WHISPER_DEVICE=cpu        # cpu | cuda                                 ║
║     WHISPER_COMPUTE=int8      # int8 | float16 | float32                   ║
║     MAX_FILE_SIZE_MB=25       # Maximum upload size in megabytes           ║
║     GROQ_API_KEY=gsk_...      # Only if using Groq alternative             ║
║                                                                            ║
║  3. Run the server:                                                        ║
║     uvicorn whisper_api:app --host 0.0.0.0 --port 8001 --reload            ║
║                                                                            ║
║  4. Test with curl (multipart):                                            ║
║     curl -X POST http://localhost:8001/transcribe -F "file=@test.mp3"      ║
║                                                                            ║
║  5. Test with curl (raw binary):                                           ║
║     curl -X POST http://localhost:8001/transcribe                          ║
║          -H "Content-Type: audio/mpeg" --data-binary @test.mp3             ║
║                                                                            ║
║  6. Test URL download:                                                     ║
║     curl -X POST http://localhost:8001/transcribe                          ║
║          -H "Content-Type: application/json"                               ║
║          -d '{"url": "https://example.com/audio.mp3"}'                     ║
║                                                                            ║
║  7. Health check:                                                          ║
║     curl http://localhost:8001/health                                      ║
║                                                                            ║
║  INTEGRATION WITH RELAY.APP                                                ║
║  ──────────────────────────                                                 ║
║  Step 3 "Call Speech-to-Text API":                                         ║
║    Method:   POST                                                          ║
║    URL:      http://<your-host>:8001/transcribe                            ║
║    Encoding: Binary (raw file upload)   ← use this option                  ║
║    Body:     ref → trigger.payload.file                                    ║
║    Result:   response.body.text → the transcribed text                     ║
║                                                                            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import tempfile
import logging
from pathlib import Path

# ─── Fix Windows terminal encoding ───────────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ─── Load environment variables ──────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ─── Configuration ───────────────────────────────────────────────────────────
WHISPER_MODEL   = os.getenv("WHISPER_MODEL",   "base")
WHISPER_DEVICE  = os.getenv("WHISPER_DEVICE",  "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
MAX_FILE_SIZE_MB    = int(os.getenv("MAX_FILE_SIZE_MB", "25"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Supported audio extensions (all formats Whisper/ffmpeg can handle)
SUPPORTED_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm",
    ".wma", ".aac", ".mp4", ".mpeg", ".mpga", ".oga",
}

# MIME type → file extension map for raw binary uploads
BINARY_EXT_MAP = {
    "audio/mpeg":            ".mp3",
    "audio/mp3":             ".mp3",
    "audio/wav":             ".wav",
    "audio/x-wav":           ".wav",
    "audio/wave":            ".wav",
    "audio/mp4":             ".m4a",
    "audio/x-m4a":           ".m4a",
    "audio/flac":            ".flac",
    "audio/ogg":             ".ogg",
    "audio/oga":             ".ogg",
    "audio/webm":            ".webm",
    "audio/aac":             ".aac",
    "audio/x-aac":           ".aac",
    "video/mp4":             ".mp4",
    "video/webm":            ".webm",
    "application/octet-stream": ".wav",  # safe default
}

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("whisper_api")


# ══════════════════════════════════════════════════════════════════════════════
#  FastAPI App
# ══════════════════════════════════════════════════════════════════════════════
app = FastAPI(
    title="Whisper Transcription API",
    description="Speech-to-text transcription powered by Whisper. Accepts multipart, raw binary, or JSON URL.",
    version="2.0.0",
)

# ─── CORS Middleware ──────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
#  Model Loading
# ══════════════════════════════════════════════════════════════════════════════
model = None


def load_model():
    """Load the Whisper model once at startup."""
    global model
    if model is not None:
        return

    logger.info(
        f"Loading Whisper model='{WHISPER_MODEL}' "
        f"device={WHISPER_DEVICE} compute={WHISPER_COMPUTE}..."
    )
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)
    logger.info("✅ Whisper model loaded successfully!")


@app.on_event("startup")
async def startup_event():
    """Load model when the server starts."""
    load_model()


# ══════════════════════════════════════════════════════════════════════════════
#  Pydantic Models
# ══════════════════════════════════════════════════════════════════════════════
class TranscriptionResponse(BaseModel):
    status: str = "success"
    text: str
    language: str
    duration_seconds: float


class ErrorResponse(BaseModel):
    status: str = "error"
    message: str


# ══════════════════════════════════════════════════════════════════════════════
#  Helper Functions
# ══════════════════════════════════════════════════════════════════════════════

def validate_file_extension(filename: str) -> bool:
    """Check if the file extension is a supported audio format."""
    return Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS


def resample_audio_if_needed(file_path: str) -> str:
    """
    Resample audio to 16 kHz mono WAV if needed (e.g., Twilio sends 8 kHz).
    Returns the path to the (possibly resampled) audio file.
    """
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(file_path)
        if audio.frame_rate != 16000:
            logger.info(f"Resampling audio from {audio.frame_rate} Hz → 16000 Hz")
            audio = audio.set_frame_rate(16000).set_channels(1)
            resampled_path = file_path + ".resampled.wav"
            audio.export(resampled_path, format="wav")
            return resampled_path
        return file_path
    except Exception as e:
        logger.warning(f"Resampling skipped ({e}). Whisper will try the original file.")
        return file_path


def transcribe_file(file_path: str) -> dict:
    """Run Whisper transcription on an audio file."""
    segments_generator, info = model.transcribe(
        file_path,
        beam_size=1,
        condition_on_previous_text=False,
        temperature=0.0,
    )
    segments = list(segments_generator)
    full_text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
    return {
        "text": full_text,
        "language": info.language or "unknown",
        "duration_seconds": round(info.duration, 2),
    }


def download_audio_from_url(url: str) -> str:
    """Download audio from a remote URL and save to a temp file."""
    import requests as req
    from urllib.parse import urlparse

    logger.info(f"Downloading audio from URL: {url}")
    try:
        response = req.get(url, stream=True, timeout=30)
        response.raise_for_status()
    except req.exceptions.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to download audio from URL: {e}")

    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Remote file exceeds maximum size of {MAX_FILE_SIZE_MB} MB.",
        )

    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        content_type = response.headers.get("Content-Type", "")
        ext = BINARY_EXT_MAP.get(content_type.split(";")[0].strip(), ".wav")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    total_bytes = 0
    for chunk in response.iter_content(chunk_size=8192):
        total_bytes += len(chunk)
        if total_bytes > MAX_FILE_SIZE_BYTES:
            tmp.close()
            os.unlink(tmp.name)
            raise HTTPException(
                status_code=400,
                detail=f"Remote file exceeds maximum size of {MAX_FILE_SIZE_MB} MB.",
            )
        tmp.write(chunk)
    tmp.close()
    logger.info(f"Downloaded {total_bytes / 1024:.1f} KB → {tmp.name}")
    return tmp.name


# ══════════════════════════════════════════════════════════════════════════════
#  API Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "model": WHISPER_MODEL,
        "device": WHISPER_DEVICE,
        "max_file_size_mb": MAX_FILE_SIZE_MB,
    }


@app.post(
    "/transcribe",
    response_model=TranscriptionResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad request"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
    summary="Transcribe audio to text",
    description=(
        "Accepts audio via three methods:\n"
        "1. **Multipart form-data** — any field name, any Content-Type\n"
        "2. **Raw binary body** — Content-Type: audio/mpeg, audio/wav, etc. (use for Relay.app Binary encoding)\n"
        "3. **JSON body** — `{\"url\": \"https://...\"}`"
    ),
)
async def transcribe(request: Request):
    """
    Main transcription endpoint. Tries input sources in this order:
      1. multipart/form-data  (any field name)
      2. raw binary body      (Content-Type: audio/*, video/*, application/octet-stream)
      3. JSON body            ({"url": "https://..."})
    """
    tmp_path = None
    resampled_path = None

    try:
        ct = request.headers.get("content-type", "").lower()
        logger.info(f"POST /transcribe — Content-Type: '{ct}'")
        
        # ── DEBUG LOGGING FOR RELAY.APP WORKFLOW ─────────────────────────────
        try:
            with open("relay_debug.txt", "a", encoding="utf-8") as f:
                f.write("=== INCOMING REQUEST ===\n")
                f.write(f"Content-Type: {ct}\n")
                for k, v in request.headers.items():
                    f.write(f"Header: {k} = {v}\n")
        except Exception:
            pass

        # ── 1. Multipart form-data (any field name) ───────────────────────────
        tmp_path = None
        if "multipart/form-data" in ct or "application/x-www-form-urlencoded" in ct:
            try:
                form = await request.form()

                # ── Verbose per-field logging so we can see exactly what arrives ──
                for key, value in form.items():
                    if hasattr(value, "filename"):
                        logger.info(
                            f"  Form field '{key}': UploadFile "
                            f"filename='{value.filename}' "
                            f"content_type='{getattr(value, 'content_type', '?')}'"
                        )
                    else:
                        # Log string values (may be a URL from Relay.app)
                        preview = str(value)[:300]
                        logger.info(f"  Form field '{key}': str = '{preview}'")

                # ── Pass A: look for a proper file upload ─────────────────────
                for key, value in form.items():
                    if hasattr(value, "filename") and hasattr(value, "read") and value.filename:
                        logger.info(f"File upload found in field='{key}' filename='{value.filename}'")

                        if not validate_file_extension(value.filename):
                            ext = Path(value.filename).suffix.lower()
                            return JSONResponse(
                                status_code=400,
                                content={
                                    "status": "error",
                                    "message": (
                                        f"Unsupported format '{ext}'. "
                                        f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
                                    ),
                                },
                            )

                        data = await value.read()
                        if len(data) == 0:
                            return JSONResponse(
                                status_code=400,
                                content={"status": "error", "message": "Uploaded file is empty."},
                            )
                        if len(data) > MAX_FILE_SIZE_BYTES:
                            return JSONResponse(
                                status_code=400,
                                content={
                                    "status": "error",
                                    "message": f"File too large ({len(data)/1024/1024:.1f} MB). Max: {MAX_FILE_SIZE_MB} MB.",
                                },
                            )

                        ext = Path(value.filename).suffix.lower()
                        tf = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                        tf.write(data)
                        tf.close()
                        tmp_path = tf.name
                        break

                # ── Pass B: Relay.app sends file as a URL string in the form ──
                if tmp_path is None:
                    for key, value in form.items():
                        if isinstance(value, str) and value.startswith("http"):
                            logger.info(f"URL string found in form field='{key}': {value[:200]}")
                            tmp_path = download_audio_from_url(value)
                            break

            except Exception as form_err:
                logger.warning(f"Form parse error: {form_err}")

        # ── 2. Raw binary body (Relay.app "Binary" encoding) ──────────────────
        if tmp_path is None and any(
            ct.split(";")[0].strip().startswith(p)
            for p in ("audio/", "video/", "application/octet-stream")
        ):
            mime = ct.split(";")[0].strip()
            ext = BINARY_EXT_MAP.get(mime, ".wav")
            raw = await request.body()
            logger.info(f"Raw binary body: mime='{mime}' size={len(raw)} bytes → ext='{ext}'")

            if len(raw) == 0:
                return JSONResponse(
                    status_code=400,
                    content={"status": "error", "message": "Raw binary body is empty."},
                )
            if len(raw) > MAX_FILE_SIZE_BYTES:
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "error",
                        "message": f"File too large ({len(raw)/1024/1024:.1f} MB). Max: {MAX_FILE_SIZE_MB} MB.",
                    },
                )

            tf = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            tf.write(raw)
            tf.close()
            tmp_path = tf.name

        # ── 3. JSON body with {"url": "..."} ──────────────────────────────────
        if tmp_path is None:
            url = None
            try:
                body = await request.json()
                if isinstance(body, dict):
                    url = body.get("url")
            except Exception:
                pass

            if not url:
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "error",
                        "message": (
                            "No audio file received. Send audio via:\n"
                            "  1. multipart/form-data (any field name)\n"
                            "  2. Raw binary body (Content-Type: audio/mpeg, audio/wav, etc.)\n"
                            "  3. JSON body: {\"url\": \"https://...\"}\n\n"
                            f"Received Content-Type was: '{ct}'"
                        ),
                    },
                )

            tmp_path = download_audio_from_url(url)

        # ── Resample if needed ────────────────────────────────────────────────
        resampled_path = resample_audio_if_needed(tmp_path)
        audio_path = resampled_path

        # ── Transcribe ────────────────────────────────────────────────────────
        logger.info(f"Starting transcription: {audio_path}")
        start_time = time.time()
        result = transcribe_file(audio_path)
        elapsed = time.time() - start_time

        logger.info(
            f"✅ Done in {elapsed:.2f}s | "
            f"lang={result['language']} | "
            f"dur={result['duration_seconds']}s | "
            f"chars={len(result['text'])}"
        )

        return {
            "status": "success",
            "text": result["text"],
            "language": result["language"],
            "duration_seconds": result["duration_seconds"],
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"❌ Transcription failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Transcription failed: {str(e)}"},
        )

    finally:
        for path in [tmp_path, resampled_path]:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass


# ══════════════════════════════════════════════════════════════════════════════
#  Custom Error Handlers
# ══════════════════════════════════════════════════════════════════════════════

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "An unexpected internal error occurred."},
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Run directly with: python whisper_api.py
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("API_PORT", "8001"))
    logger.info(f"Starting Whisper API on http://0.0.0.0:{port}")
    uvicorn.run(
        "whisper_api:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  TESTING COMMANDS
# ══════════════════════════════════════════════════════════════════════════════
#
#  Health check:
#    curl http://localhost:8001/health
#
#  Multipart (any field name):
#    curl -X POST http://localhost:8001/transcribe -F "file=@test.mp3"
#    curl -X POST http://localhost:8001/transcribe -F "audio=@test.wav"
#
#  Raw binary (Relay.app Binary encoding):
#    curl -X POST http://localhost:8001/transcribe \
#         -H "Content-Type: audio/mpeg" --data-binary @test.mp3
#
#  URL download:
#    curl -X POST http://localhost:8001/transcribe \
#         -H "Content-Type: application/json" \
#         -d '{"url": "https://example.com/audio.mp3"}'
#
# ══════════════════════════════════════════════════════════════════════════════
