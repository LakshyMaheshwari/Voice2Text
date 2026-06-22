/**
 * AI Meeting Assistant — Background Service Worker
 *
 * Handles:
 * - Tab audio capture via chrome.tabCapture
 * - WebSocket connection to the backend
 * - Audio chunk streaming
 * - Recording state management
 */

// ─── State ──────────────────────────────────────────────────────────────────────
let mediaRecorder = null;
let socket = null;
let recordingState = {
  isRecording: false,
  meetingId: null,
  tabId: null,
};

const BACKEND_URL = 'http://localhost:5000';

// ─── Socket.io via fetch-based polling (service worker compatible) ──────────────
// Since service workers can't use the socket.io client library directly,
// we use a simple WebSocket connection instead.

function connectWebSocket(token) {
  return new Promise((resolve, reject) => {
    // Use native WebSocket with Socket.io's WebSocket transport
    // Socket.io server accepts raw WebSocket at /socket.io/?EIO=4&transport=websocket
    const wsUrl = `ws://localhost:5000/socket.io/?EIO=4&transport=websocket`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      console.log('[BG] WebSocket connected');
      // Socket.io handshake: send auth
      socket.send(`40{"token":"${token}"}`);
      resolve(socket);
    };

    socket.onmessage = (event) => {
      const data = event.data;
      handleSocketMessage(data);
    };

    socket.onerror = (error) => {
      console.error('[BG] WebSocket error:', error);
      reject(error);
    };

    socket.onclose = () => {
      console.log('[BG] WebSocket closed');
      socket = null;
    };
  });
}

function handleSocketMessage(raw) {
  // Socket.io protocol: messages start with type code
  // 0 = open, 2 = ping, 3 = pong, 40 = connect, 42 = event
  if (raw === '2') {
    // Ping — respond with pong
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send('3');
    }
    return;
  }

  if (raw.startsWith('42')) {
    try {
      const payload = JSON.parse(raw.substring(2));
      const [eventName, eventData] = payload;

      if (eventName === 'joined') {
        console.log('[BG] Joined meeting:', eventData);
        broadcastToPopup({ type: 'joined', data: eventData });
      }

      if (eventName === 'transcription') {
        console.log('[BG] Transcription:', eventData);
        broadcastToPopup({ type: 'transcription', data: eventData });
      }

      if (eventName === 'processing-status') {
        console.log('[BG] Processing status:', eventData);
        broadcastToPopup({ type: 'processing-status', data: eventData });

        if (eventData.status === 'completed' || eventData.status === 'failed') {
          recordingState.isRecording = false;
          recordingState.meetingId = null;
          saveState();
        }
      }

      if (eventName === 'error') {
        console.error('[BG] Server error:', eventData);
        broadcastToPopup({ type: 'error', data: eventData });
      }
    } catch (e) {
      // Not a JSON event
    }
  }
}

function emitSocketEvent(eventName, data) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(`42${JSON.stringify([eventName, data])}`);
  }
}

// ─── Audio Capture ──────────────────────────────────────────────────────────────

async function startCapture(tabId, meetingId, token) {
  try {
    // Connect WebSocket if not already
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      await connectWebSocket(token);
    }

    // Join meeting room
    emitSocketEvent('join-meeting', { meetingId });

    // Capture tab audio
    const stream = await chrome.tabCapture.capture({
      audio: true,
      video: false,
    });

    if (!stream) {
      throw new Error('Failed to capture tab audio');
    }

    // Create AudioContext to process audio
    const audioContext = new AudioContext({ sampleRate: 16000 });
    const source = audioContext.createMediaStreamSource(stream);

    // Use ScriptProcessorNode to get raw PCM chunks
    // (AudioWorklet would be better but isn't fully supported in service workers)
    const processor = audioContext.createScriptProcessor(4096, 1, 1);

    processor.onaudioprocess = (event) => {
      if (!recordingState.isRecording) return;

      const inputData = event.inputBuffer.getChannelData(0);
      // Convert float32 to int16 PCM
      const pcmData = new Int16Array(inputData.length);
      for (let i = 0; i < inputData.length; i++) {
        const s = Math.max(-1, Math.min(1, inputData[i]));
        pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }

      // Send as binary via WebSocket
      if (socket && socket.readyState === WebSocket.OPEN) {
        // Socket.io binary: we need to send as a Socket.io event
        emitSocketEvent('audio-chunk', Array.from(pcmData.buffer));
      }
    };

    source.connect(processor);
    processor.connect(audioContext.destination);

    // Update state
    recordingState = {
      isRecording: true,
      meetingId,
      tabId,
      stream,
      audioContext,
      processor,
      source,
    };

    await saveState();
    console.log('[BG] Recording started for meeting:', meetingId);

    return { success: true, meetingId };
  } catch (error) {
    console.error('[BG] Capture error:', error);
    return { success: false, error: error.message };
  }
}

async function stopCapture() {
  try {
    if (recordingState.isRecording) {
      // Notify server
      emitSocketEvent('end-recording', {});

      // Stop audio processing
      if (recordingState.processor) {
        recordingState.processor.disconnect();
      }
      if (recordingState.source) {
        recordingState.source.disconnect();
      }
      if (recordingState.audioContext) {
        await recordingState.audioContext.close();
      }
      if (recordingState.stream) {
        recordingState.stream.getTracks().forEach(track => track.stop());
      }

      const meetingId = recordingState.meetingId;

      recordingState = {
        isRecording: false,
        meetingId: null,
        tabId: null,
      };

      await saveState();
      console.log('[BG] Recording stopped');

      return { success: true, meetingId };
    }

    return { success: false, error: 'Not recording' };
  } catch (error) {
    console.error('[BG] Stop error:', error);
    return { success: false, error: error.message };
  }
}

// ─── State Persistence ──────────────────────────────────────────────────────────

async function saveState() {
  await chrome.storage.local.set({
    recordingState: {
      isRecording: recordingState.isRecording,
      meetingId: recordingState.meetingId,
      tabId: recordingState.tabId,
    }
  });
}

async function loadState() {
  const data = await chrome.storage.local.get('recordingState');
  if (data.recordingState) {
    recordingState.isRecording = data.recordingState.isRecording;
    recordingState.meetingId = data.recordingState.meetingId;
    recordingState.tabId = data.recordingState.tabId;
  }
}

// ─── Message Handling (from popup & content scripts) ─────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    switch (message.type) {
      case 'GET_STATE':
        sendResponse({
          isRecording: recordingState.isRecording,
          meetingId: recordingState.meetingId,
        });
        break;

      case 'START_RECORDING': {
        const { meetingId, token, tabId } = message;
        const result = await startCapture(tabId, meetingId, token);
        sendResponse(result);
        break;
      }

      case 'STOP_RECORDING': {
        const result = await stopCapture();
        sendResponse(result);
        break;
      }

      case 'PAGE_INFO':
        // From content script — store page context
        console.log('[BG] Page info:', message.data);
        await chrome.storage.local.set({ pageInfo: message.data });
        sendResponse({ received: true });
        break;

      default:
        sendResponse({ error: 'Unknown message type' });
    }
  })();
  return true; // Keep message channel open for async response
});

// ─── Broadcast to popup ─────────────────────────────────────────────────────────

function broadcastToPopup(message) {
  chrome.runtime.sendMessage(message).catch(() => {
    // Popup not open — that's fine
  });
}

// ─── Initialize ─────────────────────────────────────────────────────────────────
loadState();
console.log('[BG] AI Meeting Assistant service worker loaded');
