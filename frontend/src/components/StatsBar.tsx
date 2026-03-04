import { Users, Zap, Mail, Linkedin, Phone } from 'lucide-react'
import type { JobResult } from '@/lib/api'

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
      style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}
    >
      <div
        className="inline-flex items-center justify-center w-8 h-8 rounded-lg mb-3"
        style={{ background: `${accentColor}18`, boxShadow: `0 0 12px ${glowColor}` }}
      >
        {icon}
      </div>
      <div className="text-2xl font-bold mb-0.5" style={{ color: '#e2e8f8', letterSpacing: '-0.02em' }}>{value}</div>
      <div className="text-xs" style={{ color: 'rgba(226,232,248,0.4)' }}>{label}</div>
      {sub && <div className="text-xs mt-0.5" style={{ color: 'rgba(226,232,248,0.25)' }}>{sub}</div>}
    </div>
  )
}

export function StatsBar({ result }: Props) {
  const { total_leads, hit_leads, nohit_leads, stats } = result
  const hitRate = total_leads > 0 ? Math.round((hit_leads / total_leads) * 100) : 0

  return (
    <div className="w-full max-w-5xl mx-auto">
      <h2 className="text-base font-semibold mb-4" style={{ color: 'rgba(226,232,248,0.6)', letterSpacing: '-0.01em' }}>
        Résumé du pipeline
      </h2>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <StatCard icon={<Users className="w-4 h-4" style={{ color: '#4d9fff' }} />} accentColor="#4d9fff" glowColor="rgba(77,159,255,0.15)" label="Leads totaux" value={total_leads} />
        <StatCard icon={<Zap className="w-4 h-4" style={{ color: '#34d399' }} />} accentColor="#34d399" glowColor="rgba(52,211,153,0.15)" label="Leads hit" value={hit_leads} sub={`${hitRate}% du total`} />
        <StatCard icon={<Users className="w-4 h-4" style={{ color: 'rgba(226,232,248,0.3)' }} />} accentColor="rgba(226,232,248,0.3)" glowColor="rgba(226,232,248,0.05)" label="No-hit" value={nohit_leads} sub={`${100 - hitRate}% du total`} />
        <StatCard icon={<Mail className="w-4 h-4" style={{ color: '#9b6bff' }} />} accentColor="#9b6bff" glowColor="rgba(155,107,255,0.15)" label="Emails trouvés" value={`${stats.email_pct}%`} sub={`${stats.email_count ?? 0} / ${total_leads} leads`} />
        <StatCard icon={<Linkedin className="w-4 h-4" style={{ color: '#4d9fff' }} />} accentColor="#4d9fff" glowColor="rgba(77,159,255,0.15)" label="LinkedIn" value={`${stats.linkedin_pct}%`} sub={`${stats.linkedin_count ?? 0} / ${total_leads} leads`} />
        <StatCard icon={<Phone className="w-4 h-4" style={{ color: '#22d3ee' }} />} accentColor="#22d3ee" glowColor="rgba(34,211,238,0.15)" label="Téléphones" value={`${stats.phone_pct}%`} sub={`${stats.phone_count ?? 0} / ${total_leads} · Site: ${stats.website_count ?? 0} / ${total_leads}`} />
      </div>

      {/* Score bar */}
      <div
        className="mt-3 rounded-xl px-5 py-4"
        style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}
      >
        <div className="flex justify-between text-sm mb-2.5">
          <span className="font-medium" style={{ color: 'rgba(226,232,248,0.5)' }}>Score moyen</span>
          <span className="font-mono font-semibold" style={{ color: '#e2e8f8' }}>{stats.avg_score} / 100</span>
        </div>
        <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{ width: `${stats.avg_score}%`, background: 'linear-gradient(90deg, #4d9fff, #34d399)' }}
          />
        </div>
        <div className="flex justify-between text-xs mt-1.5" style={{ color: 'rgba(226,232,248,0.2)' }}>
          <span>email+40 · linkedin+30 · phone+20 · web+10</span>
          <span>seuil hit: 50</span>
        </div>
      </div>
    </div>
  )
}
