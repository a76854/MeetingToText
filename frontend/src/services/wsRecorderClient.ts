/**
 * Pure-TypeScript transport for the /api/record/{task_id} websocket.
 *
 * Owns everything about the WIRE: socket lifecycle, outbound frame builders,
 * inbound frame dispatch, heartbeat, exponential-backoff reconnect engine, and
 * the outage "gap" MediaRecorder. Zero Vue/UI knowledge — every inbound frame
 * is reported through `WsRecorderCallbacks`; every UI-state question it needs
 * answered goes through the `WsRecorderHost` accessors.
 *
 * Why a class, not a composable: recording survives route changes, so this is
 * a module-level singleton (created by recorder.ts). The server-side mirror of
 * every frame lives in backend/app/services/record_session.py,
 * section "## Wire protocol contract".
 */
export interface WsRecorderCallbacks {
  /** {"type":"partial","text":..,"final":?} — live ASR text chunk */
  onPartial: (text: string | undefined, isFinal: boolean) => void
  /** {"status":"resumed"} — server adopted our suspended session */
  onResumed: () => void
  /** {"status":"done","task_id":..} — navigate to transcript; gap blob uploads as second task */
  onDone: (taskId: string, gapBlob: Blob | null) => Promise<void>
  /** {"status":"error","code":"session_busy"} — fatal only outside a reconnect */
  onSessionBusy: (message: string | undefined) => void
  /** {"status":"error"} — reset session; salvage gap audio or surface error */
  onError: (message: string | undefined, gapBlob: Blob | null) => void
  /** {"status":"discarded"} — needs no client action (cancel path) */
  onDiscarded: () => void
  /** transport dropped mid-recording for the first time in a cycle */
  onConnectionLost: () => void
  /** reconnect grace deadline exceeded — fall back to local salvage */
  onGiveUpReconnect: () => void
  /** reconnect socket adopted: awaiting the server's resumed confirmation */
  onReconnectAdopted: () => void
}

export interface WsRecorderHost {
  /** current recording task id ('' before start) */
  taskId: () => string
  /** orchestrator state === 'recording' */
  isRecording: () => boolean
  /** orchestrator state === 'stopping' */
  isStopping: () => boolean
  /** live mic stream for the gap recorder; null before capture starts */
  stream: () => MediaStream | null
  /** orchestrator full teardown (called from the done/error handlers) */
  resetAll: () => void
}

/** Preferred webm container for MediaRecorder; plain 'audio/webm' as fallback. */
export function pickWebmMime(): string {
  return MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : 'audio/webm'
}

