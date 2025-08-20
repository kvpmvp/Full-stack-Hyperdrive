import os
import base64
import time
from typing import Tuple, Dict, Any, List, Optional
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
    Defaults to Algonode TestNet (no token required).
    Override via:
      ALGOD_URL=https://testnet-api.algonode.cloud
      ALGOD_TOKEN=
    """
    token = os.getenv("ALGOD_TOKEN", "")
    url = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
    return algod.AlgodClient(token, url)


def get_network_hint() -> str:
    return os.getenv("NETWORK", "testnet")


# ---------------------------
# Optional server-side signer
# ---------------------------
def _creator_signer() -> Tuple[Optional[str], Optional[bytes]]:
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
# Compiled program loader
# ---------------------------
def _get_programs() -> Tuple[bytes, bytes]:
    """
    Retrieve approval/clear programs as raw bytes.

    Priority:
    1) backend.pyteal_compiled.get_approval_teal() / get_clear_teal() (base64)
    2) Compile TEAL sources from contracts/artifacts/{approval,clear}.teal via algod.compile
    """
    # 1) Preferred: baked-in base64 programs (fast, no network)
    try:
        from backend.pyteal_compiled import get_approval_teal, get_clear_teal  # type: ignore
        approval_teal_b64 = get_approval_teal()
        clear_teal_b64 = get_clear_teal()
        if approval_teal_b64 and clear_teal_b64:
            return base64.b64decode(approval_teal_b64), base64.b64decode(clear_teal_b64)
    except Exception:
        pass

    # 2) Fallback: compile TEAL source files with the node
    client = get_algod()
    root = os.path.dirname(os.path.dirname(__file__))  # repo/backend -> repo/
    art_dir = os.path.join(root, "contracts", "artifacts")
    approval_path = os.path.join(art_dir, "approval.teal")
    clear_path = os.path.join(art_dir, "clear.teal")

    if not (os.path.exists(approval_path) and os.path.exists(clear_path)):
        raise RuntimeError(
            "No compiled programs found. Either provide backend.pyteal_compiled "
            "with base64 programs or generate contracts/artifacts/*.teal via `python contracts/compile.py`."
        )

    with open(approval_path, "r", encoding="utf-8") as f:
        approval_src = f.read()
    with open(clear_path, "r", encoding="utf-8") as f:
        clear_src = f.read()

    # algod.compile returns JSON with 'result' = base64 compiled program
    a = client.compile(approval_src)
    c = client.compile(clear_src)
    if "result" not in a or "result" not in c:
        raise RuntimeError("Algod compile did not return 'result' field")

    approval_prog = base64.b64decode(a["result"])
    clear_prog = base64.b64decode(c["result"])
    return approval_prog, clear_prog


def compute_escrow_address(project, app_id: int) -> str:
    """For this app, the escrow is the application address."""
    return get_application_address(app_id)


# ---------------------------
# Client-signed DEPLOY helpers
# ---------------------------
def _build_app_create_txn(project, creator_addr: str) -> transaction.ApplicationCreateTxn:
    """
    Build an *unsigned* ApplicationCreate transaction using compiled TEAL.
    Sets a flat fee (4000 µAlgo) to cover program size.
    """
    if not creator_addr or not encoding.is_valid_address(creator_addr):
        raise RuntimeError("Invalid creator_address")

    client = get_algod()
    sp = client.suggested_params()
    # --- Critical: cover program size with a flat fee ---
    sp.flat_fee = True
    sp.fee = 4000  # adjust upward if node still returns fee-related 400s

    admin_address = os.getenv("ADMIN_ADDRESS")
    if not admin_address or not encoding.is_valid_address(admin_address):
        raise RuntimeError("ADMIN_ADDRESS missing or invalid")

    approval_prog, clear_prog = _get_programs()

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
        approval_program=approval_prog,
        clear_program=clear_prog,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=app_args,
    )


def build_deploy_group(project, creator_address: str) -> Dict[str, Any]:
    """
    Build the unsigned *create-app* group for client signing.
    We return a single-item "group" array (just the create txn).
    Funding the 2% deposit can be done after finalize.
    Response: {"group": ["base64txn"], "message": "..."}
    """
    create_txn = _build_app_create_txn(project, creator_address)
    blobs = [_b64_unsigned(create_txn)]  # single-txn "group"
    return {"group": blobs, "message": "Sign to deploy the Hyperdrive app."}


# ---------------------------
# Server-side DEPLOY (optional)
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

    # --- Critical: flat fee for create ---
    sp = client.suggested_params()
    sp.flat_fee = True
    sp.fee = 4000

    admin_address = os.getenv("ADMIN_ADDRESS")
    if not admin_address or not encoding.is_valid_address(admin_address):
        raise RuntimeError("ADMIN_ADDRESS missing or invalid")

    approval_prog, clear_prog = _get_programs()

    start_ts = int(time.time())
    deadline_ts = start_ts + (DEADLINE_DAYS * 24 * 60 * 60)
    scaled_rate = int(float(project.token_rate_per_algo) * 1_000_000)

    # Create app
    global_schema = transaction.StateSchema(num_uints=8, num_byte_slices=2)
    local_schema = transaction.StateSchema(num_uints=0, num_byte_slices=0)

    txn_create = transaction.ApplicationCreateTxn(
        sender=addr,
        sp=sp,
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval_prog,
        clear_program=clear_prog,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=[
            int(project.goal_microalgos).to_bytes(8, "big"),
            int(project.token_asset_id).to_bytes(8, "big"),
            int(scaled_rate).to_bytes(8, "big"),
            int(APP_FEE_BPS).to_bytes(8, "big"),
            bytes.fromhex(encoding.decode_address(admin_address).hex()),
            int(start_ts).to_bytes(8, "big"),
            int(deadline_ts).to_bytes(8, "big"),
        ],
    )

    signed_create = txn_create.sign(sk)
    txid = client.send_transaction(signed_create)
    result = transaction.wait_for_confirmation(client, txid, 12)
    app_id = result["application-index"]
    app_addr = get_application_address(app_id)

    # Deposit 2% (creator to app)
    app_deposit = (int(project.goal_microalgos) * APP_FEE_BPS) // 10_000
    sp2 = client.suggested_params()  # normal suggested fee OK for payments
    pay = transaction.PaymentTxn(sender=addr, sp=sp2, receiver=app_addr, amt=app_deposit)
    signed_pay = pay.sign(sk)
    txid2 = client.send_transaction(signed_pay)
    transaction.wait_for_confirmation(client, txid2, 12)

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
    atxn = transaction.ApplicationNoOpTxn(
        sender=from_address,
        sp=sp,
        index=int(project.app_id),
        app_args=[b"contribute"],
    )

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
        sender=address,
        sp=sp,
        index=int(project.app_id),
        app_args=[b"claim_tokens"],
        foreign_assets=[int(project.token_asset_id)],
    )
    return {"txn": _b64_unsigned(atxn), "message": "Sign and send with your wallet."}


def build_refund_txn(project, address: str) -> Dict[str, Any]:
    client = get_algod()
    sp = client.suggested_params()
    if not project.app_id:
        raise RuntimeError("Project not deployed on chain")

    atxn = transaction.ApplicationNoOpTxn(
        sender=address,
        sp=sp,
        index=int(project.app_id),
        app_args=[b"claim_refund"],
    )
    return {"txn": _b64_unsigned(atxn), "message": "Sign and send with your wallet."}
