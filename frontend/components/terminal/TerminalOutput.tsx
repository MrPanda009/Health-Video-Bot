'use client'

import { useEffect, useMemo, useRef } from 'react'
import Convert from 'ansi-to-html'
import { CheckCircle, XCircle } from 'lucide-react'
import { CopyButton } from './CopyButton'

const convert = new Convert({ escapeXML: true })

interface TerminalOutputProps {
  lines: string[]
  isRunning: boolean
  exitCode: number | null
}

export function TerminalOutput({ lines, isRunning, exitCode }: TerminalOutputProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  const plainText = useMemo(() => lines.join(''), [lines])

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950">
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
        <div className="flex items-center gap-2">
          <div className="h-2.5 w-2.5 rounded-full bg-red-500" />
          <div className="h-2.5 w-2.5 rounded-full bg-yellow-500" />
          <div className="h-2.5 w-2.5 rounded-full bg-green-500" />
          <span className="ml-2 text-xs text-zinc-500">Output</span>
        </div>
        <div className="flex items-center gap-2">
          {exitCode !== null && (
            <span className="flex items-center gap-1 text-xs">
              {exitCode === 0 ? (
                <CheckCircle size={13} className="text-green-400" />
              ) : (
                <XCircle size={13} className="text-red-400" />
              )}
              <span className={exitCode === 0 ? 'text-green-400' : 'text-red-400'}>
                exit {exitCode}
              </span>
            </span>
          )}
          {plainText && <CopyButton text={plainText} />}
        </div>
      </div>
      <div className="max-h-96 overflow-y-auto p-3">
        <pre className="font-mono text-xs leading-5 text-zinc-200">
          {lines.map((line, i) => (
            <span
              key={i}
              dangerouslySetInnerHTML={{ __html: convert.toHtml(line) }}
            />
          ))}
          {isRunning && <span className="animate-pulse text-zinc-400">▋</span>}
          {lines.length === 0 && !isRunning && (
            <span className="text-zinc-600">No output yet.</span>
          )}
        </pre>
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
