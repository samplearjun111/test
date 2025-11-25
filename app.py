
from flask import Flask, request, jsonify
import requests
import os
import tempfile
import json
import openai
from docx import Document
import pdfplumber

app = Flask(__name__)

# Load environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TALENTLMS_API_KEY = os.getenv("TALENTLMS_API_KEY")
TALENTLMS_DOMAIN = os.getenv("TALENTLMS_DOMAIN")

openai.api_key = OPENAI_API_KEY

def extract_text(file_path):
    if file_path.endswith('.pdf'):
        with pdfplumber.open(file_path) as pdf:
            return ".join(page.extract_text() for page in pdf.pages if page.extract_text())"
    elif file_path.endswith('.docx'):
        doc = Document(file_path)
        return ".join([p.text for p in doc.paragraphs])"
    else:
        return "Unsupported file type."

def evaluate_text(text):
    prompt = f"Grade this assignment: {text} Return JSON with keys: score (0-100) and feedback."
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a grading assistant."},
            {"role": "user", "content": prompt}
        ]
    )
    content = response['choices'][0]['message']['content']
    try:
        return json.loads(content)
    except:
        return {"score": None, "feedback": content}

def mark_completion_in_talentlms(user_id, course_id):
    url = f"https://{TALENTLMS_DOMAIN}/api/v1/gotocourse/user_id:{user_id},course_id:{course_id}"
    headers = {"Authorization": f"Basic {TALENTLMS_API_KEY}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return {"status": "success", "details": response.json()}
    else:
        return {"status": "error", "details": response.text}

@app.route('/evaluate', methods=['POST'])
def evaluate():
    file = request.files['file']
    user_id = request.form.get('user_id')
    course_id = request.form.get('course_id')

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        file.save(tmp.name)
        text = extract_text(tmp.name)

    evaluation = evaluate_text(text)

    # Mark completion in TalentLMS
    completion_status = mark_completion_in_talentlms(user_id, course_id)

    return jsonify({"evaluation": evaluation, "completion_update": completion_status})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
