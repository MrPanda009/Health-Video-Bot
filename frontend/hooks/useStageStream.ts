'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { StageKey, StageStreamEvent } from '@/lib/types'

/**
 * Merge an incoming chunk into the line buffer, honouring carriage returns.
 *
 * \r without a following \n means "go back to start of the current line" —
 * the standard trick used by tqdm, MoviePy's progress bar, and wget-style
 * downloaders to overwrite a single line in place.
 *
 * The buffer is an array of strings where every element except the last ends
 * with \n.  The last element is the "current line" still being written.
 */
function applyChunk(prev: string[], chunk: string): string[] {
  const lines = [...prev]
  // Pop the current (partial) line so we can append to it
  let current = lines.length > 0 ? lines.pop()! : ''

  // Split on \r\n, \n, or bare \r — keeping the separators as tokens
  const parts = chunk.split(/(\r\n|\n|\r)/)

  for (const part of parts) {
    if (part === '\r\n' || part === '\n') {
      lines.push(current + part)
      current = ''
    } else if (part === '\r') {
      current = '' // overwrite current line from the beginning
    } else {
      current += part
    }
  }

  lines.push(current)
  return lines
}

export interface StreamParams {
  topic?: string
  pmid?: string
}

export function useStageStream(jobId: string) {
  const [activeStage, setActiveStage] = useState<StageKey | null>(null)
  const [lines, setLines] = useState<string[]>([])
  const [isRunning, setIsRunning] = useState(false)
  const [exitCode, setExitCode] = useState<number | null>(null)
  const [awaitingInput, setAwaitingInput] = useState(false)
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
    setAwaitingInput(false)
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
      setAwaitingInput(false)

      es.onmessage = (e) => {
        const event: StageStreamEvent = JSON.parse(e.data)
        if (event.type === 'stdout' || event.type === 'stderr') {
          setLines((prev) => applyChunk(prev, event.data))
        } else if (event.type === 'awaiting_input') {
          setAwaitingInput(true)
        } else if (event.type === 'exit') {
          setExitCode(event.exitCode ?? -1)
          setIsRunning(false)
          setAwaitingInput(false)
          es.close()
          esRef.current = null
        } else if (event.type === 'error') {
          setLines((prev) => [...prev, `\x1b[31mERROR: ${event.data}\x1b[0m\n`])
          setIsRunning(false)
          setAwaitingInput(false)
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

  const sendInput = useCallback(
    async (data: string) => {
      setAwaitingInput(false)
      await fetch(`/api/jobs/${jobId}/stdin`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data }),
      })
    },
    [jobId],
  )

  return { activeStage, lines, isRunning, exitCode, awaitingInput, start, stop, clear, sendInput }
}
