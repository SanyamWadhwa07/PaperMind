import { Image as ImageIcon, FileImage } from 'lucide-react'

export default function FiguresDisplay({ figures }) {
  if (!figures || figures.length === 0) {
    return (
      <div className="text-center py-8 text-[#8F8F8F] dark:text-[#8F8F8F]">
        <FileImage className="w-12 h-12 mx-auto mb-3 opacity-50" />
        <p>No figures detected in this paper</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-[#C4935F] dark:text-[#D9A86C] mb-4 flex items-center gap-2">
        <ImageIcon className="w-5 h-5" />
        Figures & Tables ({figures.length})
      </h3>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {figures.map((figure, idx) => (
          <div
            key={idx}
            className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-gray-800/50 hover:border-[#00988F] dark:hover:border-[#00A7A0] transition-colors"
          >
            {/* Figure Number & ID */}
            <div className="flex items-start justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold text-[#00988F] dark:text-[#00A7A0]">
                  Figure {figure.figure_number || idx + 1}
                </span>
                {figure.page && (
                  <span className="text-xs text-[#8F8F8F] dark:text-[#8F8F8F]">
                    Page {figure.page}
                  </span>
                )}
              </div>
              
              {/* Relevance Score */}
              {figure.relevance && (
                <div className="flex items-center gap-1">
                  <div className="w-12 bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                    <div
                      className="bg-[#00988F] dark:bg-[#00A7A0] h-2 rounded-full transition-all"
                      style={{ width: `${figure.relevance * 100}%` }}
                    />
                  </div>
                  <span className="text-xs text-[#8F8F8F] dark:text-[#8F8F8F]">
                    {Math.round(figure.relevance * 100)}%
                  </span>
                </div>
              )}
            </div>

            {/* Caption */}
            <p className="text-sm text-[#1B1B1B] dark:text-[#F5F5F5] leading-relaxed">
              {figure.caption || 'No caption available'}
            </p>

            {/* Section */}
            {figure.section && figure.section !== 'unknown' && (
              <div className="mt-2 pt-2 border-t border-gray-100 dark:border-gray-700">
                <span className="text-xs text-[#8F8F8F] dark:text-[#8F8F8F]">
                  Section: <span className="text-[#00988F] dark:text-[#00A7A0]">{figure.section}</span>
                </span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
