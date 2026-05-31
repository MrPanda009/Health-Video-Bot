'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { StageKey, StageStreamEvent } from '@/lib/types'

export interface StreamParams {
  topic?: string
  pmid?: string
}

export function useStageStream(jobId: string, stage: StageKey | null) {
  const [lines, setLines] = useState<string[]>([])
  const [isRunning, setIsRunning] = useState(false)
  const [exitCode, setExitCode] = useState<number | null>(null)
  const esRef = useRef<EventSource | null>(null)

  const stop = useCallback(() => {
    esRef.current?.close()
    esRef.current = null
    setIsRunning(false)
  }, [])

  const start = useCallback(
    (params?: StreamParams) => {
      if (!stage) return
      esRef.current?.close()

      const qs = new URLSearchParams()
      if (params?.topic) qs.set('topic', params.topic)
      if (params?.pmid) qs.set('pmid', params.pmid)

      const url = `/api/jobs/${jobId}/stage/${stage}/stream?${qs.toString()}`
      const es = new EventSource(url)
      esRef.current = es
      setLines([])
      setIsRunning(true)
      setExitCode(null)

      es.onmessage = (e) => {
        const event: StageStreamEvent = JSON.parse(e.data)
        if (event.type === 'stdout' || event.type === 'stderr') {
          setLines((prev) => [...prev, event.data])
        } else if (event.type === 'exit') {
          setExitCode(event.exitCode ?? -1)
          setIsRunning(false)
          es.close()
          esRef.current = null
        } else if (event.type === 'error') {
          setLines((prev) => [...prev, `\x1b[31mERROR: ${event.data}\x1b[0m\n`])
          setIsRunning(false)
          es.close()
          esRef.current = null
        }
      }

      es.onerror = () => {
        setIsRunning(false)
        es.close()
        esRef.current = null
      }
    },
    [jobId, stage],
  )

  useEffect(() => {
    return () => {
      esRef.current?.close()
    }
  }, [])

  return { lines, isRunning, exitCode, start, stop }
}
