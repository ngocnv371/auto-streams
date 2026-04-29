import React, { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import htm from "htm";

const html = htm.bind(React.createElement);

// Utils
function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function badge(status) {
  return html`<span class=${`badge badge-${status}`}
    >${status.replace(/_/g, " ")}</span
  >`;
}
function statusColor(s) {
  return (
    {
      idea: "var(--s-idea)",
      approved: "var(--s-approved)",
      content_ready: "var(--s-content_ready)",
      scenes_ready: "var(--s-scenes_ready)",
      tts_ready: "var(--s-tts_ready)",
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

// API helper
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

// Toast
function Toast({ msg, type }) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (msg) {
      setShow(true);
      const t = setTimeout(() => setShow(false), 2800);
      return () => clearTimeout(t);
    }
  }, [msg]);
  return html`<div id="toast" className=${show ? `show ${type}` : ""}>
    ${msg}
  </div>`;
}

// SSE Indicator
function SSEIndicator({ status }) {
  let dotClass = "sse-dot ";
  if (status === "running") dotClass += "running";
  else if (status === "disconnected") dotClass += "error";
  else dotClass += "idle";
  return html`
    <div class="sse-indicator" id="sse-indicator" title="Pipeline status">
      <div class=${dotClass} id="sse-dot"></div>
      <span class="sse-label" id="sse-label">${status}</span>
    </div>
  `;
}

// Activity Log
function ActivityLog({ log }) {
  if (!log.length)
    return html`<div class="activity-log" id="activity-log">
      <div class="activity-empty">No activity yet</div>
    </div>`;
  return html`
    <div class="activity-log" id="activity-log">
      ${log.map(
        (e) => html`
          <div class="activity-entry level-${escHtml(e.level)}">
            <span class="activity-time"
              >${e.ts.toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              })}</span
            >
            <span class="activity-msg">${escHtml(e.msg)}</span>
            ${e.project_id
              ? html`<span class="activity-pid" title="${escHtml(e.project_id)}"
                  >${e.project_id.slice(0, 8)}</span
                >`
              : ""}
          </div>
        `,
      )}
    </div>
  `;
}

// Topic Dropdown
function TopicDropdown({
  allTopics,
  currentTopicId,
  selectTopic,
  addTopic,
  deleteTopic,
  open,
  setOpen,
}) {
  const inputRef = useRef();
  useEffect(() => {
    if (open && inputRef.current) inputRef.current.focus();
  }, [open]);
  return html`
    <div
      class="topic-dropdown"
      id="topic-dropdown"
      style=${{ display: open ? "block" : "none" }}
    >
      <div class="topic-dropdown-header">Workspace</div>
      <div class="topic-list" id="topic-list-dd">
        ${!allTopics.length
          ? html`<div class="topic-empty">No topics yet — add one below.</div>`
          : allTopics.map(
              (t) => html`
                <div
                  class="topic-item ${t.id === currentTopicId
                    ? "selected"
                    : ""}"
                  onClick=${() => {
                    selectTopic(t.id, t.topic);
                    setOpen(false);
                  }}
                >
                  <span class="topic-text" title="${escHtml(t.topic)}"
                    >${escHtml(t.topic)}</span
                  >
                  <button
                    class="topic-del"
                    title="Delete"
                    onClick=${(e) => {
                      e.stopPropagation();
                      deleteTopic(t.id);
                    }}
                  >
                    ✕
                  </button>
                </div>
              `,
            )}
      </div>
      <div class="topic-add-row">
        <input
          class="topic-add-input"
          id="topic-add-input"
          placeholder="New one-sentence topic…"
          ref=${inputRef}
          onKeyDown=${(e) => {
            if (e.key === "Enter") addTopic(e.target.value);
          }}
        />
        <button
          class="topic-add-btn"
          onClick=${() => addTopic(inputRef.current.value)}
        >
          Add
        </button>
      </div>
    </div>
  `;
}

