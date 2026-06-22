require('dotenv').config()
const app = require('./src/app')
const connectToDB = require('./src/config/database')
const jwt = require('jsonwebtoken')
const meetingModel = require('./src/models/Meeting.model')
const whisperService = require('./src/services/whisperService')
const processingService = require('./src/services/processingService')

// 5.1 - Create HTTP server and attach Socket.io
const server = require('http').createServer(app)
const io = require('socket.io')(server, {
    cors: { origin: '*' }
})

connectToDB()

// 7.2 - In-memory cache: meetingId → array of transcript segments
const transcriptCache = {}

// 5.2 - Socket.io JWT authentication middleware
io.use((socket, next) => {
    const token = socket.handshake.auth.token

    if(!token){
        return next(new Error('Authentication error: No token provided'))
    }

    try {
        const decoded = jwt.verify(token, process.env.JWT_SECRET)
        socket.userId = decoded.id
        next()
    } catch(error) {
        return next(new Error('Authentication error: Invalid token'))
    }
})

// 5.3 - Connection handler
io.on('connection', (socket) => {
    console.log(`Socket connected: ${socket.id} | User: ${socket.userId}`)

    // Join a meeting room
    socket.on('join-meeting', (meetingId) => {
        socket.data.meetingId = meetingId
        socket.join(meetingId)

        // Initialise cache for this meeting if not already
        if(!transcriptCache[meetingId]){
            transcriptCache[meetingId] = []
        }

        console.log(`Socket ${socket.id} joined meeting room: ${meetingId}`)
        socket.emit('joined-meeting', { meetingId, message: 'Joined meeting room' })
    })

    // 6.3 - Bridge audio chunk to Whisper service
    socket.on('audio-chunk', (chunk) => {
        const meetingId = socket.data.meetingId
        console.log(`Audio chunk received from socket ${socket.id} | meeting: ${meetingId} | size: ${chunk?.length || 0} bytes`)
        whisperService.sendAudioChunk(chunk, meetingId)
    })

    // End recording → call processingService to finalise (Task 7.3)
    socket.on('end-recording', async () => {
        const meetingId = socket.data.meetingId

        if(!meetingId){
            return socket.emit('error', { message: 'No meeting joined' })
        }

        try {
            // Mark as processing first
            await meetingModel.findByIdAndUpdate(meetingId, {
                status: 'processing',
                endTime: new Date()
            })

            console.log(`Meeting ${meetingId} marked as processing`)
            socket.emit('recording-ended', { meetingId, status: 'processing' })

            // Send flush command to Python whisper server to process any remaining audio
            // The actual finalisation will happen when we receive the 'flush_done' message back
            whisperService.flushMeeting(meetingId)

            // Fallback: if no flush_done in 10 seconds, finalise anyway to prevent hanging
            setTimeout(async () => {
                if (transcriptCache[meetingId]) {
                    console.log(`[WhisperServer] ⚠️ Flush timeout for meeting ${meetingId} - finalizing anyway.`)
                    const segments = transcriptCache[meetingId] || []
                    try {
                        await processingService.finaliseMeeting(meetingId, segments, io)
                    } catch(e) {}
                    delete transcriptCache[meetingId]
                }
            }, 10000)

        } catch(error) {
            console.error('Error ending recording:', error.message)
            socket.emit('error', { message: 'Failed to end recording' })
        }
    })

    // Disconnect cleanup
    socket.on('disconnect', () => {
        console.log(`Socket disconnected: ${socket.id} | User: ${socket.userId}`)
    })
})

const PORT = process.env.PORT || 3000
server.listen(PORT, () => {
    console.log(`Server is running on port ${PORT}`)

    // 6.2 - Connect to Whisper service and register transcription message handler
    whisperService.connect()

    whisperService.onMessage(async (message) => {
        // Handle control messages
        if (message.type === 'flush_done') {
            const meetingId = message.meetingId
            console.log(`[WhisperServer] Flush done for meeting ${meetingId}`)
            const segments = transcriptCache[meetingId] || []
            try {
                // Pass 'io' instead of 'socket' because the specific socket might be gone
                await processingService.finaliseMeeting(meetingId, segments, io)
            } catch(e) { console.error('Finalisation error:', e.message) }
            delete transcriptCache[meetingId]
            return
        }

        // Expected message from Python: { meetingId, text, speaker, isFinal, start, end }
        const { meetingId, text, speaker, isFinal, start, end } = message

        if(!meetingId){
            console.warn('[WhisperService] Received message without meetingId:', message)
            return
        }

        console.log(`[Transcription] Meeting: ${meetingId} | Speaker: ${speaker} | isFinal: ${isFinal} | Text: ${text}`)

        // Emit live transcription to all clients in the meeting room
        io.to(meetingId).emit('transcription', { text, speaker, isFinal, start, end })

        // Cache ALL segments for post-processing (not just isFinal)
        // Each Whisper chunk is independently finalized, so we cache all of them
        if(!transcriptCache[meetingId]){
            transcriptCache[meetingId] = []
        }
        transcriptCache[meetingId].push({ speaker, text, start, end })
        console.log(`[TranscriptCache] Cached segment for meeting ${meetingId} | Total: ${transcriptCache[meetingId].length}`)
    })
})
