const { GoogleGenAI } = require('@google/genai')

class SummarizeService {
    constructor() {
        // Initializes with process.env.GEMINI_API_KEY. We pass an empty object 
        // to prevent a TypeError bug in the SDK if options are completely omitted.
        this.ai = new GoogleGenAI(process.env.GEMINI_API_KEY ? { apiKey: process.env.GEMINI_API_KEY } : {})
    }

    async generateSummary(fullText) {
        if (!process.env.GEMINI_API_KEY) {
            return "Summarization disabled: Please add GEMINI_API_KEY to your .env file."
        }

        if (!fullText || fullText.trim() === '') {
            return "No transcript available to summarize."
        }

        try {
            const prompt = `You are an AI meeting assistant. Summarize the following meeting transcript. Provide a concise summary, followed by a bulleted list of key takeaways and action items if any are present.\n\nTranscript:\n${fullText}`
            
            const response = await this.ai.models.generateContent({
                model: 'gemini-2.5-flash',
                contents: prompt,
            });

            return response.text
        } catch (error) {
            console.error('[SummarizeService] Error generating summary:', error)
            return "Failed to generate summary due to an AI error."
        }
    }
}

module.exports = new SummarizeService()
