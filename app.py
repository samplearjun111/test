import os
import tempfile
import json

from flask import Flask, request, jsonify
from flask_cors import CORS

import pdfplumber
from docx import Document
import google.generativeai as genai


# ==============================
#   CONFIGURATION
# ==============================

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise RuntimeError("Missing GOOGLE_API_KEY environment variable")

genai.configure(api_key=GOOGLE_API_KEY)

# Choose your Gemini model (adjust if needed)
GEMINI_MODEL_NAME = "gemini-1.5-flash"


# ==============================
#   FLASK APP
# ==============================

app = Flask(__name__)
CORS(app)  # allow all origins; tighten if needed


# ==============================
#   HELPER: TEXT EXTRACTION
# ==============================

def extract_text_from_file(file_storage):
    """
    Accepts a Flask FileStorage object (from request.files['file'])
    and extracts text from PDF or DOCX. Returns a string.
    """
    original_name = file_storage.filename or ""
    lower_name = original_name.lower()

    # Save to a temporary file first
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        file_storage.save(tmp.name)
        tmp_path = tmp.name

    text = ""

    try:
        if lower_name.endswith(".pdf"):
            with pdfplumber.open(tmp_path) as pdf:
                pages_text = [
                    page.extract_text() or "" for page in pdf.pages
                ]
            text = "\n".join(pages_text)

        elif lower_name.endswith(".docx"):
            doc = Document(tmp_path)
            text = "\n".join(p.text for p in doc.paragraphs)

        else:
            # Fallback: try to read as plain text
            try:
                with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except Exception:
                text = ""

    finally:
        # Clean up temp file
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return text.strip()


# ==============================
#   HELPER: GEMINI CALL
# ==============================

def call_gemini(prompt: str) -> str:
    """
    Calls Gemini with a simple text prompt and returns the raw text output.
    """
    model = genai.GenerativeModel(GEMINI_MODEL_NAME)
    resp = model.generate_content(prompt)
    return (resp.text or "").strip()


# ==============================
#   ROUTE: HEALTH CHECK
# ==============================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ==============================
#   ROUTE: /evaluate  (FILE UPLOAD)
#   For the doc-upload assignment iframe (PDF/DOCX)
# ==============================

@app.route("/evaluate", methods=["POST"])
def evaluate_file():
    """
    Expects multipart/form-data with field 'file'.
    Returns:
    {
      "evaluation": { "score": <0-100 or null>, "feedback": "<string>" },
      "completion_update": { "status": "skipped", "details": "..." }
    }
    """
    if "file" not in request.files:
        return jsonify({
            "error": "Missing file upload. Expected form field 'file'."
        }), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename."}), 400

    # Extract text
    text = extract_text_from_file(file)
    if not text:
        evaluation = {
            "score": None,
            "feedback": "No readable text found in the uploaded file."
        }
        return jsonify({
            "evaluation": evaluation,
            "completion_update": {
                "status": "skipped",
                "details": "Missing user_id/course_id or TalentLMS config"
            }
        }), 200

    # Build grading prompt
    grading_prompt = f"""
You are grading a written assignment.

Assignment:
The learner uploads a document and you must evaluate it for:
- correctness
- clarity
- completeness
- structure

Return a short JSON only with:
- "score": integer 0-100
- "feedback": short text feedback

Do not include any extra keys.

Student submission:
{text}
"""

    try:
        raw = call_gemini(grading_prompt)
    except Exception as e:
        evaluation = {
            "score": None,
            "feedback": f"Gemini error: {str(e)}"
        }
        return jsonify({
            "evaluation": evaluation,
            "completion_update": {
                "status": "skipped",
                "details": "Missing user_id/course_id or TalentLMS config"
            }
        }), 200

    # Try to parse JSON from model
    try:
        evaluation = json.loads(raw)
        if "score" not in evaluation or "feedback" not in evaluation:
            raise ValueError("Missing keys in evaluation JSON")
    except Exception:
        # Fall back: treat raw as feedback
        evaluation = {
            "score": None,
            "feedback": raw
        }

    # NOTE: TalentLMS completion is now handled via SCORM, so we keep this as informational
    completion_update = {
        "status": "skipped",
        "details": "Completion handled by SCORM or external logic; no direct LMS update."
    }

    return jsonify({
        "evaluation": evaluation,
        "completion_update": completion_update
    }), 200


# ==============================
#   ROUTE: /exam_evaluate  (STRICT JSON EXAM)
#   For the 10-question SCORM exam
# ==============================

