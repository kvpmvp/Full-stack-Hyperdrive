// backend/static/js/wallet.js
// Hyperdrive wallet helper (homepage + project page) — React-bridge-driven version.

let connectedAddr = null;

/* ---------------------------------- UI ---------------------------------- */
function shorten(addr) {
  return addr ? addr.slice(0, 6) + "..." + addr.slice(-4) : "";
}

function reflectConnection(addr) {
  connectedAddr = addr || null;

  const pd = document.getElementById("connected-address");
  if (pd) pd.textContent = connectedAddr ? `Connected: ${connectedAddr}` : "Not connected";

  const btnProject = document.getElementById("btn-connect");
  if (btnProject) btnProject.textContent = connectedAddr ? `Connected: ${shorten(connectedAddr)}` : "Connect Wallet";

  const homeInfo = document.getElementById("connected-address-home");
  if (homeInfo) homeInfo.textContent = connectedAddr ? `Connected: ${connectedAddr}` : "";
}

function initFromGlobal() {
  const fromBridge =
    (window.Hyperdrive && window.Hyperdrive.getActiveAddress && window.Hyperdrive.getActiveAddress()) || null;
  const preset = fromBridge || window.connectedAccount || null;
  reflectConnection(preset);
}

window.addEventListener("wallet:activeAddress", (e) => {
  const addr = e?.detail?.address || null;
  reflectConnection(addr);
});

/* ------------------------ Signer bridge readiness ------------------------ */
async function ensureSignerReady(timeoutMs = 5000) {
  if (window.Hyperdrive && typeof window.Hyperdrive.signAndSendGroup === "function") return;

  let resolved = false;
  const onReady = () => {
    if (resolved) return;
    resolved = true;
    window.removeEventListener("hyperdrive:bridge-ready", onReady);
  };
  window.addEventListener("hyperdrive:bridge-ready", onReady);

  const poll = new Promise((resolve) => {
    const id = setInterval(() => {
      if (window.Hyperdrive && typeof window.Hyperdrive.signAndSendGroup === "function") {
        clearInterval(id);
        resolve();
      }
    }, 100);
  });

  const timeout = new Promise((resolve) => setTimeout(resolve, timeoutMs));
  await Promise.race([poll, timeout]);
}

function getActiveAddress() {
  return (
    (window.Hyperdrive && window.Hyperdrive.getActiveAddress && window.Hyperdrive.getActiveAddress()) ||
    window.connectedAccount ||
    null
  );
}

/* ---------------------------- Signing helpers ---------------------------- */
async function signAndSendGroup(b64Group) {
  await ensureSignerReady();
  if (!window.Hyperdrive || typeof window.Hyperdrive.signAndSendGroup !== "function") {
    throw new Error("No wallet connected yet. Please connect Pera or Defly first.");
  }
  return window.Hyperdrive.signAndSendGroup(b64Group); // returns txId
}

async function signAndSendSingle(b64Txn) {
  await ensureSignerReady();
  if (!window.Hyperdrive || typeof window.Hyperdrive.signAndSendSingle !== "function") {
    throw new Error("No wallet connected yet. Please connect Pera or Defly first.");
  }
  return window.Hyperdrive.signAndSendSingle(b64Txn); // returns txId
}

