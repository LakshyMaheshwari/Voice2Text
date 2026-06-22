// Task 5.4 - WebSocket test script
// Run: node test-socket.js <your_jwt_token> <meeting_id>
//
// Get your token by logging in via POST /api/auth/login
// Get your meetingId via POST /api/meetings

const { io } = require('socket.io-client')

const TOKEN = process.argv[2]
const MEETING_ID = process.argv[3]

if(!TOKEN || !MEETING_ID){
    console.error('Usage: node test-socket.js <jwt_token> <meeting_id>')
    process.exit(1)
}

console.log('Connecting to server...')

const socket = io('http://localhost:5000', {
    auth: { token: TOKEN }
})

socket.on('connect', () => {
    console.log(`✅ Connected! Socket ID: ${socket.id}`)

    // Step 1: Join a meeting room
    console.log(`Joining meeting room: ${MEETING_ID}`)
    socket.emit('join-meeting', MEETING_ID)
})

socket.on('joined-meeting', (data) => {
    console.log('✅ Joined meeting:', data)

    // Step 2: Send dummy audio chunks
    console.log('Sending 3 dummy audio chunks...')
    for(let i = 1; i <= 3; i++){
        const dummyChunk = Buffer.from(`dummy-audio-chunk-${i}`)
        socket.emit('audio-chunk', dummyChunk)
        console.log(`  Sent chunk ${i} (${dummyChunk.length} bytes)`)
    }

    // Step 3: End recording after 1 second
    setTimeout(() => {
        console.log('Sending end-recording event...')
        socket.emit('end-recording')
    }, 1000)
})

socket.on('recording-ended', (data) => {
    console.log('✅ Recording ended:', data)
})

socket.on('summary-ready', (data) => {
    console.log('\n✅ Summary ready (transcript saved to DB):')
    console.log(`   TranscriptId : ${data.transcriptId}`)
    console.log(`   Full Text    : ${data.fullText}`)
    console.log(`   Segments     : ${data.segments?.length || 0}`)
    console.log(`   Summary      : ${data.summary || '(pending summarisation)'}`)
    console.log('\nAll tests passed! Disconnecting...')
    socket.disconnect()
})

socket.on('connect_error', (err) => {
    console.error('❌ Connection error:', err.message)
    process.exit(1)
})

socket.on('error', (err) => {
    console.error('❌ Socket error:', err)
})

socket.on('disconnect', () => {
    console.log('Disconnected from server.')
    process.exit(0)
})