/** ws:// or wss:// URL of the recording session endpoint. */
export function wsUrl(id: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/api/record/${id}`
}

const HEARTBEAT_MS = 10_000 // server liveness death = 3x grace; ping keeps it alive
const RECONNECT_BASE_MS = 1000 // backoff: 1s -> 2s -> 4s ... capped at 5s
const RECONNECT_MAX_MS = 5000
// Matches the backend default reconnect_grace_seconds: past this the server has
// finalized the suspended wav, so adopting would silently split the recording.
const RECONNECT_GIVE_UP_MS = 60_000
const STOP_DELIVER_TIMEOUT_MS = 3000 // bounded single-shot reconnect used when stopping mid-outage

export class WsRecorderClient {
  private ws: WebSocket | null = null
  private sampleRate = 0 // captured once per session; re-sent as config after reconnect
  private reconnectTimer: number | null = null // pending backoff attempt
  private reconnectAttempt = 0 // exponential backoff counter
  private reconnectStartedAt = 0 // Date.now() of first drop; drives give-up deadline
  private reconnecting = false // between first drop and successful reopen / give-up
  private probeSock: WebSocket | null = null // in-flight reconnect socket (pre-open)
  private heartbeatInterval: number | null = null
  private gapRecorder: MediaRecorder | null = null
  private gapChunks: Blob[] = []
  private gapBlob: Blob | null = null // retained outage audio; second task at stop
  private connectTimer: number | null = null // open-timeout for a fresh connect()

  constructor(private host: WsRecorderHost, private cb: WsRecorderCallbacks) {}

  // --- fresh-session connect -------------------------------------------------

  /**
   * Open the socket for a brand-new recording. Resolves once OPEN, rejects on
   * socket error or when the open window expires while the orchestrator is
   * still `preparing`. The orchestrator MUST call attach() before sending any
   * PCM, so inbound frames are routed through the callbacks.
   */
  connect(taskId: string, timeoutMs: number, stillPreparing: () => boolean): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      let sock: WebSocket
      try {
        sock = new WebSocket(wsUrl(taskId))
      } catch {
        reject(new Error('ws_error'))
        return
      }
      this.ws = sock
      sock.binaryType = 'arraybuffer'
      this.connectTimer = window.setTimeout(() => {
        if (stillPreparing()) reject(new Error('ws_timeout'))
      }, timeoutMs)
      sock.onopen = () => { this.clearConnectTimer(); resolve() }
      sock.onerror = () => { this.clearConnectTimer(); reject(new Error('ws_error')) }
    })
  }

  /** Is the current socket still in the process of opening? */
  isConnecting(): boolean {
    return this.ws !== null && this.ws.readyState !== WebSocket.OPEN
  }

  /** Is the current socket open and usable for sending? */
  isOpen(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN
  }

  // --- outbound frame builders ----------------------------------------------

  /** {"type":"config","sample_rate":..} — sent on open and after every reconnect */
  sendConfig(sampleRate: number): void {
    if (!this.ws) return
    try { this.ws.send(JSON.stringify({ type: 'config', sample_rate: sampleRate })) } catch {}
  }

  /** {"action":"stop"} — raw send; callers wrap in try/catch where they must */
  sendStop(): void {
    this.ws!.send(JSON.stringify({ action: 'stop' }))
  }

  /** {"action":"discard"} — raw send; callers wrap in try/catch where they must */
  sendDiscard(): void {
    this.ws!.send(JSON.stringify({ action: 'discard' }))
  }

  /**
   * Convert a Float32 worklet chunk to int16 PCM and stream it. No-op while
   * the socket is not OPEN (the gap recorder covers such windows).
   */
  sendPcm(f32: Float32Array): void {
    if (!this.isOpen()) return
    const i16 = new Int16Array(f32.length)
    for (let i = 0; i < f32.length; i++) {
      const s = Math.max(-1, Math.min(1, f32[i]))
      i16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
    }
    this.ws!.send(i16.buffer)
  }

  setSampleRate(sr: number): void {
    this.sampleRate = sr
  }

  // --- inbound dispatch (attachWsHandlers) -----------------------------------

  /**
   * Route inbound frames through the callbacks. Attached to the initial socket
   * after media acquisition, and re-attached to every adopted reconnect socket.
   */
  attach(): void {
    if (!this.ws) return
    this.ws.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'partial') {
          this.cb.onPartial(msg.text, !!msg.final)
        } else if (msg.status === 'resumed') {
          // Server adopted the suspended session after our reconnect.
          this.cb.onResumed()
        } else if (msg.status === 'done') {
          // Capture the retained gap BEFORE the orchestrator resets (reset
          // discards gap state), then hand both over for navigation/upload.
          const gapToUpload = this.gapBlob
          await this.cb.onDone(msg.task_id || '', gapToUpload)
        } else if (msg.status === 'error' && msg.code === 'session_busy') {
          // Second concurrent WS for this task. While reconnecting this is just
          // a stale owner: retry on the next backoff tick. Otherwise fatal.
          if (this.reconnecting) {
            try { this.ws?.close() } catch {}
            this.ws = null
          } else {
            this.cb.onSessionBusy(msg.message)
          }
        } else if (msg.status === 'error') {
          const gapSalvage = this.gapBlob
          this.cb.onError(msg.message, gapSalvage)
        }
        // {"status":"discarded"} needs no client action (cancel path).
      } catch {}
    }
    this.ws.onclose = () => { this.handleConnectionLost() }
    this.ws.onerror = () => { this.handleConnectionLost() }
  }

  close(): void {
    this.clearConnectTimer()
    if (!this.ws) return
    try { this.ws.close() } catch {}
    this.ws = null
  }

  // --- heartbeat: {"type":"ping"} every 10s while the WS is open -------------

  startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeatInterval = window.setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try { this.ws.send(JSON.stringify({ type: 'ping' })) } catch {}
      }
    }, HEARTBEAT_MS)
  }

  stopHeartbeat(): void {
    if (this.heartbeatInterval) { clearInterval(this.heartbeatInterval); this.heartbeatInterval = null }
  }

  // --- gap capture: local MediaRecorder covering the outage window ------------

  startGapRecorder(): void {
    const s = this.host.stream()
    if (this.gapRecorder || !s) return
    try {
      this.gapChunks = []
      this.gapRecorder = new MediaRecorder(s, { mimeType: pickWebmMime() })
      this.gapRecorder.ondataavailable = (e) => {
        if (this.gapRecorder && e.data.size > 0) this.gapChunks.push(e.data)
      }
      this.gapRecorder.start(1000)
    } catch { this.gapRecorder = null }
  }

  // Stop the gap recorder and RETAIN its audio: appended to gapBlob so repeated
  // outages in one session accumulate into one blob.
  async finalizeGapCapture(): Promise<void> {
    const rec = this.gapRecorder
    if (!rec) return
    this.gapRecorder = null
    if (rec.state === 'recording') {
      try { rec.requestData() } catch {}
      await new Promise(r => setTimeout(r, 300))
      try { rec.stop() } catch {}
    }
    if (this.gapChunks.length > 0) {
      const part = new Blob(this.gapChunks, { type: 'audio/webm' })
      this.gapBlob = this.gapBlob ? new Blob([this.gapBlob, part], { type: 'audio/webm' }) : part
    }
    this.gapChunks = []
  }

  discardGap(): void {
    if (this.gapRecorder && this.gapRecorder.state !== 'inactive') {
      try { this.gapRecorder.stop() } catch {}
    }
    this.gapRecorder = null
    this.gapChunks = []
    this.gapBlob = null
  }

  getGapBlob(): Blob | null {
    return this.gapBlob
  }

  clearGapBlob(): void {
    this.gapBlob = null
  }

  // --- reconnect loop: exponential backoff until reopen or grace-expiry -------

  cancelReconnectLoop(): void {
    if (this.reconnectTimer !== null) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null }
    if (this.probeSock && this.probeSock.readyState !== WebSocket.OPEN) {
      try { this.probeSock.close() } catch {}
    }
    this.probeSock = null
    this.reconnecting = false
    this.reconnectStartedAt = 0
    this.reconnectAttempt = 0
  }

  /** Transport dropped: capture the outage locally and start the backoff loop. */
  handleConnectionLost(): void {
    if (!this.host.isRecording()) return
    this.stopHeartbeat()
    this.ws = null
    this.startGapRecorder()
    if (this.reconnecting) {
      this.scheduleReconnect()
      return
    }
    this.reconnecting = true
    this.reconnectAttempt = 0
    this.reconnectStartedAt = Date.now()
    this.cb.onConnectionLost()
    this.scheduleReconnect()
  }

  /**
   * Single bounded reconnect used by stopRecording when the WS is already down:
   * resolves true once the stop intent was delivered (done/error then flow
   * through the callbacks), false if the server stayed unreachable.
   */
  tryDeliverStop(): Promise<boolean> {
    return new Promise((resolve) => {
      let settled = false
      const settle = (v: boolean) => { if (!settled) { settled = true; resolve(v) } }
      let sock: WebSocket
      try { sock = new WebSocket(wsUrl(this.host.taskId())) } catch { settle(false); return }
      sock.binaryType = 'arraybuffer'
      const failT = window.setTimeout(() => {
        if (!settled) { try { sock.close() } catch {} }
      }, STOP_DELIVER_TIMEOUT_MS)
      sock.onopen = () => {
        clearTimeout(failT)
        if (settled) { try { sock.close() } catch {}; return }
        this.adoptSocket(sock, false)
        settle(true)
      }
      sock.onclose = () => { clearTimeout(failT); settle(false) }
      sock.onerror = () => {}
    })
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) return
    if (Date.now() - this.reconnectStartedAt >= RECONNECT_GIVE_UP_MS) {
      this.giveUpReconnect()
      return
    }
    const delay = Math.min(RECONNECT_BASE_MS * 2 ** this.reconnectAttempt, RECONNECT_MAX_MS)
    this.reconnectAttempt++
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      if (this.host.isRecording()) this.tryReconnect()
    }, delay)
  }

  private giveUpReconnect(): void {
    this.cancelReconnectLoop()
    // Grace clearly expired server-side: adopting would split the recording.
    // Keep the gap recorder running as plain local capture; stopRecording routes
    // to the gap-upload path via the closed-WS branch.
    this.cb.onGiveUpReconnect()
  }

  private tryReconnect(): void {
    if (!this.host.isRecording()) return
    let sock: WebSocket
    try { sock = new WebSocket(wsUrl(this.host.taskId())) } catch { this.scheduleReconnect(); return }
    sock.binaryType = 'arraybuffer'
    this.probeSock = sock
    sock.onopen = () => {
      if (this.host.isStopping()) {
        this.adoptSocket(sock, false)
        return
      }
      if (!this.host.isRecording()) {
        try { sock.close() } catch {}
        return
      }
      this.adoptSocket(sock, true)
    }
    sock.onclose = () => {
      if (this.probeSock === sock) this.probeSock = null
      this.handleConnectionLost()
    }
    sock.onerror = () => { this.handleConnectionLost() }
  }

  private adoptSocket(sock: WebSocket, resume: boolean): void {
    this.ws = sock
    this.probeSock = null
    this.attach()
    try { sock.send(JSON.stringify({ type: 'config', sample_rate: this.sampleRate })) } catch {}
    if (resume) {
      this.startHeartbeat()
      this.reconnecting = false
      this.reconnectStartedAt = 0
      this.reconnectAttempt = 0
      this.cb.onReconnectAdopted()
      void this.finalizeGapCapture()
    } else {
      // Stopping mid-outage: hand {"action":"stop"} over now so the server
      // finalizes the pre-disconnect wav immediately; "done" (and the gap
      // upload) arrive through the callbacks.
      try { sock.send(JSON.stringify({ action: 'stop' })) } catch {}
    }
  }

  private clearConnectTimer(): void {
    if (this.connectTimer !== null) { clearTimeout(this.connectTimer); this.connectTimer = null }
  }
}
