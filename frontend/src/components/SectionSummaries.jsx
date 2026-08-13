import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { Prose, cx } from './ui/primitives'

export default function SectionSummaries({ summaries }) {
  const [expandedSections, setExpandedSections] = useState(['introduction'])

  if (!summaries || Object.keys(summaries).length === 0) {
    return <p className="text-sm text-ink-faint">No section summaries available.</p>
  }

  const toggleSection = (section) => {
    setExpandedSections((prev) =>
      prev.includes(section)
        ? prev.filter((s) => s !== section)
        : [...prev, section],
    )
  }

  const entries = Object.entries(summaries)

  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface">
      {entries.map(([section, text], index) => {
        const isExpanded = expandedSections.includes(section)
        const wordCount = text.trim().split(/\s+/).length

        return (
          <div key={section} className={cx(index > 0 && 'border-t border-line')}>
            <button
              type="button"
              onClick={() => toggleSection(section)}
              aria-expanded={isExpanded}
              className="flex w-full items-center gap-3 px-5 py-3.5 text-left transition-colors duration-fast ease-out hover:bg-surface-hover"
            >
              {/* Papers number their sections; so does the reader's index. */}
              <span className="font-mono tabular text-code text-ink-faint">
                §{String(index + 1).padStart(2, '0')}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm font-medium capitalize text-ink">
                {section.replace(/_/g, ' ')}
              </span>
              <span className="shrink-0 font-mono tabular text-code text-ink-faint">
                {wordCount}w
              </span>
              <ChevronDown
                className={cx(
                  'h-4 w-4 shrink-0 text-ink-faint transition-transform duration-fast ease-out',
                  isExpanded && 'rotate-180',
                )}
                aria-hidden="true"
              />
            </button>

            {isExpanded && (
              <div className="animate-fade border-t border-line bg-surface-sunk px-5 py-4">
                {/* Section digests come from the same generator as the main
                    synthesis, so they carry the same stray markdown. */}
                <Prose>{text}</Prose>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
