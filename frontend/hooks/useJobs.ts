'use client'

import useSWR from 'swr'
import type { JobSummary } from '@/lib/types'

const fetcher = (url: string) => fetch(url).then((r) => r.json())

export function useJobs() {
  const { data, error, mutate, isLoading } = useSWR<{ jobs: JobSummary[] }>(
    '/api/jobs',
    fetcher,
    { refreshInterval: 3000 },
  )
  return {
    jobs: data?.jobs ?? [],
    isLoading,
    error,
    mutate,
  }
}
