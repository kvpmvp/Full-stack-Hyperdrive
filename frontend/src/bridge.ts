declare global {
  interface Window {
    connectedAccount?: string | null
  }
}

export function setConnectedAccount(addr: string | null) {
  window.connectedAccount = addr ?? null
  // Also fire a small event in case other scripts wish to react
  window.dispatchEvent(new CustomEvent('wallet:activeAddress', { detail: { address: addr } }))
}