import os
import tempfile
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import openai
from docx import Document
import pdfplumber
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)  # Use origins=[...] in production

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TALENTLMS_API_KEY = os.getenv("TALENTLMS_API_KEY")
TALENTLMS_DOMAIN = os.getenv("TALENTLMS_DOMAIN")

openai.api_key = OPENAI_API_KEY

ALLOWED_EXT = {'.pdf', '.docx'}

def extract_text(file_path, ext):
    try:
        if ext == '.pdf':
            with pdfplumber.open(file_path) as pdf:
                pages = [p.extract_text() for p in pdf.pages]
                pages = [p for p in pages if p]
                return "\n".join(pages).strip()
        elif ext == '.docx':
            doc = Document(file_path)
            return "\n".join([p.text for p in doc.paragraphs]).strip()
        else:
            return ""
    except Exception as e:
        print("Error extracting text:", e)
        return ""

def evaluate_text_with_openai(text):
    prompt = f"Grade this assignment for correctness and clarity. Return JSON with keys: score (0-100) and feedback.\n\nAssignment text:\n{text}"
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "You are a helpful grading assistant. Output only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=800
        )
    except Exception as e:
        print("OpenAI API call failed:", e)
        return {"score": None, "feedback": f"OpenAI error: {str(e)}"}

    print("OpenAI raw response:", response)
    try:
        content = response['choices'][0]['message']['content']
        start = content.find('{')
        end = content.rfind('}')
        if start != -1 and end != -1:
            json_text = content[start:end+1]
            return json.loads(json_text)
        else:
            return {"score": None, "feedback": content}
    except Exception as e:
        print("Failed to parse OpenAI content:", e)
        return {"score": None, "feedback": str(response)}

def mark_completion_in_talentlms(user_id, course_id, score=None, feedback=None):
    if not user_id or not course_id or not TALENTLMS_DOMAIN or not TALENTLMS_API_KEY:
        return {"status": "skipped", "details": "Missing user_id/course_id or TalentLMS config"}
    try:
        url = f"https://{TALENTLMS_DOMAIN}/api/v1/gotocourse/user_id:{user_id},course_id:{course_id}"
        headers = {"Authorization": f"Basic {TALENTLMS_API_KEY}"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return {"status": "success", "details": resp.json()}
        else:
            return {"status": "error", "details": resp.text}
    except Exception as e:
        print("TalentLMS update failed:", e)
        return {"status": "error", "details": str(e)}

@app.route('/evaluate', methods=['POST'])
def evaluate():
    print("Incoming /evaluate request from:", request.remote_addr)
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    uploaded = request.files['file']
    filename = secure_filename(uploaded.filename or "uploaded")
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXT:
        return jsonify({"error": f"Unsupported file type: {ext}"}), 400

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp_path = tmp.name
    try:
        uploaded.save(tmp_path)
    except Exception as e:
        print("Failed to save uploaded file:", e)
        return jsonify({"error": "Failed to save uploaded file"}), 500

    print("Saved file to:", tmp_path)
    text = extract_text(tmp_path, ext)
    if not text:
        text = "No readable text found in the uploaded file."

    evaluation = evaluate_text_with_openai(text)
    print("Evaluation result:", evaluation)

    user_id = request.args.get('user_id')
    course_id = request.args.get('course_id')
    completion_status = mark_completion_in_talentlms(user_id, course_id, evaluation.get('score'), evaluation.get('feedback'))

    try:
        os.remove(tmp_path)
    except Exception:
        pass

    return jsonify({"evaluation": evaluation, "completion_update": completion_status})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))