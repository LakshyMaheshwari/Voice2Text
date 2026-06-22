const mongoose = require('mongoose')

const meetingSchema = new mongoose.Schema({
    userId: {
        type: mongoose.Schema.Types.ObjectId,
        ref: 'User',
        required: true
    },
    title: {
        type: String,
        default: 'Untitled Meeting'
    },
    status: {
        type: String,
        enum: ['recording', 'processing', 'completed', 'failed'],
        default: 'recording'
    },
    startTime: {
        type: Date
    },
    endTime: {
        type: Date
    },
    audioFileUrl: {
        type: String
    },
    transcriptId: {
        type: mongoose.Schema.Types.ObjectId,
        ref: 'Transcript'
    },
    summaryId: {
        type: mongoose.Schema.Types.ObjectId,
        ref: 'Summary'
    }
}, { timestamps: true })

module.exports = mongoose.model('Meeting', meetingSchema)
