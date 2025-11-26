# app.py - Gemini version

import os
import tempfile
import json

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from werkzeug.utils import secure_filename

import pdfplumber
from docx import Document

import google.generativeai as genai

# -----------------------------------------------------------------------------
# Flask app & CORS
# -----------------------------------------------------------------------------
app = Flask(__name__)
CORS(app)  # In prod, restrict: CORS(app, origins=["https://test-2-we9x.onrender.com"])

# -----------------------------------------------------------------------------
# Environment configuration
# -----------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TALENTLMS_API_KEY = os.getenv("TALENTLMS_API_KEY")
TALENTLMS_DOMAIN = os.getenv("TALENTLMS_DOMAIN")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("WARNING: GEMINI_API_KEY is not set. /evaluate will return an error.")

# Stable general-purpose model (text, PDFs, etc.)
GEMINI_MODEL_NAME = "gemini-2.5-flash-lite"  # as per Google Gemini API docs

ALLOWED_EXT = {".pdf", ".docx"}


# -----------------------------------------------------------------------------
# Helpers: file text extraction
# -----------------------------------------------------------------------------
def extract_text(file_path: str, ext: str) -> str:
    """Extract text from a PDF or DOCX file."""
    try:
        if ext == ".pdf":
            with pdfplumber.open(file_path) as pdf:
                pages = [p.extract_text() for p in pdf.pages]
                pages = [p for p in pages if p]
                return "\n".join(pages).strip()
        elif ext == ".docx":
            doc = Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs).strip()
        else:
            return ""
    except Exception as e:
        print("Error extracting text:", e)
        return ""


# -----------------------------------------------------------------------------
# Helpers: Gemini evaluation
# -----------------------------------------------------------------------------
def evaluate_text_with_gemini(text: str) -> dict:
    """
    Call Gemini to grade the assignment text.
    Returns a dict: { "score": <0-100 or None>, "feedback": <str> }
    """
    if not GEMINI_API_KEY:
        return {
            "score": None,
            "feedback": "Gemini error: GEMINI_API_KEY is not configured on the server.",
        }

    prompt = f"""
You are an automated grading assistant.

Evaluate the following assignment to the question Submit a document that explains how to enable LLM fine-tuning for:
- correctness
- clarity
- completeness
- structure

Return ONLY a JSON object in this exact format:

{{
  "score": <number between 0 and 100>,
  "feedback": "<detailed feedback for the learner>"
}}

Do NOT include any text before or after the JSON.

Assignment text:
{text}
"""

    try:
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        response = model.generate_content(prompt)

        # Gemini Python SDK exposes text via .text
        raw = response.text or ""
        print("Gemini raw response:", raw)

        # Try to extract JSON object from the raw string
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1:
            json_text = raw[start : end + 1]
            parsed = json.loads(json_text)
            return parsed
        else:
            # Fallback: just give the raw text as feedback
            return {"score": None, "feedback": raw}
    except Exception as e:
        print("Gemini API call failed:", e)
        return {"score": None, "feedback": f"Gemini error: {str(e)}"}


# -----------------------------------------------------------------------------
# Helpers: TalentLMS completion update
# -----------------------------------------------------------------------------
def mark_completion_in_talentlms(user_id: str, course_id: str, score=None, feedback=None) -> dict:
    """
    Optionally update TalentLMS when grading is done.
    Right now this just calls gotocourse to simulate completion/visit.
    """
    if not user_id or not course_id or not TALENTLMS_DOMAIN or not TALENTLMS_API_KEY:
        return {
            "status": "skipped",
            "details": "Missing user_id/course_id or TalentLMS config",
        }

    try:
        url = (
            f"https://{TALENTLMS_DOMAIN}/api/v1/"
            f"gotocourse/user_id:{user_id},course_id:{course_id}"
        )
        headers = {"Authorization": f"Basic {TALENTLMS_API_KEY}"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return {"status": "success", "details": resp.json()}
        else:
            return {"status": "error", "details": resp.text}
    except Exception as e:
        print("TalentLMS update failed:", e)
        return {"status": "error", "details": str(e)}


# -----------------------------------------------------------------------------
# Main endpoint: /evaluate
# -----------------------------------------------------------------------------
@app.route("/evaluate", methods=["POST"])
def evaluate():
    print("Incoming /evaluate request from:", request.remote_addr)

    # Check file upload
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    uploaded = request.files["file"]
    filename = secure_filename(uploaded.filename or "uploaded")
    _, ext = os.path.splitext(filename.lower())

    if ext not in ALLOWED_EXT:
        return jsonify({"error": f"Unsupported file type: {ext}"}), 400

    # Save to temp with proper extension so extract_text can use ext
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp_path = tmp.name

    try:
        uploaded.save(tmp_path)
    except Exception as e:
        print("Failed to save uploaded file:", e)
        return jsonify({"error": "Failed to save uploaded file"}), 500

    print("Saved file to:", tmp_path)

    # Extract text
    text = extract_text(tmp_path, ext)
    if not text:
        text = "No readable text found in the uploaded file."

    # Call Gemini for grading
    evaluation = evaluate_text_with_gemini(text)
    print("Evaluation result:", evaluation)

    # Clean up temp file
    try:
        os.remove(tmp_path)
    except Exception:
        pass

    # TalentLMS completion (optional)
    user_id = request.args.get("user_id")
    course_id = request.args.get("course_id")
    completion_status = mark_completion_in_talentlms(
        user_id,
        course_id,
        evaluation.get("score"),
        evaluation.get("feedback"),
    )

    return jsonify(
        {"evaluation": evaluation, "completion_update": completion_status}
    )


# -----------------------------------------------------------------------------
# Dev server entry point (Render uses gunicorn via Procfile)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
