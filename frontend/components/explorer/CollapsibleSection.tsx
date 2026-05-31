'use client'

import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { CopyButton } from '@/components/terminal/CopyButton'

interface CollapsibleSectionProps {
  title: string
  data?: unknown
  defaultOpen?: boolean
  children?: React.ReactNode
  empty?: boolean
}

export function CollapsibleSection({
  title,
  data,
  defaultOpen = false,
  children,
  empty = false,
}: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen)

  const jsonText = data !== undefined ? JSON.stringify(data, null, 2) : ''

  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <span className="flex items-center gap-2 text-sm font-medium text-zinc-900 dark:text-zinc-100">
          <ChevronRight
            size={15}
            className={`shrink-0 text-zinc-400 transition-transform ${open ? 'rotate-90' : ''}`}
          />
          {title}
          {empty && (
            <span className="text-xs font-normal text-zinc-400">(not yet populated)</span>
          )}
        </span>
        {!empty && data !== undefined && (
          <CopyButton text={jsonText} className="shrink-0" />
        )}
      </button>
      {open && !empty && (
        <div className="border-t border-zinc-200 dark:border-zinc-800">
          {children ?? (
            <pre className="max-h-80 overflow-auto p-4 font-mono text-xs leading-5 text-zinc-700 dark:text-zinc-300">
              {jsonText}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
