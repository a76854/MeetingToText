import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api } from './client'

function mockFetchOnce(response: Partial<Response> & { json?: () => Promise<unknown>; statusText?: string; ok?: boolean }) {
  const fetchMock = vi.fn().mockResolvedValue(response as Response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('api/client request layer', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('prefixes URLs with /api for getTask', async () => {
    const json = vi.fn().mockResolvedValue({ id: '1', status: 'done', filename: 'a.wav' })
    const fetchMock = mockFetchOnce({ ok: true, json } as unknown as Response)
    const res = await api.getTask('abc123')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/task/abc123')
    expect((opts as RequestInit).method).toBeUndefined()
    expect(res).toEqual({ id: '1', status: 'done', filename: 'a.wav' })
  })

  it('listTasks calls /api/tasks with /api prefix', async () => {
    const json = vi.fn().mockResolvedValue({ tasks: [] })
    const fetchMock = mockFetchOnce({ ok: true, json } as unknown as Response)
    await api.listTasks()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/tasks')
  })

  it('deleteTask uses DELETE method and returns {status:"ok"} shape', async () => {
    const json = vi.fn().mockResolvedValue({ status: 'ok' })
    const fetchMock = mockFetchOnce({ ok: true, json } as unknown as Response)
    const res = await api.deleteTask('my-id')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/task/my-id')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('DELETE')
    expect(res).toEqual({ status: 'ok' })
  })

  it('deleteSetting encodes the key and uses DELETE', async () => {
    const json = vi.fn().mockResolvedValue({ status: 'ok' })
    const fetchMock = mockFetchOnce({ ok: true, json } as unknown as Response)
    const res = await api.deleteSetting('llm_api_key')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/settings/llm_api_key')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('DELETE')
    expect(res).toEqual({ status: 'ok' })

    // key with special chars is encoded
    const fetchMock2 = mockFetchOnce({ ok: true, json: vi.fn().mockResolvedValue({ status: 'ok' }) } as unknown as Response)
    vi.stubGlobal('fetch', fetchMock2)
    await api.deleteSetting('a/b c')
    expect(fetchMock2.mock.calls[0][0]).toBe('/api/settings/a%2Fb%20c')
  })

  it('deleteRecordingSession returns {status:"ok"} shape aligned to backend', async () => {
    const json = vi.fn().mockResolvedValue({ status: 'ok' })
    const fetchMock = mockFetchOnce({ ok: true, json } as unknown as Response)
    const res = await api.deleteRecordingSession('task-1')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/record/task-1')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('DELETE')
    expect(res).toEqual({ status: 'ok' })
  })

  it('normalizes error via data.detail when response is not ok', async () => {
    const json = vi.fn().mockResolvedValue({ detail: 'Not found' })
    const fetchMock = mockFetchOnce({ ok: false, statusText: 'Not Found', json } as unknown as Response)
    await expect(api.getTask('missing')).rejects.toThrow('Not found')
    expect(fetchMock).toHaveBeenCalled()
  })

  it('falls back to statusText when detail is missing', async () => {
    const json = vi.fn().mockResolvedValue({})
    const fetchMock = mockFetchOnce({ ok: false, statusText: 'Internal Error', json } as unknown as Response)
    await expect(api.listTasks()).rejects.toThrow('Internal Error')
    expect(fetchMock).toHaveBeenCalled()
  })

  it('falls back to statusText when json parsing fails', async () => {
    const json = vi.fn().mockRejectedValue(new SyntaxError('bad json'))
    const fetchMock = mockFetchOnce({ ok: false, statusText: 'Bad Gateway', json } as unknown as Response)
    await expect(api.getTask('x')).rejects.toThrow('Bad Gateway')
    expect(fetchMock).toHaveBeenCalled()
  })

  it('exportUrl and audioUrl build /api-prefixed URLs without calling fetch', () => {
    expect(api.exportUrl('id123', 'srt')).toBe('/api/export/id123?format=srt')
    expect(api.exportUrl('id123', 'a/b')).toBe('/api/export/id123?format=a%2Fb')
    expect(api.audioUrl('id999')).toBe('/api/audio/id999')
    // ensure fetch was never called in this test
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    // calling pure helpers again should not invoke fetch
    api.exportUrl('x', 'txt')
    api.audioUrl('y')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('sends JSON Content-Type header by default', async () => {
    const json = vi.fn().mockResolvedValue({ tasks: [] })
    const fetchMock = mockFetchOnce({ ok: true, json } as unknown as Response)
    await api.getSettings()
    const opts = fetchMock.mock.calls[0][1] as RequestInit
    expect((opts.headers as Record<string, string>)['Content-Type']).toBe('application/json')
  })

  it('updateSettings POSTs JSON body', async () => {
    const json = vi.fn().mockResolvedValue({ status: 'ok' })
    const fetchMock = mockFetchOnce({ ok: true, json } as unknown as Response)
    await api.updateSettings({ llm_model: 'gpt-4' })
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/settings')
    expect(opts.method).toBe('POST')
    expect(opts.body).toBe(JSON.stringify({ llm_model: 'gpt-4' }))
  })
})
