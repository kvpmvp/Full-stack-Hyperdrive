import React from 'react'
import { useWallet } from '@txnlab/use-wallet-react'
import { setConnectedAccount } from './bridge'

export default function Account() {
  const { activeAddress, wallets } = useWallet()

  if (!activeAddress) return null

  const disconnect = async () => {
    const active = wallets?.find(w => w.isActive)
    if (active) {
      await active.disconnect()
      setConnectedAccount(null)
    } else {
      localStorage.removeItem('@txnlab/use-wallet:v3')
      location.reload()
    }
  }

  return (
    <div className="flex items-center justify-between p-2 rounded-lg bg-slate-800/50 text-sm">
      <div className="truncate">
        Connected:&nbsp;
        <span className="font-mono">{activeAddress}</span>
      </div>
      <button onClick={disconnect} className="ml-3 px-3 py-1 rounded-lg bg-slate-700 hover:bg-slate-600">
        Disconnect
      </button>
    </div>
  )
}