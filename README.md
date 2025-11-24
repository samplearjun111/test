# TalentLMS Grader - Webhook Version

This repo implements the webhook-only workflow:
- TalentLMS posts assignment submissions to your webhook endpoint
- The server extracts text (from files), grades using OpenAI (optional) or mock grader
- If the submission passes, the server can auto-post the grade back to TalentLMS
- Flagged submissions (failed) appear in /review for manual approval and posting

Important files:
- server.js : main app
- views/ : admin UI templates
- public/ : static assets
- .env.example : environment variables

Uploaded TalentLMS API docs you provided are available on the server at:
/mnt/data/TalentLMS-API.zip

Environment variables to set in Render:
OPENAI_API_KEY=sk-...
WEBHOOK_SECRET=your-webhook-secret
TALENTLMS_API_URL=https://movate.talentlms.com/api
TALENTLMS_API_KEY=your_talentlms_api_key
TALENTLMS_GRADE_ENDPOINT=/assignments/{assignment_id}/grade
PASS_THRESHOLD=60
PORT=8080

Webhook configuration (in TalentLMS):
- URL: https://<your-render-app>.onrender.com/webhook/assignment
- Method: POST (multipart/form-data)
- Headers: X-WEBHOOK-SECRET: <your-webhook-secret>
- Fields (examples TalentLMS may send): user_id, assignment_id, submission_text
- If TalentLMS sends files, ensure field name is 'submission_file' or the config matches.

To run locally:
npm install
cp .env.example .env
npm start

Note: If your TalentLMS uses Basic Auth or a different grade endpoint/payload, please paste the exact endpoint or docs and I will update the code accordingly.
