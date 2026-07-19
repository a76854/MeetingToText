const BASE = '/api'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(BASE + url, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || res.statusText)
  }
  return res.json()
}

export interface TaskInfo {
  id: string
  status: string
  filename: string
  audio_path?: string
  created_at?: string
  progress?: { current_step: string; steps: { name: string; status: string; message: string }[]; overall: number }
  result?: { full_text: string; segments: any[]; duration: number }
  minutes?: string
  error?: string
}

export interface TemplateInfo {
  id: string
  name: string
  description: string
}

export interface TranscriptData {
  task_id: string
  status: string
  full_text: string
  segments: any[]
  duration: number
}

export interface SettingsData {
  llm_base_url: string
  llm_model: string
  llm_api_key_set: boolean
  asr_model_type: string
}

export const api = {
  upload: (file: File): Promise<{ task_id: string; filename: string }> => {
    const form = new FormData()
    form.append('file', file)
    return request('/upload', { method: 'POST', headers: {}, body: form })
  },

  getTask: (id: string): Promise<TaskInfo> => request(`/task/${id}`),

  startTranscribe: (id: string): Promise<{ status: string; task_id: string }> =>
    request(`/transcribe/${id}`, { method: 'POST' }),

  getTranscript: (id: string): Promise<TranscriptData> => request(`/transcript/${id}`),

  streamProgress: (id: string, onProgress: (t: TaskInfo) => void, onDone: (t: TaskInfo) => void, onError: (e: string) => void) => {
    const es = new EventSource(BASE + `/transcribe/${id}/stream`)
    es.addEventListener('progress', (e: any) => onProgress(JSON.parse(e.data)))
    es.addEventListener('done', (e: any) => { es.close(); onDone(JSON.parse(e.data)) })
    es.addEventListener('error', (e: any) => { es.close(); try { onError(JSON.parse(e.data).error) } catch { onError('连接失败') } })
    es.onerror = () => { es.close(); onError('SSE 连接断开') }
    return es
  },

  getTemplates: (): Promise<{ templates: TemplateInfo[] }> => request('/templates'),

  generateMinutes: (task_id: string, template_id: string, custom_instructions = ''): Promise<{ minutes: string }> =>
    request('/generate', {
      method: 'POST',
      body: JSON.stringify({ task_id, template_id, custom_instructions }),
    }),

  getSettings: (): Promise<SettingsData> => request('/settings'),

  updateSettings: (s: Record<string, any>): Promise<{ status: string }> =>
    request('/settings', { method: 'POST', body: JSON.stringify(s) }),
}
