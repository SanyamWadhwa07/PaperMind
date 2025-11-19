import { FileText, Users, Calendar, Tag, ExternalLink } from 'lucide-react'

export default function PaperCard({ paper, onSummarize, index = 0 }) {
  const formatDate = (dateString) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffTime = Math.abs(now - date)
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))
    
    if (diffDays < 7) {
      return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`
    } else if (diffDays < 30) {
      const weeks = Math.floor(diffDays / 7)
      return `${weeks} week${weeks > 1 ? 's' : ''} ago`
    } else if (diffDays < 365) {
      const months = Math.floor(diffDays / 30)
      return `${months} month${months > 1 ? 's' : ''} ago`
    } else {
      const years = Math.floor(diffDays / 365)
      return `${years} year${years > 1 ? 's' : ''} ago`
    }
  }

  return (
    <div 
      className="card hover:shadow-xl transition-all duration-300 hover:border-[#00988F]/40 dark:hover:border-[#00A7A0]/40 group animate-slide-up"
      style={{ animationDelay: `${index * 0.1}s` }}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 space-y-3">
          <h4 className="text-lg font-semibold text-[#C4935F] dark:text-[#D9A86C] leading-tight">
            {paper.title}
          </h4>
          
          <div className="flex flex-wrap gap-3 text-sm text-[#1B1B1B] dark:text-[#F5F5F5]">
            <div className="flex items-center gap-1">
              <Users className="w-4 h-4" />
              <span>
                {paper.authors.slice(0, 3).join(', ')}
                {paper.authors.length > 3 && ` +${paper.authors.length - 3} more`}
              </span>
            </div>
            
            <div className="flex items-center gap-1.5">
              <Calendar className="w-4 h-4 text-[#00988F] dark:text-[#00A7A0]" />
              <span className="font-medium text-[#00988F] dark:text-[#00A7A0]">
                {formatDate(paper.published)}
              </span>
              <span className="text-gray-400">•</span>
              <span className="text-xs text-gray-500">{paper.published.split('T')[0]}</span>
            </div>
            
            {paper.primary_category && (
              <div className="flex items-center gap-1">
                <Tag className="w-4 h-4" />
                <span className="badge badge-blue text-xs">{paper.primary_category}</span>
              </div>
            )}
          </div>

          {paper.summary && (
            <p className="text-sm text-[#1B1B1B] dark:text-[#F5F5F5] line-clamp-2">
              {paper.summary}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <button
            onClick={() => onSummarize(paper)}
            className="btn-primary whitespace-nowrap"
          >
            <FileText className="w-4 h-4" />
            Summarize
          </button>
          {paper.pdf_url && (
            <a
              href={paper.pdf_url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary text-sm whitespace-nowrap"
            >
              <ExternalLink className="w-3 h-3" />
              View PDF
            </a>
          )}
        </div>
      </div>
    </div>
  )
}
