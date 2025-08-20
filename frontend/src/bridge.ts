// frontend/src/bridge.ts
// Expose a stable in-page signer backed by the React hook's signTransactions

import algosdk, { Algodv2, Transaction } from "algosdk"

declare global {
  interface Window {
    connectedAccount?: string | null
    Hyperdrive?: {
      getActiveAddress: () => string | null
      signAndSendGroup: (b64Group: string[]) => Promise<string>
      signAndSendSingle: (b64Txn: string) => Promise<string>
    }
  }
}

/** Keep your existing global + event */
export function setConnectedAccount(addr: string | null) {
  window.connectedAccount = addr ?? null
  window.dispatchEvent(new CustomEvent("wallet:activeAddress", { detail: { address: addr } }))
}

/**
 * Attach the signer bridge using the hook-provided signTransactions() function.
 * We DO NOT call methods on wallet objects anymore.
 */
export function attachWalletBridge(params: {
  getActiveAddress: () => string | null
  signTransactions: (txns: Uint8Array[]) => Promise<Uint8Array[]>
}) {
  const algod = new Algodv2(
    "",
    (import.meta.env.VITE_ALGOD_URL as string) || "https://testnet-api.algonode.cloud",
    ""
  )

  function getActiveAddress(): string | null {
    return params.getActiveAddress()
  }

  async function signAndSendGroup(b64Group: string[]): Promise<string> {
    const addr = getActiveAddress()
    if (!addr) throw new Error("No active wallet. Please connect first.")

    // decode base64 -> unsigned txns -> bytes -> sign -> send
    const unsignedTxns: Transaction[] = b64Group.map((b64) =>
      algosdk.decodeUnsignedTransaction(Buffer.from(b64, "base64"))
    )
    const unsignedBytes: Uint8Array[] = unsignedTxns.map((t) => algosdk.encodeUnsignedTransaction(t))

    const signed: Uint8Array[] = await params.signTransactions(unsignedBytes)
    const { txId } = await algod.sendRawTransaction(signed).do()
    return txId
  }

  async function signAndSendSingle(b64Txn: string): Promise<string> {
    return signAndSendGroup([b64Txn])
  }

  window.Hyperdrive = { getActiveAddress, signAndSendGroup, signAndSendSingle }
  // Let non-React scripts know the bridge is ready
  window.dispatchEvent(new CustomEvent("hyperdrive:bridge-ready"))
}
