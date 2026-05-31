'use client'

import useSWR from 'swr'
import type { Clip, ClipStats } from '@/lib/types'

const fetcher = (url: string) => fetch(url).then((r) => r.json())

export function useClips(status: string = 'all') {
  const { data, error, mutate, isLoading } = useSWR<{ clips: Clip[]; stats: ClipStats }>(
    `/api/clips?status=${status}`,
    fetcher,
  )
  return {
    clips: data?.clips ?? [],
    stats: data?.stats ?? null,
    isLoading,
    error,
    mutate,
  }
}
