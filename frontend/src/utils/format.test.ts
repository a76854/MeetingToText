import { describe, it, expect } from 'vitest'
import { formatDateTime, formatDuration } from './format'

describe('formatDateTime', () => {
  it('formats a valid ISO string as YYYY-MM-DD HH:mm', () => {
    const out = formatDateTime('2024-03-15T08:05:00.000Z')
    expect(out).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
  })

  it('pads single-digit month, day, hours and minutes', () => {
    // Use a date where components are single digit; timezone may shift but pattern must hold with padding
    const out = formatDateTime('2024-01-02T03:04:00.000Z')
    expect(out).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
    // Ensure no single-digit segment without padding, e.g. " 3:4" would fail
    expect(out).not.toMatch(/ \d:\d$/)
    expect(out).not.toMatch(/-\d-/)
  })

  it('returns a string containing date and time parts separated by space', () => {
    const out = formatDateTime('2024-12-31T23:59:00.000Z')
    expect(out).toContain(' ')
    const [datePart, timePart] = out.split(' ')
    expect(datePart.split('-')).toHaveLength(3)
    expect(timePart.split(':')).toHaveLength(2)
  })

  it('does not throw for an invalid date string (falls back or returns NaN-filled)', () => {
    expect(() => formatDateTime('not-a-date')).not.toThrow()
    const out = formatDateTime('not-a-date')
    expect(typeof out).toBe('string')
  })

  it('does not throw for empty string', () => {
    expect(() => formatDateTime('')).not.toThrow()
  })
})

describe('formatDuration', () => {
  it('returns empty string for null, undefined and NaN', () => {
    expect(formatDuration(null)).toBe('')
    expect(formatDuration(undefined)).toBe('')
    expect(formatDuration(NaN)).toBe('')
  })

  it('formats 0 seconds as 00:00', () => {
    expect(formatDuration(0)).toBe('00:00')
  })

  it('formats seconds under a minute with zero-padded mm:ss', () => {
    expect(formatDuration(5)).toBe('00:05')
    expect(formatDuration(59)).toBe('00:59')
  })

  it('formats seconds under an hour as mm:ss', () => {
    expect(formatDuration(65)).toBe('01:05')
    expect(formatDuration(3599)).toBe('59:59')
  })

  it('formats one hour exactly as h:mm:ss', () => {
    expect(formatDuration(3600)).toBe('1:00:00')
  })

  it('formats over an hour as h:mm:ss with zero-padded minutes and seconds', () => {
    expect(formatDuration(3661)).toBe('1:01:01')
    expect(formatDuration(7325)).toBe('2:02:05')
  })

  it('floors fractional seconds', () => {
    expect(formatDuration(65.9)).toBe('01:05')
    expect(formatDuration(3600.99)).toBe('1:00:00')
  })
})
