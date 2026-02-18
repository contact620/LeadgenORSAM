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
  color: string
}

function StatCard({ icon, label, value, sub, color }: StatCardProps) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
      <div className={`inline-flex items-center justify-center w-9 h-9 rounded-lg ${color} mb-3`}>
        {icon}
      </div>
      <div className="text-2xl font-bold text-gray-900">{value}</div>
      <div className="text-sm text-gray-500 mt-0.5">{label}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  )
}

export function StatsBar({ result }: Props) {
  const { total_leads, hit_leads, nohit_leads, stats } = result
  const hitRate = total_leads > 0 ? Math.round((hit_leads / total_leads) * 100) : 0

  return (
    <div className="w-full max-w-5xl mx-auto">
      <h2 className="text-lg font-semibold text-gray-800 mb-4">Résumé du pipeline</h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <StatCard
          icon={<Users className="w-4 h-4 text-blue-600" />}
          color="bg-blue-50"
          label="Leads totaux"
          value={total_leads}
        />
        <StatCard
          icon={<Zap className="w-4 h-4 text-green-600" />}
          color="bg-green-50"
          label="Leads hit"
          value={hit_leads}
          sub={`${hitRate}% du total`}
        />
        <StatCard
          icon={<Users className="w-4 h-4 text-gray-500" />}
          color="bg-gray-50"
          label="No-hit"
          value={nohit_leads}
          sub={`${100 - hitRate}% du total`}
        />
        <StatCard
          icon={<Mail className="w-4 h-4 text-violet-600" />}
          color="bg-violet-50"
          label="Emails trouvés"
          value={`${stats.email_pct}%`}
        />
        <StatCard
          icon={<Linkedin className="w-4 h-4 text-blue-700" />}
          color="bg-blue-50"
          label="LinkedIn trouvés"
          value={`${stats.linkedin_pct}%`}
        />
        <StatCard
          icon={<Phone className="w-4 h-4 text-teal-600" />}
          color="bg-teal-50"
          label="Téléphones"
          value={`${stats.phone_pct}%`}
          sub={`Site: ${stats.website_pct}%`}
        />
      </div>

      {/* Avg score bar */}
      <div className="mt-4 bg-white rounded-xl border border-gray-200 shadow-sm px-5 py-4">
        <div className="flex justify-between text-sm mb-2">
          <span className="text-gray-600 font-medium">Score moyen</span>
          <span className="font-mono text-gray-900 font-semibold">{stats.avg_score} / 100</span>
        </div>
        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full bg-gradient-to-r from-blue-500 to-green-500 transition-all duration-700"
            style={{ width: `${stats.avg_score}%` }}
          />
        </div>
        <div className="flex justify-between text-xs text-gray-400 mt-1">
          <span>email+40  linkedin+30  phone+20  web+10</span>
          <span>seuil hit: 50</span>
        </div>
      </div>
    </div>
  )
}