/* --------------------------------- Wireup -------------------------------- */
document.addEventListener("DOMContentLoaded", () => {
  initFromGlobal();

  // ---- DEPLOY (client-signed): build -> sign -> finalize ----
  const btnDeploy = document.getElementById("btn-deploy");
  if (btnDeploy) {
    btnDeploy.addEventListener("click", async () => {
      const hint = document.getElementById("deploy-hint");
      try {
        await ensureSignerReady();

        const addr = getActiveAddress();
        if (!addr) throw new Error("Connect a wallet first.");

        hint && (hint.textContent = "Building deploy transaction…");
        const r = await fetch(`/api/projects/${projectId}/deploy/build`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ creator_address: addr }),
        });

        const raw = await r.text();
        let data = {};
        try { data = JSON.parse(raw); } catch {}
        if (!r.ok) throw new Error(data.error || raw || `Build deploy failed (${r.status})`);

        const group = data.group;
        if (!group || !group.length) throw new Error(data.error || "No deploy group returned.");

        hint && (hint.textContent = "Waiting for wallet signature…");
        const txId = await signAndSendGroup(group);

        hint && (hint.textContent = "Finalizing deployment…");
        const finR = await fetch(`/api/projects/${projectId}/deploy/finalize`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ txId }),
        });
        const finRaw = await finR.text();
        let fin = {};
        try { fin = JSON.parse(finRaw); } catch {}
        if (!finR.ok) throw new Error(fin.error || finRaw || `Finalize failed (${finR.status})`);

        hint && (hint.textContent = `Deployed! App ID ${fin.app_id}. Reloading…`);
        setTimeout(() => window.location.reload(), 800);
      } catch (e) {
        console.error(e);
        alert(e?.message || String(e));
        const hint = document.getElementById("deploy-hint");
        if (hint) hint.textContent = "";
      }
    });
  }

  // ---- CONTRIBUTE: build group -> sign group ----
  const btnContrib = document.getElementById("btn-contribute");
  if (btnContrib) {
    btnContrib.addEventListener("click", async () => {
      try {
        await ensureSignerReady();

        const addr = getActiveAddress();
        if (!addr) { alert("Connect wallet first."); return; }

        const amtEl = document.getElementById("contrib-amt");
        const amountAlgo = parseFloat(amtEl?.value || "0");
        if (!amountAlgo || amountAlgo <= 0) { alert("Enter an amount > 0"); return; }

        const r = await fetch(`/api/projects/${projectId}/build_contribution`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ from_address: addr, amount_algo: amountAlgo }),
        });
        const raw = await r.text();
        let data = {};
        try { data = JSON.parse(raw); } catch {}
        if (!r.ok) throw new Error(data.error || raw || `Build failed (${r.status})`);

        const txId = await signAndSendGroup(data.group);
        alert(`Contributed! TxID: ${txId}\n\nExplorer:\nhttps://testnet.algoexplorer.io/tx/${txId}`);
      } catch (e) {
        console.error(e);
        alert(e?.message || String(e));
      }
    });
  }

  // ---- CLAIM TOKENS: build single -> sign single ----
  const btnClaim = document.getElementById("btn-claim-tokens");
  if (btnClaim) {
    btnClaim.addEventListener("click", async () => {
      try {
        await ensureSignerReady();

        const addr = getActiveAddress();
        if (!addr) { alert("Connect wallet first."); return; }

        const r = await fetch(`/api/projects/${projectId}/build_claim_tokens`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ address: addr }),
        });
        const raw = await r.text();
        let data = {};
        try { data = JSON.parse(raw); } catch {}
        if (!r.ok) throw new Error(data.error || raw || `Build failed (${r.status})`);

        const txId = await signAndSendSingle(data.txn);
        alert(`Claim submitted! TxID: ${txId}`);
      } catch (e) {
        console.error(e);
        alert(e?.message || String(e));
      }
    });
  }

  // ---- REFUND: build single -> sign single ----
  const btnRefund = document.getElementById("btn-refund");
  if (btnRefund) {
    btnRefund.addEventListener("click", async () => {
      try {
        await ensureSignerReady();

        const addr = getActiveAddress();
        if (!addr) { alert("Connect wallet first."); return; }

        const r = await fetch(`/api/projects/${projectId}/build_refund`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ address: addr }),
        });
        const raw = await r.text();
        let data = {};
        try { data = JSON.parse(raw); } catch {}
        if (!r.ok) throw new Error(data.error || raw || `Build failed (${r.status})`);

        const txId = await signAndSendSingle(data.txn);
        alert(`Refund submitted! TxID: ${txId}`);
      } catch (e) {
        console.error(e);
        alert(e?.message || String(e));
      }
    });
  }
});
