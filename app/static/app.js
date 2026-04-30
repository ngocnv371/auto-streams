// ═══════════════════════════════════════════════════════════
//  Server-Sent Events — real-time pipeline feedback
// ═══════════════════════════════════════════════════════════
const ACTIVITY_MAX = 60;
let _activityLog = [];
let _evtSource = null;
let _sseRetryTimer = null;
let _refreshTimer = null;

function connectSSE() {
  if (_evtSource) {
    _evtSource.close();
    _evtSource = null;
  }
  clearTimeout(_sseRetryTimer);
  _evtSource = new EventSource("/api/events");

  _evtSource.onopen = () => {
    setNavIndicator(false, "connected");
  };

  _evtSource.onmessage = (e) => {
    let data;
    try {
      data = JSON.parse(e.data);
    } catch {
      return;
    }

    if (data.type === "status") {
      setNavIndicator(
        data.active > 0,
        data.active > 0 ? `running (${data.active})` : "idle",
      );
    } else if (data.type === "activity") {
      pushActivity(data);
    } else if (data.type === "project_update") {
      onProjectUpdate(data.project_id, data.status);
    }
  };

  _evtSource.onerror = () => {
    setNavIndicator(false, "disconnected");
    _evtSource.close();
    _evtSource = null;
    _sseRetryTimer = setTimeout(connectSSE, 4000);
  };
}

function setNavIndicator(active, labelText) {
  const dot = $("sse-dot");
  const label = $("sse-label");
  if (!dot) return;
  dot.className =
    "sse-dot " +
    (active ? "running" : labelText === "disconnected" ? "error" : "idle");
  if (label) label.textContent = labelText || (active ? "running" : "idle");
}

function pushActivity(data) {
  _activityLog.unshift({
    ts: data.ts ? new Date(data.ts * 1000) : new Date(),
    msg: data.msg || "",
    level: data.level || "info",
    project_id: data.project_id || null,
    stage: data.stage || null,
  });
  if (_activityLog.length > ACTIVITY_MAX) _activityLog.length = ACTIVITY_MAX;
  renderActivityLog();
}

function renderActivityLog() {
  const el = $("activity-log");
  if (!el) return;
  if (!_activityLog.length) {
    el.innerHTML = '<div class="activity-empty">No activity yet</div>';
    return;
  }
  el.innerHTML = _activityLog
    .map(
      (e) => `
    <div class="activity-entry level-${escHtml(e.level)}">
      <span class="activity-time">${e.ts.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
      <span class="activity-msg">${escHtml(e.msg)}</span>
      ${e.project_id ? `<span class="activity-pid" title="${escHtml(e.project_id)}">${e.project_id.slice(0, 8)}</span>` : ""}
    </div>`,
    )
    .join("");
}

function onProjectUpdate(project_id, status) {
  // Auto-refresh the open detail panel for this project
  if (_detailId === project_id) {
    openDetail(project_id);
  }
  // Debounce dashboard + list refresh
  clearTimeout(_refreshTimer);
  _refreshTimer = setTimeout(() => {
    loadDashboard();
    if (activePage === "projects") loadProjects();
  }, 600);
}

// ═══════════════════════════════════════════════════════════
//  Utils
// ═══════════════════════════════════════════════════════════
const $ = (id) => document.getElementById(id);

