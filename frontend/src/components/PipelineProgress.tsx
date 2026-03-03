import { CheckCircle2, Circle, Loader2, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ProgressEvent, PipelineStatus } from '@/hooks/usePipeline'

const STEPS = [
  { id: 1, label: 'Scraping Apollo',       desc: 'Extraction des leads via Playwright' },
  { id: 2, label: 'Enrichissement Google', desc: 'LinkedIn URL + site web' },
  { id: 3, label: 'Dropcontact',           desc: 'Email pro + téléphone' },
  { id: 4, label: 'Calcul du hit score',   desc: 'Score 0-100, seuil 50' },
  { id: 5, label: 'Enrichissement IA',     desc: 'GPT-4o-mini (leads hit uniquement)' },
]

function mapApiStepToDisplay(apiStep: number, stepProgress: number): number {
  // API steps: 1=setup, 2=scraping Apollo, 3=enrichissement, 4=hit score, 5=IA
  // Display steps: 1=scraping Apollo, 2=Google, 3=Dropcontact, 4=hit score, 5=IA
  if (apiStep <= 1) return 0
  if (apiStep === 2) return 1
  if (apiStep === 3) return stepProgress >= 0.5 ? 3 : 2  // <0.5 = Google, >=0.5 = Dropcontact
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
  const currentDisplayStep = latestEvent ? mapApiStepToDisplay(latestEvent.step, latestEvent.progress) : 0
  const totalProgress = latestEvent?.total_progress ?? 0
  const pct = status === 'done' ? 100 : Math.round(totalProgress * 100)

  return (
    <div className="w-full max-w-2xl mx-auto space-y-5">
      {/* Overall progress */}
      <div className="glass-card" style={{ padding: '20px 24px' }}>
        <div className="flex justify-between text-sm mb-3">
          <span className="font-medium" style={{ color: status === 'error' ? '#f87171' : status === 'done' ? '#34d399' : '#e2e8f8' }}>
            {status === 'done' ? 'Pipeline terminé ✓' : status === 'error' ? 'Erreur' : 'Pipeline en cours…'}
          </span>
          <span className="font-mono text-xs" style={{ color: 'rgba(226,232,248,0.4)' }}>{pct}%</span>
        </div>
        <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${pct}%`,
              background: status === 'error'
                ? '#f87171'
                : status === 'done'
                  ? 'linear-gradient(90deg, #34d399, #4d9fff)'
                  : 'linear-gradient(90deg, #4d9fff, #9b6bff)',
            }}
          />
        </div>
      </div>

      {/* Error banner */}
      {status === 'error' && error && (
        <div className="rounded-xl p-4 flex gap-3" style={{ background: 'rgba(248,113,113,0.06)', border: '1px solid rgba(248,113,113,0.2)' }}>
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" style={{ color: '#f87171' }} />
          <div>
            <p className="font-medium text-sm mb-1" style={{ color: '#fca5a5' }}>Erreur pipeline</p>
            <p className="text-sm" style={{ color: 'rgba(252,165,165,0.7)' }}>{error}</p>
          </div>
        </div>
      )}

      {/* Steps */}
      <div className="glass-card overflow-hidden">
        {STEPS.map((step, idx) => {
          const isCompleted = status === 'done' || currentDisplayStep > step.id
          const isActive    = status === 'running' && currentDisplayStep === step.id
          const isPending   = !isCompleted && !isActive

          return (
            <div
              key={step.id}
              className="flex items-start gap-4 px-5 py-4"
              style={{
                borderBottom: idx < STEPS.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
                background: isActive ? 'rgba(77,159,255,0.04)' : 'transparent',
              }}
            >
              {/* Icon */}
              <div className="shrink-0 mt-0.5">
                {isCompleted ? (
                  <CheckCircle2 className="w-5 h-5" style={{ color: '#34d399' }} />
                ) : isActive ? (
                  <Loader2 className="w-5 h-5 animate-spin" style={{ color: '#4d9fff' }} />
                ) : (
                  <Circle className="w-5 h-5" style={{ color: isPending ? 'rgba(226,232,248,0.12)' : 'rgba(226,232,248,0.25)' }} />
                )}
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className="text-sm font-medium"
                    style={{ color: isCompleted ? '#34d399' : isActive ? '#63a0ff' : 'rgba(226,232,248,0.3)' }}
                  >
                    {step.label}
                  </span>
                  <span className="text-xs font-mono" style={{ color: 'rgba(226,232,248,0.2)' }}>#{idx + 1}</span>
                </div>
                <p className="text-xs mt-0.5" style={{ color: 'rgba(226,232,248,0.3)' }}>{step.desc}</p>
                {isActive && latestEvent?.message && (
                  <p className="mt-1.5 text-xs font-mono truncate" style={{ color: '#4d9fff' }}>
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
        <div
          className="rounded-xl p-4 max-h-48 overflow-y-auto"
          style={{ background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.06)' }}
        >
          <p className="text-xs font-mono mb-2 uppercase tracking-wider" style={{ color: 'rgba(226,232,248,0.2)' }}>Logs</p>
          <div className="space-y-1">
            {events.slice(-20).map((evt, i) => (
              <p key={i} className="text-xs font-mono leading-relaxed" style={{ color: 'rgba(226,232,248,0.5)' }}>
                <span style={{ color: 'rgba(226,232,248,0.25)' }}>[Step {evt.step}]</span>{' '}
                {evt.message}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
