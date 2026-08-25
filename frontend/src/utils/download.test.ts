import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { downloadUrl, downloadBlob, downloadText } from './download'

describe('downloadUrl', () => {
  let clickSpy: ReturnType<typeof vi.fn>
  let appended: HTMLElement | null = null
  let removed: HTMLElement | null = null

  beforeEach(() => {
    clickSpy = vi.fn()
    const origCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
      const el = origCreate(tag)
      if (tag === 'a') {
        vi.spyOn(el as HTMLAnchorElement, 'click').mockImplementation(clickSpy as unknown as typeof el.click)
      }
      return el
    }) as unknown as typeof document.createElement)

    vi.spyOn(document.body, 'appendChild').mockImplementation(((node: Node) => {
      appended = node as HTMLElement
      return node
    }) as unknown as typeof document.body.appendChild)

    vi.spyOn(document.body, 'removeChild').mockImplementation(((node: Node) => {
      removed = node as HTMLElement
      return node
    }) as unknown as typeof document.body.removeChild)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    appended = null
    removed = null
  })

  it('creates an anchor, sets href and download, appends, clicks and removes', () => {
    downloadUrl('https://example.com/file.txt', 'file.txt')
    expect(appended).not.toBeNull()
    expect((appended as HTMLAnchorElement).href).toContain('https://example.com/file.txt')
    expect((appended as HTMLAnchorElement).download).toBe('file.txt')
    expect(clickSpy).toHaveBeenCalledTimes(1)
    expect(removed).toBe(appended)
  })

  it('supports empty filename (defers to server disposition)', () => {
    downloadUrl('https://example.com/blob', '')
    expect((appended as HTMLAnchorElement).download).toBe('')
    expect(clickSpy).toHaveBeenCalledTimes(1)
  })
})

describe('downloadBlob', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('creates an object URL, delegates to downloadUrl, and revokes the URL', () => {
    const create = vi.fn().mockReturnValue('blob:mock-url')
    const revoke = vi.fn()
    vi.stubGlobal('URL', {
      createObjectURL: create,
      revokeObjectURL: revoke,
    } as unknown as typeof URL)

    const append = vi.spyOn(document.body, 'appendChild').mockImplementation(((n: Node) => n) as unknown as typeof document.body.appendChild)
    const remove = vi.spyOn(document.body, 'removeChild').mockImplementation(((n: Node) => n) as unknown as typeof document.body.removeChild)
    const origCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
      const el = origCreate(tag)
      if (tag === 'a') vi.spyOn(el as HTMLAnchorElement, 'click').mockImplementation(vi.fn() as unknown as typeof el.click)
      return el
    }) as unknown as typeof document.createElement)

    const blob = new Blob(['hello'], { type: 'text/plain' })
    downloadBlob('hello.txt', blob)

    expect(create).toHaveBeenCalledWith(blob)
    expect(revoke).toHaveBeenCalledWith('blob:mock-url')
    // ensure anchor href received the object URL
    expect(append).toHaveBeenCalled()
    expect(remove).toHaveBeenCalled()
  })

  it('revokes the URL even if downloadUrl append throws', () => {
    const create = vi.fn().mockReturnValue('blob:mock-url')
    const revoke = vi.fn()
    vi.stubGlobal('URL', {
      createObjectURL: create,
      revokeObjectURL: revoke,
    } as unknown as typeof URL)
    vi.spyOn(document.body, 'appendChild').mockImplementation(() => {
      throw new Error('append fail')
    })
    const blob = new Blob(['x'], { type: 'text/plain' })
    expect(() => downloadBlob('x.txt', blob)).toThrow('append fail')
    expect(revoke).toHaveBeenCalledWith('blob:mock-url')
  })
})

describe('downloadText', () => {
  it('wraps text in a Blob with the given MIME and delegates to downloadBlob', () => {
    const create = vi.fn().mockReturnValue('blob:text-url')
    const revoke = vi.fn()
    vi.stubGlobal('URL', {
      createObjectURL: create,
      revokeObjectURL: revoke,
    } as unknown as typeof URL)

    const append = vi.spyOn(document.body, 'appendChild').mockImplementation(((n: Node) => n) as unknown as typeof document.body.appendChild)
    const remove = vi.spyOn(document.body, 'removeChild').mockImplementation(((n: Node) => n) as unknown as typeof document.body.removeChild)
    const origCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
      const el = origCreate(tag)
      if (tag === 'a') vi.spyOn(el as HTMLAnchorElement, 'click').mockImplementation(vi.fn() as unknown as typeof el.click)
      return el
    }) as unknown as typeof document.createElement)

    downloadText('note.md', '# Hello world', 'text/markdown;charset=utf-8')
    expect(create).toHaveBeenCalledTimes(1)
    const blobArg = create.mock.calls[0][0] as Blob
    expect(blobArg.type).toBe('text/markdown;charset=utf-8')
    expect(revoke).toHaveBeenCalledWith('blob:text-url')
    expect(append).toHaveBeenCalled()
    expect(remove).toHaveBeenCalled()
    vi.restoreAllMocks()
  })

  it('defaults to text/markdown;charset=utf-8 when no MIME given', () => {
    const create = vi.fn().mockReturnValue('blob:url')
    const revoke = vi.fn()
    vi.stubGlobal('URL', {
      createObjectURL: create,
      revokeObjectURL: revoke,
    } as unknown as typeof URL)
    vi.spyOn(document.body, 'appendChild').mockImplementation(((n: Node) => n) as unknown as typeof document.body.appendChild)
    vi.spyOn(document.body, 'removeChild').mockImplementation(((n: Node) => n) as unknown as typeof document.body.removeChild)
    const origCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
      const el = origCreate(tag)
      if (tag === 'a') vi.spyOn(el as HTMLAnchorElement, 'click').mockImplementation(vi.fn() as unknown as typeof el.click)
      return el
    }) as unknown as typeof document.createElement)

    downloadText('a.md', 'hello')
    const blobArg = create.mock.calls[0][0] as Blob
    expect(blobArg.type).toBe('text/markdown;charset=utf-8')
    expect(revoke).toHaveBeenCalled()
    vi.restoreAllMocks()
  })
})
