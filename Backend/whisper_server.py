import sys
import asyncio
import json
import argparse
import numpy as np
import websockets
from faster_whisper import WhisperModel

# Fix Windows terminal encoding
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ─── Config ──────────────────────────────────────────────────────────────────
SAMPLE_RATE = 16000          # Hz — Whisper's required input rate
BYTES_PER_SAMPLE = 2         # int16 = 2 bytes
CHUNK_SECONDS = 3            # Process every 3 seconds of audio
CHUNK_BYTES = SAMPLE_RATE * CHUNK_SECONDS * BYTES_PER_SAMPLE  # 96,000 bytes

model = None  # Loaded once at startup

import wave
import os

# ─── Audio processing ─────────────────────────────────────────────────────────
def transcribe_sync(audio_float32):
    """
    Runs faster-whisper synchronously.
    CRITICAL FIX: model.transcribe() returns (generator, info).
    You must iterate the GENERATOR to get actual segments — do NOT wrap in list() directly.
    """
    segments_generator, info = model.transcribe(
        audio_float32,
        beam_size=1,          # beam_size=1 is fastest (greedy)
        language="en",
        vad_filter=False,     # Keep off — VAD filters out short speech
        condition_on_previous_text=False,
        temperature=0.0,      # Deterministic output
    )
    # Must consume the generator HERE (inside the thread), not outside
    segments = list(segments_generator)
    return segments, info

async def process_audio(websocket, meeting_id, audio_bytes):
    """Convert PCM int16 bytes → float32 → run Whisper → send JSON results."""
    if not audio_bytes or len(audio_bytes) < BYTES_PER_SAMPLE * 100:
        return

    try:
        # Simpler debug: just append raw PCM bytes to a file
        with open(f"debug_raw_{meeting_id}.pcm", "ab") as f:
            f.write(audio_bytes)

        # Convert raw int16 PCM → float32 numpy array
        audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0

        max_amp = float(np.max(np.abs(audio_float32)))
        duration = len(audio_float32) / SAMPLE_RATE
        print(f"[Whisper] Transcribing {duration:.2f}s | meeting={meeting_id} | max_amp={max_amp:.4f}")

        # Run in thread executor so event loop stays responsive
        loop = asyncio.get_event_loop()
        segments, info = await loop.run_in_executor(None, transcribe_sync, audio_float32)

        print(f"[Whisper] Got {len(segments)} segment(s) | detected_language={info.language} | prob={info.language_probability:.2f}")

        if not segments:
            print(f"[Whisper] No speech detected for meeting={meeting_id}")
            return

        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            response = {
                "meetingId": meeting_id,
                "text": text,
                "speaker": "Speaker 1",
                "isFinal": True,
                "start": round(seg.start, 2),
                "end": round(seg.end, 2)
            }
            print(f"[Whisper] [{seg.start:.1f}s -> {seg.end:.1f}s] {text}")
            await websocket.send(json.dumps(response))

    except Exception as e:
        print(f"[Whisper] ERROR in process_audio: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()


# ─── Connection handler ────────────────────────────────────────────────────────
async def handle_connection(websocket):
    addr = websocket.remote_address
    print(f"[Whisper] Client connected: {addr}")

    # Per-meeting audio buffers
    buffers = {}

    try:
        async for message in websocket:
            if isinstance(message, bytes):
                # Protocol: JSON header + '\n' + raw int16 PCM audio bytes
                newline_pos = message.find(b'\n')
                if newline_pos == -1:
                    print("[Whisper] WARNING: binary message has no header newline, skipping")
                    continue

                try:
                    header = json.loads(message[:newline_pos].decode('utf-8'))
                    meeting_id = header.get('meetingId')
                    audio_data = message[newline_pos + 1:]
                except Exception as e:
                    print(f"[Whisper] WARNING: failed to parse header: {e}")
                    continue

                if not meeting_id:
                    print("[Whisper] WARNING: no meetingId in header")
                    continue

                if meeting_id not in buffers:
                    buffers[meeting_id] = bytearray()
                    print(f"[Whisper] New buffer started for meeting={meeting_id}")

                buffers[meeting_id].extend(audio_data)
                buf_len = len(buffers[meeting_id])
                print(f"[Whisper] Buffer [{meeting_id}]: {buf_len}/{CHUNK_BYTES} bytes ({audio_data.__len__()} new)")

                if buf_len >= CHUNK_BYTES:
                    chunk = bytes(buffers[meeting_id])
                    buffers[meeting_id].clear()
                    print(f"[Whisper] Buffer full — processing {len(chunk)} bytes for meeting={meeting_id}")
                    await process_audio(websocket, meeting_id, chunk)

            elif isinstance(message, str):
                try:
                    msg = json.loads(message)
                except Exception:
                    continue

                if msg.get('type') == 'flush':
                    meeting_id = msg.get('meetingId')
                    print(f"[Whisper] FLUSH received for meeting={meeting_id}")

                    if meeting_id and meeting_id in buffers:
                        remaining = bytes(buffers.pop(meeting_id))
                        print(f"[Whisper] Flushing {len(remaining)} remaining bytes")
                        if len(remaining) >= BYTES_PER_SAMPLE * 100:
                            await process_audio(websocket, meeting_id, remaining)

                    # Always acknowledge flush
                    ack = json.dumps({"type": "flush_done", "meetingId": meeting_id})
                    await websocket.send(ack)
                    print(f"[Whisper] flush_done sent for meeting={meeting_id}")

    except websockets.exceptions.ConnectionClosedOK:
        print(f"[Whisper] Client disconnected cleanly: {addr}")
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"[Whisper] Client disconnected with error: {e}")
    except Exception as e:
        print(f"[Whisper] Unexpected error in handle_connection: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()


# ─── Main ─────────────────────────────────────────────────────────────────────
async def main(model_size, device, compute_type):
    global model
    print(f"[Whisper] Loading model='{model_size}' device={device} compute_type={compute_type}...")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    print(f"[Whisper] Model loaded! Listening on ws://localhost:8765")

    async with websockets.serve(
        handle_connection,
        "localhost",
        8765,
        max_size=100 * 1024 * 1024  # 100MB max message
    ):
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real-time Whisper WebSocket Server")
    parser.add_argument("--model", default="tiny", choices=["tiny", "base", "small", "medium", "large-v2", "large-v3"])
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--compute-type", default="int8", choices=["int8", "float16", "float32"])
    args = parser.parse_args()

    asyncio.run(main(args.model, args.device, args.compute_type))
