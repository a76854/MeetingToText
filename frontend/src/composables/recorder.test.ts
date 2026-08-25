import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// --- hoisted mocks so factory and test share the same objects ---
const mockApi = vi.hoisted(() => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
  upload: vi.fn(),
  deleteRecordingSession: vi.fn().mockReturnValue(Promise.resolve({ status: 'ok' })),
}))

const mockCaptureInstance = vi.hoisted(() => ({
  acquireMediaStream: vi.fn(),
  startStreaming: vi.fn(),
  startVolumeOnly: vi.fn(),
  teardownGraph: vi.fn(),
  teardownTracks: vi.fn(),
  getStream: vi.fn().mockReturnValue(null),
  getSampleRate: vi.fn().mockReturnValue(48000),
  setOnVolume: vi.fn(),
}))

const mockClientInstance = vi.hoisted(() => ({
  connect: vi.fn().mockResolvedValue(undefined),
  isOpen: vi.fn().mockReturnValue(false),
  isConnecting: vi.fn().mockReturnValue(false),
  attach: vi.fn(),
  sendConfig: vi.fn(),
  sendStop: vi.fn(),
  sendDiscard: vi.fn(),
  sendPcm: vi.fn(),
  setSampleRate: vi.fn(),
  close: vi.fn(),
  cancelReconnectLoop: vi.fn(),
  stopHeartbeat: vi.fn(),
  discardGap: vi.fn(),
  startHeartbeat: vi.fn(),
  teardownAudioGraph: vi.fn(),
  finalizeGapCapture: vi.fn().mockResolvedValue(undefined),
  getGapBlob: vi.fn().mockReturnValue(null),
  clearGapBlob: vi.fn(),
  tryDeliverStop: vi.fn().mockResolvedValue(false),
}))

vi.mock('../api/client', () => ({
  api: mockApi,
}))

vi.mock('../services/wsRecorderClient', () => ({
  WsRecorderClient: vi.fn(function MockWs() {
    return mockClientInstance
  }),
  pickWebmMime: vi.fn().mockReturnValue('audio/webm'),
}))

vi.mock('./useAudioCapture', () => ({
  useAudioCapture: vi.fn(() => mockCaptureInstance),
}))

vi.mock('../utils/download', () => ({
  downloadBlob: vi.fn(),
}))

// Import after mocks are hoisted
import {
  state,
  taskId,
  error,
  timer,
  volume,
  liveText,
  liveStatus,
  liveError,
  warning,
  streamingAsrEnabled,
  noiseSuppression,
  audioSource,
  loadSettings,
  toggleStreamingAsr,
  cancelRecording,
} from './recorder'

