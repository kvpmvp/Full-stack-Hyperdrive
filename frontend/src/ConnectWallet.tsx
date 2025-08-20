import React from 'react'
import { useWallet, Wallet, WalletId } from '@txnlab/use-wallet-react'
import Account from './Account'
import { setConnectedAccount } from './bridge'

interface ConnectWalletProps {
  openModal: boolean
  closeModal: () => void
}

const ConnectWallet: React.FC<ConnectWalletProps> = ({ openModal, closeModal }) => {
  const { wallets, activeAddress } = useWallet()
  const dialogRef = React.useRef<HTMLDialogElement | null>(null)

  // Open/close the native <dialog> properly
  React.useEffect(() => {
    const dlg = dialogRef.current
    if (!dlg) return
    try {
      if (openModal && !dlg.open) {
        dlg.showModal()
      } else if (!openModal && dlg.open) {
        dlg.close()
      }
    } catch {
      /* ignore if <dialog> unsupported */
    }
  }, [openModal])

  // Keep global bridge in sync for non‑React code
  React.useEffect(() => {
    setConnectedAccount(activeAddress ?? null)
  }, [activeAddress])

  const isKmd = (wallet: Wallet) => wallet.id === WalletId.KMD

  // Treat these error texts as a user-cancel/dismiss (no alert)
  const isDismissError = (err: unknown) => {
    const msg = ((err as any)?.message || String(err || '')).toLowerCase()
    return (
      msg.includes('closed by user') ||
      msg.includes('user closed') ||
      msg.includes('user rejected') ||
      msg.includes('rejected') ||
      msg.includes('cancelled') ||
      msg.includes('canceled') ||
      msg.includes('modal closed')
    )
  }

  // Click handler: close modal first so Pera/Defly UI isn't hidden behind it
  const handleConnectClick = (wallet: Wallet) => async (e: React.MouseEvent) => {
    e.preventDefault()

    // Close the selector immediately for clean UX
    const dlg = dialogRef.current
    try {
      if (dlg?.open) dlg.close()
    } catch {}

    // Defer connect() to next frame so the close renders first
    requestAnimationFrame(async () => {
      try {
        await wallet.connect()
        // Success → nothing else to do; Account shows up next time user opens selector
      } catch (err) {
        if (isDismissError(err)) {
          // User simply closed the provider popup or canceled → do nothing
          console.debug('Wallet connect dismissed:', err)
          return
        }
        console.error('Wallet connect error:', err)
        alert((err as Error)?.message ?? String(err))
        // If you prefer to reopen the selector on real errors, uncomment:
        // try { dlg?.showModal() } catch {}
      }
    })
  }

  return (
    <dialog
      ref={dialogRef}
      className="rounded-xl bg-slate-900 text-slate-100 p-0 backdrop:bg-black/50 w-[32rem] max-w-[95vw] border border-slate-700"
      onClose={closeModal}
    >
      <form method="dialog" className="p-5">
        <div className="flex items-start justify-between">
          <h3 className="font-bold text-2xl">Select wallet provider</h3>
          <button
            aria-label="Close"
            className="px-2 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-sm"
            onClick={(e) => {
              e.preventDefault()
              closeModal()
            }}
          >
            ✕
          </button>
        </div>

        <div className="grid m-2 pt-5">
          {activeAddress && (
            <>
              <Account />
              <div className="my-4 h-px bg-slate-700" />
            </>
          )}

          {!activeAddress &&
            wallets?.map((wallet) => (
              <button
                data-test-id={`${wallet.id}-connect`}
                className="border border-teal-800 m-2 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 flex items-center gap-3 text-left"
                key={`provider-${wallet.id}`}
                onClick={handleConnectClick(wallet)}
              >
                {!isKmd(wallet) && (
                  <img
                    alt={`wallet_icon_${wallet.id}`}
                    src={wallet.metadata.icon}
                    style={{ objectFit: 'contain', width: '30px', height: 'auto' }}
                  />
                )}
                <span>{isKmd(wallet) ? 'LocalNet Wallet' : wallet.metadata.name}</span>
              </button>
            ))}
        </div>

        <div className="flex justify-end gap-2 mt-6">
          <button
            data-test-id="close-wallet-modal"
            className="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700"
            onClick={(e) => {
              e.preventDefault()
              closeModal()
            }}
          >
            Close
          </button>
          {activeAddress && (
            <button
              className="px-3 py-2 rounded-lg bg-amber-600 hover:bg-amber-500"
              data-test-id="logout"
              onClick={async (e) => {
                e.preventDefault()
                if (wallets) {
                  const active = wallets.find((w) => w.isActive)
                  if (active) {
                    await active.disconnect()
                    setConnectedAccount(null)
                  } else {
                    localStorage.removeItem('@txnlab/use-wallet:v3')
                    window.location.reload()
                  }
                }
              }}
            >
              Logout
            </button>
          )}
        </div>
      </form>
    </dialog>
  )
}

export default ConnectWallet