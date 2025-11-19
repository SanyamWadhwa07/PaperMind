import { Database, Cpu, BarChart3 } from 'lucide-react'

export default function EntityDisplay({ entities }) {
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
                <span
                  key={idx}
                  className={`badge badge-${color}`}
                >
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
