import axios from 'axios'

// API base URL based on environment
const API_BASE_URL = process.env.NODE_ENV === 'production'
  ? '/api'
  : 'http://localhost:8124/api'

const request = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000
})

// --- request interceptor: attach Bearer token -------------------
request.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = 'Bearer ' + token
  }
  return config
})

// --- Auth API ----------------------------------------------------

export const register = (username, nickname, password) => {
  return request.post('/auth/register', { username, nickname, password }).then(r => r.data)
}

export const login = (username, password) => {
  return request.post('/auth/login', { username, password }).then(r => r.data)
}

export const logout = () => {
  return request.post('/auth/logout').then(r => r.data)
}

export const fetchCurrentUser = () => {
  const token = localStorage.getItem('token')
  if (!token) return Promise.reject(new Error('no token'))
  return request.get('/auth/userinfo', {
    headers: { Authorization: 'Bearer ' + token }
    }).then(r => r.data)
}

// --- Session API -------------------------------------------------

export const listSessions = (chatType) => {
  return request.get('/session/list', { params: { chat_type: chatType } }).then(r => r.data)
}

export const createSession = (chatType, title) => {
  return request.post('/session/create', { chat_type: chatType, title }).then(r => r.data)
}

export const renameSession = (sessionId, title) => {
  return request.put('/session/rename', { session_id: sessionId, title }).then(r => r.data)
}

export const deleteSession = (sessionId) => {
  return request.delete('/session/' + sessionId).then(r => r.data)
}

export const getSessionMessages = (sessionId) => {
  return request.get('/session/' + sessionId + '/messages').then(r => r.data)
}

export const getSessionSummary = (sessionId) => {
  return request.get('/session/' + sessionId + '/summary').then(r => r.data)
}

// --- RAG document management API -------------------------------

export const listRagDocuments = () => {
  return request.get('/rag/documents').then(r => r.data)
}

export const getRagDocument = (name) => {
  return request.get('/rag/documents/' + encodeURIComponent(name)).then(r => r.data)
}

export const getRagDocumentChunks = (name) => {
  return request.get('/rag/documents/' + encodeURIComponent(name) + '/chunks').then(r => r.data)
}

export const createRagDocument = (document) => {
  return request.post('/rag/documents', document).then(r => r.data)
}

export const uploadRagDocument = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/rag/documents/upload', formData).then(r => r.data)
}

export const deleteRagDocument = (name) => {
  return request.delete('/rag/documents/' + encodeURIComponent(name)).then(r => r.data)
}

// --- SSE helper --------------------------------------------------

// onMessage / onError are optional: callers may also assign
// eventSource.onmessage / eventSource.onerror right after the
// EventSource has been created (the pattern used by the chat views).
export const connectSSE = (url, params, onMessage, onError) => {
  const queryString = Object.keys(params)
    .map(key => encodeURIComponent(key) + '=' + encodeURIComponent(params[key]))
    .join('&')

  const fullUrl = API_BASE_URL + url + '?' + queryString

  const eventSource = new EventSource(fullUrl)

  eventSource.onmessage = event => {
    // NOTE: a single SSE event may contain newlines (Markdown tables).
    // The browser joins multi-line `data:` lines into one message, so we
    // pass event.data through untouched - never split it.
    const data = event.data
    if (onMessage) onMessage(data)
  }

  eventSource.onerror = error => {
    if (onError) onError(error)
    eventSource.close()
  }

  return eventSource
}

export const connectPostSSE = (url, formData) => {
  const controller = new AbortController()
  const connection = {
    onmessage: null,
    onerror: null,
    closed: false,
    close() {
      this.closed = true
      controller.abort()
    }
  }

  ;(async () => {
    try {
      const token = localStorage.getItem('token')
      const response = await fetch(API_BASE_URL + url, {
        method: 'POST',
        headers: token ? { Authorization: 'Bearer ' + token } : {},
        body: formData,
        signal: controller.signal
      })
      if (!response.ok) {
        let message = `请求失败（${response.status}）`
        try {
          const body = await response.json()
          message = body.error || body.msg || message
        } catch { /* response is not JSON */ }
        throw new Error(message)
      }
      if (!response.body) throw new Error('服务器未返回流式响应')

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      const dispatch = block => {
        const data = block
          .split(/\r?\n/)
          .filter(line => line.startsWith('data:'))
          .map(line => line.slice(5).replace(/^ /, ''))
          .join('\n')
        if (data) connection.onmessage?.({ data })
      }

      while (!connection.closed) {
        const { value, done } = await reader.read()
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
        const blocks = buffer.split(/\r?\n\r?\n/)
        buffer = blocks.pop() || ''
        blocks.forEach(dispatch)
        if (done) {
          if (buffer.trim()) dispatch(buffer)
          break
        }
      }
    } catch (error) {
      if (error?.name !== 'AbortError' && !connection.closed) {
        connection.onerror?.(error)
      }
    }
  })()

  return connection
}

// 论文精读助手 Chat (Chain mode, supports session_id for multi-turn)
export const chatWithPaperReader = (message, sessionId, onMessage, onError) => {
  const params = { message }
  if (sessionId) params.session_id = sessionId
  return connectSSE('/ai/paper_reader/chat/sse', params, onMessage, onError)
}

export const chatWithPaperPdf = (file, message, sessionId) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('message', message)
  if (sessionId) formData.append('session_id', sessionId)
  return connectPostSSE('/ai/paper_reader/pdf/sse', formData)
}

// CV 科研问答智能体 Chat (Agent mode, supports session_id for multi-turn)
export const chatWithCvAgent = (message, sessionId, onMessage, onError) => {
  const params = { message }
  if (sessionId) params.session_id = sessionId
  return connectSSE('/ai/cv_agent/chat', params, onMessage, onError)
}

export default {
  chatWithPaperReader,
  chatWithPaperPdf,
  chatWithCvAgent
}
