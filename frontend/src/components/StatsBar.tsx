import { Users, Zap, Mail, Linkedin, Phone, Sparkles, Smartphone, MessageCircle, Wallet } from 'lucide-react'
import type { JobResult } from '@/lib/api'
import { emailSourceLabel } from '@/lib/tiers'

interface Props {
  result: JobResult
}

interface StatCardProps {
  icon: React.ReactNode
  label: string
  value: string | number
  sub?: string
  accentColor: string
  glowColor: string
}

function StatCard({ icon, label, value, sub, accentColor, glowColor }: StatCardProps) {
  return (
    <div
      className="rounded-xl p-4 transition-all duration-200 hover:-translate-y-0.5"
      style={{ background: 'var(--th-glass-sm-bg)', border: '1px solid var(--th-glass-sm-border)' }}
    >
      <div
        className="inline-flex items-center justify-center w-8 h-8 rounded-lg mb-3"
        style={{ background: `${accentColor}18`, boxShadow: `0 0 12px ${glowColor}` }}
      >
        {icon}
      </div>
      <div className="text-2xl font-bold mb-0.5" style={{ color: 'var(--th-text-primary)', letterSpacing: '-0.02em' }}>{value}</div>
      <div className="text-xs" style={{ color: 'var(--th-text-quaternary)' }}>{label}</div>
      {sub && <div className="text-xs mt-0.5" style={{ color: 'var(--th-text-faint)' }}>{sub}</div>}
    </div>
  )
}