// Project Detail Modal
function ProjectDetailModal({ projectId, onClose }) {
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    api("GET", `/projects/${projectId}`)
      .then(setProject)
      .catch(() => setProject(null))
      .finally(() => setLoading(false));
  }, [projectId]);

  if (!projectId) return null;

  return html`
    <div class="detail-overlay" id="detail-overlay" onClick=${onClose}></div>
    <div class="detail-panel open" id="detail-panel">
      <div class="detail-header">
        <div class="detail-header-info">
          <div class="detail-title" id="dp-title">
            ${project ? project.title : ""}
          </div>
          <div class="detail-meta" id="dp-meta">
            ${project ? badge(project.status) : ""}
            <span class="text-muted">
              ${project ? escHtml(project.id) : ""}
            </span>
            ${" "} - ${project ? fmtDate(project.created_at) : ""}
          </div>
        </div>
        <button class="detail-close" onClick=${onClose}>✕</button>
      </div>
      <div class="detail-actions" id="dp-actions">
        <!-- Actions can be added here -->
      </div>
      <div id="dp-body">
        ${loading
          ? html`<div class="empty">Loading…</div>`
          : project
            ? html`<${ProjectDetailBody} project=${project} />`
            : html`<div class="empty">Not found</div>`}
      </div>
    </div>
  `;
}

function ProjectDetailBody({ project }) {
  const meta = project.metadata || {};
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
  const scenes = meta.scenes || [];

  return html`
    <div>
      ${metaFields.length
        ? html`<div class="detail-section">
            <div class="detail-section-title">Metadata</div>
            <div class="meta-fields">
              ${metaFields.map(
                ([label, value]) =>
                  html`<div><b>${label}:</b> ${escHtml(value)}</div>`,
              )}
            </div>
          </div>`
        : null}
      ${project.tags && Array.isArray(project.tags) && project.tags.length
        ? html`<div class="detail-section">
            <div class="detail-section-title">Tags</div>
            <div class="flex gap-1 flex-wrap">
              ${project.tags.map(
                (t) =>
                  html`<span class="px-2 py-1 bg-gray-200 rounded"
                    >${escHtml(t)}</span
                  >`,
              )}
            </div>
          </div>`
        : null}
      <${ScenesSection} projectId=${project.id} scenes=${scenes} />
    </div>
  `;
}

// Projects Page (table and detail trigger)
function ProjectsPage({ currentTopicId, showDetail }) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [availableTags, setAvailableTags] = useState([]);

  useEffect(() => {
    if (!currentTopicId) {
      setProjects([]);
      setAvailableTags([]);
      return;
    }
    setLoading(true);
    api("GET", `/projects?topic_id=${currentTopicId}&limit=200`)
      .then((data) => {
        const arr = Array.isArray(data) ? data : [];
        setProjects(arr);
        // Build unique tag list
        const tagSet = new Set();
        arr.forEach((p) => {
          if (Array.isArray(p.tags)) {
            p.tags.forEach((t) => tagSet.add(t));
          }
        });
        setAvailableTags(Array.from(tagSet).sort());
      })
      .catch(() => {
        setProjects([]);
        setAvailableTags([]);
      })
      .finally(() => setLoading(false));
  }, [currentTopicId]);

  // Filtered projects
  const filteredProjects = projects.filter((p) => {
    let statusOk = true;
    let tagOk = true;
    if (statusFilter) statusOk = p.status === statusFilter;
    if (tagFilter) tagOk = Array.isArray(p.tags) && p.tags.includes(tagFilter);
    return statusOk && tagOk;
  });

  // Build available status list from loaded projects
  const availableStatuses = Array.from(new Set(projects.map((p) => p.status)))
    .filter(Boolean)
    .sort();

  if (!currentTopicId)
    return html`<div class="empty">Select a topic to view projects.</div>`;

  if (loading) return html`<div class="empty">Loading…</div>`;

  return html`
    <div
      class="filters-row"
      style=${{
        marginBottom: "1em",
        display: "flex",
        gap: "1em",
        alignItems: "center",
      }}
    >
      <label
        >Status:
        <select
          value=${statusFilter}
          onChange=${(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All</option>
          ${availableStatuses.map(
            (s) => html`<option value=${s}>${s.replace(/_/g, " ")}</option>`,
          )}
        </select>
      </label>
      <label
        >Tag:
        <select
          value=${tagFilter}
          onChange=${(e) => setTagFilter(e.target.value)}
        >
          <option value="">All</option>
          ${availableTags.map((t) => html`<option value=${t}>${t}</option>`)}
        </select>
      </label>
      <button
        class="btn-sm"
        onClick=${() => {
          setStatusFilter("");
          setTagFilter("");
        }}
      >
        Clear Filters
      </button>
    </div>

    ${filteredProjects.length === 0
      ? html`<div class="empty">No projects found.</div>`
      : html`
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Tags</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              ${filteredProjects.map(
                (p) =>
                  html`<tr onClick=${() => showDetail(p.id)}>
                    <td class="td-title">${escHtml(p.title)}</td>
                    <td>${badge(p.status)}</td>
                    <td class="flex gap-1">
                      ${p.tags && Array.isArray(p.tags) && p.tags.length
                        ? p.tags.map(
                            (t) =>
                              html`<span class="px-2 py-1 bg-gray-200 rounded"
                                >${escHtml(t)}</span
                              >`,
                          )
                        : html`<span class="text-muted">—</span>`}
                    </td>
                    <td class="td-date">${fmtDate(p.created_at)}</td>
                    <td class="td-actions">
                      <button
                        class="btn-sm"
                        onClick=${(e) => {
                          e.stopPropagation();
                          showDetail(p.id);
                        }}
                      >
                        Detail
                      </button>
                    </td>
                  </tr>`,
              )}
            </tbody>
          </table>
        `}
  `;
}

