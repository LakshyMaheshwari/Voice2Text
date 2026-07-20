import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
import httpx

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Voice to Justice - API Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
client = httpx.AsyncClient(timeout=300.0)

RELAY_WEBHOOK_URL = "https://hook.relay.app/api/v1/playbook/cmrsprshw3g5b0plx1pf15ad9/trigger/U3PMBa-YDU-szZXYNLauIw"

# Serve the frontend from /static, and the root / returns index.html
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
async def serve_frontend():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.post("/relay-webhook")
async def relay_webhook_proxy(request: Request):
    """Proxy the Relay webhook call so the browser avoids CORS issues."""
    body = await request.body()
    try:
        res = await client.post(
            RELAY_WEBHOOK_URL,
            content=body,
            headers={"Content-Type": "application/json"}
        )
        return Response(content=res.content, status_code=res.status_code, headers=dict(res.headers))
    except Exception as e:
        return Response(
            content=f'{{"status":"error", "message":"Relay proxy error: {str(e)}"}}',
            status_code=502,
            media_type="application/json"
        )

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def gateway(request: Request, path: str):
    # Route /transcribe and /health to the Whisper API (port 8001)
    if path.startswith("transcribe") or path == "health":
        target_port = 8001
    else:
        # Route /ask, /upload, etc., to the RAG API (port 8000)
        target_port = 8000

    target_url = f"http://127.0.0.1:{target_port}/{path}"
    
    # Read the body from the incoming request
    body = await request.body()
    
    # Forward the request to the correct internal server
    req = client.build_request(
        request.method,
        target_url,
        headers=request.headers.raw,
        content=body
    )
    
    try:
        res = await client.send(req)
        return Response(content=res.content, status_code=res.status_code, headers=dict(res.headers))
    except Exception as e:
        return Response(content=f'{{"status":"error", "message":"Gateway error: {str(e)}"}}', status_code=502, media_type="application/json")

if __name__ == "__main__":
    print("Starting API Gateway on http://localhost:8080")
    print("   -> Frontend: http://localhost:8080/")
    print("   -> Routing /transcribe to port 8001")
    print("   -> Routing everything else to port 8000")
    uvicorn.run(app, host="0.0.0.0", port=8080)
