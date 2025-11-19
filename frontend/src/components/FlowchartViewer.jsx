import { useEffect, useRef, useState } from 'react'
import mermaid from 'mermaid'
import { ExternalLink, AlertCircle, GitBranch } from 'lucide-react'

export default function FlowchartViewer({ flowchart }) {
  const chartRef = useRef(null)
  const [renderError, setRenderError] = useState(null)
  const [isRendering, setIsRendering] = useState(false)

  useEffect(() => {
    if (!flowchart || !chartRef.current) return
    
    const renderChart = async () => {
      try {
        setIsRendering(true)
        setRenderError(null)
        
        // Clear previous content
        const container = chartRef.current
        container.innerHTML = ''
        
        // Initialize mermaid with safe settings
        mermaid.initialize({ 
          startOnLoad: false,
          theme: 'default',
          securityLevel: 'loose',
          flowchart: {
            useMaxWidth: true,
            htmlLabels: true,
          }
        })
        
        // Generate unique ID
        const chartId = `mermaid-chart-${Date.now()}`
        
        // Render the chart - mermaid.render returns the SVG string
        const { svg } = await mermaid.render(chartId, flowchart)
        
        // Insert the SVG into the container
        if (container && svg) {
          container.innerHTML = svg
        }
      } catch (error) {
        console.error('Mermaid rendering error:', error)
        setRenderError(error?.message || 'Failed to render flowchart')
      } finally {
        setIsRendering(false)
      }
    }
    
    renderChart()
  }, [flowchart])

  if (!flowchart) {
    return (
      <div className="bg-gradient-to-br from-blue-50 to-indigo-50 border-2 border-dashed border-blue-300 rounded-lg p-12">
        <div className="text-center space-y-4 max-w-2xl mx-auto">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-100 rounded-full mb-2">
            <GitBranch className="w-8 h-8 text-blue-600" />
          </div>
          
          <h3 className="text-xl font-bold text-gray-900">
            No Methodology Flowchart Available
          </h3>
          
          <p className="text-gray-700">
            A flowchart could not be generated from this paper's methodology section.
          </p>
          
          <div className="bg-white rounded-lg p-4 text-left">
            <p className="text-sm font-medium text-gray-700 mb-2">
              <AlertCircle className="w-4 h-4 inline mr-1" />
              Flowcharts are generated when the methodology contains:
            </p>
            <ul className="text-sm text-gray-600 space-y-1 ml-5">
              <li>• Process verbs (train, test, evaluate, implement, etc.)</li>
              <li>• Step-by-step procedures or algorithms</li>
              <li>• Sequential methodology descriptions</li>
              <li>• At least 2-3 distinct process steps</li>
            </ul>
          </div>
          
          <p className="text-xs text-gray-500">
            This paper may use a different writing style or the methodology section may be brief.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Mermaid Chart */}
      {isRendering ? (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-8 text-center">
          <div className="animate-pulse space-y-3">
            <GitBranch className="w-12 h-12 text-blue-500 mx-auto animate-bounce" />
            <p className="text-blue-700 font-medium">Rendering flowchart...</p>
          </div>
        </div>
      ) : renderError ? (
        <div className="bg-red-50 border-2 border-red-200 rounded-lg p-6">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-6 h-6 text-red-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-red-800 font-semibold mb-1">Flowchart Rendering Error</p>
              <p className="text-red-700 text-sm">{renderError}</p>
              <p className="text-red-600 text-xs mt-2">
                Try viewing the code below or opening in the Mermaid Live Editor.
              </p>
            </div>
          </div>
        </div>
      ) : (
        <div className="bg-gradient-to-br from-white to-gray-50 rounded-lg border-2 border-gray-200 shadow-sm">
          <div className="bg-gradient-to-r from-blue-500 to-purple-500 text-white px-4 py-2 rounded-t-lg">
            <p className="text-sm font-medium flex items-center gap-2">
              <GitBranch className="w-4 h-4" />
              Methodology Flowchart
            </p>
          </div>
          <div 
            ref={chartRef} 
            className="p-8 overflow-x-auto min-h-[300px]"
          />
        </div>
      )}

      {/* Code View */}
      <details className="bg-gray-50 rounded-lg">
        <summary className="px-4 py-3 cursor-pointer font-medium text-gray-700 hover:bg-gray-100 rounded-lg">
          View Mermaid Code
        </summary>
        <div className="px-4 pb-4 pt-2">
          <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto text-sm">
            <code>{flowchart}</code>
          </pre>
        </div>
      </details>

      {/* External Link */}
      <a
        href={`https://mermaid.live/edit#pako:${encodeURIComponent(flowchart || '')}`}
        target="_blank"
        rel="noopener noreferrer"
        className="btn-secondary inline-flex"
      >
        <ExternalLink className="w-4 h-4" />
        Open in Mermaid Live Editor
      </a>
    </div>
  )
}