export function StatsBar({ result }: Props) {
  const { total_leads, hit_leads, nohit_leads, pending_quota_leads, stats } = result
  const hitRate = total_leads > 0 ? Math.round((hit_leads / total_leads) * 100) : 0
  const topSource = Object.entries(stats.email_by_source ?? {}).sort((a, b) => b[1] - a[1])[0]
  // Finder credits only. getprospect_verify is also in provider_credits, but
  // it counts verifications, not searches: adding it produced a single number
  // out of two different units — and one that contradicted this tile's own
  // "Prospeo + GetProspect + Hunter" caption.
  const EMAIL_FINDERS = ['prospeo', 'getprospect', 'hunter']
  const totalCredits = EMAIL_FINDERS.reduce(
    (s, name) => s + (stats.provider_credits?.[name]?.remaining ?? 0), 0)

  return (
    <div className="w-full max-w-5xl mx-auto">
      <h2 className="text-base font-semibold mb-4" style={{ color: 'var(--th-text-secondary)', letterSpacing: '-0.01em' }}>
        Résumé du pipeline
      </h2>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <StatCard icon={<Users className="w-4 h-4" style={{ color: 'var(--th-primary)' }} />} accentColor="#4d9fff" glowColor="rgba(77,159,255,0.15)" label="Leads totaux" value={total_leads} />
        <StatCard icon={<Zap className="w-4 h-4" style={{ color: 'var(--th-success)' }} />} accentColor="#34d399" glowColor="rgba(52,211,153,0.15)" label="Joignables" value={hit_leads} sub={`${hitRate}% du total`} />
        <StatCard icon={<Users className="w-4 h-4" style={{ color: 'var(--th-text-muted)' }} />} accentColor="rgba(226,232,248,0.3)" glowColor="rgba(226,232,248,0.05)" label="Non joignables" value={nohit_leads} sub={`${100 - hitRate}% du total`} />
        {pending_quota_leads > 0 && (
          <StatCard icon={<Zap className="w-4 h-4" style={{ color: '#60a5fa' }} />} accentColor="#60a5fa" glowColor="rgba(96,165,250,0.15)" label="En attente de quota" value={pending_quota_leads} sub="pas écartés — repassent au reset" />
        )}
        <StatCard icon={<Mail className="w-4 h-4" style={{ color: 'var(--th-purple)' }} />} accentColor="#9b6bff" glowColor="rgba(155,107,255,0.15)" label="Emails trouvés" value={`${stats.email_pct}%`} sub={topSource ? `Principale source : ${emailSourceLabel(topSource[0])}` : `${stats.email_count ?? 0} / ${total_leads} leads`} />
        <StatCard icon={<Linkedin className="w-4 h-4" style={{ color: 'var(--th-primary)' }} />} accentColor="#4d9fff" glowColor="rgba(77,159,255,0.15)" label="LinkedIn" value={`${stats.linkedin_pct}%`} sub={`${stats.linkedin_count ?? 0} / ${total_leads} leads`} />
        <StatCard icon={<Phone className="w-4 h-4" style={{ color: 'var(--th-cyan)' }} />} accentColor="#22d3ee" glowColor="rgba(34,211,238,0.15)" label="Téléphones" value={`${stats.phone_pct}%`} sub={`${stats.phone_count ?? 0} / ${total_leads} · Site: ${stats.website_count ?? 0} / ${total_leads}`} />
        <StatCard icon={<Smartphone className="w-4 h-4" style={{ color: '#22d3ee' }} />} accentColor="#22d3ee" glowColor="rgba(34,211,238,0.15)" label="Mobiles" value={stats.mobile_count ?? 0} sub={`sur ${total_leads} leads`} />
        <StatCard icon={<MessageCircle className="w-4 h-4" style={{ color: '#34d399' }} />} accentColor="#34d399" glowColor="rgba(52,211,153,0.15)" label="WhatsApp" value={stats.whatsapp_count ?? 0} sub="lien publié sur le site" />
        <StatCard icon={<Wallet className="w-4 h-4" style={{ color: '#fbbf24' }} />} accentColor="#fbbf24" glowColor="rgba(251,191,36,0.15)" label="Crédits email restants" value={Math.round(totalCredits)} sub="Prospeo + GetProspect + Hunter" />
      </div>

      {/* Email sources */}
      {stats.email_by_source && Object.keys(stats.email_by_source).length > 0 && (
        <div
          className="mt-3 rounded-xl px-5 py-4"
          style={{ background: 'var(--th-glass-sm-bg)', border: '1px solid var(--th-glass-sm-border)' }}
        >
          <div className="flex items-center gap-2 mb-3">
            <Mail className="w-4 h-4" style={{ color: 'var(--th-purple)' }} />
            <span className="font-medium text-sm" style={{ color: 'var(--th-text-tertiary)' }}>Emails trouvés par source</span>
          </div>
          <div className="flex flex-wrap gap-3">
            {Object.entries(stats.email_by_source)
              .sort((a, b) => b[1] - a[1])
              .map(([source, count]) => (
                <span key={source} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
                      style={{ background: 'var(--th-glass-inset)', color: 'var(--th-text-tertiary)', border: '1px solid var(--th-glass-sm-border)' }}>
                  {emailSourceLabel(source)} : <span style={{ color: 'var(--th-text-primary)' }}>{count}</span>
                </span>
              ))}
          </div>
        </div>
      )}

      {/* Pre-score bar */}
      <div
        className="mt-3 rounded-xl px-5 py-4"
        style={{ background: 'var(--th-glass-sm-bg)', border: '1px solid var(--th-glass-sm-border)' }}
      >
        <div className="flex justify-between text-sm mb-2.5">
          <span className="font-medium" style={{ color: 'var(--th-text-tertiary)' }}>Pré-score moyen</span>
          <span className="font-mono font-semibold" style={{ color: 'var(--th-text-primary)' }}>{stats.avg_score} / 60</span>
        </div>
        <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--th-border-default)' }}>
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{ width: `${(stats.avg_score / 60) * 100}%`, background: 'linear-gradient(90deg, #4d9fff, #34d399)' }}
          />
        </div>
        <div className="flex justify-between text-xs mt-1.5" style={{ color: 'var(--th-text-ghost)' }}>
          <span>secteur · taille · localisation — priorisation gratuite, jamais un verdict</span>
        </div>
      </div>

      {/* Executive summary */}
      {result.executive_summary && (
        <div
          className="mt-3 rounded-xl px-5 py-4"
          style={{ background: 'var(--th-primary-soft)', border: '1px solid var(--th-primary-border)' }}
        >
          <div className="flex items-center gap-2 mb-2">
            <Sparkles className="w-4 h-4" style={{ color: 'var(--th-primary)' }} />
            <span className="font-semibold text-sm" style={{ color: 'var(--th-primary)' }}>Résumé exécutif</span>
          </div>
          <p className="text-sm leading-relaxed" style={{ color: 'var(--th-text-secondary)' }}>
            {result.executive_summary}
          </p>
        </div>
      )}
    </div>
  )
}
