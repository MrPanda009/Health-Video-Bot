'use client'

import useSWR from 'swr'
import type { Job } from '@/lib/types'

const fetcher = (url: string) => fetch(url).then((r) => r.json())

export function useJob(jobId: string, isActive: boolean) {
  const { data, error, mutate, isLoading } = useSWR<{ job: Job }>(
    `/api/jobs/${jobId}`,
    fetcher,
    { refreshInterval: isActive ? 2000 : 10000 },
  )
  return {
    job: data?.job ?? null,
    isLoading,
    error,
    mutate,
  }
}