const fnFromPath = (path) =>
  path ? path.replace(/\\/g, "/").split("/").pop() : null;

// Scenes Section
function ScenesSection({ projectId, scenes }) {
  if (!Array.isArray(scenes) || scenes.length === 0) {
    return html`<div class="scenes-section empty">No scenes available.</div>`;
  }
  return html`
    <div class="scenes-section">
      <div class="scenes-title">Scenes</div>
      <div class="scenes-list">
        ${scenes.map(
          (scene, idx) => html`
            <div class="scene-card" key=${idx}>
              <div class="scene-thumb-wrap">
                <img
                  class="scene-thumb"
                  src=${`/api/projects/${projectId}/image/${fnFromPath(scene.image_path)}`}
                  alt="Scene ${idx + 1} thumbnail"
                  loading="lazy"
                  width="128"
                  height="72"
                  onError=${(e) => (e.target.style.display = "none")}
                />
              </div>
              <div class="scene-info">
                <div class="scene-voiceover">${escHtml(scene.voiceover)}</div>
                <div class="scene-prompt">
                  <b>Prompt:</b> ${escHtml(scene.image_prompt)}
                </div>
                <div class="scene-meta">
                  <span
                    ><b>Start:</b> ${scene.audio_start?.toFixed(2) ??
                    "-"}s</span
                  >
                  <span
                    ><b>End:</b> ${scene.audio_end?.toFixed(2) ?? "-"}s</span
                  >
                  <span
                    ><b>Duration:</b> ${scene.duration?.toFixed(2) ??
                    "-"}s</span
                  >
                </div>
              </div>
            </div>
          `,
        )}
      </div>
    </div>
  `;
}

