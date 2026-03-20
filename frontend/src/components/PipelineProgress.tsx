import { CheckCircle2, Circle, Loader2, AlertCircle, XCircle } from 'lucide-react'

import type { ProgressEvent, PipelineStatus } from '@/hooks/usePipeline'

const STEPS = [
  { id: 1, label: 'Scraping Apollo',       desc: 'Extraction des leads via Playwright' },
  { id: 2, label: 'Enrichissement Google', desc: 'LinkedIn URL + site web' },
  { id: 3, label: 'Dropcontact',           desc: 'Email pro + téléphone' },
  { id: 4, label: 'Calcul du hit score',   desc: 'Score 0-100, seuil 50' },
  { id: 5, label: 'Scoring ICP',           desc: 'Profil client idéal (Claude AI)' },
  { id: 6, label: 'Enrichissement IA',     desc: 'Claude AI — résumé, angle de conversion' },
  { id: 7, label: 'Perplexity',            desc: 'Maturité digitale, budget, signaux' },
]

function mapApiStepToDisplay(apiStep: number, stepProgress: number): number {
  if (apiStep <= 1) return 0
  if (apiStep === 2) return 1
  if (apiStep === 3) return stepProgress >= 0.5 ? 3 : 2
  if (apiStep === 4) return 4
  if (apiStep === 5) return 5
  if (apiStep === 6) return 6
  return 7
}

function formatEta(ms: number): string {
  if (ms < 60000) return `~${Math.max(1, Math.round(ms / 1000))}s`
  const min = Math.floor(ms / 60000)
  const sec = Math.round((ms % 60000) / 1000)
  return `~${min}m ${sec}s`
}

interface Props {
  status: PipelineStatus
  latestEvent: ProgressEvent | null
  events: ProgressEvent[]
  jobId: string | null
  error: string | null
  startedAt?: number | null
  onCancel?: () => void
}

export function PipelineProgress({ status, latestEvent, events, error, startedAt, onCancel }: Props) {
  const currentDisplayStep = latestEvent ? mapApiStepToDisplay(latestEvent.step, latestEvent.progress) : 0
  const totalProgress = latestEvent?.total_progress ?? 0
  const pct = status === 'done' ? 100 : Math.round(totalProgress * 100)

  // ETA calculation
  let etaStr: string | null = null
  if (status === 'running' && startedAt && totalProgress > 0.05) {
    const elapsed = Date.now() - startedAt
    const remaining = (elapsed / totalProgress) * (1 - totalProgress)
    etaStr = formatEta(remaining)
  }

  return (
    <div className="w-full max-w-2xl mx-auto space-y-5">
      {/* Overall progress */}
      <div className="glass-card" style={{ padding: '20px 24px' }}>
        <div className="flex justify-between text-sm mb-3">
          <span className="font-medium" style={{ color: status === 'error' ? 'var(--th-error)' : status === 'done' ? 'var(--th-success)' : 'var(--th-text-primary)' }}>
            {status === 'done' ? 'Pipeline terminé ✓' : status === 'error' ? 'Erreur' : 'Pipeline en cours…'}
          </span>
          <div className="flex items-center gap-3">
            {etaStr && (
              <span className="text-xs" style={{ color: 'var(--th-text-muted)' }}>{etaStr} restantes</span>
            )}
            <span className="font-mono text-xs" style={{ color: 'var(--th-text-quaternary)' }}>{pct}%</span>
          </div>
        </div>
        <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--th-border-default)' }}>
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${pct}%`,
              background: status === 'error'
                ? 'var(--th-error)'
                : status === 'done'
                  ? 'linear-gradient(90deg, #34d399, #4d9fff)'
                  : 'linear-gradient(90deg, #4d9fff, #9b6bff)',
            }}
          />
        </div>
        {/* Cancel button */}
        {status === 'running' && onCancel && (
          <button
            onClick={() => { if (confirm('Annuler le pipeline en cours ?')) onCancel() }}
            className="flex items-center gap-1.5 text-xs font-medium mt-3 px-3 py-1.5 rounded-lg transition-all"
            style={{ color: 'var(--th-error)', background: 'var(--th-error-soft)', border: '1px solid var(--th-error-border)', cursor: 'pointer', fontFamily: 'inherit' }}
          >
            <XCircle className="w-3.5 h-3.5" />
            Annuler le pipeline
          </button>
        )}
      </div>

      {/* Error banner */}
      {status === 'error' && error && (
        <div className="rounded-xl p-4 flex gap-3" style={{ background: 'var(--th-error-soft)', border: '1px solid var(--th-error-border)' }}>
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" style={{ color: 'var(--th-error)' }} />
          <div>
            <p className="font-medium text-sm mb-1" style={{ color: 'var(--th-error)' }}>Erreur pipeline</p>
            <p className="text-sm" style={{ color: 'var(--th-text-secondary)' }}>{error}</p>
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
              className="flex items-start gap-4 px-5 py-4 transition-all duration-300"
              style={{
                borderBottom: idx < STEPS.length - 1 ? '1px solid var(--th-border-subtle)' : 'none',
                background: isActive ? 'var(--th-primary-soft)' : 'transparent',
              }}
            >
              <div className="shrink-0 mt-0.5">
                {isCompleted ? (
                  <CheckCircle2 className="w-5 h-5" style={{ color: 'var(--th-success)' }} />
                ) : isActive ? (
                  <Loader2 className="w-5 h-5 animate-spin" style={{ color: 'var(--th-primary)' }} />
                ) : (
                  <Circle className="w-5 h-5" style={{ color: isPending ? 'var(--th-text-ghost)' : 'var(--th-text-faint)' }} />
                )}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className="text-sm font-medium"
                    style={{ color: isCompleted ? 'var(--th-success)' : isActive ? 'var(--th-primary)' : 'var(--th-text-muted)' }}
                  >
                    {step.label}
                  </span>
                  <span className="text-xs font-mono" style={{ color: 'var(--th-text-ghost)' }}>#{idx + 1}</span>
                </div>
                <p className="text-xs mt-0.5" style={{ color: 'var(--th-text-muted)' }}>{step.desc}</p>
                {isActive && latestEvent?.message && (
                  <p className="mt-1.5 text-xs font-mono truncate" style={{ color: 'var(--th-primary)' }}>
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
          style={{ background: 'var(--th-log-bg)', border: '1px solid var(--th-border-default)' }}
        >
          <p className="text-xs font-mono mb-2 uppercase tracking-wider" style={{ color: 'var(--th-text-ghost)' }}>Logs</p>
          <div className="space-y-1">
            {events.slice(-20).map((evt, i) => (
              <p key={i} className="text-xs font-mono leading-relaxed" style={{ color: 'var(--th-text-tertiary)' }}>
                <span style={{ color: 'var(--th-text-faint)' }}>[Step {evt.step}]</span>{' '}
                {evt.message}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
