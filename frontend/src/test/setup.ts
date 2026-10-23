import '@testing-library/jest-dom';

// Mock ResizeObserver for JSDOM
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Mock Cytoscape container bounding client rect
Element.prototype.getBoundingClientRect = () => ({
  width: 800,
  height: 600,
  top: 0,
  left: 0,
  bottom: 600,
  right: 800,
  x: 0,
  y: 0,
  toJSON: () => {},
});

// Mock window.location for JSDOM relative fetch
if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'location', {
    value: new URL('http://localhost:3000'),
    writable: true,
  });
}
