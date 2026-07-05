'use client'

import { useCallback, useRef, useState } from 'react'
import useSWR from 'swr'
import {
  Bell,
  CheckCircle2,
  ChevronDown,
  Clapperboard,
  Cpu,
  Info,
  Loader2,
  Sliders,
  Sparkles,
} from 'lucide-react'
import { useSettings } from '@/hooks/useSettings'
import type { SettingsPatch } from '@/hooks/useSettings'
import type { AppSettings, AssemblySettings, AudioSettings, PipelineSettings } from '@/lib/types'
import { LLM_PROVIDERS } from '@/lib/types'

const audioFetcher = (url: string) =>
  fetch(url).then((r) => r.json() as Promise<{ files: string[] }>)

// ─── Primitives ───────────────────────────────────────────────────────────────

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      role="switch"
      aria-checked={value}
      onClick={() => onChange(!value)}
      className={[
        'relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors',
        value ? 'bg-blue-600' : 'bg-zinc-200 dark:bg-zinc-700',
      ].join(' ')}
    >
      <span
        className={[
          'inline-block h-4 w-4 rounded-full bg-white shadow transition-transform',
          value ? 'translate-x-6' : 'translate-x-1',
        ].join(' ')}
      />
    </button>
  )
}

function Select<T extends string>({
  value,
  onChange,
  options,
  disabled,
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string; description?: string }[]
  disabled?: boolean
}) {
  return (
    <div className="relative">
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as T)}
        className={[
          'w-full appearance-none rounded-lg border px-3 py-2 pr-8 text-sm',
          'border-zinc-300 bg-white text-zinc-900',
          'dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100',
          'focus:outline-none focus:ring-2 focus:ring-blue-500',
          'disabled:cursor-not-allowed disabled:opacity-40',
        ].join(' ')}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown
        size={14}
        className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-400"
      />
    </div>
  )
}

function RangeSlider({
  value,
  min,
  max,
  step,
  onChange,
  onCommit,
  disabled,
  format,
}: {
  value: number
  min: number
  max: number
  step: number
  onChange: (v: number) => void
  onCommit?: (v: number) => void
  disabled?: boolean
  format?: (v: number) => string
}) {
  const pct = ((value - min) / (max - min)) * 100
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        onMouseUp={(e) => onCommit?.(parseFloat((e.target as HTMLInputElement).value))}
        onTouchEnd={(e) => onCommit?.(parseFloat((e.target as HTMLInputElement).value))}
        onBlur={(e) => onCommit?.(parseFloat(e.target.value))}
        style={{ '--pct': `${pct}%` } as React.CSSProperties}
        className={[
          'h-1.5 w-full cursor-pointer appearance-none rounded-full',
          'bg-gradient-to-r from-blue-500 to-blue-500 bg-[length:var(--pct)_100%]',
          'bg-no-repeat',
          '[background-image:linear-gradient(#3b82f6,#3b82f6)]',
          '[background-size:var(--pct)_100%]',
          'bg-zinc-200 dark:bg-zinc-700',
          'disabled:cursor-not-allowed disabled:opacity-40',
          '[&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4',
          '[&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full',
          '[&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:shadow-md',
          '[&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-zinc-300',
        ].join(' ')}
      />
      <span className="w-12 shrink-0 text-right font-mono text-sm text-zinc-600 dark:text-zinc-400">
        {format ? format(value) : value}
      </span>
    </div>
  )
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

function Section({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: React.ElementType
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-2xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-start gap-3 border-b border-zinc-100 px-5 py-4 dark:border-zinc-800">
        <div className="mt-0.5 rounded-lg bg-zinc-100 p-1.5 dark:bg-zinc-800">
          <Icon size={16} className="text-zinc-600 dark:text-zinc-400" />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{title}</h2>
          <p className="mt-0.5 text-xs text-zinc-500">{description}</p>
        </div>
      </div>
      <div className="divide-y divide-zinc-100 dark:divide-zinc-800">{children}</div>
    </section>
  )
}

