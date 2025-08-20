import base64, pathlib
from pyteal import compileTeal, Mode
from backend.pyteal_src.hyperdrive_app import get_approval, get_clear

out = pathlib.Path("contracts/artifacts")
out.mkdir(parents=True, exist_ok=True)

approval_teal = compileTeal(get_approval(), mode=Mode.Application, version=8)
clear_teal = compileTeal(get_clear(), mode=Mode.Application, version=8)

(out / "approval.teal").write_text(approval_teal)
(out / "clear.teal").write_text(clear_teal)

print("Wrote:", (out / "approval.teal"), (out / "clear.teal"))
