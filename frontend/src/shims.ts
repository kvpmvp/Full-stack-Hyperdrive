// Minimal browser shims for libs that expect Node globals.
;(function () {
  const g: any = typeof globalThis !== 'undefined' ? globalThis : window as any

  // process.env.NODE_ENV is commonly read by libs for feature flags
  if (!g.process) g.process = {}
  if (!g.process.env) g.process.env = {}
  if (!g.process.env.NODE_ENV) g.process.env.NODE_ENV = 'production'

  // Some packages look for global
  if (!g.global) g.global = g
})()