import { describe, expect, it } from 'vitest'
import { computePdfAnchor, pdfRectsToViewport } from './pdfAnchor'

const viewport = {
  convertToPdfPoint: (x: number, y: number): [number, number] => [x / 2, 100 - y / 2],
  convertToViewportRectangle: (
    [x1, y1, x2, y2]: [number, number, number, number],
  ): [number, number, number, number] => [x1 * 2, (100 - y1) * 2, x2 * 2, (100 - y2) * 2],
}

describe('computePdfAnchor', () => {
  it('stores page-local semantic offsets and PDF-space geometry', () => {
    const range = {
      toString: () => 'important   quote',
      getClientRects: () => [{ left: 30, top: 50, width: 80, height: 20 }],
    } as unknown as Range
    const pageContainer = {
      getBoundingClientRect: () => ({ left: 10, top: 20 }),
    } as unknown as HTMLElement

    const result = computePdfAnchor({
      range,
      viewport,
      pageContainer,
      pageText: 'Before important quote after',
    })

    expect(result).not.toBeNull()
    expect(result?.textContent).toBe('important quote')
    expect(result?.textStart).toBe(7)
    expect(result?.textEnd).toBe(22)
    expect(result?.prefix).toBe('Before')
    expect(result?.suffix).toBe('after')
    expect(result?.rects).toEqual([{ x: 10, y: 75, width: 40, height: 10 }])
  })

  it('keeps a paintable anchor when extracted text cannot be aligned', () => {
    const range = {
      toString: () => 'visual only',
      getClientRects: () => [{ left: 0, top: 0, width: 20, height: 10 }],
    } as unknown as Range
    const pageContainer = {
      getBoundingClientRect: () => ({ left: 0, top: 0 }),
    } as unknown as HTMLElement

    const result = computePdfAnchor({ range, viewport, pageContainer, pageText: 'different extraction' })

    expect(result?.textStart).toBeNull()
    expect(result?.textEnd).toBeNull()
    expect(result?.rects).toHaveLength(1)
  })
})

describe('pdfRectsToViewport', () => {
  it('normalizes the PDF bottom-left origin for absolute overlays', () => {
    expect(pdfRectsToViewport([{ x: 10, y: 75, width: 40, height: 10 }], viewport)).toEqual([
      { left: 20, top: 30, width: 80, height: 20 },
    ])
  })
})
