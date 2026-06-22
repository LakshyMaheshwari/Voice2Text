const mongoose = require('mongoose')

const summarySchema = new mongoose.Schema({
    meetingId: {
        type: mongoose.Schema.Types.ObjectId,
        ref: 'Meeting',
        required: true
    },
    keyPoints: [
        { type: String }
    ],
    actionItems: [
        {
            description: { type: String },
            assignedTo: { type: String },
            done: { type: Boolean, default: false }
        }
    ],
    fullSummary: {
        type: String
    },
    createdAt: {
        type: Date,
        default: Date.now
    }
})

module.exports = mongoose.model('Summary', summarySchema)