function toast(msg, type = "success") {
  const el = $("toast");
  el.textContent = msg;
  el.className = `show ${type}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => {
    el.className = "";
  }, 2800);
}

async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch("/api" + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  if (res.status === 204) return null;
  return res.json();
}

function badge(status) {
  return `<span class="badge badge-${status}">${status.replace(/_/g, " ")}</span>`;
}
function statusColor(s) {
  return (
    {
      idea: "var(--s-idea)",
      approved: "var(--s-approved)",
      content_ready: "var(--s-content_ready)",
      scenes_ready: "var(--s-scenes_ready)",
      tts_ready: "var(--s-tts_ready)",
      music_ready: "var(--s-music_ready)",
      images_ready: "var(--s-images_ready)",
      media_ready: "var(--s-media_ready)",
      clips_ready: "var(--s-clips_ready)",
      rendered: "var(--s-rendered)",
      uploaded: "var(--s-uploaded)",
      failed: "var(--s-failed)",
    }[s] || "var(--text)"
  );
}
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return (
    d.toLocaleDateString() +
    " " +
    d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  );
}
function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ═══════════════════════════════════════════════════════════
//  State
// ═══════════════════════════════════════════════════════════
let currentTopicId = localStorage.getItem("as_topic_id") || 'all';
let currentTopicText = localStorage.getItem("as_topic_text") || null;
let allTopics = [];
let activePage = "splash";
let selectedCount = 5;

// ═══════════════════════════════════════════════════════════
//  Topic workspace
// ═══════════════════════════════════════════════════════════
function toggleTopicDropdown(e) {
  e.stopPropagation();
  $("topic-dropdown").classList.toggle("open");
  if ($("topic-dropdown").classList.contains("open")) {
    setTimeout(() => $("topic-add-input").focus(), 50);
  }
}

document.addEventListener("click", (e) => {
  if (!$("topic-ws").contains(e.target))
    $("topic-dropdown").classList.remove("open");
});

async function loadTopics() {
  try {
    allTopics = await api("GET", "/topics");
  } catch {
    allTopics = [];
  }
  if (currentTopicId && !allTopics.find((t) => t.id === currentTopicId)) {
    currentTopicId = 'all';
    currentTopicText = null;
    localStorage.removeItem("as_topic_id");
    localStorage.removeItem("as_topic_text");
  }
  renderTopicDropdown();
  applyTopic();
}

function renderTopicDropdown() {
  const list = $("topic-list-dd");
  let html = "";
  if (!allTopics.length) {
    html = '<div class="topic-empty">No topics yet — add one below.</div>';
  } else {
    // Add 'All Topics' option
    html += `<div class="topic-item ${currentTopicId === "all" ? "selected" : ""}"
      onclick="selectTopic('all', 'All Topics')">
      <span class="topic-text" title="All Topics">All Topics</span>
    </div>`;
    html += allTopics
      .map(
        (t) => `
      <div class="topic-item ${t.id === currentTopicId ? "selected" : ""}"
           onclick="selectTopic('${escHtml(t.id)}', ${escHtml(JSON.stringify(t.topic))})">
        <span class="topic-text" title="${escHtml(t.topic)}">${escHtml(t.topic)}</span>
        <button class="topic-del" title="Delete" onclick="deleteTopic(event,'${escHtml(t.id)}')">✕</button>
      </div>`,
      )
      .join("");
  }
  list.innerHTML = html;
}

function selectTopic(id, text) {
  currentTopicId = id;
  currentTopicText = text;
  localStorage.setItem("as_topic_id", id);
  localStorage.setItem("as_topic_text", text);
  $("topic-dropdown").classList.remove("open");
  applyTopic();
  refreshCurrentPage();
}

function applyTopic() {
  const btn = $("topic-ws-btn");
  if (currentTopicId && currentTopicId !== "all") {
    btn.classList.remove("no-topic");
    $("topic-ws-label").textContent = currentTopicText || "Topic selected";
    $("btn-generate").disabled = false;
  } else if (currentTopicId === "all") {
    btn.classList.remove("no-topic");
    $("topic-ws-label").textContent = "All Topics";
    $("btn-generate").disabled = true;
  } else {
    btn.classList.add("no-topic");
    $("topic-ws-label").textContent = "Select a topic…";
    $("btn-generate").disabled = true;
  }
  renderTopicDropdown();
  if (!currentTopicId) switchPage("splash");
  else if (activePage === "splash") {
    switchPage("dashboard");
    loadDashboard();
  }
}

async function addTopic() {
  const input = $("topic-add-input");
  const text = input.value.trim();
  if (!text) return;
  try {
    const t = await api("POST", "/topics", { topic: text });
    allTopics.push(t);
    input.value = "";
    selectTopic(t.id, t.topic);
    toast("Topic created", "success");
  } catch (e) {
    toast(e.message, "error");
  }
}

async function deleteTopic(e, id) {
  e.stopPropagation();
  const t = allTopics.find((t) => t.id === id);
  if (
    !confirm(
      `Delete topic "${t?.topic}"?\nThis will fail if it has associated projects.`,
    )
  )
    return;
  try {
    await api("DELETE", `/topics/${id}`);
    allTopics = allTopics.filter((t) => t.id !== id);
    if (currentTopicId === id) {
      currentTopicId = null;
      currentTopicText = null;
      localStorage.removeItem("as_topic_id");
      localStorage.removeItem("as_topic_text");
    }
    toast("Topic deleted", "success");
    renderTopicDropdown();
    applyTopic();
  } catch (e) {
    toast(e.message, "error");
  }
}

// ═══════════════════════════════════════════════════════════
//  Navigation
// ═══════════════════════════════════════════════════════════
function switchPage(id) {
  document
    .querySelectorAll(".page")
    .forEach((p) => p.classList.remove("active"));
  $(`page-${id}`).classList.add("active");
  activePage = id;
}

function showPage(id, tab) {
  if (!currentTopicId) {
    toast("Select a topic first", "error");
    return;
  }
  document
    .querySelectorAll(".nav-tab")
    .forEach((t) => t.classList.remove("active"));
  tab.classList.add("active");
  switchPage(id);
  if (id === "dashboard") loadDashboard();
  if (id === "projects") loadProjects();
}

function refreshCurrentPage() {
  if (activePage === "dashboard") loadDashboard();
  if (activePage === "projects") loadProjects();
}

// ═══════════════════════════════════════════════════════════
//  Dashboard
// ═══════════════════════════════════════════════════════════
const PIPELINE_STATUSES = [
  "idea",
  "approved",
  "content_ready",
  "scenes_ready",
  "tts_ready",
  "music_ready",
  "images_ready",
  "media_ready",
  "clips_ready",
  "rendered",
  "uploaded",
  "failed",
];

async function loadDashboard() {
  try {
    const params = new URLSearchParams({ limit: "200" });
    if (currentTopicId !== "all") params.set("topic_id", currentTopicId);
    const data = await api("GET", `/dashboard?${params}`);
    const sc = data.status_counts;
    $("s-total").textContent = data.total;
    $("s-rendered").textContent = sc.rendered || 0;
    $("s-failed").textContent = sc.failed || 0;
    $("s-idea").textContent = sc.idea || 0;

    $("pipeline-steps").innerHTML = PIPELINE_STATUSES.map(
      (s) => `
      <div class="pipeline-step" style="border-top:3px solid ${statusColor(s)}">
        <div class="step-count" style="color:${statusColor(s)}">${sc[s] ?? 0}</div>
        <div class="step-label">${s.replace(/_/g, " ")}</div>
      </div>`,
    ).join("");

    const labels = {
      text_queue: "Text / LLM",
      tts_queue: "TTS Audio",
      music_queue: "Music",
      image_queue: "Images",
      render_queue: "Render",
    };
    const qc = data.queue_counts;
    $("queue-grid").innerHTML = Object.entries(labels)
      .map(
        ([k, label]) => `
      <div class="queue-card">
        <div class="queue-name">${label}</div>
        <div class="queue-count" id="qc-${k}">${qc[k] ?? 0}</div>
        <div class="queue-label">pending</div>
        <button class="queue-run" id="qrun-${k}" ${(qc[k] ?? 0) === 0 ? "disabled" : ""} onclick="runQueue('${k}')">▶ Run</button>
      </div>`,
      )
      .join("");
  } catch (e) {
    toast("Dashboard error: " + e.message, "error");
  }
}

// ═══════════════════════════════════════════════════════════
//  Projects
// ═══════════════════════════════════════════════════════════
let _debounceT = null;
function debounceLoadProjects() {
  clearTimeout(_debounceT);
  _debounceT = setTimeout(loadProjects, 280);
}

async function loadProjects() {
  if (!currentTopicId) return;
  const search = $("search-input").value.trim();
  const tagFilter = $("tag-filter")?.value || "";
  const status = $("status-filter").value;
  const params = new URLSearchParams({ limit: "200" });
  if (currentTopicId !== "all") params.set("topic_id", currentTopicId);
  if (search) params.set("search", search);
  if (status) params.set("status", status);
  const wrap = $("projects-table-wrap");
  try {
    const allProjects = await api("GET", `/projects?${params}`);
    // Rebuild tag select with unique tags from the full result set
    const tagSel = $("tag-filter");
    if (tagSel) {
      const current = tagSel.value;
      const allTags = [...new Set(allProjects.flatMap((p) => p.tags))].sort();
      tagSel.innerHTML =
        '<option value="">All tags</option>' +
        allTags
          .map(
            (t) =>
              `<option value="${escHtml(t)}"${t === current ? " selected" : ""}>${escHtml(t)}</option>`,
          )
          .join("");
    }
    const projects = tagFilter
      ? allProjects.filter((p) => p.tags.includes(tagFilter))
      : allProjects;
    if (!projects.length) {
      wrap.innerHTML =
        '<div class="empty">No projects yet — Generate Ideas to get started.</div>';
      return;
    }
    wrap.innerHTML = `
      <table>
        <thead><tr><th>Title</th><th>Status</th><th>Tags</th><th>Created</th><th>Actions</th></tr></thead>
        <tbody>${projects
          .map(
            (p) => `
          <tr onclick="openDetail('${p.id}')">
            <td class="td-title">${escHtml(p.title)}</td>
            <td>${badge(p.status)}</td>
            <td class="td-tags">${p.tags.map((t) => `<span class="tag">${escHtml(t)}</span>`).join("") || '<span class="text-muted">—</span>'}</td>
            <td class="td-date">${fmtDate(p.created_at)}</td>
            <td class="td-actions" onclick="event.stopPropagation()">
              ${p.status === "idea" ? `<button class="btn-sm approve" onclick="approveProject('${p.id}')">Approve</button>` : ""}
              ${["idea", "approved"].includes(p.status) ? `<button class="btn-sm reject" onclick="rejectProject('${p.id}')">Reject</button>` : ""}
              ${p.status === "approved" ? `<button class="btn-sm run" onclick="runPipeline('${p.id}')">▶ Run</button>` : ""}
              ${["rendered", "uploaded", "failed", "media_ready", "images_ready", "clips_ready"].includes(p.status) ? `<button class="btn-sm rerender" onclick="reRender('${p.id}')">↺ Re-render</button>` : ""}
              <button class="btn-sm delete" onclick="deleteProject('${p.id}')">Delete</button>
            </td>
          </tr>`,
          )
          .join("")}
        </tbody>
      </table>`;
  } catch (e) {
    wrap.innerHTML = `<div class="empty">Error: ${escHtml(e.message)}</div>`;
  }
}

// ═══════════════════════════════════════════════════════════
//  Generate Ideas modal
// ═══════════════════════════════════════════════════════════
function selectCount(n) {
  selectedCount = n;
  document.querySelectorAll(".count-option").forEach((el) => {
    el.classList.toggle("selected", parseInt(el.textContent) === n);
  });
}

function openGenerateModal() {
  if (!currentTopicId) return;
  $("gen-modal-sub").textContent = `Topic: ${currentTopicText}`;
  $("gen-results").innerHTML = "";
  $("gen-count-field").style.display = "";
  $("gen-actions").innerHTML = `
    <button class="btn-secondary" onclick="closeGenerateModal()">Cancel</button>
    <button class="btn-primary" onclick="submitGenerate()"><span>Generate</span></button>`;
  $("gen-modal").classList.add("open");
}
function closeGenerateModal() {
  $("gen-modal").classList.remove("open");
}

async function submitGenerate() {
  $("gen-count-field").style.display = "none";
  $("gen-results").innerHTML = "";
  $("gen-actions").innerHTML = `
    <button class="btn-secondary" disabled>Cancel</button>
    <button class="btn-primary" disabled><div class="spinner"></div><span>Generating…</span></button>`;
  try {
    const ideas = await api("POST", "/ideas/generate", {
      topic_id: currentTopicId,
      count: selectedCount,
    });
    $("gen-results").innerHTML = `
      <div style="font-size:.8rem;color:var(--success);margin-bottom:.5rem;">✓ ${ideas.length} idea${ideas.length !== 1 ? "s" : ""} created</div>
      <div class="generated-list">${ideas
        .map(
          (p) => `
        <div class="gen-item">
          <div class="gen-title">${escHtml(p.title)}</div>
          ${p.metadata?.summary ? `<div class="gen-summary">${escHtml(p.metadata.summary)}</div>` : ""}
        </div>`,
        )
        .join("")}
      </div>`;
    $("gen-actions").innerHTML =
      `<button class="btn-primary" onclick="closeGenerateModal()">Done</button>`;
    loadDashboard();
    if (activePage === "projects") loadProjects();
    toast(`${ideas.length} ideas generated`, "success");
  } catch (e) {
    $("gen-results").innerHTML =
      `<div style="color:var(--danger);font-size:.85rem;margin-bottom:.5rem;">Error: ${escHtml(e.message)}</div>`;
    $("gen-count-field").style.display = "";
    $("gen-actions").innerHTML = `
      <button class="btn-secondary" onclick="closeGenerateModal()">Cancel</button>
      <button class="btn-primary" onclick="submitGenerate()"><span>Retry</span></button>`;
  }
}

// ═══════════════════════════════════════════════════════════
//  Project actions
// ═══════════════════════════════════════════════════════════
async function runQueue(queue) {
  const btn = $(`qrun-${queue}`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = "…";
  }
  try {
    const params = new URLSearchParams({ queue });
    if (currentTopicId && currentTopicId !== 'all') params.set("topic_id", currentTopicId);
    const res = await api("POST", `/dashboard/run-queue?${params}`);
    toast(
      `${res.queued} project${res.queued !== 1 ? "s" : ""} queued for ${queue.replace(/_/g, " ")}`,
      "success",
    );
    loadDashboard();
  } catch (e) {
    toast(e.message, "error");
    if (btn) {
      btn.disabled = false;
      btn.textContent = "▶ Run";
    }
  }
}

async function runPipeline(id) {
  const btn = document.querySelector(`[id="run-btn-${id}"]`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = "…";
  }
  try {
    await api("POST", `/projects/${id}/run`);
    toast("Pipeline started", "success");
    loadDashboard();
    if (activePage === "projects") loadProjects();
    if (_detailId === id) openDetail(id);
  } catch (e) {
    toast(e.message, "error");
    if (btn) {
      btn.disabled = false;
      btn.textContent = "▶ Run Pipeline";
    }
  }
}

async function approveProject(id) {
  try {
    await api("POST", `/projects/${id}/approve`);
    toast("Approved", "success");
    loadProjects();
    loadDashboard();
    if (_detailId === id) openDetail(id);
  } catch (e) {
    toast(e.message, "error");
  }
}
async function rejectProject(id) {
  if (!confirm("Reject this project?")) return;
  try {
    await api("POST", `/projects/${id}/reject`);
    toast("Rejected", "success");
    loadProjects();
    loadDashboard();
    if (_detailId === id) openDetail(id);
  } catch (e) {
    toast(e.message, "error");
  }
}
async function reRender(id) {
  if (
    !confirm(
      "Force re-render this project? The render stage will run from the beginning.",
    )
  )
    return;
  try {
    await api("POST", `/projects/${id}/render`);
    toast("Re-render started", "success");
    loadProjects();
    loadDashboard();
    if (_detailId === id) openDetail(id);
  } catch (e) {
    toast(e.message, "error");
  }
}

async function uploadToYouTube(id) {
  const btn = document.querySelector(`[id="upload-btn-${id}"]`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳ Uploading…";
  }
  try {
    await api("POST", `/projects/${id}/upload`);
    toast("Upload to YouTube started", "success");
    loadProjects();
    loadDashboard();
    if (_detailId === id) openDetail(id);
  } catch (e) {
    toast(e.message, "error");
    if (btn) {
      btn.disabled = false;
      btn.textContent = "⬆ Upload to YouTube";
    }
  }
}

async function openProjectFolder(id) {
  try {
    await api("POST", `/projects/${id}/open-folder`);
  } catch (e) {
    toast(e.message, "error");
  }
}

async function rerunSceneImage(id, sceneIndex, btn) {
  btn.disabled = true;
  btn.textContent = "…";
  try {
    await api("POST", `/projects/${id}/scenes/${sceneIndex}/rerun/image`);
    toast(`Scene ${sceneIndex + 1} image queued`, "success");
    setTimeout(() => openDetail(id), 800);
  } catch (e) {
    toast(e.message, "error");
    btn.disabled = false;
    btn.textContent = "↺ Image";
  }
}

async function rerunMusic(id, btn) {
  btn.disabled = true;
  btn.textContent = "…";
  try {
    await api("POST", `/projects/${id}/rerun/music`);
    toast("Music regeneration queued", "success");
    setTimeout(() => openDetail(id), 800);
  } catch (e) {
    toast(e.message, "error");
    btn.disabled = false;
    btn.textContent = "↺ Regenerate Music";
  }
}

async function rerunAllImages(id, btn) {
  if (
    !confirm(
      "Regenerate ALL scene images? This will overwrite every existing image.",
    )
  )
    return;
  btn.disabled = true;
  btn.textContent = "…";
  try {
    await api("POST", `/projects/${id}/rerun/images`);
    toast("All images queued for regeneration", "success");
    setTimeout(() => openDetail(id), 800);
  } catch (e) {
    toast(e.message, "error");
    btn.disabled = false;
    btn.textContent = "↺ All Images";
  }
}

async function rerunAllAudio(id, btn) {
  if (
    !confirm(
      "Regenerate ALL audio? This will send a new TTS request for the whole script.",
    )
  )
    return;
  btn.disabled = true;
  btn.textContent = "…";
  try {
    await api("POST", `/projects/${id}/rerun/audio`);
    toast("Audio regeneration queued", "success");
    setTimeout(() => openDetail(id), 800);
  } catch (e) {
    toast(e.message, "error");
    btn.disabled = false;
    btn.textContent = "↺ All Audio";
  }
}
async function setProjectStatus(id, status) {
  try {
    await api("PUT", `/projects/${id}/status`, { status });
    toast(`Status set to ${status}`, "success");
    loadProjects();
    loadDashboard();
    if (_detailId === id) openDetail(id);
  } catch (e) {
    toast(e.message, "error");
  }
}
async function deleteProject(id) {
  if (!confirm("Delete this project permanently?")) return;
  try {
    await api("DELETE", `/projects/${id}`);
    toast("Deleted", "success");
    loadProjects();
    loadDashboard();
    if (_detailId === id) closeDetail();
  } catch (e) {
    toast(e.message, "error");
  }
}

// ═══════════════════════════════════════════════════════════
//  Detail panel
// ═══════════════════════════════════════════════════════════
let _detailId = null;
let _detailData = null;

async function openDetail(id) {
  _detailId = id;
  try {
    const p = await api("GET", `/projects/${id}`);
    renderDetail(p);
    $("detail-overlay").classList.add("open");
    $("detail-panel").classList.add("open");
  } catch (e) {
    toast(e.message, "error");
  }
}
function closeDetail() {
  _detailId = null;
  _detailData = null;
  $("detail-overlay").classList.remove("open");
  $("detail-panel").classList.remove("open");
}
function renderDetail(p) {
  _detailData = p;
  $("dp-title").textContent = p.title;
  $("dp-meta").innerHTML =
    `${badge(p.status)} &nbsp;·&nbsp; <span class="text-muted">${escHtml(p.id)}</span> &nbsp;·&nbsp; ${fmtDate(p.created_at)}`;
  let actions = `<button class="btn-sm edit" onclick="toggleEditMode()">✎ Edit</button>`;
  if (p.status === "idea")
    actions += `<button class="btn-sm approve" onclick="approveProject('${p.id}')">Approve</button>`;
  if (["idea", "approved"].includes(p.status))
    actions += `<button class="btn-sm reject" onclick="rejectProject('${p.id}')">Reject</button>`;
  if (p.status === "approved")
    actions += `<button class="btn-sm run" id="run-btn-${p.id}" onclick="runPipeline('${p.id}')">▶ Run Pipeline</button>`;
  if (
    [
      "rendered",
      "failed",
      "media_ready",
      "images_ready",
      "clips_ready",
    ].includes(p.status)
  )
    actions += `<button class="btn-sm rerender" onclick="reRender('${p.id}')">↺ Re-render</button>`;
  if (p.status === "rendered")
    actions += `<button class="btn-sm upload" id="upload-btn-${p.id}" onclick="uploadToYouTube('${p.id}')">⬆ Upload to YouTube</button>`;
  actions += `<button class="btn-sm" title="Open project folder in Explorer" onclick="openProjectFolder('${p.id}')">📂 Open Folder</button>`;
  const allStatuses = [
    "idea",
    "approved",
    "content_ready",
    "scenes_ready",
    "tts_ready",
    "music_ready",
    "images_ready",
    "media_ready",
    "clips_ready",
    "rendered",
    "uploaded",
    "failed",
  ];
  actions += `<select class="select-filter status-jump" onchange="setProjectStatus('${p.id}', this.value)" title="Set status">${allStatuses.map((s) => `<option value="${s}"${s === p.status ? " selected" : ""}>${s.replace(/_/g, " ")}</option>`).join("")}</select>`;
  actions += `<button class="btn-sm delete" onclick="deleteProject('${p.id}')">Delete</button>`;
  $("dp-actions").innerHTML = actions;

  const meta = p.metadata || {};
  const scenes = meta.scenes || [];
  const metaFields = [
    ["Summary", meta.summary],
    ["Transcript", meta.transcript],
    ["Narrator", meta.narrator],
    ["Music prompt", meta.music],
    ["Visual guide", meta.visual_guide],
    ["Duration", meta.duration != null ? `${meta.duration}s` : null],
    ["Word count", meta.word_count],
    [
      "Uploaded at",
      meta.uploaded_at ? new Date(meta.uploaded_at).toLocaleString() : null,
    ],
  ].filter(([, v]) => v != null);

  let body = "";
  const videoFile = meta.video_path
    ? meta.video_path.replace(/\\/g, "/").split("/").pop()
    : null;
  if (videoFile) {
    const videoSrc = `/api/projects/${p.id}/video/${encodeURIComponent(videoFile)}`;
    body += `<div class="detail-section">
      <div class="detail-section-title">Preview</div>
      <div class="video-preview">
        <video controls preload="metadata" src="${videoSrc}"></video>
      </div>
    </div>`;
  }
  if (metaFields.length) {
    body += `<div class="detail-section">
      <div class="detail-section-title">Metadata</div>
      <div class="meta-grid">${metaFields
        .map(
          ([k, v]) => `
        <div class="meta-item">
          <div class="meta-key">${escHtml(k)}</div>
          <div class="meta-val pre">${escHtml(String(v))}</div>
        </div>`,
        )
        .join("")}
      </div></div>`;
  }
  if (p.tags.length) {
    body += `<div class="detail-section">
      <div class="detail-section-title">Tags</div>
      <div class="td-tags">${p.tags.map((t) => `<span class="tag">${escHtml(t)}</span>`).join("")}</div>
    </div>`;
  }
  const mediaLinks = [
    ["Music", meta.music_url],
    ["Narration", meta.audio_url],
    ["Video", meta.video_url],
    ["Thumbnail", meta.thumbnail_url],
    ["YouTube Short", meta.youtube_url],
  ].filter(([, v]) => v);
  if (mediaLinks.length) {
    body += `<div class="detail-section">
      <div class="detail-section-title">Media</div>
      <div style="display:flex;gap:.5rem;flex-wrap:wrap;">${mediaLinks.map(([l, u]) => `<a class="asset-chip" href="${escHtml(u)}" target="_blank">${escHtml(l)}</a>`).join("")}</div>
    </div>`;
  }
  const audioBase = `/api/projects/${p.id}/audio`;
  const fnFromPath = (path) =>
    path ? path.replace(/\\/g, "/").split("/").pop() : null;
  const hasScenes =
    scenes.length > 0 && (scenes[0].audio_path || scenes[0].image_path);
  if (scenes.length) {
    body += `<div class="detail-section">
      <div class="detail-section-title-row">
        <span class="detail-section-title">Scenes (${scenes.length})</span>
        <span class="section-title-actions">
          <button class="btn-sm rerun-asset" onclick="rerunAllImages('${p.id}',this)">↺ All Images</button>
          <button class="btn-sm rerun-asset" onclick="rerunAllAudio('${p.id}',this)">↺ All Audio</button>
        </span>
      </div>
      <div class="scenes-list">${scenes
        .map((s, i) => {
          const assets = [
            s.audio_url && "Audio",
            s.image_url && "Image",
            s.clip_url && "Clip",
          ].filter(Boolean);
          const audioFile = fnFromPath(s.audio_path);
          const imageFile = fnFromPath(s.image_path);
          const imageBase = `/api/projects/${p.id}/image`;
          return `<div class="scene-card">
          ${imageFile ? `<div class="scene-thumb"><img loading="lazy" src="${imageBase}/${encodeURIComponent(imageFile)}" alt="Scene ${i + 1}"></div>` : ""}
          <div class="scene-body">
            <div class="scene-num">Scene ${i + 1}${s.duration != null ? ` · ${s.duration}s` : ""}</div>
            <div class="scene-voiceover">${escHtml(s.voiceover || "")}</div>
            ${s.image_prompt ? `<div class="scene-prompt">${escHtml(s.image_prompt)}</div>` : ""}
            ${audioFile ? `<div class="scene-audio"><audio controls preload="none" src="${audioBase}/${encodeURIComponent(audioFile)}"></audio></div>` : ""}
            ${assets.length ? `<div class="scene-assets">${assets.map((a) => `<span class="asset-chip">${a}</span>`).join("")}</div>` : ""}
            <div class="scene-rerun-actions">
              ${imageFile || s.image_prompt ? `<button class="btn-sm rerun-asset" onclick="rerunSceneImage('${p.id}',${i},this)">↺ Image</button>` : ""}
            </div>
          </div>
        </div>`;
        })
        .join("")}</div></div>`;
  }
  const musicFile = fnFromPath(meta.music_path);
  if (musicFile) {
    body += `<div class="detail-section">
      <div class="detail-section-title">Background Music</div>
      <div class="music-audio"><audio controls preload="none" src="${audioBase}/${encodeURIComponent(musicFile)}"></audio></div>
      <div style="margin-top:.4rem"><button class="btn-sm rerun-asset" onclick="rerunMusic('${p.id}',this)">↺ Regenerate Music</button></div>
    </div>`;
  }
  $("dp-body").innerHTML = body || '<div class="empty">No content yet.</div>';
}

// ═══════════════════════════════════════════════════════════
//  Detail panel – edit mode
// ═══════════════════════════════════════════════════════════
function toggleEditMode() {
  if (!_detailData) return;
  const p = _detailData;
  // Replace title with an input
  $("dp-title").innerHTML =
    `<input class="edit-title-input" id="edit-title" value="${escHtml(p.title)}" />`;
  // Replace actions with Save / Cancel
  $("dp-actions").innerHTML = `
    <button class="btn-sm save" onclick="saveProjectEdits('${p.id}')">✔ Save</button>
    <button class="btn-sm" onclick="renderDetail(_detailData)">✕ Cancel</button>`;
  // Render editable body
  const meta = p.metadata || {};
  const scenes = meta.scenes || [];
  let body = "";

  // Tags
  body += `<div class="detail-section">
    <div class="detail-section-title">Tags</div>
    <input class="edit-input" id="edit-tags" placeholder="comma-separated tags"
           value="${escHtml(p.tags.join(", "))}" />
  </div>`;

  // Metadata fields
  body += `<div class="detail-section">
    <div class="detail-section-title">Metadata</div>
    <div class="edit-fields">`;
  const inputFields = [
    ["narrator", "Narrator", meta.narrator ?? ""],
    ["duration", "Duration (s)", meta.duration ?? ""],
    ["word_count", "Word Count", meta.word_count ?? ""],
  ];
  for (const [key, label, val] of inputFields) {
    body += `<div class="edit-field">
      <label class="edit-label">${escHtml(label)}</label>
      <input class="edit-input" id="edit-meta-${key}" value="${escHtml(String(val))}" />
    </div>`;
  }
  const textareaFields = [
    ["summary", "Summary", meta.summary || ""],
    ["transcript", "Transcript", meta.transcript || ""],
    ["music", "Music Prompt", meta.music || ""],
    ["visual_guide", "Visual Guide", meta.visual_guide || ""],
  ];
  for (const [key, label, val] of textareaFields) {
    body += `<div class="edit-field">
      <label class="edit-label">${escHtml(label)}</label>
      <textarea class="edit-textarea" id="edit-meta-${key}" rows="3">${escHtml(val)}</textarea>
    </div>`;
  }
  body += `</div></div>`;

  // Scenes
  if (scenes.length) {
    body += `<div class="detail-section">
      <div class="detail-section-title">Scenes (${scenes.length})</div>
      <div class="scenes-list">${scenes
        .map(
          (s, i) => `
        <div class="scene-card">
          <div class="scene-body">
            <div class="scene-num">Scene ${i + 1}${s.duration != null ? ` · ${s.duration}s` : ""}</div>
            <label class="edit-label">Voiceover</label>
            <textarea class="edit-textarea" id="edit-scene-${i}-voiceover" rows="3">${escHtml(s.voiceover || "")}</textarea>
            <label class="edit-label" style="margin-top:.5rem">Image Prompt</label>
            <textarea class="edit-textarea" id="edit-scene-${i}-image_prompt" rows="2">${escHtml(s.image_prompt || "")}</textarea>
          </div>
        </div>`,
        )
        .join("")}
      </div>
    </div>`;
  }

  $("dp-body").innerHTML = body;
}

async function saveProjectEdits(id) {
  if (!_detailData) return;
  const title = ($("edit-title")?.value ?? "").trim() || _detailData.title;
  const tagsRaw = $("edit-tags")?.value ?? "";
  const tags = tagsRaw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);

  // Start from existing metadata so we don't lose fields we don't edit (e.g. paths)
  const meta = { ..._detailData.metadata };

  const numericKeys = ["duration", "word_count"];
  const inputKeys = ["narrator", "duration", "word_count"];
  for (const key of inputKeys) {
    const el = $(`edit-meta-${key}`);
    if (!el) continue;
    const raw = el.value.trim();
    if (raw === "") {
      delete meta[key];
    } else {
      meta[key] = numericKeys.includes(key) ? parseFloat(raw) : raw;
    }
  }
  for (const key of ["summary", "transcript", "music", "visual_guide"]) {
    const el = $(`edit-meta-${key}`);
    if (!el) continue;
    const raw = el.value.trim();
    if (raw === "") {
      delete meta[key];
    } else {
      meta[key] = raw;
    }
  }

  // Update scenes
  const scenes = (meta.scenes || []).map((s, i) => {
    const voEl = $(`edit-scene-${i}-voiceover`);
    const ipEl = $(`edit-scene-${i}-image_prompt`);
    return {
      ...s,
      voiceover: voEl ? voEl.value : s.voiceover,
      image_prompt: ipEl ? ipEl.value : s.image_prompt,
    };
  });
  if (scenes.length) meta.scenes = scenes;

  try {
    const updated = await api("PATCH", `/projects/${id}`, {
      title,
      tags,
      metadata: meta,
    });
    toast("Saved", "success");
    renderDetail(updated);
    loadProjects();
    loadDashboard();
  } catch (e) {
    toast("Save failed: " + e.message, "error");
  }
}

// ═══════════════════════════════════════════════════════════
//  Keyboard
// ═══════════════════════════════════════════════════════════
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if ($("gen-modal").classList.contains("open")) closeGenerateModal();
    else if ($("detail-panel").classList.contains("open")) closeDetail();
    else $("topic-dropdown").classList.remove("open");
  }
});

// ═══════════════════════════════════════════════════════════
//  Init
// ═══════════════════════════════════════════════════════════
connectSSE();
loadTopics().then(() => {
  if (currentTopicId) {
    switchPage("dashboard");
    $("tab-dashboard").classList.add("active");
    loadDashboard();
  }
});
