const WebSocket = require('ws')

const WHISPER_URL = process.env.WHISPER_WS_URL || 'ws://localhost:8765'
const MAX_RECONNECT_ATTEMPTS = 10

class WhisperService {
    constructor() {
        this.ws = null
        this.isConnected = false
        this.reconnectAttempts = 0
        this.messageCallback = null
        this.reconnectTimer = null
    }

    connect() {
        if(this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)){
            return
        }

        console.log(`[WhisperService] Connecting to ${WHISPER_URL}...`)
        this.ws = new WebSocket(WHISPER_URL)

        this.ws.on('open', () => {
            console.log('[WhisperService] Connected to Whisper service')
            this.isConnected = true
            this.reconnectAttempts = 0
        })

        this.ws.on('message', (data) => {
            try {
                const parsed = JSON.parse(data.toString())
                if(this.messageCallback){
                    this.messageCallback(parsed)
                }
            } catch(error) {
                console.error('[WhisperService] Failed to parse message:', error.message)
            }
        })

        this.ws.on('close', (code, reason) => {
            this.isConnected = false
            console.log(`[WhisperService] Disconnected. Code: ${code} | Reason: ${reason}`)
            this._scheduleReconnect()
        })

        this.ws.on('error', (error) => {
            console.error('[WhisperService] WebSocket error:', error.message)
            this.isConnected = false
        })
    }

    _scheduleReconnect() {
        if(this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS){
            console.error('[WhisperService] Max reconnect attempts reached. Giving up.')
            return
        }

        // Exponential backoff: 1s, 2s, 4s, 8s, ... capped at 30s
        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000)
        this.reconnectAttempts++

        console.log(`[WhisperService] Reconnecting in ${delay / 1000}s... (attempt ${this.reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`)

        this.reconnectTimer = setTimeout(() => {
            this.connect()
        }, delay)
    }

    sendAudioChunk(buffer, meetingId) {
        if(!this.isConnected || !this.ws || this.ws.readyState !== WebSocket.OPEN){
            console.warn('[WhisperService] Cannot send chunk — not connected')
            return
        }

        // Prepend a small JSON header + newline + binary chunk
        // so the Python service knows which meeting this chunk belongs to
        if(meetingId){
            const header = Buffer.from(JSON.stringify({ meetingId }) + '\n')
            const packet = Buffer.concat([header, Buffer.isBuffer(buffer) ? buffer : Buffer.from(buffer)])
            this.ws.send(packet)
        } else {
            this.ws.send(buffer)
        }
    }

    flushMeeting(meetingId) {
        if (meetingId && this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'flush', meetingId }))
        }
    }

    onMessage(callback) {
        this.messageCallback = callback
    }

    disconnect() {
        if(this.reconnectTimer){
            clearTimeout(this.reconnectTimer)
        }
        if(this.ws){
            this.ws.removeAllListeners()
            this.ws.close()
            this.ws = null
        }
        this.isConnected = false
        console.log('[WhisperService] Manually disconnected')
    }
}

// Export a singleton
module.exports = new WhisperService()
