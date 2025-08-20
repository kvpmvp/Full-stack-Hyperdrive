// IMPORTANT: load shims before anything else
import './shims'

import React from 'react'
import ReactDOM from 'react-dom/client'
import { WalletProvider, WalletManager, WalletId, NetworkId, useWallet } from '@txnlab/use-wallet-react'
import ConnectWallet from './ConnectWallet'
import { setConnectedAccount, attachWalletBridge } from './bridge'

// Configure use-wallet-react: Pera + Defly only
const manager = new WalletManager({
  wallets: [WalletId.PERA, WalletId.DEFLY /*, WalletId.KMD */],
  defaultNetwork: NetworkId.TESTNET
})

function BridgeInstaller() {
  // Pull signer + activeAddress directly from the hook
  const { activeAddress, signTransactions } = useWallet()

  React.useEffect(() => {
    // Keep your legacy global in sync for labels/fallbacks
    setConnectedAccount(activeAddress ?? null)

    // Install/refresh the bridge using the *hook's* signTransactions
    attachWalletBridge({
      getActiveAddress: () => activeAddress ?? null,
      signTransactions
    })
  }, [activeAddress, signTransactions])

  return null
}

function Widget() {
  const [open, setOpen] = React.useState(false)
  return (
    <WalletProvider manager={manager}>
      <BridgeInstaller />
      <ConnectButton onClick={() => setOpen(true)} />
      <ConnectWallet openModal={open} closeModal={() => setOpen(false)} />
    </WalletProvider>
  )
}

function ConnectButton({ onClick }: { onClick: () => void }) {
  const [addr, setAddr] = React.useState<string | null>(null)

  React.useEffect(() => {
    const handler = (e: any) => setAddr(e?.detail?.address ?? null)
    window.addEventListener('wallet:activeAddress', handler as EventListener)
    return () => window.removeEventListener('wallet:activeAddress', handler as EventListener)
  }, [])

  React.useEffect(() => {
    // Restore last session label on reload
    const raw = localStorage.getItem('@txnlab/use-wallet:v3')
    if (raw) {
      try {
        const st = JSON.parse(raw)
        const a = st?.state?.activeAccount?.address as string | undefined
        if (a) {
          setAddr(a)
          setConnectedAccount(a)
        }
      } catch {}
    }
  }, [])

  const label = addr ? `Connected: ${addr.slice(0, 6)}...${addr.slice(-4)}` : 'Connect Wallet'
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white"
    >
      {label}
    </button>
  )
}

// Mount after DOM is ready, on ALL .connect-wallet nodes
function mountAll() {
  const nodes = Array.from(document.querySelectorAll<HTMLElement>('.connect-wallet'))
  nodes.forEach((el) => {
    if ((el as any).__mounted) return
    ;(el as any).__mounted = true
    ReactDOM.createRoot(el).render(<Widget />)
  })
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', mountAll)
} else {
  mountAll()
}
