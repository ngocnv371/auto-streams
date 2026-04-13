# auto-streams

A tool to automate bulk production of YouTube Shorts.

## Tech Stack

- **Backend**: Python, FastAPI, SQLAlchemy (async), aiosqlite
- **Video**: MoviePy, Pillow, faster-whisper (subtitle alignment)
- **AI Integrations**: Google Gemini, OpenAI-compatible APIs, ComfyUI (HTTP), KittenTTS
- **Config**: YAML file
- **Database**: SQLite

## Workflow

Each project moves through a pipeline. Steps can be batched across projects to maximize throughput (e.g., run all image generation back-to-back before switching ComfyUI models).

```
[Idea Pool]
    │
    ▼
[approved]  ─── user approves idea ───────────────────────────────┐
    │                                                              │
    ▼                                                              │
[content_ready]  ─── generate: transcript, narrator,              │
    │                           music prompt, visual_guide         │
    ▼                                                              │
[scenes_ready]   ─── generate: scenes[] from transcript           │
    │                           + narrator + visual_guide          │
    ▼                                                              │
[tts_ready]      ─── generate: voiceover audio per scene          │
    │                                                              │
    ▼                                                              │
[music_ready]    ─── generate: project-level background music     │
    │                                                              │
    ▼                                                              │
[images_ready]   ─── generate: image per scene                    │
    │                                                              │
    ▼                                                              │
[clips_ready]    ─── render: clip per scene (audio + image        │
    │                         + subtitles + tail padding)          │
    ▼                                                              │
[done]           ─── stitch all clips → final video               │
    │                                                              │
    ▼                                                              │
[failed]  ◄──────────── any unrecoverable error ──────────────────┘
```

### Batch queuing

Because ComfyUI benefits from keeping models loaded, steps are collected and executed in batch:

| Queue | Collected from |
|-------|---------------|
| `text_queue` | transcript + prompts generation (LLM calls) |
| `tts_queue` | voiceover per scene (advances to `tts_ready`) |
| `music_queue` | background music per project (advances to `music_ready`) |
| `image_queue` | image per scene |
| `render_queue` | clip rendering (local, CPU/GPU) |

## Projects

### Status lifecycle

`idea` → `approved` → `content_ready` → `scenes_ready` → `tts_ready` → `music_ready` → `images_ready` → `clips_ready` → `done` | `failed`

### Data model

```typescript
interface Project {
  id: string;
  title: string;
  status: ProjectStatus;
  tags: string[];
  metadata: Metadata;        // stored as JSON in SQLite
  created_at: Date;
  updated_at: Date;
}

interface Metadata {
  // Content
  summary?: string;                       // Idea / story brief
  transcript?: string;                    // Full narration text
  word_count?: number;

  // Generation prompts
  narrator?: string;                      // Voice persona / style description
  music?: string;                         // Music generation prompt
  visual_guide?: string;                  // Style guide for image prompts

  // Project-level media
  music_url?: string;                     // Generated background music file
  audio_url?: string;                     // Full narration audio (concatenated)
  video_url?: string;                     // Final compiled video
  thumbnail_url?: string;                 // Cover image
  duration?: number;                      // Total duration in seconds
  selected_cover_image_index?: number;

  // Scenes
  scenes?: Scene[];

  // Per-run generation config (overrides global config)
  config?: ProjectConfig;
}

interface Scene {
  voiceover: string;                      // Narration text for this scene
  image_prompt: string;                   // Image generation prompt

  // Generated assets (populated during pipeline)
  audio_url?: string;                     // Scene voiceover audio file
  image_url?: string;                     // Scene image file
  clip_url?: string;                      // Rendered scene clip
  duration?: number;                      // Scene audio duration in seconds
}

interface ProjectConfig {
  image?: {
    aspectRatio?: string;                 // e.g. "9:16"
  };
  narration?: {
    voice?: string;
    speed?: number;
  };
  video?: {
    enableKenBurns?: boolean;
    enableParticles?: boolean;
    subtitleStyle?: SubtitleStyle;
  };
}
```

### Assets on disk

All generated files are stored under `./temp/{project_id}/`:

```
temp/{project_id}/
  music.wav
  narration.wav          # full narration (optional, for reference)
  scene_00/
    audio.wav
    image.png
    clip.mp4
  scene_01/
    ...
  final.mp4
  thumbnail.png
```

## AI Providers

Configurable per generation type. The active provider for each type is set in the YAML config.

| Type | Providers |
|------|-----------|
| Text (LLM) | `gemini`, `openai` (OpenAI-compatible) |
| Image | `gemini`, `comfy` |
| TTS | `gemini`, `kittentts` |
| Music | `comfy` |

### ComfyUI integration

ComfyUI workflows are defined as JSON files under `./assets/`. The placeholder `__PROMPT__` in the workflow JSON is replaced at runtime with the generated prompt before submitting to the ComfyUI API.

- `assets/comfy-zimage.json` — image generation workflow
- `assets/comfy-music.json` — music generation workflow

## Web UI

A browser-based dashboard served by the FastAPI backend.

**Views:**
- **Dashboard** — overall pipeline progress; per-queue status; counts by project status
- **Projects list** — sortable/filterable table of all projects with inline status badges
- **Project detail** — per-scene breakdown; preview generated assets; trigger individual regeneration steps; approve/reject ideas

**Actions available from UI:**
- Approve / reject idea
- Trigger a specific pipeline step (or full run) for a project
- Start / pause batch queues
- Preview audio, images, clips, and final video inline

## Configuration

A local `config.yml` drives all runtime settings