"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    WHISPER TRANSCRIPTION API (FastAPI)                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                            ║
║  A production-ready REST API for speech-to-text transcription.             ║
║  Designed to be called by Activepieces, n8n, or any HTTP client.           ║
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
║  4. Test with curl:                                                        ║
║     curl -X POST http://localhost:8001/transcribe -F "file=@test.mp3"      ║
║                                                                            ║
║  5. Test URL download:                                                     ║
║     curl -X POST http://localhost:8001/transcribe                          ║
║          -H "Content-Type: application/json"                               ║
║          -d '{"url": "https://example.com/audio.mp3"}'                     ║
║                                                                            ║
║  6. Health check:                                                          ║
║     curl http://localhost:8001/health                                      ║
║                                                                            ║
║  INTEGRATION WITH ACTIVEPIECES                                             ║
║  ────────────────────────────────                                           ║
║  Use the "HTTP Request" piece:                                             ║
║    Method:  POST                                                           ║
║    URL:     http://<your-host>:8001/transcribe                             ║
║    Body:    Form Data → field "file" → your audio file                     ║
║    Result:  response.body.text → the transcribed text                      ║
║                                                                            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import io
import time
import tempfile
import logging
from pathlib import Path
from typing import Optional

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

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ─── Configuration ───────────────────────────────────────────────────────────
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "25"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Supported audio extensions (all formats Whisper/ffmpeg can handle)
SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm",
                        ".wma", ".aac", ".mp4", ".mpeg", ".mpga", ".oga"}

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
    description="Speech-to-text transcription service powered by Whisper.",
    version="1.0.0",
)

# ─── CORS Middleware (allow all origins for Activepieces / frontend access) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
#  Model Loading (uses faster-whisper, matching your existing whisper_server.py)
# ══════════════════════════════════════════════════════════════════════════════
model = None


def load_model():
    """Load the Whisper model once at startup."""
    global model
    if model is not None:
        return

    logger.info(f"Loading Whisper model='{WHISPER_MODEL}' device={WHISPER_DEVICE} compute={WHISPER_COMPUTE}...")

    # ── Option A: faster-whisper (DEFAULT — matches your existing setup) ─────
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)

    # ── Option B: openai-whisper (uncomment to use the original OpenAI package)
    # import whisper
    # model = whisper.load_model(WHISPER_MODEL)

    logger.info(f"✅ Whisper model loaded successfully!")


@app.on_event("startup")
async def startup_event():
    """Load model when the server starts."""
    load_model()


# ══════════════════════════════════════════════════════════════════════════════
#  Pydantic Models for request/response
# ══════════════════════════════════════════════════════════════════════════════
class URLRequest(BaseModel):
    """Request body for URL-based transcription."""
    url: str


class TranscriptionResponse(BaseModel):
    """Successful transcription response."""
    status: str = "success"
    text: str
    language: str
    duration_seconds: float


class ErrorResponse(BaseModel):
    """Error response."""
    status: str = "error"
    message: str


# ══════════════════════════════════════════════════════════════════════════════
#  Helper Functions
# ══════════════════════════════════════════════════════════════════════════════

def validate_file_extension(filename: str) -> bool:
    """Check if the file extension is a supported audio format."""
    ext = Path(filename).suffix.lower()
    return ext in SUPPORTED_EXTENSIONS


def resample_audio_if_needed(file_path: str) -> str:
    """
    Resample audio to 16 kHz mono WAV if needed (e.g., Twilio sends 8 kHz).
    faster-whisper and Whisper both expect 16 kHz input.
    Uses pydub (requires ffmpeg installed on the system).

    Returns the path to the (possibly resampled) audio file.
    """
    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_file(file_path)
        sample_rate = audio.frame_rate

        # Resample if not 16 kHz
        if sample_rate != 16000:
            logger.info(f"Resampling audio from {sample_rate} Hz → 16000 Hz")
            audio = audio.set_frame_rate(16000).set_channels(1)
            resampled_path = file_path + ".resampled.wav"
            audio.export(resampled_path, format="wav")
            return resampled_path

        return file_path

    except Exception as e:
        # If pydub fails, let Whisper try to handle the original file.
        # faster-whisper uses ffmpeg internally and can often handle it.
        logger.warning(f"Resampling skipped (pydub error: {e}). Whisper will try the original file.")
        return file_path


