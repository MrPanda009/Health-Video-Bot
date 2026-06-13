'use client'

import useSWR from 'swr'
import type { AppSettings, AssemblySettings, AudioSettings, PipelineSettings } from '@/lib/types'

export type SettingsPatch = {
  assembly?: Partial<AssemblySettings>
  pipeline?: Partial<PipelineSettings>
  audio?: Partial<AudioSettings>
}

interface SettingsResponse {
  settings: AppSettings
  env: {
    llm_model: string
    llm_provider: string
    pipeline_root: string
    python_bin: string
  }
}

const fetcher = (url: string) => fetch(url).then((r) => r.json())

export function useSettings() {
  const { data, error, isLoading, mutate } = useSWR<SettingsResponse>(
    '/api/settings',
    fetcher,
    { revalidateOnFocus: false },
  )

  async function saveSettings(patch: SettingsPatch): Promise<AppSettings | null> {
    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      if (!res.ok) return null
      const updated: AppSettings = await res.json()
      await mutate(
        (prev) => prev ? { ...prev, settings: updated } : prev,
        { revalidate: false },
      )
      return updated
    } catch {
      return null
    }
  }

  return {
    settings: data?.settings ?? null,
    env: data?.env ?? null,
    isLoading,
    fetchError: error ? String(error) : null,
    saveSettings,
    mutate,
  }
}
