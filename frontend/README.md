# Health Video Bot — Frontend Dashboard

Next.js dashboard for the Hindi health video pipeline. Provides a UI to create jobs,
run pipeline stages, stream live logs, browse the B-roll clip library, and manage
WhisperX model downloads.

## Tech stack

- **Next.js** (App Router) — server components + API routes
- **React** + **Tailwind CSS**
- **SWR** — data fetching and cache invalidation
- **SSE (Server-Sent Events)** — streaming stage logs and model download progress

## Setup

```bash
npm install
```

Create `.env.local`:
```
PIPELINE_ROOT=..                        # path to the Python project root
PYTHON_BIN=../.venv/bin/python3         # path to the venv Python binary
```

```bash
npm run dev   # http://localhost:3000
```

## Pages

| Route | What it does |
|---|---|
| `/jobs` | List all jobs with status badges and live polling |
| `/jobs/[jobId]` | Per-job detail: pipeline timeline, stage runner, job data explorer |
| `/clips` | B-roll clip library — filter by status, verify file integrity |
| `/models` | WhisperX model download status + one-click download with live progress |

## API routes

### Jobs
| Endpoint | Method | What it does |
|---|---|---|
| `/api/jobs` | GET | List all jobs (summary) |
| `/api/jobs` | POST | Create a new job |
| `/api/jobs/[jobId]` | GET | Full job JSON |
| `/api/jobs/[jobId]/stage/[stage]` | POST | `{action: "run"}` → returns stream URL; `{action: "skip"}` → advances status |
| `/api/jobs/[jobId]/stage/[stage]/stream` | GET | SSE stream of stage stdout/stderr/exit |

### Clips
| Endpoint | Method | What it does |
|---|---|---|
| `/api/clips` | GET | List clips from broll_cache.db (supports `?status=active\|missing\|deleted\|all`) |
| `/api/clips/verify` | POST | Run `broll_db.py verify` and return missing clip IDs |

### Models
| Endpoint | Method | What it does |
|---|---|---|
| `/api/models` | GET | Runs `model_manager.py status` → JSON of all models + download status |
| `/api/models/download` | POST `{modelId}` | SSE stream of `model_manager.py download <id>` output |

### Assets
| Endpoint | Method | What it does |
|---|---|---|
| `/api/assets/[...path]` | GET | Serves files from the `assets/` directory (for thumbnail previews etc.) |

## Stage runner flow

1. User clicks **Run** on a stage row in `PipelineTimeline`
2. Frontend POSTs `{action: "run"}` to `/api/jobs/[jobId]/stage/[stage]`
3. Server responds with `{streamUrl: "/api/jobs/.../stream"}`
4. `useStageStream` hook opens an `EventSource` on the stream URL
5. Server spawns the Python stage script and relays stdout/stderr as SSE events
6. On exit event, `useStageStream` signals `PipelineTimeline` to re-fetch the job
7. Stage 1 auto-sends `"1\n"` to stdin after 20 s if no PMID is supplied (auto-selects top result)

## Model download flow

1. User clicks **Download** on a model card in `/models`
2. Frontend POSTs `{modelId}` to `/api/models/download`
3. Response is a streaming SSE body (no redirect — read directly from `Response.body`)
4. `ModelsPage` reads the stream, appends lines to `TerminalOutput`, and calls `mutate()` on exit
5. After download completes, the model status card updates to show "Downloaded"

## Key components

| Component | What it does |
|---|---|
| `PipelineTimeline` | Renders stage rows, manages the active SSE stream, shows terminal output |
| `StageRow` | Single stage with Run/Skip buttons and state icon |
| `TerminalOutput` | ANSI-capable terminal output panel with auto-scroll |
| `JobDataExplorer` | Collapsible sections for study / claims / content / assets / output |
| `ModelPanel` (in `/models/page.tsx`) | Model card grid with download buttons and status badges |
| `ClipRow` (in `/clips/page.tsx`) | Expandable B-roll clip row with source URL and full path |

## Hooks

| Hook | What it does |
|---|---|
| `useJob(jobId)` | SWR fetch for a single job, polls every 5 s while status is non-terminal |
| `useJobs()` | SWR fetch for the jobs list |
| `useStageStream(jobId)` | Manages the active SSE EventSource; exposes `lines`, `isRunning`, `exitCode` |
| `useClips(status)` | SWR fetch for the clip library |
| `useModels()` | SWR fetch for WhisperX model status |

## Pipeline config (`lib/pipeline-config.ts`)

All stage definitions live here. Each stage entry has:
```ts
{
  key: StageKey           // e.g. "stage_4d"
  label: string           // display name
  script: string          // relative path to Python script
  prerequisite: JobStatus // job must be at this status before running
  completedStatus: JobStatus | null  // null for sub-stages (4a/4b/4c/4d)
}
```

Sub-stages (4a–4d) do not individually change job status. The frontend API sets
`stage_4_complete` when "Skip all" is clicked on the Stage 4 group, or when all
sub-stages have been run individually.
