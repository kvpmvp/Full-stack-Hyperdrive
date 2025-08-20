import os, base64, json, time
from typing import Tuple, Dict, Any, List
from dotenv import load_dotenv

from algosdk.v2client import algod
from algosdk import transaction, account, mnemonic, encoding
from algosdk.logic import get_application_address

# These match the PyTeal contract in backend/pyteal_src/hyperdrive_app.py
APP_FEE_BPS = 200  # 2%
DEADLINE_DAYS = 60

load_dotenv()

# ---------------------------
# Algod / network utilities
# ---------------------------
def get_algod() -> algod.AlgodClient:
    """
    Default to Algonode TestNet (no token required).
    Override via:
      ALGOD_URL=https://testnet-api.algonode.cloud
      ALGOD_TOKEN=
    """
    token = os.getenv("ALGOD_TOKEN", "")
    url = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
    return algod.AlgodClient(token, url)

def get_network_hint():
    return os.getenv("NETWORK", "testnet")

# ---------------------------
# Optional server-side signer
# ---------------------------
def _creator_signer():
    m = os.getenv("CREATOR_MNEMONIC")
    if not m:
        return None, None
    sk = mnemonic.to_private_key(m)
    addr = account.address_from_private_key(sk)
    return addr, sk

# ---------------------------
# Helper: base64 encode unsigned txn for wallets
# ---------------------------
def _b64_unsigned(txn: transaction.Transaction) -> str:
    """
    Returns base64-encoded msgpack of an UNSIGNED transaction.
    Compatible across py-algosdk versions.
    """
    return encoding.msgpack_encode(txn)  # already a base64 string

# ---------------------------
# Client-signed DEPLOY helpers
# ---------------------------
def _build_app_create_txn(project, creator_addr: str) -> transaction.ApplicationCreateTxn:
    """
    Build an *unsigned* ApplicationCreate transaction using compiled TEAL.
    """
    client = get_algod()

    from backend.pyteal_compiled import get_approval_teal, get_clear_teal
    approval_teal_b64 = get_approval_teal()
    clear_teal_b64 = get_clear_teal()

    sp = client.suggested_params()

    admin_address = os.getenv("ADMIN_ADDRESS")
    if not admin_address or not encoding.is_valid_address(admin_address):
        raise RuntimeError("ADMIN_ADDRESS missing or invalid")

    start_ts = int(time.time())
    deadline_ts = start_ts + (DEADLINE_DAYS * 24 * 60 * 60)
    scaled_rate = int(float(project.token_rate_per_algo) * 1_000_000)

    # Global/local schema must match the app expectations
    global_schema = transaction.StateSchema(num_uints=8, num_byte_slices=2)
    local_schema = transaction.StateSchema(num_uints=0, num_byte_slices=0)

    app_args: List[bytes] = [
        int(project.goal_microalgos).to_bytes(8, "big"),
        int(project.token_asset_id).to_bytes(8, "big"),
        int(scaled_rate).to_bytes(8, "big"),
        int(APP_FEE_BPS).to_bytes(8, "big"),
        bytes.fromhex(encoding.decode_address(admin_address).hex()),
        int(start_ts).to_bytes(8, "big"),
        int(deadline_ts).to_bytes(8, "big"),
    ]

    return transaction.ApplicationCreateTxn(
        sender=creator_addr,
        sp=sp,
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=base64.b64decode(approval_teal_b64),
        clear_program=base64.b64decode(clear_teal_b64),
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=app_args,
    )

def build_deploy_group(project, creator_address: str) -> Dict[str, Any]:
    """
    Build the unsigned *create-app* group for client signing.
    We return a single-item "group" array (just the create txn). Funding (2% deposit) can be done after finalize.
    Response: {"group": ["base64txn", ...]}
    """
    if not creator_address or not encoding.is_valid_address(creator_address):
        raise RuntimeError("Invalid creator_address")

    create_txn = _build_app_create_txn(project, creator_address)

    # single-txn "group" is fine for wallet flows
    blobs = [_b64_unsigned(create_txn)]
    return {"group": blobs, "message": "Sign to deploy the Hyperdrive app."}

def compute_escrow_address(project, app_id: int) -> str:
    """
    For this app, the escrow is the application address.
    """
    return get_application_address(app_id)