@app.route("/exam_evaluate", methods=["POST"])
def exam_evaluate():
    """
    Strict JSON input for the LLM exam.

    Expected JSON body:
    {
      "topic": "LLM Fundamentals and Fine-Tuning",
      "assignmentId": "llm_exam_001",
      "answers": {
        "q1": "text...",
        "q2": "text...",
        ...
      }
    }

    Returns JSON:
    {
      "perQuestion": {
        "q1": {"score": 0-10, "feedback": "..."},
        ...
      },
      "totalScore": 0-100,
      "overallFeedback": "..."
    }
    """
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({
            "error": "Invalid JSON payload. Expected application/json body.",
            "example_format": {
                "topic": "LLM Fundamentals",
                "assignmentId": "exam_01",
                "answers": {"q1": "text", "q2": "text"}
            }
        }), 400

    # ---- STRICT VALIDATION ----

    # 1. topic: required, non-empty string
    if "topic" not in data or not isinstance(data["topic"], str) or not data["topic"].strip():
        return jsonify({
            "error": "Missing or invalid 'topic'. The SCORM wrapper MUST pass the exam topic.",
            "expected": "topic: string"
        }), 400
    topic = data["topic"].strip()

    # 2. assignmentId: required, string
    if "assignmentId" not in data or not isinstance(data["assignmentId"], str):
        return jsonify({
            "error": "Missing 'assignmentId'. The SCORM wrapper MUST send a unique identifier.",
            "expected": "assignmentId: string"
        }), 400
    assignment_id = data["assignmentId"].strip()

    # 3. answers: required, dict
    if "answers" not in data or not isinstance(data["answers"], dict):
        return jsonify({
            "error": "Missing or invalid 'answers'. Must be an object { q1: answer, q2: answer, ... }",
            "expected": "answers: dict"
        }), 400
    answers = data["answers"]

    # 4. At least one answer
    if len(answers.keys()) == 0:
        return jsonify({
            "error": "No answers submitted.",
            "expected": "answers: { q1: '...', q2: '...' }"
        }), 400

    # ---- BUILD STRICT GRADING PROMPT ----

    grading_prompt = f"""
You are grading a student exam.

STRICT RULES:
- Grade ONLY based on correctness, clarity, completeness, and relevance to the topic.
- DO NOT reward extremely brief or generic answers.
- Be consistent across questions.
- Score each question from 0 to 10.
- totalScore (0-100) should be the sum or scaled aggregate of all question scores.
- Provide concise feedback for each answer (1-3 sentences).
- Output MUST be valid JSON only.

Exam topic: "{topic}"
Assignment ID: "{assignment_id}"

Student answers (JSON):
{json.dumps(answers, indent=2)}

Produce JSON ONLY in this exact structure:

{{
  "perQuestion": {{
    "q1": {{"score": <0-10>, "feedback": "<string>"}},
    "q2": {{"score": <0-10>, "feedback": "<string>"}},
    ...
  }},
  "totalScore": <0-100>,
  "overallFeedback": "<string>"
}}
"""

    try:
        raw_output = call_gemini(grading_prompt)
    except Exception as e:
        return jsonify({
            "error": "Gemini API error",
            "details": str(e)
        }), 500

    # ---- PARSE & VALIDATE MODEL OUTPUT ----

    try:
        result = json.loads(raw_output)
    except Exception:
        return jsonify({
            "error": "Gemini returned non-JSON output.",
            "raw_output": raw_output[:800]
        }), 500

    # totalScore must exist and be numeric
    if "totalScore" not in result or not isinstance(result["totalScore"], (int, float)):
        return jsonify({
            "error": "Invalid AI output. Missing or non-numeric 'totalScore'.",
            "ai_output": result
        }), 500

    total_score = float(result["totalScore"])
    if total_score < 0 or total_score > 100:
        return jsonify({
            "error": "Invalid 'totalScore' range. Must be between 0 and 100.",
            "ai_output": result
        }), 500

    # Optionally ensure perQuestion exists
    if "perQuestion" not in result or not isinstance(result["perQuestion"], dict):
        # Don't hard-fail – instead normalize
        result["perQuestion"] = result.get("perQuestion", {})

    return jsonify(result), 200


# ==============================
#   MAIN ENTRY (for local dev)
# ==============================

if __name__ == "__main__":
    # For local testing; on Render you'll use gunicorn: gunicorn app:app
    app.run(host="0.0.0.0", port=5000, debug=True)
