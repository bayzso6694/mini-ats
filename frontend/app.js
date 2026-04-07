const API_BASE = "http://localhost:8000";

const jobForm = document.getElementById("jobForm");
const jobMsg = document.getElementById("jobMsg");
const uploadForm = document.getElementById("uploadForm");
const uploadStatusList = document.getElementById("uploadStatusList");
const uploadJobSelect = document.getElementById("uploadJobSelect");
const watchJobSelect = document.getElementById("watchJobSelect");
const rankingBody = document.getElementById("rankingBody");
const wsStatus = document.getElementById("wsStatus");
const refreshBtn = document.getElementById("refreshRankings");
const statusDot = document.querySelector(".dot");

let ws = null;
const uploadRowsByCandidateId = new Map();

function setSocketConnected(connected) {
  wsStatus.textContent = `Socket: ${connected ? "Connected" : "Disconnected"}`;
  statusDot.style.background = connected ? "#60d394" : "#de6b6b";
  statusDot.style.boxShadow = connected ? "0 0 8px #60d394" : "0 0 8px #de6b6b";
}

function normalizeCluster(label) {
  const value = (label || "").toLowerCase();
  if (value.includes("strong")) return "strong";
  if (value.includes("weak")) return "weak";
  return "moderate";
}

function renderRankings(rows) {
  rankingBody.innerHTML = "";
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.className = normalizeCluster(row.cluster_label);

    const fit = Number(row.fit_score || 0).toFixed(1);
    const prob = Number((row.hire_probability || 0) * 100).toFixed(1);

    tr.innerHTML = `
      <td>${row.rank ?? "-"}</td>
      <td>${row.name}</td>
      <td>${row.email}</td>
      <td>
        <div>${fit}</div>
        <div class="progress"><span style="width:${Math.max(0, Math.min(100, fit))}%"></span></div>
      </td>
      <td>${prob}%</td>
      <td><span class="badge ${normalizeCluster(row.cluster_label)}">${row.cluster_label || "-"}</span></td>
      <td><span class="badge ${row.status || "pending"}">${row.status || "pending"}</span></td>
      <td><span class="badge ${row.shortlist_status || "none"}">${row.shortlist_status || "none"}</span></td>
      <td>
        <div class="action-wrap">
          <button type="button" class="action-btn short" data-candidate-id="${row.id}" data-decision="shortlisted">Shortlist</button>
          <button type="button" class="action-btn reject" data-candidate-id="${row.id}" data-decision="rejected">Reject</button>
          <button type="button" class="action-btn clear" data-candidate-id="${row.id}" data-decision="none">Clear</button>
        </div>
      </td>
    `;
    rankingBody.appendChild(tr);
  });

  rankingBody.querySelectorAll(".action-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const candidateId = btn.dataset.candidateId;
      const decision = btn.dataset.decision;
      await updateShortlist(candidateId, decision);
    });
  });
}

function updateUploadBadge(candidateId, status) {
  const entry = uploadRowsByCandidateId.get(Number(candidateId));
  if (!entry) return;
  entry.innerHTML = `<strong>${entry.dataset.filename}</strong> <span class="badge ${status}">${status}</span>`;
}

async function fetchJobs() {
  const res = await fetch(`${API_BASE}/jobs`);
  if (!res.ok) throw new Error("Failed to load jobs");
  return res.json();
}

async function refreshJobs() {
  const jobs = await fetchJobs();

  uploadJobSelect.innerHTML = "";
  watchJobSelect.innerHTML = "";

  jobs.forEach((job) => {
    const option1 = document.createElement("option");
    option1.value = job.id;
    option1.textContent = `#${job.id} ${job.title}`;
    uploadJobSelect.appendChild(option1);

    const option2 = document.createElement("option");
    option2.value = job.id;
    option2.textContent = `#${job.id} ${job.title}`;
    watchJobSelect.appendChild(option2);
  });

  if (jobs.length > 0) {
    await refreshRankings(jobs[0].id);
    connectWs(jobs[0].id);
  } else {
    rankingBody.innerHTML = "";
    setSocketConnected(false);
  }
}

async function refreshRankings(jobId) {
  if (!jobId) return;
  const res = await fetch(`${API_BASE}/candidates/${jobId}/rankings`);
  if (!res.ok) return;
  const rows = await res.json();
  renderRankings(rows);
}

async function updateShortlist(candidateId, decision) {
  const res = await fetch(`${API_BASE}/candidates/${candidateId}/shortlist`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  if (!res.ok) return;
  const jobId = watchJobSelect.value;
  await refreshRankings(jobId);
}

function connectWs(jobId) {
  if (!jobId) return;
  if (ws) ws.close();

  ws = new WebSocket(`ws://localhost:8000/ws/${jobId}`);

  ws.onopen = () => {
    setSocketConnected(true);
    ws.send("ping");
  };

  ws.onmessage = async (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.candidate_id && payload.status) {
        updateUploadBadge(payload.candidate_id, payload.status);
      }
    } catch (e) {
      // Ignore malformed payloads and still refresh rankings.
    }
    await refreshRankings(jobId);
  };

  ws.onclose = () => {
    setSocketConnected(false);
  };

  ws.onerror = () => {
    setSocketConnected(false);
  };
}

jobForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    title: document.getElementById("jobTitle").value.trim(),
    description: document.getElementById("jobDescription").value.trim(),
    required_skills: document.getElementById("requiredSkills").value.trim(),
    min_experience: Number(document.getElementById("minExperience").value || 0),
  };

  const res = await fetch(`${API_BASE}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    jobMsg.textContent = "Failed to create job";
    return;
  }

  const data = await res.json();
  jobMsg.textContent = `Created job #${data.id}`;
  await refreshJobs();
});

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const files = document.getElementById("resumeFiles").files;
  const jobId = uploadJobSelect.value;
  const baseName = document.getElementById("candidateName").value.trim();
  const baseEmail = document.getElementById("candidateEmail").value.trim();

  if (!jobId || files.length === 0) return;

  for (let i = 0; i < files.length; i += 1) {
    const file = files[i];
    const row = document.createElement("div");
    row.innerHTML = `<strong>${file.name}</strong> <span class="badge pending">Uploading...</span>`;
    uploadStatusList.prepend(row);

    const formData = new FormData();
    formData.append("job_id", jobId);
    formData.append("name", files.length > 1 ? `${baseName} ${i + 1}` : baseName);
    formData.append(
      "email",
      files.length > 1 ? baseEmail.replace("@", `+${i + 1}@`) : baseEmail
    );
    formData.append("file", file);

    const res = await fetch(`${API_BASE}/candidates/upload`, {
      method: "POST",
      body: formData,
    });

    if (res.ok) {
      const candidate = await res.json();
      row.dataset.filename = file.name;
      row.innerHTML = `<strong>${file.name}</strong> <span class="badge pending">Pending...</span>`;
      uploadRowsByCandidateId.set(candidate.id, row);
    } else {
      row.innerHTML = `<strong>${file.name}</strong> <span class="badge error">Upload Failed</span>`;
    }
  }

  await refreshRankings(jobId);
});

watchJobSelect.addEventListener("change", async () => {
  const jobId = watchJobSelect.value;
  await refreshRankings(jobId);
  connectWs(jobId);
});

refreshBtn.addEventListener("click", async () => {
  const jobId = watchJobSelect.value;
  await refreshRankings(jobId);
});

window.addEventListener("load", async () => {
  try {
    await refreshJobs();
  } catch (e) {
    jobMsg.textContent = "Backend is not reachable yet.";
  }
});