# ---------------------------
# Server-side DEPLOY (optional; already in your code)
# ---------------------------
def ensure_deploy_if_requested(project) -> Tuple[int, str]:
    """
    Server-side deploy using CREATOR_MNEMONIC (if present).
    Also funds the app with a 2% deposit after creation.
    """
    addr, sk = _creator_signer()
    if not sk:
        raise RuntimeError("No CREATOR_MNEMONIC set. Project saved but on-chain deploy skipped.")

    client = get_algod()

    from backend.pyteal_compiled import get_approval_teal, get_clear_teal
    approval_teal_b64 = get_approval_teal()
    clear_teal_b64 = get_clear_teal()

    sp = client.suggested_params()
    admin_address = os.getenv("ADMIN_ADDRESS")
    if not admin_address or not encoding.is_valid_address(admin_address):
        raise RuntimeError("ADMIN_ADDRESS missing or invalid")

    start_ts = int(time.time())
    deadline_ts = start_ts + (DEADLINE_DAYS * 24 * 60 * 60)
    scaled_rate = int(project.token_rate_per_algo * 1_000_000)

    # Create app
    global_schema = transaction.StateSchema(num_uints=8, num_byte_slices=2)
    local_schema = transaction.StateSchema(num_uints=0, num_byte_slices=0)

    txn_create = transaction.ApplicationCreateTxn(
        sender=addr,
        sp=sp,
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=base64.b64decode(approval_teal_b64),
        clear_program=base64.b64decode(clear_teal_b64),
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=[
            project.goal_microalgos.to_bytes(8, "big"),
            project.token_asset_id.to_bytes(8, "big"),
            scaled_rate.to_bytes(8, "big"),
            APP_FEE_BPS.to_bytes(8, "big"),
            bytes.fromhex(encoding.decode_address(admin_address).hex()),
            start_ts.to_bytes(8, "big"),
            deadline_ts.to_bytes(8, "big"),
        ],
    )

    signed_create = txn_create.sign(sk)
    txid = client.send_transaction(signed_create)
    result = transaction.wait_for_confirmation(client, txid, 10)
    app_id = result["application-index"]
    app_addr = get_application_address(app_id)

    # Deposit 2% (creator to app) - recommended via deploy tooling or manual funding
    app_deposit = (project.goal_microalgos * APP_FEE_BPS) // 10_000
    sp = client.suggested_params()
    pay = transaction.PaymentTxn(sender=addr, sp=sp, receiver=app_addr, amt=app_deposit)
    signed_pay = pay.sign(sk)
    txid2 = client.send_transaction(signed_pay)
    transaction.wait_for_confirmation(client, txid2, 10)

    return app_id, app_addr

# ---------------------------
# Contribution / Claims / Refund
# ---------------------------
def build_contribution_txn(project, from_address: str, amount_algo: float) -> Dict[str, Any]:
    client = get_algod()
    sp = client.suggested_params()
    amt = int(float(amount_algo) * 1_000_000)

    if not project.app_id:
        raise RuntimeError("Project not deployed on chain yet")

    # Derive escrow if missing
    escrow_addr = project.escrow_address or get_application_address(int(project.app_id))

    # group: payment to escrow + app call "contribute"
    ptxn = transaction.PaymentTxn(sender=from_address, sp=sp, receiver=escrow_addr, amt=amt)
    atxn = transaction.ApplicationNoOpTxn(sender=from_address, sp=sp, index=int(project.app_id), app_args=[b"contribute"])

    gid = transaction.calculate_group_id([ptxn, atxn])
    ptxn.group = gid
    atxn.group = gid

    blobs = [_b64_unsigned(ptxn), _b64_unsigned(atxn)]
    return {"group": blobs, "message": "Sign and send group with your wallet."}

def build_claim_tokens_txn(project, address: str) -> Dict[str, Any]:
    client = get_algod()
    sp = client.suggested_params()
    if not project.app_id:
        raise RuntimeError("Project not deployed on chain")

    atxn = transaction.ApplicationNoOpTxn(
        sender=address, sp=sp, index=int(project.app_id),
        app_args=[b"claim_tokens"],
        foreign_assets=[int(project.token_asset_id)]
    )
    return {"txn": _b64_unsigned(atxn), "message": "Sign and send with your wallet."}

def build_refund_txn(project, address: str) -> Dict[str, Any]:
    client = get_algod()
    sp = client.suggested_params()
    if not project.app_id:
        raise RuntimeError("Project not deployed on chain")

    atxn = transaction.ApplicationNoOpTxn(
        sender=address, sp=sp, index=int(project.app_id),
        app_args=[b"claim_refund"]
    )
    return {"txn": _b64_unsigned(atxn), "message": "Sign and send with your wallet."}
