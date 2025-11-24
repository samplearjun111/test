/**
 * TalentLMS Grader - webhook-only server.js
 * - POST /webhook/assignment : receives TalentLMS webhook (text or file in multipart/form-data)
 * - extracts text from files (PDF/DOCX/Image) and grades (OpenAI or mock)
 * - posts grade back to TalentLMS using TALENTLMS_API_URL + TALENTLMS_GRADE_ENDPOINT
 * - provides /review UI for flagged submissions
 *
 * Deploy to Render: npm install && npm start
 */
import express from "express";
// remove the import line entirely
// use fetch(...) as-is — Node 18+ provides global fetch
import bodyParser from "body-parser";
import multer from "multer";
import dotenv from "dotenv";
import path from "path";
import { fileURLToPath } from "url";
import fs from "fs";
import pdf from "pdf-parse";
import mammoth from "mammoth";
import Tesseract from "tesseract.js";
import FormData from "form-data";

dotenv.config();
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const upload = multer({ dest: path.join(__dirname, "tmp_uploads") });

app.set("view engine", "ejs");
app.set("views", path.join(__dirname, "views"));
app.use(express.static(path.join(__dirname, "public")));
app.use(bodyParser.json({ limit: "20mb" }));
app.use(bodyParser.urlencoded({ extended: true }));

const OPENAI_KEY = process.env.OPENAI_API_KEY || "";
const PASS_THRESHOLD = parseInt(process.env.PASS_THRESHOLD || "60", 10);
const WEBHOOK_SECRET = process.env.WEBHOOK_SECRET || "changeme";
const TALENTLMS_API_URL = process.env.TALENTLMS_API_URL || "";
const TALENTLMS_API_KEY = process.env.TALENTLMS_API_KEY || "";
const TALENTLMS_GRADE_ENDPOINT = process.env.TALENTLMS_GRADE_ENDPOINT || "/assignments/{assignment_id}/grade";

const flaggedSubmissions = [];

async function extractTextFromFile(filePath, mimetype, originalname) {
  try {
    if (mimetype === "application/pdf" || originalname.toLowerCase().endsWith(".pdf")) {
      const data = fs.readFileSync(filePath);
      const out = await pdf(data);
      return out.text || "";
    }
    if (mimetype === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" || originalname.toLowerCase().endsWith(".docx")) {
      const result = await mammoth.extractRawText({path: filePath});
      return result.value || "";
    }
    if (mimetype.startsWith("image/") || ["png","jpg","jpeg","tif","tiff"].some(ext => originalname.toLowerCase().endsWith(ext))) {
      const { data: { text } } = await Tesseract.recognize(filePath, "eng", { logger: m => {} });
      return text || "";
    }
    const txt = fs.readFileSync(filePath, "utf8");
    return txt;
  } catch (e) {
    console.error("File extraction failed:", e);
    return "";
  }
}

function mockGrade(studentAnswer, expectedPoints = ["Point A","Point B","Point C"]) {
  const text = (studentAnswer || "").toLowerCase();
  const maxAccuracy = 50, maxClarity = 20, maxStructure = 30;
  let accuracy = 0;

  if (expectedPoints.length > 0) {
    const per = Math.round(maxAccuracy / expectedPoints.length);
    expectedPoints.forEach(p => {
      if (text.includes(p.toLowerCase())) accuracy += per;
    });
    accuracy = Math.min(accuracy, maxAccuracy);
  } else {
    if (text.length > 800) accuracy = Math.round(maxAccuracy * 0.95);
    else if (text.length > 400) accuracy = Math.round(maxAccuracy * 0.75);
    else if (text.length > 200) accuracy = Math.round(maxAccuracy * 0.5);
    else accuracy = Math.round(maxAccuracy * 0.25);
  }

  let clarity = 10;
  if (text.length > 500) clarity = 18;
  else if (text.length > 200) clarity = 12;
  else clarity = 7;
  clarity = Math.min(clarity, maxClarity);

  let structure = 10;
  if (text.includes("conclusion") || text.includes("summary")) structure = 25;
  else if (text.includes("introduction") || text.includes("conclude")) structure = 18;
  structure = Math.min(structure, maxStructure);

  const total = Math.round(accuracy + clarity + structure);
  const breakdown = [
    { criteria: "Accuracy", score: Math.round(accuracy), max: maxAccuracy },
    { criteria: "Clarity", score: clarity, max: maxClarity },
    { criteria: "Structure", score: structure, max: maxStructure }
  ];
  const passed = total >= PASS_THRESHOLD;
  const flags = [];
  if (!passed) flags.push("manual_review");

  return {
    score: total,
    max_score: 100,
    passed,
    rubric_breakdown: breakdown,
    overall_feedback: "Auto-graded (mock). Improve missing expected points and structure.",
    corrections: "",
    flags
  };
}

