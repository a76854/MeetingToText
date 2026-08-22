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
  error: string
}

export interface SettingsData {
  llm_base_url: string
  llm_model: string
  llm_api_key_set: boolean
  llm_temperature: number
  llm_max_tokens: number
  asr_model_type: string
  asr_model_name: string
  asr_needs_punc: boolean
  ncpu: number
  asr_batch_size_s: number
  asr_merge_length_s: number
  asr_merge_vad: boolean
  asr_max_single_segment_time: number
  streaming_asr_enabled: boolean
  streaming_asr_model_name: string
  browser_noise_suppression: boolean
  audio_source: string
}

export interface TaskListItem {
  id: string
  filename: string
  status: string
  created_at: string
  duration: number
  has_minutes: boolean
  has_transcript: boolean
  error: string
}

export const api = {
  upload: (file: File): Promise<{ task_id: string; filename: string }> => {
    const form = new FormData()
    form.append('file', file)
    return request('/upload', { method: 'POST', headers: {}, body: form })
  },

  getTask: (id: string): Promise<TaskInfo> => request(`/task/${id}`),

  listTasks: (): Promise<{ tasks: TaskListItem[] }> => request(`/tasks`),

  deleteTask: (id: string): Promise<{ status: string; task_id: string }> =>
    request(`/task/${id}`, { method: 'DELETE' }),

  startTranscribe: (id: string): Promise<{ status: string; task_id: string }> =>
    request(`/transcribe/${id}`, { method: 'POST' }),

  retryTranscribe: (id: string): Promise<{ status: string; task_id: string }> =>
    request(`/transcribe/${id}/retry`, { method: 'POST' }),

  getTranscript: (id: string): Promise<TranscriptData> => request(`/transcript/${id}`),

  updateTranscript: (id: string, segments: any[]): Promise<{ status: string; task_id: string; segment_count: number }> =>
    request(`/transcript/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ segments }),
    }),

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

  updateMinutes: (task_id: string, minutes: string): Promise<{ minutes: string }> =>
    request(`/minutes/${task_id}`, {
      method: 'PUT',
      body: JSON.stringify({ minutes }),
    }),

  getSettings: (): Promise<SettingsData> => request('/settings'),

  updateSettings: (s: Record<string, any>): Promise<{ status: string }> =>
    request('/settings', { method: 'POST', body: JSON.stringify(s) }),

  deleteSetting: (key: string): Promise<{ status: string; key: string }> =>
    request(`/settings/${encodeURIComponent(key)}`, { method: 'DELETE' }),

  exportUrl: (id: string, format: string) => `${BASE}/export/${id}?format=${encodeURIComponent(format)}`,

  audioUrl: (id: string) => `${BASE}/audio/${id}`,
}
