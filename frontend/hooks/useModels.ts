'use client'

import useSWR from 'swr'

export interface ModelInfo {
  id: string
  hf_repo: string
  label: string
  type: 'transcription' | 'alignment'
  language?: string
  size_gb: number
  description: string
  downloaded: boolean
}

export interface ModelsData {
  models: ModelInfo[]
  whisperx_installed: boolean
  error?: string
}

const fetcher = (url: string) => fetch(url).then((r) => r.json())

export function useModels() {
  const { data, error, isLoading, mutate } = useSWR<ModelsData>(
    '/api/models',
    fetcher,
    { revalidateOnFocus: false },
  )

  return {
    models: data?.models ?? [],
    whisperxInstalled: data?.whisperx_installed ?? false,
    fetchError: data?.error ?? (error ? String(error) : null),
    isLoading,
    mutate,
  }
}
