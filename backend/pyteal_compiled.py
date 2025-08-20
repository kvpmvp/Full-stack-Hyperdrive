# Provide helpers that compile the PyTeal contract into TEAL and return base64-encoded program bytes.
import base64
from .pyteal_src.hyperdrive_app import get_approval, get_clear
from pyteal import compileTeal, Mode

def get_approval_teal() -> str:
    teal = compileTeal(get_approval(), mode=Mode.Application, version=8)
    return base64.b64encode(teal.encode()).decode()

def get_clear_teal() -> str:
    teal = compileTeal(get_clear(), mode=Mode.Application, version=8)
    return base64.b64encode(teal.encode()).decode()
