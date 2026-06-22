const express = require('express')
const meetingModel = require('../models/Meeting.model')
const transcriptModel = require('../models/Transcript.model')
const summaryModel = require('../models/Summary.model')
const authMiddleware = require('../middleware/auth')

const meetingRoutes = express.Router()

// All routes are protected
meetingRoutes.use(authMiddleware)

// POST / → Create a new meeting
meetingRoutes.post("/", async (req, res) => {
    try {
        const {title, startTime} = req.body

        const meeting = await meetingModel.create({
            userId: req.user.id,
            title: title || 'Untitled Meeting',
            status: 'recording',
            startTime: startTime || new Date()
        })

        res.status(201).json({
            message: "Meeting created",
            meeting
        })
    } catch(error) {
        res.status(500).json({message: "Failed to create meeting", error: error.message})
    }
})

// GET / → Get all meetings for logged-in user (sorted by date desc)
meetingRoutes.get("/", async (req, res) => {
    try {
        const meetings = await meetingModel
            .find({userId: req.user.id})
            .sort({createdAt: -1})
            .populate('transcriptId')
            .populate('summaryId')

        res.status(200).json({
            message: "Meetings fetched",
            count: meetings.length,
            meetings
        })
    } catch(error) {
        res.status(500).json({message: "Failed to fetch meetings", error: error.message})
    }
})

// GET /:id → Get a single meeting by ID
meetingRoutes.get("/:id", async (req, res) => {
    try {
        const meeting = await meetingModel
            .findOne({_id: req.params.id, userId: req.user.id})
            .populate('transcriptId')
            .populate('summaryId')

        if(!meeting){
            return res.status(404).json({message: "Meeting not found"})
        }

        res.status(200).json({meeting})
    } catch(error) {
        res.status(500).json({message: "Failed to fetch meeting", error: error.message})
    }
})

// PUT /:id → Update a meeting
meetingRoutes.put("/:id", async (req, res) => {
    try {
        const meeting = await meetingModel.findOne({_id: req.params.id, userId: req.user.id})

        if(!meeting){
            return res.status(404).json({message: "Meeting not found"})
        }

        const updatedMeeting = await meetingModel.findByIdAndUpdate(
            req.params.id,
            req.body,
            {new: true, runValidators: true}
        )

        res.status(200).json({
            message: "Meeting updated",
            meeting: updatedMeeting
        })
    } catch(error) {
        res.status(500).json({message: "Failed to update meeting", error: error.message})
    }
})

// DELETE /:id → Delete a meeting and its transcript + summary
meetingRoutes.delete("/:id", async (req, res) => {
    try {
        const meeting = await meetingModel.findOne({_id: req.params.id, userId: req.user.id})

        if(!meeting){
            return res.status(404).json({message: "Meeting not found"})
        }

        // Cascade delete transcript and summary
        if(meeting.transcriptId){
            await transcriptModel.findByIdAndDelete(meeting.transcriptId)
        }
        if(meeting.summaryId){
            await summaryModel.findByIdAndDelete(meeting.summaryId)
        }

        await meetingModel.findByIdAndDelete(req.params.id)

        res.status(200).json({message: "Meeting deleted successfully"})
    } catch(error) {
        res.status(500).json({message: "Failed to delete meeting", error: error.message})
    }
})

module.exports = meetingRoutes