describe('recorder composable — offline state transitions', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    // reset refs to known baseline without invoking media layer
    state.value = 'idle'
    taskId.value = ''
    error.value = ''
    timer.value = '00:00'
    volume.value = 0
    liveText.value = ''
    liveStatus.value = 'idle'
    liveError.value = ''
    warning.value = ''
    streamingAsrEnabled.value = false
    noiseSuppression.value = true
    audioSource.value = 'mic'

    // reset mock call history but keep implementations
    mockApi.getSettings.mockReset()
    mockApi.updateSettings.mockReset()
    mockApi.upload.mockReset()
    mockApi.deleteRecordingSession.mockClear()
    mockCaptureInstance.acquireMediaStream.mockReset()
    mockCaptureInstance.startStreaming.mockReset()
    mockCaptureInstance.startVolumeOnly.mockReset()
    mockCaptureInstance.teardownGraph.mockClear()
    mockCaptureInstance.teardownTracks.mockClear()
    mockCaptureInstance.setOnVolume.mockClear()
    mockCaptureInstance.getStream.mockReturnValue(null)
    mockClientInstance.connect.mockClear()
    mockClientInstance.close.mockClear()
    mockClientInstance.cancelReconnectLoop.mockClear()
    mockClientInstance.stopHeartbeat.mockClear()
    mockClientInstance.discardGap.mockClear()
    mockClientInstance.sendDiscard.mockClear()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts in idle with clean defaults', () => {
    expect(state.value).toBe('idle')
    expect(error.value).toBe('')
    expect(liveStatus.value).toBe('idle')
    expect(streamingAsrEnabled.value).toBe(false)
  })

  it('cancelRecording is a no-op when already idle', () => {
    state.value = 'idle'
    cancelRecording()
    expect(state.value).toBe('idle')
    expect(mockClientInstance.sendDiscard).not.toHaveBeenCalled()
  })

  it('cancelRecording from recording transitions through cancelling to idle after 400ms', () => {
    vi.useFakeTimers()
    state.value = 'recording'
    taskId.value = 'abc123'
    mockClientInstance.isOpen = vi.fn().mockReturnValue(true) as unknown as typeof mockClientInstance.isOpen
    // Re-establish after reset above, isOpen mock was cleared but we set return
    // Need to ensure api.deleteRecordingSession is callable
    mockApi.deleteRecordingSession.mockReturnValue(Promise.resolve({ status: 'ok' }))

    cancelRecording()
    expect(state.value).toBe('cancelling')

    vi.advanceTimersByTime(400)
    expect(state.value).toBe('idle')
    vi.useRealTimers()
  })

  it('loadSettings populates refs on success', async () => {
    mockApi.getSettings.mockResolvedValue({
      streaming_asr_enabled: true,
      browser_noise_suppression: false,
      audio_source: 'mic+system',
    })
    await loadSettings()
    expect(streamingAsrEnabled.value).toBe(true)
    expect(noiseSuppression.value).toBe(false)
    expect(audioSource.value).toBe('mic+system')
  })

  it('loadSettings falls back to defaults when api rejects', async () => {
    streamingAsrEnabled.value = true
    noiseSuppression.value = false
    audioSource.value = 'system'
    mockApi.getSettings.mockRejectedValue(new Error('network'))
    await loadSettings()
    expect(streamingAsrEnabled.value).toBe(false)
    expect(noiseSuppression.value).toBe(true)
    expect(audioSource.value).toBe('mic')
  })

  it('loadSettings defaults audio_source to mic when empty string', async () => {
    mockApi.getSettings.mockResolvedValue({
      streaming_asr_enabled: false,
      browser_noise_suppression: true,
      audio_source: '',
    })
    await loadSettings()
    expect(audioSource.value).toBe('mic')
  })

  it('toggleStreamingAsr updates the ref and persists via api', async () => {
    mockApi.updateSettings.mockResolvedValue({ status: 'ok' })
    streamingAsrEnabled.value = false
    await toggleStreamingAsr(true)
    expect(streamingAsrEnabled.value).toBe(true)
    expect(mockApi.updateSettings).toHaveBeenCalledWith({ streaming_asr_enabled: true })

    await toggleStreamingAsr(false)
    expect(streamingAsrEnabled.value).toBe(false)
    expect(mockApi.updateSettings).toHaveBeenCalledWith({ streaming_asr_enabled: false })
  })

  it('toggleStreamingAsr reverts the ref when persistence fails', async () => {
    mockApi.updateSettings.mockRejectedValue(new Error('fail'))
    streamingAsrEnabled.value = false
    await toggleStreamingAsr(true)
    // should revert to previous value
    expect(streamingAsrEnabled.value).toBe(false)

    streamingAsrEnabled.value = true
    mockApi.updateSettings.mockRejectedValue(new Error('fail'))
    await toggleStreamingAsr(false)
    expect(streamingAsrEnabled.value).toBe(true)
  })

  it('does not invoke any media layer during offline transitions (load/toggle/cancel)', async () => {
    mockApi.getSettings.mockResolvedValue({
      streaming_asr_enabled: false,
      browser_noise_suppression: true,
      audio_source: 'mic',
    })
    await loadSettings()
    expect(mockCaptureInstance.acquireMediaStream).not.toHaveBeenCalled()
    expect(mockClientInstance.connect).not.toHaveBeenCalled()

    mockApi.updateSettings.mockResolvedValue({ status: 'ok' })
    await toggleStreamingAsr(true)
    expect(mockCaptureInstance.acquireMediaStream).not.toHaveBeenCalled()

    state.value = 'idle'
    cancelRecording()
    expect(mockCaptureInstance.acquireMediaStream).not.toHaveBeenCalled()
  })
})
