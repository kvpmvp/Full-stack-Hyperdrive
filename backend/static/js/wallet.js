let connectedAddr = null;

function setConnected(addr) {
  connectedAddr = addr;
  const el = document.getElementById('connected-address');
  if (el) el.textContent = addr ? `Connected: ${addr}` : 'Not connected';
}

async function connectWallet() {
  try {
    const pera = new window.PeraWalletConnect();
    const accounts = await pera.connect();
    setConnected(accounts[0]);
    window._wallet = pera;
  } catch (e) {
    alert('Wallet connect failed: ' + e.message);
  }
}

async function signAndSend(raws, single=false) {
  if (!connectedAddr) throw new Error('Connect wallet first');
  const pera = window._wallet || new window.PeraWalletConnect();
  const txns = Array.isArray(raws) ? raws : [raws];
  const decoded = txns.map(b64 => new Uint8Array(atob(b64).split('').map(c => c.charCodeAt(0))));
  const signed = await pera.signTransaction([decoded]);
  alert('Signed! Submit the signed blob to your node/relay.');
  return signed;
}

document.addEventListener('DOMContentLoaded', () => {
  const btnConnect = document.getElementById('btn-connect');
  if (btnConnect) btnConnect.addEventListener('click', connectWallet);

  const btnContrib = document.getElementById('btn-contribute');
  if (btnContrib) btnContrib.addEventListener('click', async () => {
    const amt = parseFloat(document.getElementById('contrib-amt').value || '0');
    if (!amt || amt <= 0) { alert('Enter amount'); return; }
    const res = await fetch(`/api/projects/${projectId}/build_contribution`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ from_address: connectedAddr, amount_algo: amt })
    }).then(r => r.json());
    await signAndSend(res.group);
  });

  const btnClaim = document.getElementById('btn-claim-tokens');
  if (btnClaim) btnClaim.addEventListener('click', async () => {
    const res = await fetch(`/api/projects/${projectId}/build_claim_tokens`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ address: connectedAddr })
    }).then(r => r.json());
    await signAndSend(res.txn, true);
  });

  const btnRefund = document.getElementById('btn-refund');
  if (btnRefund) btnRefund.addEventListener('click', async () => {
    const res = await fetch(`/api/projects/${projectId}/build_refund`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ address: connectedAddr })
    }).then(r => r.json());
    await signAndSend(res.txn, true);
  });
});
