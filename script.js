
document.getElementById('uploadForm').addEventListener('submit', async (e) => {
  e.preventDefault();

  const file = document.getElementById('fileInput').files[0];
  const params = new URLSearchParams(window.location.search);
  const userId = params.get('user_id');
  const courseId = params.get('course_id');

  const formData = new FormData();
  formData.append('file', file);

  const backendUrl = `https://test-1-werq.onrender.com/evaluate?user_id=${userId}&course_id=${courseId}`;

  document.getElementById('result').innerHTML = '<p class="text-info">Processing...</p>';

  try {
    const response = await fetch(backendUrl, {
      method: 'POST',
      body: formData
    });

    const data = await response.json();
    document.getElementById('result').innerHTML = `
      <h4>Evaluation Result</h4>
      <p><strong>Score:</strong> ${data.evaluation.score}</p>
      <p><strong>Feedback:</strong> ${data.evaluation.feedback}</p>
      <hr>
      <h5>TalentLMS Update:</h5>
      <p>Status: ${data.completion_update.status}</p>
    `;
  } catch (error) {
    document.getElementById('result').innerHTML = '<p class="text-danger">Error processing request.</p>';
  }
});