def transcribe_file(file_path: str) -> dict:
    """
    Run Whisper transcription on an audio file.
    Returns a dict with text, language, and duration.
    """

    # ── Option A: faster-whisper (DEFAULT) ───────────────────────────────────
    segments_generator, info = model.transcribe(
        file_path,
        beam_size=1,                        # Greedy decoding (fastest)
        condition_on_previous_text=False,
        temperature=0.0,                    # Deterministic output
    )

    # Consume the generator to get all segments
    segments = list(segments_generator)

    # Combine all segment texts into a single transcript
    full_text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())

    return {
        "text": full_text,
        "language": info.language or "unknown",
        "duration_seconds": round(info.duration, 2),
    }

    # ── Option B: openai-whisper (uncomment if using the original package) ───
    # result = model.transcribe(file_path, fp16=False)
    # return {
    #     "text": result["text"].strip(),
    #     "language": result.get("language", "unknown"),
    #     "duration_seconds": round(
    #         result["segments"][-1]["end"] if result.get("segments") else 0.0, 2
    #     ),
    # }


def download_audio_from_url(url: str) -> str:
    """
    Download audio from a remote URL and save to a temp file.
    Returns the path to the downloaded file.
    """
    import requests as req

    logger.info(f"Downloading audio from URL: {url}")

    try:
        response = req.get(url, stream=True, timeout=30)
        response.raise_for_status()
    except req.exceptions.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to download audio from URL: {e}")

    # Check Content-Length if available
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Remote file exceeds maximum size of {MAX_FILE_SIZE_MB} MB."
        )

    # Determine extension from URL or Content-Type
    from urllib.parse import urlparse
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        # Try to guess from Content-Type
        content_type = response.headers.get("Content-Type", "")
        type_map = {
            "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
            "audio/wav": ".wav", "audio/x-wav": ".wav",
            "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
            "audio/flac": ".flac", "audio/ogg": ".ogg",
            "audio/webm": ".webm",
        }
        ext = type_map.get(content_type.split(";")[0].strip(), ".wav")

    # Save to temp file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    total_bytes = 0
    for chunk in response.iter_content(chunk_size=8192):
        total_bytes += len(chunk)
        if total_bytes > MAX_FILE_SIZE_BYTES:
            tmp.close()
            os.unlink(tmp.name)
            raise HTTPException(
                status_code=400,
                detail=f"Remote file exceeds maximum size of {MAX_FILE_SIZE_MB} MB."
            )
        tmp.write(chunk)
    tmp.close()

    logger.info(f"Downloaded {total_bytes / 1024:.1f} KB → {tmp.name}")
    return tmp.name


# ══════════════════════════════════════════════════════════════════════════════
#  Groq Whisper API Alternative (commented out — uncomment to use)
# ══════════════════════════════════════════════════════════════════════════════
#
# def transcribe_with_groq(file_path: str) -> dict:
#     """
#     Transcribe audio using Groq's FREE Whisper API.
#     No GPU needed — runs on Groq's cloud infrastructure.
#
#     Setup:
#       1. Get a free API key at https://console.groq.com
#       2. Set GROQ_API_KEY in your .env file
#
#     This replaces the local Whisper model entirely.
#     """
#     import requests as req
#
#     api_key = os.getenv("GROQ_API_KEY")
#     if not api_key:
#         raise HTTPException(status_code=500, detail="GROQ_API_KEY not set in environment.")
#
#     url = "https://api.groq.com/openai/v1/audio/transcriptions"
#     headers = {"Authorization": f"Bearer {api_key}"}
#
#     with open(file_path, "rb") as f:
#         files = {"file": (Path(file_path).name, f, "audio/mpeg")}
#         data = {
#             "model": "whisper-large-v3",      # Groq's supported model
#             "response_format": "verbose_json",  # Get language + duration
#         }
#         response = req.post(url, headers=headers, files=files, data=data, timeout=120)
#
#     if response.status_code != 200:
#         raise HTTPException(
#             status_code=500,
#             detail=f"Groq API error ({response.status_code}): {response.text}"
#         )
#
#     result = response.json()
#     return {
#         "text": result.get("text", "").strip(),
#         "language": result.get("language", "unknown"),
#         "duration_seconds": round(result.get("duration", 0.0), 2),
#     }


