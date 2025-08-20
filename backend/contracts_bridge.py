import os, base64, json, time
from typing import Tuple
from dotenv import load_dotenv

from algosdk.v2client import algod
from algosdk import transaction, account, mnemonic, encoding
from algosdk.logic import get_application_address

# These match the PyTeal contract in contracts/hyperdrive_app.py
APP_FEE_BPS = 200  # 2%
DEADLINE_DAYS = 60

load_dotenv()

def get_algod():
    token = os.getenv("ALGOD_TOKEN", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    url = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
    return algod.AlgodClient(token, url)

def get_network_hint():
    return os.getenv("NETWORK", "testnet")

def _creator_signer():
    m = os.getenv("CREATOR_MNEMONIC")
    if not m:
        return None, None
    sk = mnemonic.to_private_key(m)
    addr = account.address_from_private_key(sk)
    return addr, sk

def ensure_deploy_if_requested(project) -> Tuple[int, str]:
    # Deploy the stateful app if env has creator mnemonic. Returns (app_id, app_address).
    # This function expects the creator to fund a 2% deposit (in microAlgos) after creation.
    addr, sk = _creator_signer()
    if not sk:
        raise RuntimeError("No CREATOR_MNEMONIC set. Project saved but on-chain deploy skipped.")

    client = get_algod()

    from .pyteal_compiled import get_approval_teal, get_clear_teal
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
            project.goal_microalgos.to_bytes(8,'big'),
            project.token_asset_id.to_bytes(8,'big'),
            scaled_rate.to_bytes(8,'big'),
            APP_FEE_BPS.to_bytes(8,'big'),
            bytes.fromhex(encoding.decode_address(admin_address).hex()),
            start_ts.to_bytes(8,'big'),
            deadline_ts.to_bytes(8,'big'),
        ],
    )

    signed_create = txn_create.sign(sk)
    txid = get_algod().send_transaction(signed_create)
    result = transaction.wait_for_confirmation(client, txid, 10)
    app_id = result["application-index"]
    app_addr = get_application_address(app_id)

    # Deposit 2% (creator to app) - recommended via deploy tooling or manual funding
    app_deposit = (project.goal_microalgos * APP_FEE_BPS) // 10_000
    sp = client.suggested_params()
    pay = transaction.PaymentTxn(
        sender=addr,
        sp=sp,
        receiver=app_addr,
        amt=app_deposit
    )
    signed_pay = pay.sign(sk)
    txid2 = client.send_transaction(signed_pay)
    transaction.wait_for_confirmation(client, txid2, 10)

    return app_id, app_addr


def build_contribution_txn(project, from_address: str, amount_algo: float):
    client = get_algod()
    sp = client.suggested_params()
    amt = int(amount_algo * 1_000_000)

    if not project.app_id or not project.escrow_address:
        raise RuntimeError("Project not deployed on chain yet")

    # group: payment to app + app call "contribute"
    ptxn = transaction.PaymentTxn(sender=from_address, sp=sp, receiver=project.escrow_address, amt=amt)
    atxn = transaction.ApplicationNoOpTxn(sender=from_address, sp=sp, index=project.app_id, app_args=[b"contribute"])

    gid = transaction.calculate_group_id([ptxn, atxn])
    ptxn.group = gid
    atxn.group = gid

    utxns = [ptxn, atxn]
    blobs = [base64.b64encode(txn.bytes()).decode() for txn in utxns]
    return {"group": blobs, "message": "Sign and send group with your wallet."}


def build_claim_tokens_txn(project, address: str):
    client = get_algod()
    sp = client.suggested_params()
    if not project.app_id:
        raise RuntimeError("Project not deployed on chain")

    atxn = transaction.ApplicationNoOpTxn(
        sender=address, sp=sp, index=project.app_id,
        app_args=[b"claim_tokens"],
        foreign_assets=[project.token_asset_id]
    )
    return {"txn": base64.b64encode(atxn.bytes()).decode(), "message": "Sign and send with your wallet."}


def build_refund_txn(project, address: str):
    client = get_algod()
    sp = client.suggested_params()
    if not project.app_id:
        raise RuntimeError("Project not deployed on chain")

    atxn = transaction.ApplicationNoOpTxn(
        sender=address, sp=sp, index=project.app_id,
        app_args=[b"claim_refund"]
    )
    return {"txn": base64.b64encode(atxn.bytes()).decode(), "message": "Sign and send with your wallet."}
