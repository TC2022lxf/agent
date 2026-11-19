import '@testing-library/jest-dom/vitest'

// jsdom has no PointerEvent; without it clientX/clientY are dropped from pointer events.
if (typeof window.PointerEvent === 'undefined') {
  class PointerEventPolyfill extends MouseEvent {
    pointerId: number
    constructor(type: string, init: MouseEventInit & { pointerId?: number } = {}) {
      super(type, init)
      this.pointerId = init.pointerId ?? 1
    }
  }
  // @ts-expect-error test-only polyfill
  window.PointerEvent = PointerEventPolyfill
}

// jsdom has no ResizeObserver; the canvas measures its frame with one. Tests never resize,
// so a no-op observer that reports once is enough.
if (typeof globalThis.ResizeObserver === 'undefined') {
  class ResizeObserverStub {
    constructor(_cb: ResizeObserverCallback) {}
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver
}
