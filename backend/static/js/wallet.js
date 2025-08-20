// Hyperdrive wallet helper (homepage + project page) — React-driven version.
// React widget sets `window.connectedAccount` and dispatches `wallet:activeAddress` events.

let connectedAddr = null;

// ---- UI helpers ----
function shorten(addr) {
  return addr ? addr.slice(0, 6) + "..." + addr.slice(-4) : "";
}

function reflectConnection(addr) {
  // Store local state
  connectedAddr = addr || null;

  // Project page widgets
  const pd = document.getElementById("connected-address");
  if (pd) pd.textContent = connectedAddr ? `Connected: ${connectedAddr}` : "Not connected";

  const btnProject = document.getElementById("btn-connect");
  if (btnProject) btnProject.textContent = connectedAddr ? `Connected: ${shorten(connectedAddr)}` : "Connect Wallet";

  // Home page info (index.html)
  const homeInfo = document.getElementById("connected-address-home");
  if (homeInfo) homeInfo.textContent = connectedAddr ? `Connected: ${connectedAddr}` : "";
}

// Initialize from any pre-set global (React widget may have set this before we loaded)
function initFromGlobal() {
  const preset = window.connectedAccount || null;
  reflectConnection(preset);
}

// React widget will dispatch this whenever active address changes
window.addEventListener("wallet:activeAddress", (e) => {
  const addr = e?.detail?.address || null;
  reflectConnection(addr);
});

// ---- Optional Pera UMD signer (only if present) ----
function resolvePeraCtor() {
  let mod = window.PeraWalletConnect;
  if (!mod) return null;
  if (mod && typeof mod === "object" && typeof mod.default === "function") mod = mod.default;
  return typeof mod === "function" ? mod : null;
}

// ---- Signing helper ----
// If a Pera UMD signer is present, use it. Otherwise, we assume signing is handled by the React widget,
// or you can add a backend `/api/broadcast` to relay signed blobs.
async function signAndSend(raws) {
  if (!connectedAddr) throw new Error("Connect a wallet first (top-right Connect Wallet).");

  const txns = Array.isArray(raws) ? raws : [raws];
  const decoded = txns.map((b64) =>
    new Uint8Array(atob(b64).split("").map((c) => c.charCodeAt(0)))
  );

  const PeraCtor = resolvePeraCtor();
  if (PeraCtor) {
    // 416002 = TestNet; adjust if needed
    const pera = window._wallet || new PeraCtor({ chainId: 416002 });
    const signed = await pera.signTransaction([decoded]);

    // Prototype: we don't auto-broadcast. Add a server endpoint if desired.
    alert(
      "Signed! Submit the signed blob to your node/relay.\n(Dev tip: add an /api/broadcast endpoint to send it from the server.)"
    );
    return signed;
  }

  // No UMD signer available — React widget should own signing if you wire it there.
  // For now, provide a helpful message.
  throw new Error(
    "No in-page signer available. The React wallet widget manages connections; " +
    "either wire signing there or add a server /api/broadcast to relay signed blobs."
  );
}

// ---- Page wiring: contribute / claim / refund ----
document.addEventListener("DOMContentLoaded", () => {
  // Reflect any previously stored connection
  initFromGlobal();

  // Contribute
  const btnContrib = document.getElementById("btn-contribute");
  if (btnContrib) {
    btnContrib.addEventListener("click", async () => {
      try {
        const amt = parseFloat(document.getElementById("contrib-amt").value || "0");
        if (!amt || amt <= 0) {
          alert("Enter an amount");
          return;
        }
        const res = await fetch(`/api/projects/${projectId}/build_contribution`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ from_address: connectedAddr, amount_algo: amt }),
        }).then((r) => r.json());

        await signAndSend(res.group);
      } catch (e) {
        console.error(e);
        alert(e?.message || String(e));
      }
    });
  }

  // Claim tokens
  const btnClaim = document.getElementById("btn-claim-tokens");
  if (btnClaim) {
    btnClaim.addEventListener("click", async () => {
      try {
        const res = await fetch(`/api/projects/${projectId}/build_claim_tokens`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ address: connectedAddr }),
        }).then((r) => r.json());

        await signAndSend(res.txn);
      } catch (e) {
        console.error(e);
        alert(e?.message || String(e));
      }
    });
  }

  // Refund
  const btnRefund = document.getElementById("btn-refund");
  if (btnRefund) {
    btnRefund.addEventListener("click", async () => {
      try {
        const res = await fetch(`/api/projects/${projectId}/build_refund`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ address: connectedAddr }),
        }).then((r) => r.json());

        await signAndSend(res.txn);
      } catch (e) {
        console.error(e);
        alert(e?.message || String(e));
      }
    });
  }
});