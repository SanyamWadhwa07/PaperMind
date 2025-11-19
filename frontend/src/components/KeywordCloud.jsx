export default function KeywordCloud({ overallKeywords, sectionKeywords }) {
  return (
    <div className="space-y-6">
      {/* Overall Keywords */}
      <div>
        <h3 className="text-lg font-semibold mb-3 text-[#C4935F] dark:text-[#D9A86C]">Overall Keywords</h3>
        <div className="flex flex-wrap gap-2">
          {overallKeywords && overallKeywords.length > 0 ? (
            overallKeywords.map((keyword, idx) => (
              <span
                key={idx}
                className="badge badge-blue text-base"
                style={{
                  fontSize: `${0.875 + (overallKeywords.length - idx) * 0.05}rem`,
                }}
              >
                {keyword}
              </span>
            ))
          ) : (
            <p className="text-sm text-[#8F8F8F] dark:text-[#8F8F8F]">No keywords extracted</p>
          )}
        </div>
      </div>

      {/* Section Keywords */}
      {sectionKeywords && Object.keys(sectionKeywords).length > 0 && (
        <div>
          <h3 className="text-lg font-semibold mb-4 text-green-400">Keywords by Section</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(sectionKeywords).map(([section, keywords]) => (
              <div key={section} className="bg-gray-50 rounded-lg p-4">
                <h4 className="font-medium text-green-400 mb-2 capitalize">
                  {section.replace('_', ' ')}
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {keywords.slice(0, 5).map((keyword, idx) => (
                    <span
                      key={idx}
                      className="text-xs px-2 py-1 bg-primary-100 text-primary-800 rounded-full"
                    >
                      {keyword}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
