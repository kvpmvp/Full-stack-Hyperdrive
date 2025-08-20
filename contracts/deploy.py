import os, time, base64
from dotenv import load_dotenv
from algosdk.v2client import algod
from algosdk import transaction, account, mnemonic, encoding
from algosdk.logic import get_application_address
from pyteal import compileTeal, Mode

from backend.pyteal_src.hyperdrive_app import get_approval, get_clear

load_dotenv()

ALGOD_URL = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
ALGOD_TOKEN = os.getenv("ALGOD_TOKEN", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
ADMIN_ADDRESS = os.getenv("ADMIN_ADDRESS")
CREATOR_MNEMONIC = os.getenv("CREATOR_MNEMONIC")

if not ADMIN_ADDRESS or not encoding.is_valid_address(ADMIN_ADDRESS):
    raise SystemExit("Set ADMIN_ADDRESS in .env")
if not CREATOR_MNEMONIC:
    raise SystemExit("Set CREATOR_MNEMONIC in .env")

client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_URL)

sk = mnemonic.to_private_key(CREATOR_MNEMONIC)
addr = account.address_from_private_key(sk)

def deploy(goal_microalgos: int, token_asset_id: int, token_rate_per_algo: float):
    approval_teal = compileTeal(get_approval(), mode=Mode.Application, version=8)
    clear_teal = compileTeal(get_clear(), mode=Mode.Application, version=8)

    ap = client.compile(approval_teal)
    cp = client.compile(clear_teal)
    approval = base64.b64decode(ap["result"])
    clear = base64.b64decode(cp["result"])

    sp = client.suggested_params()
    start_ts = int(time.time())
    deadline_ts = start_ts + 60*24*60*60
    scaled_rate = int(token_rate_per_algo * 1_000_000)
    fee_bps = 200

    txn = transaction.ApplicationCreateTxn(
        sender=addr,
        sp=sp,
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=transaction.StateSchema(num_uints=8, num_byte_slices=2),
        local_schema=transaction.StateSchema(num_uints=0, num_byte_slices=0),
        app_args=[
            goal_microalgos.to_bytes(8, 'big'),
            token_asset_id.to_bytes(8, 'big'),
            scaled_rate.to_bytes(8, 'big'),
            fee_bps.to_bytes(8, 'big'),
            bytes.fromhex(encoding.decode_address(ADMIN_ADDRESS).hex()),
            start_ts.to_bytes(8, 'big'),
            deadline_ts.to_bytes(8, 'big'),
        ]
    )
    stx = txn.sign(sk)
    txid = client.send_transaction(stx)
    res = transaction.wait_for_confirmation(client, txid, 10)
    app_id = res["application-index"]
    app_addr = get_application_address(app_id)
    print("Deployed app:", app_id, "address:", app_addr)

    # Optional: deposit 2% of goal immediately
    dep = (goal_microalgos * fee_bps) // 10_000
    sp = client.suggested_params()
    pay = transaction.PaymentTxn(sender=addr, sp=sp, receiver=app_addr, amt=dep)
    stx2 = pay.sign(sk)
    txid2 = client.send_transaction(stx2)
    transaction.wait_for_confirmation(client, txid2, 10)
    print("Deposited 2%:", dep, "microAlgos")

    return app_id, app_addr

if __name__ == "__main__":
    # Replace with your params
    app_id, app_addr = deploy(goal_microalgos=1_000_000, token_asset_id=12345, token_rate_per_algo=1000.0)
    print("Done.")
