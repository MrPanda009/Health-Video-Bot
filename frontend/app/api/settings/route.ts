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
}

export function readSettings(): AppSettings {
  try {
    if (fs.existsSync(SETTINGS_FILE)) {
      const parsed = JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf-8'))
      return {
        assembly: { ...DEFAULT_SETTINGS.assembly, ...(parsed.assembly ?? {}) },
        pipeline: { ...DEFAULT_SETTINGS.pipeline, ...(parsed.pipeline ?? {}) },
      }
    }
  } catch {
    // fall through to defaults
  }
  return DEFAULT_SETTINGS
}

export async function GET() {
  const settings = readSettings()
  // process.env only has vars from frontend/.env.local; the pipeline's .env lives
  // one level up, so we parse it directly to get the real runtime values.
  const dotEnv = readDotEnv()
  const get = (key: string, fallback: string) =>
    dotEnv[key] ?? process.env[key] ?? fallback
  const env = {
    llm_model: get('LLM_MODEL', 'claude-sonnet-4-6'),
    llm_provider: get('LLM_PROVIDER', 'auto'),
    pipeline_root: PIPELINE_ROOT,
    python_bin: process.env.PYTHON_BIN ?? dotEnv['PYTHON_BIN'] ?? 'python3',
  }
  return Response.json({ settings, env })
}

export async function PUT(request: Request) {
  try {
    const body = (await request.json()) as Partial<AppSettings>
    const current = readSettings()
    const updated: AppSettings = {
      assembly: { ...current.assembly, ...(body.assembly ?? {}) },
      pipeline: { ...current.pipeline, ...(body.pipeline ?? {}) },
    }
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(updated, null, 2))
    return Response.json(updated)
  } catch (err) {
    return Response.json({ error: String(err) }, { status: 500 })
  }
}
