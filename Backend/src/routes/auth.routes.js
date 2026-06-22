const express = require('express')
const userModel = require('../models/User.model')
const jwt = require('jsonwebtoken')
const bcrypt = require('bcryptjs')
const authMiddleware = require('../middleware/auth')

const authroutes = express.Router()

authroutes.post("/register", async (req, res) => {
    try {
        const {email, name, password} = req.body

        const existingUser = await userModel.findOne({email})
        if(existingUser){
            return res.status(400).json({message: "Email already registered"})
        }

        const salt = await bcrypt.genSalt(10)
        const hashedPassword = await bcrypt.hash(password, salt)

        const user = await userModel.create({
            email, password: hashedPassword, name
        })

        const token = jwt.sign({
            id: user._id,
            email: user.email
        },
        process.env.JWT_SECRET,
        { expiresIn: "7d" }
        )

        res.cookie("jwt_token", token)

        res.status(201).json({
            message: "User Registered",
            user: {email, name},
            token
        })
    } catch(error) {
        res.status(500).json({message: "Registration failed", error: error.message})
    }
})

authroutes.post("/login", async (req, res) => {
    try {
        const {email, password} = req.body

        const user = await userModel.findOne({email})
        if(!user){
            return res.status(400).json({message: "Invalid credentials"})
        }

        const isMatch = await bcrypt.compare(password, user.password)
        if(!isMatch){
            return res.status(400).json({message: "Invalid credentials"})
        }

        const token = jwt.sign({
            id: user._id,
            email: user.email
        },
        process.env.JWT_SECRET,
        { expiresIn: "7d" }
        )

        res.cookie("jwt_token", token)

        res.status(200).json({
            message: "User Logged In",
            user: {email: user.email, name: user.name},
            token
        })
    } catch(error) {
        res.status(500).json({message: "Login failed", error: error.message})
    }
})

authroutes.get("/me", authMiddleware, async (req, res) => {
    try {
        const user = await userModel.findById(req.user.id);
        if (!user) {
            return res.status(404).json({ message: "User not found" });
        }
        res.status(200).json({ user });
    } catch (error) {
        res.status(500).json({ message: "Failed to fetch user", error: error.message });
    }
})

module.exports = authroutes
