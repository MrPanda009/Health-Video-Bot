'use client'

import useSWR from 'swr'
import type { Topic, TopicStats } from '@/lib/types'

const fetcher = (url: string) => fetch(url).then((r) => r.json())

export function useTopics() {
  const { data, error, mutate, isLoading } = useSWR<{ topics: Topic[]; stats: TopicStats }>(
    '/api/topics',
    fetcher,
  )
  return {
    topics: data?.topics ?? [],
    stats: data?.stats ?? null,
    isLoading,
    error,
    mutate,
  }
}
