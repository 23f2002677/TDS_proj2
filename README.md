🚀 Overview

This project implements an automatic LLM-powered quiz solver for the TDS LLM Analysis Quiz (IITM BS Data Science / TDS Course).
Your deployed endpoint receives a POST request, loads a quiz page (often JavaScript-rendered), extracts data, analyzes it, and submits the correct answer within 3 minutes, automatically following multi-step quiz chains.

The system is designed to solve tasks involving:
	•	🔍 Web scraping (JS-enabled via Playwright)
	•	📄 PDF parsing
	•	📊 CSV / Excel processing
	•	🧹 Text & data cleaning
	•	📈 Data analysis & visualization extraction
	•	🤖 LLM-backed heuristic reasoning
	•	🔁 Multi-question recursion

⸻

🌐 API Endpoint

Your endpoint will look like:
https://your-render-app.onrender.com/api/quiz-webhook

It accepts this JSON payload:
{
  "email": "your-student-email",
  "secret": "your-secret",
  "url": "https://example.com/quiz-123"
}

✔ Required conditions
	•	Valid JSON → returns 400 if invalid
	•	Secret must match your environment → returns 403 if wrong
	•	Correct secret → server returns 200 OK, starts solving quiz in background

⸻

⚙️ Environment Variables (Render)

Set the following in Render → Service → Environment:

Variable
Description
QUIZ_EMAIL
Your student email (used for quiz submissions)
QUIZ_SECRET
Secret string you submitted in the Google Form
PORT
Auto-set by Render (your app uses it)