function SettingRow({
  label,
  description,
  control,
  indent,
}: {
  label: string
  description?: string
  control: React.ReactNode
  indent?: boolean
}) {
  return (
    <div
      className={[
        'flex items-center justify-between gap-6 px-5 py-4',
        indent ? 'bg-zinc-50/60 dark:bg-zinc-950/30' : '',
      ].join(' ')}
    >
      <div className={indent ? 'ml-6' : ''}>
        <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{label}</p>
        {description && (
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{description}</p>
        )}
      </div>
      <div className="shrink-0">{control}</div>
    </div>
  )
}

function SettingRowWide({
  label,
  description,
  children,
  indent,
}: {
  label: string
  description?: string
  children: React.ReactNode
  indent?: boolean
}) {
  return (
    <div
      className={[
        'px-5 py-4',
        indent ? 'bg-zinc-50/60 dark:bg-zinc-950/30' : '',
      ].join(' ')}
    >
      <div className={indent ? 'ml-6' : ''}>
        <p className="mb-2 text-sm font-medium text-zinc-800 dark:text-zinc-200">{label}</p>
        {description && (
          <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">{description}</p>
        )}
        {children}
      </div>
    </div>
  )
}

// ─── Animation preview cards ──────────────────────────────────────────────────

const ANIMATION_OPTIONS = [
  {
    value: 'ken_burns' as const,
    label: 'Ken Burns',
    description: 'Slow zoom-in toward center (1.0× → 1.15×) via Remotion interpolation. Classic documentary look.',
  },
  {
    value: 'slide_in' as const,
    label: 'Slide In',
    description: 'Slides in from the right (0.3 s), holds, then exits left. Good for factual beats.',
  },
  {
    value: 'zoom_punch' as const,
    label: 'Zoom Punch',
    description: 'Grows from 95% to 105% over the clip. Adds subtle energy without distraction.',
  },
]

// ─── Page ─────────────────────────────────────────────────────────────────────

type SettingsOverrides = {
  assembly?: Partial<AssemblySettings>
  pipeline?: Partial<PipelineSettings>
  audio?: Partial<AudioSettings>
}

