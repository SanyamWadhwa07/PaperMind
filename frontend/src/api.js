import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000/api'

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

export const searchPapers = async (query, maxResults = 5) => {
  const response = await api.post('/search', { query, max_results: maxResults })
  return response.data
}

export const uploadPDF = async (file) => {
  const formData = new FormData()
  formData.append('file', file)
  const response = await api.post('/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return response.data
}

export const summarizePaper = async (paperData) => {
  const response = await api.post('/summarize', paperData)
  return response.data
}

export const summarizePaperAsync = async (paperData) => {
  const response = await api.post('/summarize/async', paperData)
  return response.data
}

export const getProcessingStatus = async (taskId) => {
  const response = await api.get(`/status/${taskId}`)
  return response.data
}

export const listSummaries = async () => {
  const response = await api.get('/summaries')
  return response.data
}

export const getSummary = async (summaryId) => {
  const response = await api.get(`/summary/${summaryId}`)
  return response.data
}

export const exportSummary = async (summaryId, format = 'json') => {
  const response = await api.get(`/export/${summaryId}?format=${format}`, {
    responseType: format === 'markdown' ? 'blob' : 'json',
  })
  return response.data
}

export const batchSummarize = async (papers) => {
  const response = await api.post('/batch/summarize', { papers })
  return response.data
}

// New database-saving endpoints (requires authentication)
export const processArxivPaper = async (arxivId, token) => {
  const response = await api.post('/process/arxiv', 
    { arxiv_id: arxivId },
    { headers: { 'Authorization': `Bearer ${token}` } }
  )
  return response.data
}

export const processUploadedPaper = async (file, token) => {
  const formData = new FormData()
  formData.append('file', file)
  const response = await api.post('/process/upload', formData, {
    headers: { 
      'Content-Type': 'multipart/form-data',
      'Authorization': `Bearer ${token}`
    },
  })
  return response.data
}

export default api
