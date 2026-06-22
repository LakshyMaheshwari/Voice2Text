const mongoose = require('mongoose')

const transcriptSchema = new mongoose.Schema({
    meetingId: {
        type: mongoose.Schema.Types.ObjectId,
        ref: 'Meeting',
        required: true
    },
    segments: [
        {
            speaker: { type: String },
            text: { type: String },
            start: { type: Number },
            end: { type: Number }
        }
    ],
    fullText: {
        type: String
    },
    createdAt: {
        type: Date,
        default: Date.now
    }
})

module.exports = mongoose.model('Transcript', transcriptSchema)