export default function SettingsPage() {
  const { settings, env, isLoading, fetchError, saveSettings } = useSettings()
  const { data: audioData } = useSWR('/api/audio', audioFetcher, { revalidateOnFocus: false })

  // Track only user-made overrides on top of server state — avoids setState-in-effect
  const [overrides, setOverrides] = useState<SettingsOverrides>({})
  // LLM provider/model live in .env (not settings.json) — tracked separately.
  const [envOverrides, setEnvOverrides] = useState<{ provider?: string; model?: string }>({})
  const [keyDraft, setKeyDraft] = useState('')
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved'>('idle')
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Derived merged view — cast is safe because settings provides all required fields
  const local: AppSettings | null = settings
    ? {
        assembly: { ...settings.assembly, ...(overrides.assembly ?? {}) } as AssemblySettings,
        pipeline: { ...settings.pipeline, ...(overrides.pipeline ?? {}) } as PipelineSettings,
        audio: { ...settings.audio, ...(overrides.audio ?? {}) } as AudioSettings,
      }
    : null

  const triggerSave = useCallback(
    async (patch: SettingsPatch) => {
      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = setTimeout(async () => {
        setSaveState('saving')
        const result = await saveSettings(patch)
        if (result) {
          setSaveState('saved')
          setTimeout(() => setSaveState('idle'), 1800)
        } else {
          setSaveState('idle')
        }
      }, 350)
    },
    [saveSettings],
  )

  function patchAssembly(patch: Partial<AssemblySettings>) {
    setOverrides((prev: SettingsOverrides) => ({ ...prev, assembly: { ...(prev.assembly ?? {}), ...patch } }))
    triggerSave({ assembly: patch })
  }

  function patchPipeline(patch: Partial<PipelineSettings>) {
    setOverrides((prev: SettingsOverrides) => ({ ...prev, pipeline: { ...(prev.pipeline ?? {}), ...patch } }))
    triggerSave({ pipeline: patch })
  }

  function patchAudio(patch: Partial<AudioSettings>) {
    setOverrides((prev: SettingsOverrides) => ({ ...prev, audio: { ...(prev.audio ?? {}), ...patch } }))
    triggerSave({ audio: patch })
  }

  // Always send provider + model together (idempotent) so a debounced save never
  // drops one for the other. `keys` is included only when committing an API key.
  function patchEnv(
    next: { provider?: string; model?: string },
    keyPatch?: Record<string, string>,
  ) {
    const provider = next.provider ?? envOverrides.provider ?? env?.llm_provider ?? 'auto'
    const model = next.model ?? envOverrides.model ?? env?.llm_model ?? ''
    setEnvOverrides((prev) => ({ ...prev, ...next }))
    triggerSave({
      env: { LLM_PROVIDER: provider, LLM_MODEL: model, ...(keyPatch ? { keys: keyPatch } : {}) },
    })
  }

  if (isLoading || !local) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-50 dark:bg-zinc-950">
        <Loader2 size={24} className="animate-spin text-zinc-400" />
      </div>
    )
  }

  if (fetchError) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16">
        <p className="text-sm text-red-500">Failed to load settings: {fetchError}</p>
      </div>
    )
  }

  const a = local.assembly
  const p = local.pipeline
  const aud = local.audio

  // Audio file options — ensure the currently-selected values appear even if the
  // file list hasn't loaded yet (or the file was removed from assets/music/).
  const audioFiles = audioData?.files ?? []
  const audioOptions = (current: string) =>
    Array.from(new Set([...(current ? [current] : []), ...audioFiles])).map((f) => ({
      value: f,
      label: f,
    }))

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <div className="mx-auto max-w-2xl px-4 py-10">

        {/* Header */}
        <div className="mb-8 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">Settings</h1>
            <p className="mt-1 text-sm text-zinc-500">
              Global defaults for the video pipeline. Changes save automatically.
            </p>
          </div>
          <div className="flex h-8 items-center gap-1.5 text-xs font-medium">
            {saveState === 'saving' && (
              <span className="flex items-center gap-1 text-zinc-400">
                <Loader2 size={12} className="animate-spin" /> Saving…
              </span>
            )}
            {saveState === 'saved' && (
              <span className="flex items-center gap-1 text-green-600 dark:text-green-400">
                <CheckCircle2 size={12} /> Saved
              </span>
            )}
          </div>
        </div>

        <div className="space-y-6">

          {/* ── Video Assembly ───────────────────────────────────────────────── */}
          <Section
            icon={Sparkles}
            title="Video Assembly"
            description="Animations and transitions applied by Remotion in stage 5 and video_assembler.py"
          >
            {/* Animations toggle */}
            <SettingRow
              label="Image animations"
              description="Animate still images (.jpg, .png) placed in B-roll slots"
              control={
                <Toggle
                  value={a.animations_enabled}
                  onChange={(v) => patchAssembly({ animations_enabled: v })}
                />
              }
            />

            {/* Animation type */}
            <SettingRowWide
              label="Animation style"
              description={
                ANIMATION_OPTIONS.find((o) => o.value === a.animation_type)?.description
              }
              indent
            >
              <div className="grid grid-cols-3 gap-2">
                {ANIMATION_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    disabled={!a.animations_enabled}
                    onClick={() => patchAssembly({ animation_type: opt.value })}
                    className={[
                      'rounded-xl border px-3 py-2.5 text-left text-xs font-medium transition-colors',
                      'disabled:cursor-not-allowed disabled:opacity-40',
                      a.animation_type === opt.value
                        ? 'border-blue-400 bg-blue-50 text-blue-700 dark:border-blue-600 dark:bg-blue-950/40 dark:text-blue-300'
                        : 'border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-750',
                    ].join(' ')}
                  >
                    {opt.label}
                    {a.animation_type === opt.value && (
                      <span className="ml-1 text-blue-500 dark:text-blue-400">✓</span>
                    )}
                  </button>
                ))}
              </div>
            </SettingRowWide>

            {/* Transitions toggle */}
            <SettingRow
              label="Clip transitions"
              description="Apply crossfade between consecutive B-roll clips"
              control={
                <Toggle
                  value={a.transitions_enabled}
                  onChange={(v) => patchAssembly({ transitions_enabled: v })}
                />
              }
            />

            {/* Transition type */}
            <SettingRow
              label="Transition style"
              indent
              control={
                <div className="w-40">
                  <Select
                    value={a.transition_type}
                    onChange={(v) => patchAssembly({ transition_type: v })}
                    disabled={!a.transitions_enabled}
                    options={[{ value: 'crossfade', label: 'Crossfade' }]}
                  />
                </div>
              }
            />

            {/* Transition duration */}
            <SettingRowWide
              label="Transition duration"
              description="Overlap duration for crossfades"
              indent
            >
              <div className={a.transitions_enabled ? '' : 'opacity-40 pointer-events-none'}>
                <RangeSlider
                  value={a.transition_duration}
                  min={0.1}
                  max={1.0}
                  step={0.05}
                  onChange={(v) =>
                    setOverrides((prev: SettingsOverrides) => ({
                      ...prev,
                      assembly: { ...(prev.assembly ?? {}), transition_duration: v },
                    }))
                  }
                  onCommit={(v) => patchAssembly({ transition_duration: v })}
                  disabled={!a.transitions_enabled}
                  format={(v) => `${v.toFixed(2)}s`}
                />
              </div>
            </SettingRowWide>

            {/* Caption combine ms (page switch speed) */}
            <SettingRowWide
              label="Caption page switch speed"
              description="Max duration in milliseconds for words to stay grouped on screen before switching pages"
            >
              <RangeSlider
                value={a.caption_combine_ms ?? 1500}
                min={500}
                max={3000}
                step={100}
                onChange={(v) =>
                  setOverrides((prev: SettingsOverrides) => ({
                    ...prev,
                    assembly: { ...(prev.assembly ?? {}), caption_combine_ms: v },
                  }))
                }
                onCommit={(v) => patchAssembly({ caption_combine_ms: v })}
                format={(v) => `${v}ms`}
              />
            </SettingRowWide>

            {/* Caption font family */}
            <SettingRow
              label="Caption font"
              description="Font family used for the word-highlighted caption overlay"
              control={
                <div className="w-64">
                  <Select
                    value={a.font_family ?? 'NotoSansDevanagari'}
                    onChange={(v) => patchAssembly({ font_family: v })}
                    options={[
                      { value: 'NotoSansDevanagari', label: 'Noto Sans Devanagari' },
                      { value: 'Poppins', label: 'Poppins (Modern Sans-Serif)' },
                      { value: 'AnekDevanagari', label: 'Anek Devanagari' },
                      { value: 'Mukta', label: 'Mukta' },
                      { value: 'TiroDevanagariHindi', label: 'Tiro Devanagari Hindi' },
                      { value: 'Hind', label: 'Hind' },
                      { value: 'SystemFont', label: 'System Fallback (No Google Font)' },
                    ]}
                  />
                </div>
              }
            />
          </Section>

          {/* ── Subscribe Animation ──────────────────────────────────────────── */}
          <Section
            icon={Bell}
            title="Subscribe Animation"
            description="Sound effects for the end-screen subscribe button (a cursor clicks the bell, then it rings). Files are read from assets/music/."
          >
            <SettingRow
              label="Click sound"
              description="Plays when the cursor clicks the bell"
              control={
                <div className="w-64">
                  <Select
                    value={aud.subscribe_click_sound}
                    onChange={(v) => patchAudio({ subscribe_click_sound: v })}
                    options={audioOptions(aud.subscribe_click_sound)}
                  />
                </div>
              }
            />
            <SettingRow
              label="Bell sound"
              description="Plays ~0.2 s after the click, as the bell rings"
              control={
                <div className="w-64">
                  <Select
                    value={aud.subscribe_bell_sound}
                    onChange={(v) => patchAudio({ subscribe_bell_sound: v })}
                    options={audioOptions(aud.subscribe_bell_sound)}
                  />
                </div>
              }
            />
          </Section>

          {/* ── Pipeline defaults ─────────────────────────────────────────────── */}
          <Section
            icon={Clapperboard}
            title="Pipeline Defaults"
            description="Default values used when creating or running jobs from the dashboard"
          >
            {/* Default render mode */}
            <SettingRow
              label="Default render mode"
              description="Draft skips quality gate and uses faster settings in Stage 5"
              control={
                <div className="flex overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-700">
                  {(['draft', 'final'] as const).map((mode) => (
                    <button
                      key={mode}
                      onClick={() => patchPipeline({ default_render_mode: mode })}
                      className={[
                        'px-3 py-1.5 text-xs font-medium capitalize transition-colors',
                        p.default_render_mode === mode
                          ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
                          : 'bg-white text-zinc-600 hover:bg-zinc-50 dark:bg-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800',
                      ].join(' ')}
                    >
                      {mode}
                    </button>
                  ))}
                </div>
              }
            />

            {/* Default whisper model */}
            <SettingRow
              label="Default WhisperX model"
              description="Used by Stage 4d (captions) when not explicitly overridden"
              control={
                <div className="w-44">
                  <Select
                    value={p.default_whisper_model as AssemblySettings['animation_type']}
                    onChange={(v) => patchPipeline({ default_whisper_model: v })}
                    options={[
                      { value: 'large-v2' as never, label: 'large-v2 (recommended)' },
                      { value: 'large-v3' as never, label: 'large-v3' },
                      { value: 'medium' as never, label: 'medium' },
                      { value: 'small' as never, label: 'small (fastest)' },
                    ]}
                  />
                </div>
              }
            />

            {/* Render concurrency — frames Remotion renders in parallel (Stage 5) */}
            {(() => {
              const cpuCount = env?.cpu_count ?? 8
              const autoVal = Math.max(1, Math.floor(cpuCount / 2))
              return (
                <SettingRowWide
                  label="Render concurrency"
                  description={`Frames Remotion renders in parallel in Stage 5. Higher = faster, but uses more CPU and memory. Detected ${cpuCount} cores — “Auto” uses ${autoVal} (half). Drag to 0 for Auto.`}
                >
                  <RangeSlider
                    value={p.render_concurrency}
                    min={0}
                    max={cpuCount}
                    step={1}
                    onChange={(v) =>
                      setOverrides((prev: SettingsOverrides) => ({
                        ...prev,
                        pipeline: { ...(prev.pipeline ?? {}), render_concurrency: v },
                      }))
                    }
                    onCommit={(v) => patchPipeline({ render_concurrency: v })}
                    format={(v) => (v === 0 ? 'Auto' : String(v))}
                  />
                </SettingRowWide>
              )
            })()}
          </Section>

          {/* ── LLM Provider ─────────────────────────────────────────────────── */}
          {env && (() => {
            const provider = envOverrides.provider ?? env.llm_provider
            const model = envOverrides.model ?? env.llm_model
            const meta = LLM_PROVIDERS.find((p) => p.id === provider) ?? LLM_PROVIDERS[0]
            const keyEnv = meta.keyEnv
            const keyIsSet = keyEnv ? Boolean(env.keys?.[keyEnv]) : false
            const inputClasses = [
              'w-full rounded-lg border px-3 py-2 text-sm',
              'border-zinc-300 bg-white text-zinc-900',
              'dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100',
              'focus:outline-none focus:ring-2 focus:ring-blue-500',
            ].join(' ')
            return (
              <Section
                icon={Cpu}
                title="LLM Provider"
                description="Used by Stage 2 (claim extraction) and Stage 3 (content generation). Written to .env — applies on the next stage run."
              >
                <SettingRow
                  label="Provider"
                  description="Groq, NVIDIA, and OpenRouter are OpenAI-compatible. Auto resolves claude* → Anthropic, else OpenAI."
                  control={
                    <div className="w-44">
                      <Select
                        value={provider}
                        onChange={(v) => {
                          setKeyDraft('')
                          patchEnv({ provider: v })
                        }}
                        options={LLM_PROVIDERS.map((p) => ({ value: p.id, label: p.label }))}
                      />
                    </div>
                  }
                />
                <SettingRowWide
                  label="Model"
                  description="Exact model id for the selected provider"
                  indent
                >
                  <input
                    type="text"
                    value={model}
                    placeholder={meta.placeholder}
                    spellCheck={false}
                    onChange={(e) => patchEnv({ model: e.target.value })}
                    className={`${inputClasses} font-mono`}
                  />
                </SettingRowWide>
                {keyEnv && (
                  <SettingRowWide
                    label={`${meta.label} API key`}
                    description={
                      keyIsSet
                        ? `${keyEnv} is set. Enter a new value to replace it; leave blank to keep the current key.`
                        : `${keyEnv} is not set. Paste the key to enable this provider.`
                    }
                    indent
                  >
                    <input
                      type="password"
                      value={keyDraft}
                      placeholder={keyIsSet ? '•••••••• set' : 'sk-…'}
                      autoComplete="off"
                      spellCheck={false}
                      onChange={(e) => setKeyDraft(e.target.value)}
                      onBlur={() => {
                        if (keyEnv && keyDraft.trim()) {
                          patchEnv({}, { [keyEnv]: keyDraft })
                          setKeyDraft('')
                        }
                      }}
                      className={`${inputClasses} font-mono`}
                    />
                  </SettingRowWide>
                )}
              </Section>
            )
          })()}

          {/* ── Environment info ─────────────────────────────────────────────── */}
          {env && (
            <Section
              icon={Info}
              title="Environment"
              description="Read from environment variables — edit .env to change these"
            >
              {[
                ['PYTHON_BIN', env.python_bin],
                ['PIPELINE_ROOT', env.pipeline_root],
              ].map(([key, val]) => (
                <SettingRow
                  key={key}
                  label={key}
                  control={
                    <span className="max-w-64 truncate rounded-md bg-zinc-100 px-2 py-1 font-mono text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                      {val}
                    </span>
                  }
                />
              ))}
            </Section>
          )}

          {/* ── CLI reference ─────────────────────────────────────────────────── */}
          <Section
            icon={Sliders}
            title="CLI Reference"
            description="These settings are passed as flags to stage 5 and video_assembler.py (both use Remotion)"
          >
            <div className="px-5 py-4 space-y-4">
              <div>
                <p className="mb-2 text-xs font-medium text-zinc-500 uppercase tracking-wide">
                  Stage 5 (via dashboard or CLI)
                </p>
                <pre className="overflow-x-auto rounded-lg bg-zinc-950 px-4 py-3 font-mono text-xs leading-5 text-zinc-300">
                  <span className="text-zinc-500"># With current settings</span>
                  {'\n'}python stages/stage_5_assembly.py [job_id] \
                  {'\n'}  {a.transitions_enabled
                    ? `--transition-type ${a.transition_type} --transition-duration ${a.transition_duration.toFixed(2)}`
                    : '--transition-type none'} \
                  {'\n'}  {a.animations_enabled
                    ? `--animation-type ${a.animation_type}`
                    : '--animation-type none'} \
                  {'\n'}  --caption-combine-ms {a.caption_combine_ms ?? 1500} \
                  {'\n'}  --font-family {a.font_family ?? 'NotoSansDevanagari'}{p.render_concurrency > 0 ? ` \\\n  --concurrency ${p.render_concurrency}` : ''}
                </pre>
              </div>
              <div>
                <p className="mb-2 text-xs font-medium text-zinc-500 uppercase tracking-wide">
                  Standalone EDL assembler
                </p>
                <pre className="overflow-x-auto rounded-lg bg-zinc-950 px-4 py-3 font-mono text-xs leading-5 text-zinc-300">
                  <span className="text-zinc-500"># With current settings</span>
                  {'\n'}python video_assembler.py base.mp4 edl.json output.mp4 \
                  {'\n'}  {a.transitions_enabled
                    ? `--transition-type ${a.transition_type} --transition-duration ${a.transition_duration.toFixed(2)}`
                    : '--transition-type none'} \
                  {'\n'}  {a.animations_enabled
                    ? `--animation-type ${a.animation_type}`
                    : '--animation-type none'}
                </pre>
              </div>
            </div>
          </Section>

        </div>
      </div>
    </div>
  )
}
