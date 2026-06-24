import { Database, Cpu, BarChart3, Wrench, FlaskConical } from 'lucide-react'

// Domain-agnostic typed entities from the LangGraph engine.
const KIND_META = {
  method:      { label: 'Methods',      icon: FlaskConical, color: 'purple' },
  material:    { label: 'Materials / Data', icon: Database, color: 'blue' },
  measurement: { label: 'Measurements', icon: BarChart3, color: 'green' },
  tool:        { label: 'Tools',        icon: Wrench, color: 'amber' },
}

const KIND_BADGE = {
  method: 'badge-purple', material: 'badge-blue',
  measurement: 'badge-green', tool: 'badge-amber',
}

export default function EntityDisplay({ entities, typed }) {
  // Prefer the domain-agnostic typed entities (works for any field, not just ML).
  const typedList = typed?.entities || []
  if (typedList.length > 0) {
    const byKind = { method: [], material: [], measurement: [], tool: [] }
    typedList.forEach(e => { (byKind[e.kind] || (byKind[e.kind] = [])).push(e) })

    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {Object.entries(KIND_META).map(([kind, { label, icon: Icon }]) => (
          <div key={kind} className="space-y-3">
            <div className="flex items-center gap-2">
              <Icon className="w-5 h-5 text-[#1B1B1B] dark:text-[#F5F5F5]" />
              <h3 className="text-lg font-semibold text-[#C4935F] dark:text-[#D9A86C]">{label}</h3>
            </div>
            <div className="flex flex-wrap gap-2">
              {byKind[kind]?.length > 0 ? (
                byKind[kind].map((e, idx) => (
                  <span
                    key={idx}
                    className={`badge ${KIND_BADGE[kind]}`}
                    title={e.description || ''}
                  >
                    {e.name}
                  </span>
                ))
              ) : (
                <p className="text-sm text-[#8F8F8F]">None detected</p>
              )}
            </div>
          </div>
        ))}
      </div>
    )
  }

  // Legacy fallback: datasets / models / metrics buckets.
  if (!entities) return null
  const entityTypes = [
    { key: 'datasets', label: 'Datasets', icon: Database, color: 'blue' },
    { key: 'models', label: 'Models', icon: Cpu, color: 'purple' },
    { key: 'metrics', label: 'Metrics', icon: BarChart3, color: 'green' },
  ]

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
      {entityTypes.map(({ key, label, icon: Icon, color }) => (
        <div key={key} className="space-y-3">
          <div className="flex items-center gap-2">
            <Icon className="w-5 h-5 text-[#1B1B1B] dark:text-[#F5F5F5]" />
            <h3 className="text-lg font-semibold text-[#C4935F] dark:text-[#D9A86C]">{label}</h3>
          </div>

          <div className="flex flex-wrap gap-2">
            {entities[key] && entities[key].length > 0 ? (
              entities[key].map((entity, idx) => (
                <span key={idx} className={`badge badge-${color}`}>
                  {entity}
                </span>
              ))
            ) : (
              <p className="text-sm text-[#8F8F8F] dark:text-[#8F8F8F]">No {label.toLowerCase()} detected</p>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