async function openaiGrade(studentAnswer, expectedPoints = []) {
  if (!OPENAI_KEY) return null;
  const system = "You are an objective grading assistant. Return ONLY valid JSON with keys: score (0-100), max_score, passed (bool), rubric_breakdown (array of {criteria,score,max,comment}), overall_feedback, corrections, flags.";
  const user = `Rubric:
- Accuracy (0-50)
- Clarity (0-20)
- Structure (0-30)

Expected points:
${expectedPoints.map(p => "- " + p).join("\n")}

Student answer:
${studentAnswer || ""}

Return a JSON exactly matching schema. Pass threshold: ${PASS_THRESHOLD}/100.`;

  try {
    const resp = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${OPENAI_KEY}`
      },
      body: JSON.stringify({
        model: "gpt-4o-mini",
        messages: [
          { role: "system", content: system },
          { role: "user", content: user }
        ],
        temperature: 0,
        max_tokens: 800
      })
    });
    const data = await resp.json();
    const text = data?.choices?.[0]?.message?.content || data?.choices?.[0]?.text;
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch (e) {
      const m = text.match(/\{[\s\S]*\}/);
      if (m) return JSON.parse(m[0]);
      return null;
    }
  } catch (e) {
    console.error("OpenAI call failed", e);
    return null;
  }
}

async function postGradeToTalentLMS(user_id, assignment_id, gradeObj) {
  if (!TALENTLMS_API_URL || !TALENTLMS_API_KEY) {
    throw new Error("TalentLMS URL or API key not configured");
  }
  const endpoint = (TALENTLMS_GRADE_ENDPOINT || "/assignments/{assignment_id}/grade").replace("{assignment_id}", encodeURIComponent(assignment_id)).replace("{user_id}", encodeURIComponent(user_id));
  const url = TALENTLMS_API_URL.replace(/\/$/, "") + endpoint;
  const payload = {
    user_id,
    assignment_id,
    grade: gradeObj.score,
    feedback: gradeObj.overall_feedback,
    metadata: gradeObj
  };

  const resp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${TALENTLMS_API_KEY}`
    },
    body: JSON.stringify(payload)
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error("TalentLMS POST failed: " + resp.status + " - " + text);
  }
  return await resp.json();
}

app.post("/webhook/assignment", upload.single("submission_file"), async (req, res) => {
  try {
    const secret = req.headers["x-webhook-secret"] || req.headers["x-webhook-token"];
    if (secret !== WEBHOOK_SECRET) {
      return res.status(403).json({ error: "Invalid webhook secret" });
    }

    const user_id = req.body.user_id || req.body.userId || "unknown_user";
    const assignment_id = req.body.assignment_id || req.body.assignmentId || "unknown_assignment";
    let submission_text = req.body.submission_text || req.body.text || req.body.answer || "";

    if (req.file) {
      const filePath = req.file.path;
      const mimetype = req.file.mimetype || "";
      const originalname = req.file.originalname || "";
      const extracted = await extractTextFromFile(filePath, mimetype, originalname);
      submission_text = (submission_text + "\n\n" + extracted).trim();
      try { fs.unlinkSync(filePath); } catch(e){}
    }

    let graded = null;
    if (OPENAI_KEY) {
      graded = await openaiGrade(submission_text, ["Point A", "Point B", "Point C"]);
    }
    if (!graded) graded = mockGrade(submission_text, ["Point A", "Point B", "Point C"]);

    if (!graded.passed) {
      flaggedSubmissions.push({
        id: flaggedSubmissions.length + 1,
        user_id,
        assignment_id,
        submission_text,
        result: graded,
        timestamp: new Date().toISOString()
      });
    } else {
      // auto-post passed grades if configured
      if (TALENTLMS_API_URL && TALENTLMS_API_KEY) {
        try {
          await postGradeToTalentLMS(user_id, assignment_id, graded);
        } catch (e) {
          console.error("Auto-post failed:", e.message || e);
        }
      }
    }

    return res.json({ status: "ok", graded });
  } catch (err) {
    console.error(err);
    return res.status(500).json({ error: "server error", details: String(err) });
  }
});

app.get("/review", (req, res) => {
  res.render("review", { items: flaggedSubmissions, talApiUrl: TALENTLMS_API_URL });
});

app.post("/review/approve", bodyParser.urlencoded({ extended: true }), async (req, res) => {
  try {
    const idx = parseInt(req.body.id, 10);
    const score = parseInt(req.body.score, 10);
    const feedback = req.body.feedback || "";
    const item = flaggedSubmissions.find(i => i.id === idx);
    if (!item) return res.status(404).send("Not found");

    const gradePayload = {
      score,
      max_score: 100,
      passed: score >= PASS_THRESHOLD,
      rubric_breakdown: item.result.rubric_breakdown,
      overall_feedback: feedback || item.result.overall_feedback,
      corrections: item.result.corrections || "",
      flags: []
    };

    try {
      const resp = await postGradeToTalentLMS(item.user_id, item.assignment_id, gradePayload);
      const i = flaggedSubmissions.findIndex(x => x.id === idx);
      if (i >= 0) flaggedSubmissions.splice(i,1);
      return res.render("approve_result", { success: true, resp: resp, item: item, grade: gradePayload });
    } catch (e) {
      return res.render("approve_result", { success: false, error: String(e), item: item, grade: gradePayload });
    }
  } catch (e) {
    console.error(e);
    res.status(500).send("Server error");
  }
});

app.get("/health", (req, res) => res.json({ status: "ok" }));
app.get("/", (req, res) => res.send("TalentLMS Grader Webhook Running ✔"));

const PORT = process.env.PORT || 8080;
app.listen(PORT, () => console.log("Server listening on", PORT));