# ══════════════════════════════════════════════════════════════════════════════
#  API Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health_check():
    """Health check endpoint — use this to verify the server is running."""
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
        400: {"model": ErrorResponse, "description": "Bad request (missing file, unsupported format, etc.)"},
        500: {"model": ErrorResponse, "description": "Internal server error (transcription failure)"},
    },
    summary="Transcribe an audio file to text",
    description=(
        "Upload an audio file via multipart/form-data (field name: `file`), "
        "or send a JSON body with a `url` field to download and transcribe remote audio."
    ),
)
async def transcribe(
    request: Request,
    file: Optional[UploadFile] = File(None),
):
    """
    Main transcription endpoint.

    Accepts either:
      1. A file upload via multipart/form-data (field: "file")
      2. A JSON body with {"url": "https://..."}

    Returns JSON with the transcript text, detected language, and audio duration.
    """
    tmp_path = None
    resampled_path = None

    try:
        # ── Determine input source ───────────────────────────────────────────
        if file and file.filename:
            # ── FILE UPLOAD ──────────────────────────────────────────────────
            logger.info(f"Received file upload: {file.filename} ({file.content_type})")

            # Validate extension
            if not validate_file_extension(file.filename):
                ext = Path(file.filename).suffix.lower()
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "error",
                        "message": (
                            f"Unsupported file format: '{ext}'. "
                            f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
                        ),
                    },
                )

            # Read file content and check size
            content = await file.read()
            if len(content) > MAX_FILE_SIZE_BYTES:
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "error",
                        "message": f"File too large ({len(content) / 1024 / 1024:.1f} MB). Maximum size is {MAX_FILE_SIZE_MB} MB.",
                    },
                )

            if len(content) == 0:
                return JSONResponse(
                    status_code=400,
                    content={"status": "error", "message": "Uploaded file is empty."},
                )

            # Save to temp file
            ext = Path(file.filename).suffix.lower()
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            tmp_file.write(content)
            tmp_file.close()
            tmp_path = tmp_file.name

        else:
            # ── URL DOWNLOAD (JSON body) ─────────────────────────────────────
            try:
                body = await request.json()
                url = body.get("url")
            except Exception:
                url = None

            if not url:
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "error",
                        "message": "No audio file provided. Send a file via multipart/form-data (field: 'file') or a JSON body with {'url': '...'}.",
                    },
                )

            tmp_path = download_audio_from_url(url)

        # ── Resample if needed (e.g., 8 kHz Twilio audio → 16 kHz) ──────────
        resampled_path = resample_audio_if_needed(tmp_path)
        audio_path = resampled_path

        # ── Transcribe ───────────────────────────────────────────────────────
        logger.info(f"Starting transcription: {audio_path}")
        start_time = time.time()

        result = transcribe_file(audio_path)

        # ── To use Groq instead, uncomment the line below and comment out the line above:
        # result = transcribe_with_groq(audio_path)

        elapsed = time.time() - start_time
        logger.info(
            f"✅ Transcription complete in {elapsed:.2f}s | "
            f"Language: {result['language']} | "
            f"Duration: {result['duration_seconds']}s | "
            f"Text length: {len(result['text'])} chars"
        )

        return {
            "status": "success",
            "text": result["text"],
            "language": result["language"],
            "duration_seconds": result["duration_seconds"],
        }

    except HTTPException:
        # Re-raise FastAPI HTTP exceptions as-is
        raise

    except Exception as e:
        # Catch-all for unexpected errors (corrupted audio, model failures, etc.)
        logger.error(f"❌ Transcription failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Transcription failed: {str(e)}",
            },
        )

    finally:
        # ── Cleanup temp files ───────────────────────────────────────────────
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
    """Return consistent JSON error responses for all HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Catch-all handler for unhandled exceptions."""
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
#  Transcribe a local file:
#    curl -X POST http://localhost:8001/transcribe -F "file=@test.mp3"
#
#  Transcribe from URL:
#    curl -X POST http://localhost:8001/transcribe \
#         -H "Content-Type: application/json" \
#         -d "{\"url\": \"https://example.com/audio.mp3\"}"
#
#  PowerShell (file upload):
#    Invoke-RestMethod -Uri http://localhost:8001/transcribe `
#      -Method Post -Form @{ file = Get-Item "test.mp3" }
#
#  PowerShell (URL download):
#    Invoke-RestMethod -Uri http://localhost:8001/transcribe `
#      -Method Post -ContentType "application/json" `
#      -Body '{"url":"https://example.com/audio.mp3"}'
#
# ══════════════════════════════════════════════════════════════════════════════