// Main App
function App() {
  // State
  const [activityLog, setActivityLog] = useState([]);
  const [sseStatus, setSseStatus] = useState("idle");
  const [allTopics, setAllTopics] = useState([]);
  const [detailProjectId, setDetailProjectId] = useState(null);
  const [currentTopicId, setCurrentTopicId] = useState(
    localStorage.getItem("as_topic_id") || null,
  );
  const [currentTopicText, setCurrentTopicText] = useState(
    localStorage.getItem("as_topic_text") || null,
  );
  const [topicDropdownOpen, setTopicDropdownOpen] = useState(false);
  const [activePage, setActivePage] = useState("splash");
  const [selectedCount, setSelectedCount] = useState(5);
  const [toastMsg, setToastMsg] = useState("");
  const [toastType, setToastType] = useState("success");

  // SSE
  useEffect(() => {
    let evtSource = null;
    let retryTimer = null;
    function connectSSE() {
      if (evtSource) evtSource.close();
      evtSource = new window.EventSource("/api/events");
      evtSource.onopen = () => setSseStatus("connected");
      evtSource.onmessage = (e) => {
        let data;
        try {
          data = JSON.parse(e.data);
        } catch {
          return;
        }
        if (data.type === "status") {
          // ...could handle status
        } else if (data.type === "activity") {
          setActivityLog((log) => [
            {
              ts: data.ts ? new Date(data.ts * 1000) : new Date(),
              msg: data.msg || "",
              level: data.level || "info",
              project_id: data.project_id || null,
              stage: data.stage || null,
            },
            ...log.slice(0, 59),
          ]);
        }
      };
      evtSource.onerror = () => {
        setSseStatus("disconnected");
        evtSource.close();
        evtSource = null;
        retryTimer = setTimeout(connectSSE, 4000);
      };
    }
    connectSSE();
    return () => {
      if (evtSource) evtSource.close();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, []);

  // Topics
  useEffect(() => {
    async function loadTopics() {
      try {
        const topics = await api("GET", "/topics");
        setAllTopics(topics);
        if (currentTopicId && !topics.find((t) => t.id === currentTopicId)) {
          setCurrentTopicId(null);
          setCurrentTopicText(null);
          localStorage.removeItem("as_topic_id");
          localStorage.removeItem("as_topic_text");
        }
      } catch {
        setAllTopics([]);
      }
    }
    loadTopics();
  }, [currentTopicId]);

  // Topic select
  function selectTopic(id, text) {
    setCurrentTopicId(id);
    setCurrentTopicText(text);
    localStorage.setItem("as_topic_id", id);
    localStorage.setItem("as_topic_text", text);
    setTopicDropdownOpen(false);
    setActivePage("dashboard");
  }
  async function addTopic(text) {
    text = text.trim();
    if (!text) return;
    try {
      const t = await api("POST", "/topics", { topic: text });
      setAllTopics((topics) => [...topics, t]);
      selectTopic(t.id, t.topic);
      setToastMsg("Topic created");
      setToastType("success");
    } catch (e) {
      setToastMsg(e.message);
      setToastType("error");
    }
  }
  async function deleteTopic(id) {
    const t = allTopics.find((t) => t.id === id);
    if (
      !window.confirm(
        `Delete topic "${t?.topic}"?\nThis will fail if it has associated projects.`,
      )
    )
      return;
    try {
      await api("DELETE", `/topics/${id}`);
      setAllTopics((topics) => topics.filter((t) => t.id !== id));
      if (currentTopicId === id) {
        setCurrentTopicId(null);
        setCurrentTopicText(null);
        localStorage.removeItem("as_topic_id");
        localStorage.removeItem("as_topic_text");
      }
      setToastMsg("Topic deleted");
      setToastType("success");
    } catch (e) {
      setToastMsg(e.message);
      setToastType("error");
    }
  }

  // Nav
  function showPage(id) {
    if (!currentTopicId) {
      setToastMsg("Select a topic first");
      setToastType("error");
      return;
    }
    setActivePage(id);
  }

  // Render
  return html` <React.Fragment>
    <nav>
      <div class="brand">auto<span>-streams</span></div>
      <div class="topic-ws" id="topic-ws">
        <button
          class=${`topic-ws-btn${currentTopicId ? "" : " no-topic"}`}
          id="topic-ws-btn"
          onClick=${(e) => {
            e.stopPropagation();
            setTopicDropdownOpen((v) => !v);
          }}
        >
          <span class="label" id="topic-ws-label">
            ${currentTopicId ? currentTopicText : "Select a topic…"}
          </span>
          <span class="chevron">▾</span>
        </button>
        ${html`<${TopicDropdown}
          allTopics=${allTopics}
          currentTopicId=${currentTopicId}
          selectTopic=${selectTopic}
          addTopic=${addTopic}
          deleteTopic=${deleteTopic}
          open=${topicDropdownOpen}
          setOpen=${setTopicDropdownOpen}
        />`}
      </div>
      <div class="nav-tabs">
        <button
          class=${`nav-tab${activePage === "dashboard" ? " active" : ""}`}
          id="tab-dashboard"
          onClick=${() => showPage("dashboard")}
        >
          Dashboard
        </button>
        <button
          class=${`nav-tab${activePage === "projects" ? " active" : ""}`}
          id="tab-projects"
          onClick=${() => showPage("projects")}
        >
          Projects
        </button>
      </div>
      <div class="nav-spacer"></div>
      <${SSEIndicator} status=${sseStatus} />
      <button class="btn-generate" id="btn-generate" disabled>
        Generate Ideas
      </button>
    </nav>
    <main>
      <div
        id="page-splash"
        class=${`page${activePage === "splash" ? " active" : ""}`}
      >
        <div class="splash">
          <div class="splash-icon">🗂️</div>
          <div class="splash-title">No topic selected</div>
          <div class="splash-sub">
            Choose or create a topic workspace using the dropdown in the nav
            bar.
          </div>
        </div>
      </div>
      <div
        id="page-dashboard"
        class=${`page${activePage === "dashboard" ? " active" : ""}`}
      >
        <h2>Activity</h2>
        <${ActivityLog} log=${activityLog} />
      </div>
      <div
        id="page-projects"
        class=${`page${activePage === "projects" ? " active" : ""}`}
      >
        <${ProjectsPage}
          currentTopicId=${currentTopicId}
          showDetail=${(id) => setDetailProjectId(id)}
        />
      </div>
      <${ProjectDetailModal}
        projectId=${detailProjectId}
        onClose=${() => setDetailProjectId(null)}
      />
    </main>
    <${Toast} msg=${toastMsg} type=${toastType} />
  </React.Fragment>`;
}

const root = createRoot(document.getElementById("root"));
root.render(html`<${App} />`);
