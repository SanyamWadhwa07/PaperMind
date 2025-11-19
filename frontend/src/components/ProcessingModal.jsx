import { Loader2, X } from 'lucide-react'

export default function ProcessingModal({ status, onClose }) {
  if (!status) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-[#EEF4F3] dark:bg-[#1E2020] rounded-xl shadow-xl max-w-md w-full mx-4 p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-xl font-semibold text-[#C4935F] dark:text-[#D9A86C]">Processing Paper</h3>
          {status.status === 'completed' && (
            <button
              onClick={onClose}
              className="text-[#8F8F8F] hover:text-[#00988F] dark:hover:text-[#00A7A0] transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        <div className="space-y-3">
          {/* Progress Bar */}
          <div className="w-full bg-[#E0EBE9] dark:bg-[#252727] rounded-full h-3 overflow-hidden">
            <div
              className="bg-[#00988F] dark:bg-[#00A7A0] h-full transition-all duration-500 ease-out"
              style={{ width: `${status.progress}%` }}
            />
          </div>

          {/* Status Message */}
          <div className="flex items-center gap-3 text-sm">
            {status.status === 'processing' && (
              <Loader2 className="w-5 h-5 animate-spin text-[#00988F] dark:text-[#00A7A0]" />
            )}
            <span className="text-[#1B1B1B] dark:text-[#F5F5F5]">{status.message}</span>
          </div>

          {/* Progress Percentage */}
          <p className="text-sm text-[#8F8F8F] dark:text-[#8F8F8F] text-center">
            {status.progress}% Complete
          </p>
        </div>

        {status.status === 'error' && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
            <p className="text-sm text-red-800 dark:text-red-400">{status.error}</p>
          </div>
        )}
      </div>
    </div>
  )
}
