const express = require('express');
const cors = require('cors');
const cookieParser = require('cookie-parser');
const path = require('path');
const authRoutes = require('./routes/auth.routes');
const meetingRoutes = require('./routes/meeting.routes');

const app = express();

// Allow all origins (including file:// when opened locally)
app.use(cors({
    origin: (origin, callback) => callback(null, true),
    credentials: true
}));

app.use(express.json());
app.use(cookieParser());

// Serve frontend static files
app.use(express.static(path.join(__dirname, '../../Frontend')));

app.use('/api/auth', authRoutes);
app.use('/api/meetings', meetingRoutes);

module.exports = app;