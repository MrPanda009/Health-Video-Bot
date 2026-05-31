import { AlertCircle } from 'lucide-react'
import type { JobError } from '@/lib/types'

export function ErrorBanner({ error }: { error: JobError }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-950">
      <AlertCircle className="mt-0.5 shrink-0 text-red-500" size={18} />
      <div className="min-w-0">
        <p className="text-sm font-medium text-red-800 dark:text-red-200">
          Error in {error.stage}
          {error.retries > 0 && (
            <span className="ml-2 text-xs font-normal text-red-600 dark:text-red-400">
              ({error.retries} retries)
            </span>
          )}
        </p>
        <p className="mt-1 break-words text-sm text-red-700 dark:text-red-300">{error.message}</p>
      </div>
    </div>
  )
}
