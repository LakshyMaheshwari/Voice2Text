"""
Mock Whisper WebSocket Server (for testing Task 6.4)
Run: pip install websockets
Run: python mock_whisper_server.py
Listens on ws://localhost:8765
"""

import asyncio
import json
import websockets

async def handle_connection(websocket):
    print(f"[MockWhisper] Client connected: {websocket.remote_address}")

    async for message in websocket:
        # The Node.js service sends: JSON_HEADER\nBINARY_AUDIO
        # Parse out the meetingId from the header line
        meeting_id = None
        try:
            if isinstance(message, bytes):
                # Find the first newline separating the JSON header from binary data
                newline_pos = message.find(b'\n')
                if newline_pos != -1:
                    header_bytes = message[:newline_pos]
                    audio_bytes = message[newline_pos + 1:]
                    header = json.loads(header_bytes.decode('utf-8'))
                    meeting_id = header.get('meetingId')
                    print(f"[MockWhisper] Got audio chunk | meetingId: {meeting_id} | audio size: {len(audio_bytes)} bytes")
                else:
                    print(f"[MockWhisper] Got raw binary: {len(message)} bytes (no meetingId header)")
            else:
                print(f"[MockWhisper] Got text message: {message}")
        except Exception as e:
            print(f"[MockWhisper] Parse error: {e}")

        # Send back a fake transcription response
        if meeting_id:
            response = {
                "meetingId": meeting_id,
                "text": "Hello, this is a test transcription from mock Whisper.",
                "speaker": "Speaker 1",
                "isFinal": True,
                "start": 0.0,
                "end": 2.5
            }
            await websocket.send(json.dumps(response))
            print(f"[MockWhisper] Sent transcription for meeting: {meeting_id}")

    print(f"[MockWhisper] Client disconnected")

async def main():
    print("[MockWhisper] Starting mock Whisper WebSocket server on ws://localhost:8765")
    async with websockets.serve(handle_connection, "localhost", 8765):
        print("[MockWhisper] Ready! Waiting for audio chunks...")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())
