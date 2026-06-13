import fs from 'fs'
import path from 'path'
import type { AppSettings } from '@/lib/types'

const PIPELINE_ROOT = process.env.PIPELINE_ROOT ?? path.resolve(process.cwd(), '..')
const SETTINGS_FILE = path.join(PIPELINE_ROOT, 'settings.json')

function readDotEnv(): Record<string, string> {
  try {
    const content = fs.readFileSync(path.join(PIPELINE_ROOT, '.env'), 'utf-8')
    const result: Record<string, string> = {}
    for (const line of content.split('\n')) {
      const trimmed = line.trim()
      if (!trimmed || trimmed.startsWith('#')) continue
      const eq = trimmed.indexOf('=')
      if (eq === -1) continue
      const key = trimmed.slice(0, eq).trim()
      let value = trimmed.slice(eq + 1).trim()
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1)
      }
      result[key] = value
    }
    return result
  } catch {
    return {}
  }
}

// API-key env vars surfaced in the Settings UI (booleans on GET, writable on PUT).
const LLM_KEY_ENVS = [
  'ANTHROPIC_API_KEY',
  'OPENAI_API_KEY',
  'GROQ_API_KEY',
  'NVIDIA_API_KEY',
  'OPENROUTER_API_KEY',
] as const

// Update/insert keys in the pipeline .env, preserving comments, ordering, and
// unrelated lines. Empty-string values are skipped so a blank field never wipes
// an existing secret.
function writeDotEnv(updates: Record<string, string>) {
  const envPath = path.join(PIPELINE_ROOT, '.env')
  let lines: string[] = []
  try {
    lines = fs.readFileSync(envPath, 'utf-8').split('\n')
  } catch {
    lines = []
  }
  const pending = new Map<string, string>()
  for (const [k, v] of Object.entries(updates)) {
    if (v !== '') pending.set(k, v)
  }
  const out = lines.map((line) => {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) return line
    const eq = trimmed.indexOf('=')
    if (eq === -1) return line
    const key = trimmed.slice(0, eq).trim()
    if (pending.has(key)) {
      const value = pending.get(key)!
      pending.delete(key)
      return `${key}=${value}`
    }
    return line
  })
  // Append any keys that weren't already present.
  for (const [k, v] of pending) out.push(`${k}=${v}`)
  fs.writeFileSync(envPath, out.join('\n'))
}

export const DEFAULT_SETTINGS: AppSettings = {
  assembly: {
    animations_enabled: true,
    animation_type: 'ken_burns',
    transitions_enabled: true,
    transition_type: 'crossfade',
    transition_duration: 0.4,
  },
  pipeline: {
    default_render_mode: 'final',
    default_whisper_model: 'large-v2',
  },
  audio: {
    subscribe_click_sound: 'universfield-computer-mouse-click-352734.mp3',
    subscribe_bell_sound: 'freesound_community-bell-98033.mp3',
  },
}

export function readSettings(): AppSettings {
  try {
    if (fs.existsSync(SETTINGS_FILE)) {
      const parsed = JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf-8'))
      return {
        assembly: { ...DEFAULT_SETTINGS.assembly, ...(parsed.assembly ?? {}) },
        pipeline: { ...DEFAULT_SETTINGS.pipeline, ...(parsed.pipeline ?? {}) },
        audio: { ...DEFAULT_SETTINGS.audio, ...(parsed.audio ?? {}) },
      }
    }
  } catch {
    // fall through to defaults
  }
  return DEFAULT_SETTINGS
}

// process.env only has vars from frontend/.env.local; the pipeline's .env lives
// one level up, so we parse it directly to get the real runtime values. `keys`
// reports only whether each API key is set — never the raw secret values.
function buildEnv() {
  const dotEnv = readDotEnv()
  const get = (key: string, fallback: string) =>
    dotEnv[key] ?? process.env[key] ?? fallback
  const keys: Record<string, boolean> = {}
  for (const k of LLM_KEY_ENVS) {
    keys[k] = Boolean((dotEnv[k] ?? process.env[k] ?? '').trim())
  }
  return {
    llm_model: get('LLM_MODEL', 'claude-sonnet-4-6'),
    llm_provider: get('LLM_PROVIDER', 'auto'),
    pipeline_root: PIPELINE_ROOT,
    python_bin: process.env.PYTHON_BIN ?? dotEnv['PYTHON_BIN'] ?? 'python3',
    keys,
  }
}

export async function GET() {
  return Response.json({ settings: readSettings(), env: buildEnv() })
}

type EnvPatch = {
  LLM_PROVIDER?: string
  LLM_MODEL?: string
  keys?: Record<string, string>
}

export async function PUT(request: Request) {
  try {
    const body = (await request.json()) as Partial<AppSettings> & { env?: EnvPatch }

    // LLM provider/model/keys live in .env (read by the Python stages at spawn),
    // not settings.json. Apply them separately when present.
    if (body.env) {
      const updates: Record<string, string> = {}
      if (typeof body.env.LLM_PROVIDER === 'string') updates.LLM_PROVIDER = body.env.LLM_PROVIDER
      if (typeof body.env.LLM_MODEL === 'string') updates.LLM_MODEL = body.env.LLM_MODEL
      if (body.env.keys) {
        for (const k of LLM_KEY_ENVS) {
          const v = body.env.keys[k]
          if (typeof v === 'string') updates[k] = v // writeDotEnv skips empty values
        }
      }
      writeDotEnv(updates)
    }

    const current = readSettings()
    const updated: AppSettings = {
      assembly: { ...current.assembly, ...(body.assembly ?? {}) },
      pipeline: { ...current.pipeline, ...(body.pipeline ?? {}) },
      audio: { ...current.audio, ...(body.audio ?? {}) },
    }
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(updated, null, 2))
    return Response.json({ settings: updated, env: buildEnv() })
  } catch (err) {
    return Response.json({ error: String(err) }, { status: 500 })
  }
}
