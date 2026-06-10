'use client'

import useSWR from 'swr'
import type { StudyEntry, StudyStats } from '@/lib/types'

const fetcher = (url: string) => fetch(url).then((r) => r.json())

export function useStudies(status: string = 'all') {
  const { data, error, mutate, isLoading } = useSWR<{ studies: StudyEntry[]; stats: StudyStats }>(
    `/api/studies?status=${status}`,
    fetcher,
  )
  return {
    studies: data?.studies ?? [],
    stats: data?.stats ?? null,
    isLoading,
    error,
    mutate,
  }
}
