# Hyperdrive – Algorand Crowdfunding (Full‑Stack, Python-first)

A full-stack prototype for **Hyperdrive**, a crowdfunding dApp on the Algorand blockchain.

- **Backend**: FastAPI + Jinja2 (Python)
- **Smart Contract**: PyTeal (Algorand AVM, uses Boxes to track contributions)
- **DB**: SQLite via SQLAlchemy
- **Frontend**: Server-rendered templates with TailwindCSS (CDN) + a small WalletConnect JS helper for Pera/Defly/Exodus
- **Network**: TestNet by default (configurable)

> This is a developer-ready reference implementation: create projects, list pitch decks, deploy the on-chain app (script),
> accept contributions, and handle success/refund claims via contract methods.

---

## Quick Start (Local)

### 1) Python & deps
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Environment
Copy `.env.example` to `.env` and fill in values:
- `ADMIN_ADDRESS` — Hyperdrive admin wallet address
- `ALGOD_TOKEN`, `ALGOD_URL`, `INDEXER_URL` — node endpoints (TestNet)
- `CREATOR_MNEMONIC` — (optional) if you want the backend to deploy contracts directly from the form
- `NETWORK` — `testnet` or `localnet`

### 3) Run the app
```bash
uvicorn backend.app:app --reload
```
Open http://localhost:8000

---

## Project Flow

1. **Create Project** (UI: “Create Project”)  
   Fill out project basics + token info and funding goal. You can choose to (a) only create the listing
   or (b) deploy the on-chain app immediately (requires wallet env vars).

2. **Smart Contract**  
   - Tracks each contributor’s ALGO in a **box per address**
   - Goal + deadline (60 days) enforced
   - On **success**: Creator withdraws ALGO minus **2% fee** to admin; contributors later **claim tokens** at the declared rate; the creator’s **2% deposit** is **returned**
   - On **failure** after deadline: Contributors **claim refunds**; creator can **reclaim tokens**;
     the deposited 2% fee is split: **50% admin / 50% creator**

3. **Contribute / Claim**  
   The UI builds unsigned transactions which users sign in-wallet (WalletConnect); or
   use the included Python scripts for automated testing on TestNet.

---

## Key Decisions & Notes

- **Deposit**: At app creation the creator deposits **2% of the goal** (in microAlgos).  
  On success: deposit is returned to creator.  
  On failure: deposit is split 50/50 admin/creator.
- **Fee on success**: 2% of raised ALGO (capped by goal) to admin.
- **Token distribution**: Post-success, contributors self-claim tokens (`claim_tokens`), preventing large group transactions.
- **Boxes**: Each contributor address has its own Box entry (amount in microAlgos).

> This repo is intentionally lightweight; it favors clarity over optimizations. You can harden it by adding
> input validation, pagination, auth, better error handling, indexer checks, etc.

---

## Scripts

- `contracts/compile.py` — compile PyTeal to TEAL
- `contracts/deploy.py` — deploy app to TestNet; creates the app with initial 2% deposit, token pool opt-in and funding.

---

## Legal / Security

- This is **prototype** code. Thoroughly audit before mainnet.
- Never commit live mnemonics. Use a wallet & WalletConnect in production.
