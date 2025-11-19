import { ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'

export default function SectionSummaries({ summaries }) {
  const [expandedSections, setExpandedSections] = useState(['introduction'])

  if (!summaries || Object.keys(summaries).length === 0) {
    return <p className="text-[#8F8F8F] dark:text-[#8F8F8F]">No section summaries available</p>
  }

  const toggleSection = (section) => {
    setExpandedSections(prev =>
      prev.includes(section)
        ? prev.filter(s => s !== section)
        : [...prev, section]
    )
  }

  const sectionIcons = {
    abstract: '',
    introduction: '',
    methodology: '',
    experiments: '',
    results: '',
    discussion: '',
    conclusion: '',
    related_work: '',
  }

  return (
    <div className="space-y-3">
      {Object.entries(summaries).map(([section, text]) => {
        const isExpanded = expandedSections.includes(section)
        const wordCount = text.split(' ').length

        return (
          <div
            key={section}
            className="border border-[#C4935F]/20 dark:border-[#D9A86C]/20 rounded-lg overflow-hidden"
          >
            <button
              onClick={() => toggleSection(section)}
              className="w-full px-4 py-3 bg-[#EEF4F3] dark:bg-[#1E2020] hover:bg-[#E0EBE9] dark:hover:bg-[#252727] transition-colors flex items-center justify-between"
            >
              <div className="flex items-center gap-2">
                <span className="font-medium text-[#C4935F] dark:text-[#D9A86C] capitalize">
                  {section.replace('_', ' ')}
                </span>
                <span className="text-sm text-[#8F8F8F] dark:text-[#8F8F8F]">
                  ({wordCount} words)
                </span>
              </div>
              {isExpanded ? (
                <ChevronUp className="w-5 h-5 text-[#8F8F8F] dark:text-[#8F8F8F]" />
              ) : (
                <ChevronDown className="w-5 h-5 text-[#8F8F8F] dark:text-[#8F8F8F]" />
              )}
            </button>

            {isExpanded && (
              <div className="px-4 py-4 bg-[#F9FBFA] dark:bg-[#111312]">
                <p className="text-[#1B1B1B] dark:text-[#F5F5F5] leading-relaxed">{text}</p>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
