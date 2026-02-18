import { CheckCircle2, Circle, Loader2, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ProgressEvent, PipelineStatus } from '@/hooks/usePipeline'

const STEPS = [
  { id: 1, label: 'Scraping Apollo', desc: 'Extraction des leads via Playwright' },
  { id: 2, label: 'Enrichissement Google', desc: 'LinkedIn URL + site web' },
  { id: 3, label: 'Dropcontact', desc: 'Email pro + téléphone' },
  { id: 4, label: 'Calcul du hit score', desc: 'Score 0-100, seuil 50' },
  { id: 5, label: 'Enrichissement IA', desc: 'GPT-4o-mini (leads hit uniquement)' },
]

// Map logged step numbers (which use combined 3a/3b) to display steps
function mapApiStepToDisplay(apiStep: number): number {
  // API step 3 covers both 3a (Google) and 3b (Dropcontact) → display steps 2 & 3
  if (apiStep <= 2) return apiStep
  if (apiStep === 3) return 3 // show as step 3 (Dropcontact), Google is step 2
  if (apiStep === 4) return 4
  return 5
}

interface Props {
  status: PipelineStatus
  latestEvent: ProgressEvent | null
  events: ProgressEvent[]
  jobId: string | null
  error: string | null
}

export function PipelineProgress({ status, latestEvent, events, error }: Props) {
  const currentDisplayStep = latestEvent ? mapApiStepToDisplay(latestEvent.step) : 0
  const totalProgress = latestEvent?.total_progress ?? 0

  return (
    <div className="w-full max-w-2xl mx-auto space-y-6">
      {/* Overall progress bar */}
      <div>
        <div className="flex justify-between text-sm mb-2">
          <span className="font-medium text-gray-700">
            {status === 'done' ? 'Pipeline terminé ✓' : status === 'error' ? 'Erreur' : 'Pipeline en cours...'}
          </span>
          <span className="text-gray-500 font-mono text-xs">
            {status === 'done' ? '100%' : `${Math.round(totalProgress * 100)}%`}
          </span>
        </div>
        <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
          <div
            className={cn(
              'h-full rounded-full transition-all duration-500',
              status === 'error' ? 'bg-red-500' : status === 'done' ? 'bg-green-500' : 'bg-blue-500'
            )}
            style={{ width: status === 'done' ? '100%' : `${Math.round(totalProgress * 100)}%` }}
          />
        </div>
      </div>

      {/* Error banner */}
      {status === 'error' && error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 flex gap-3">
          <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium text-red-800 text-sm">Erreur pipeline</p>
            <p className="text-red-700 text-sm mt-1">{error}</p>
          </div>
        </div>
      )}

      {/* Steps */}
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm divide-y divide-gray-100">
        {STEPS.map((step, idx) => {
          const isCompleted = status === 'done' || currentDisplayStep > step.id
          const isActive = status === 'running' && currentDisplayStep === step.id
          const isPending = !isCompleted && !isActive

          return (
            <div key={step.id} className={cn('flex items-start gap-4 px-5 py-4', isActive && 'bg-blue-50/50')}>
              {/* Step icon */}
              <div className="shrink-0 mt-0.5">
                {isCompleted ? (
                  <CheckCircle2 className="w-5 h-5 text-green-500" />
                ) : isActive ? (
                  <Loader2 className="w-5 h-5 text-blue-600 animate-spin" />
                ) : (
                  <Circle className={cn('w-5 h-5', isPending ? 'text-gray-300' : 'text-gray-400')} />
                )}
              </div>

              {/* Step content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className={cn(
                    'text-sm font-medium',
                    isCompleted ? 'text-green-700' : isActive ? 'text-blue-700' : 'text-gray-400'
                  )}>
                    {step.label}
                  </span>
                  <span className="text-xs text-gray-400">#{idx + 1}</span>
                </div>
                <p className="text-xs text-gray-500 mt-0.5">{step.desc}</p>

                {/* Live message for active step */}
                {isActive && latestEvent?.message && (
                  <p className="mt-1.5 text-xs text-blue-600 font-mono truncate">
                    {latestEvent.message}
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Log tail */}
      {events.length > 0 && (
        <div className="bg-gray-900 rounded-xl p-4 max-h-48 overflow-y-auto">
          <p className="text-xs text-gray-500 mb-2 font-mono uppercase tracking-wider">Logs</p>
          <div className="space-y-1">
            {events.slice(-20).map((evt, i) => (
              <p key={i} className="text-xs font-mono text-gray-300 leading-relaxed">
                <span className="text-gray-500">[Step {evt.step}]</span>{' '}
                {evt.message}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
