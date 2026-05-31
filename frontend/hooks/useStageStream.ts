'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { StageKey, StageStreamEvent } from '@/lib/types'

export interface StreamParams {
  topic?: string
  pmid?: string
}

export function useStageStream(jobId: string) {
  const [activeStage, setActiveStage] = useState<StageKey | null>(null)
  const [lines, setLines] = useState<string[]>([])
  const [isRunning, setIsRunning] = useState(false)
  const [exitCode, setExitCode] = useState<number | null>(null)
  const esRef = useRef<EventSource | null>(null)

  const stop = useCallback(() => {
    esRef.current?.close()
    esRef.current = null
    setIsRunning(false)
  }, [])

  const clear = useCallback(() => {
    esRef.current?.close()
    esRef.current = null
    setActiveStage(null)
    setLines([])
    setIsRunning(false)
    setExitCode(null)
  }, [])

  const start = useCallback(
    (stage: StageKey, params?: StreamParams) => {
      esRef.current?.close()

      const qs = new URLSearchParams()
      if (params?.topic) qs.set('topic', params.topic)
      if (params?.pmid) qs.set('pmid', params.pmid)

      const url = `/api/jobs/${jobId}/stage/${stage}/stream?${qs.toString()}`
      const es = new EventSource(url)
      esRef.current = es

      setActiveStage(stage)
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
    [jobId],
  )

  useEffect(() => {
    return () => {
      esRef.current?.close()
    }
  }, [])

  return { activeStage, lines, isRunning, exitCode, start, stop, clear }
}
