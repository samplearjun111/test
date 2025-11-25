
document.getElementById('uploadForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const file = document.getElementById('fileInput').files[0];
  const userId = document.getElementById('userId').value;
  const courseId = document.getElementById('courseId').value;

  const formData = new FormData();
  formData.append('file', file);
  formData.append('user_id', userId);
  formData.append('course_id', courseId);

  document.getElementById('result').innerHTML = '<p class="text-info">Processing...</p>';

  try {
    const response = await fetch('https://test-1-werq.onrender.coml.onrender.com/evaluate', {
      method: 'POST',
      body: formData
    });

    const data = await response.json();
    document.getElementById('result').innerHTML = `
      <h4>Evaluation Result</h4>
      <p><strong>Score:</strong> ${data.evaluation.score}</p>
      <p><strong>Feedback:</strong> ${data.evaluation.feedback}</p>
      <hr>
      <h5>TalentLMS Update</h5>
      <p>Status: ${data.completion_update.status}</p>
    `;
  } catch (error) {
    document.getElementById('result').innerHTML = '<p class="text-danger">Error processing request.</p>';
  }
});
