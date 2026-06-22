const Transcript = require('../models/Transcript.model')
const Meeting = require('../models/Meeting.model')
const summarizeService = require('./summarizeService')

// processingService.finaliseMeeting
// Called after end-recording with the cached segments for that meeting
async function finaliseMeeting(meetingId, segments, socket) {
    try {
        console.log(`[ProcessingService] Finalising meeting: ${meetingId} | Segments: ${segments.length}`)

        // Build fullText by joining all segment texts
        const fullText = segments.map(s => s.text).join(' ')

        // 7.1a - Save Transcript document
        const transcript = await Transcript.create({
            meetingId,
            segments,
            fullText
        })

        console.log(`[ProcessingService] Transcript saved: ${transcript._id}`)

        // 7.1b - Link transcript to meeting and mark completed
        await Meeting.findByIdAndUpdate(meetingId, {
            status: 'completed',
            transcriptId: transcript._id
        })

        console.log(`[ProcessingService] Meeting ${meetingId} marked as completed`)

        // 7.1c - Emit summary-ready to the meeting room (no summary yet initially)
        if(socket){
            // socket is actually 'io' here, so .to().emit() sends to everyone in the room
            socket.to(meetingId).emit('summary-ready', {
                meetingId,
                transcriptId: transcript._id,
                fullText,
                segments,
                summary: "Generating summary..."  
            })
        }

        // Generate summary asynchronously
        try {
            const summaryText = await summarizeService.generateSummary(fullText)
            
            // Save to DB
            transcript.summary = summaryText
            await transcript.save()

            // Update meeting status
            await Meeting.findByIdAndUpdate(meetingId, {
                status: 'completed'
            })

            // Emit final summary
            if(socket) {
                socket.to(meetingId).emit('summary-ready', {
                    meetingId,
                    transcriptId: transcript._id,
                    fullText,
                    segments,
                    summary: summaryText
                })
            }
        } catch (e) {
            console.error('[ProcessingService] Summarisation failed:', e)
        }

        return transcript
    } catch(error) {
        console.error('[ProcessingService] Error finalising meeting:', error.message)
        if(socket){
            socket.emit('error', { message: 'Failed to finalise meeting transcript' })
        }
        throw error
    }
}

module.exports = { finaliseMeeting }
