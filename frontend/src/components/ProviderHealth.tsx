import { AlertCircle, AlertTriangle } from 'lucide-react'

interface ProviderStatusEntry {
  status: string
  reason: string | null
  leads_affected: number
}

interface Props {
  providerStatus?: Record<string, ProviderStatusEntry>
  jobStatus?: string
}

const PROVIDER_LABELS: Record<string, string> = {
  dropcontact: 'Dropcontact',
  hunter: 'Hunter.io',
  serper: 'Serper',
  website: 'Scraping site web',
  perplexity: 'Perplexity',
  anthropic_facts: 'Extraction de faits',
  anthropic_angles: 'Rédaction des angles',
}

/**
 * Compact warning banner surfacing provider failures/degradations from a
 * pipeline run. Renders nothing when every provider is healthy — this is
 * meant to catch attention, not to confirm business as usual.
 */
export function ProviderHealth({ providerStatus, jobStatus }: Props) {
  const issues = Object.entries(providerStatus ?? {}).filter(
    ([, v]) => v.status === 'failed' || v.status === 'degraded'
  )

  if (issues.length === 0) return null

  return (
    <div className="w-full max-w-5xl mx-auto mb-3 space-y-2">
      {jobStatus === 'completed_with_errors' && (
        <div
          className="rounded-xl px-4 py-2.5 text-sm font-medium"
          style={{ background: 'var(--th-error-soft)', color: 'var(--th-error)', border: '1px solid var(--th-error-border)' }}
        >
          Run terminé avec des erreurs — les résultats sont incomplets.
        </div>
      )}
      <div className="rounded-xl overflow-hidden" style={{ border: '1px solid var(--th-glass-sm-border)' }}>
        {issues.map(([key, v], i) => {
          const isFailed = v.status === 'failed'
          const label = PROVIDER_LABELS[key] ?? key
          return (
            <div
              key={key}
              className="flex items-start gap-2.5 px-4 py-2.5"
              style={{
                background: isFailed ? 'var(--th-error-soft)' : 'var(--th-warning-soft)',
                borderBottom: i < issues.length - 1 ? '1px solid var(--th-glass-sm-border)' : 'none',
              }}
            >
              {isFailed
                ? <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" style={{ color: 'var(--th-error)' }} />
                : <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" style={{ color: 'var(--th-warning)' }} />}
              <div className="text-sm">
                <span className="font-medium" style={{ color: isFailed ? 'var(--th-error)' : 'var(--th-warning-text)' }}>
                  {label}
                </span>
                <span className="ml-1.5 text-xs" style={{ color: 'var(--th-text-muted)' }}>
                  {isFailed ? 'en échec' : 'dégradé'}
                  {v.leads_affected > 0 ? ` · ${v.leads_affected} lead(s) affecté(s)` : ''}
                </span>
                {v.reason && (
                  <p className="text-xs mt-0.5" style={{ color: 'var(--th-text-faint)' }}>{v.reason}</p>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
