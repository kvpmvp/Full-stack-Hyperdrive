from pyteal import *

# Hyperdrive crowdfunding app
# - Stores per-contributor microAlgo contributions in Boxes keyed by address
# - Parameters fixed at creation:
#   goal_microalgo, token_asset_id, scaled_token_rate (tokens per ALGO * 1e6),
#   fee_bps (2%), admin_address, start_ts, deadline_ts
#
# Methods:
#   - "contribute": grouped with a payment to the app address before deadline; increments box amount
#   - "claim_tokens": after success, send ASA tokens proportional to contribution
#   - "claim_refund": after deadline and not successful, refund contribution
#   - "withdraw": creator withdraws raised - fee to themselves (after success), fee to admin
#   - "finalize_failure": creator can reclaim remaining tokens; split deposit 50/50 admin/creator
#
# Notes:
#   - Creator should deposit 2% of goal after creation (recorded via 'record_deposit' or a raw payment + check in withdraw)
#   - App must be opted into the ASA and funded with token_pool by creator
#
# For simplicity, we do not auto-enforce opt-in or pool mount here; recommended via deploy tooling.

def get_approval():
    # Global state keys
    goal = Bytes("goal")            # uint
    token_id = Bytes("token_id")    # uint (ASA)
    rate = Bytes("rate")            # uint (tokens per ALGO scaled by 1e6)
    fee_bps = Bytes("fee_bps")      # uint (e.g. 200 = 2%)
    admin = Bytes("admin")          # bytes address (32 bytes)
    start_ts = Bytes("start_ts")    # uint
    deadline_ts = Bytes("deadline") # uint
    raised = Bytes("raised")        # uint
    success = Bytes("success")      # uint 0/1
    deposit = Bytes("deposit")      # uint amount actually deposited by creator

    sender = Txn.sender()
    now = Global.latest_timestamp()

    # Boxes: key = contributor address; value = uint contribution in microalgos
    def read_box(addr: Expr):
        return App.box_get(addr)

    def write_box(addr: Expr, amt: Expr):
        return App.box_put(addr, Itob(amt))

    def del_box(addr: Expr):
        return App.box_delete(addr)

    on_create = Seq(
        Assert(Txn.application_args.length() == Int(7)),
        App.globalPut(goal, Btoi(Txn.application_args[0])),
        App.globalPut(token_id, Btoi(Txn.application_args[1])),
        App.globalPut(rate, Btoi(Txn.application_args[2])),
        App.globalPut(fee_bps, Btoi(Txn.application_args[3])),
        App.globalPut(admin, Txn.application_args[4]),
        App.globalPut(start_ts, Btoi(Txn.application_args[5])),
        App.globalPut(deadline_ts, Btoi(Txn.application_args[6])),
        App.globalPut(raised, Int(0)),
        App.globalPut(success, Int(0)),
        App.globalPut(deposit, Int(0)),
        Approve(),
    )

    @Subroutine(TealType.none)
    def ensure_before_deadline():
        return Seq(
            Assert(now >= App.globalGet(start_ts)),
            Assert(now <= App.globalGet(deadline_ts)),
        )

    @Subroutine(TealType.none)
    def ensure_after_deadline():
        return Seq(
            Assert(now > App.globalGet(deadline_ts)),
        )

    @Subroutine(TealType.none)
    def mark_success_if_goal_met():
        return Seq(
            If(And(App.globalGet(success) == Int(0), App.globalGet(raised) >= App.globalGet(goal))).Then(
                App.globalPut(success, Int(1))
            )
        )

    on_record_deposit = Seq(
        Assert(Global.group_size() >= Int(2)),
        Assert(Gtxn[Global.group_index() - Int(1)].type_enum() == TxnType.Payment),
        Assert(Gtxn[Global.group_index() - Int(1)].receiver() == Global.current_application_address()),
        App.globalPut(deposit, App.globalGet(deposit) + Gtxn[Global.group_index() - Int(1)].amount()),
        Approve(),
    )

    on_contribute = Seq(
        ensure_before_deadline(),
        Assert(App.globalGet(success) == Int(0)),
        Assert(Gtxn[Global.group_index() - Int(1)].type_enum() == TxnType.Payment),
        Assert(Gtxn[Global.group_index() - Int(1)].receiver() == Global.current_application_address()),
        Assert(Gtxn[Global.group_index() - Int(1)].sender() == sender),
        (exists, val) = read_box(sender),
        If(exists).Then(
            write_box(sender, Btoi(val) + Gtxn[Global.group_index() - Int(1)].amount())
        ).Else(
            write_box(sender, Gtxn[Global.group_index() - Int(1)].amount())
        ),
        App.globalPut(raised, App.globalGet(raised) + Gtxn[Global.group_index() - Int(1)].amount()),
        mark_success_if_goal_met(),
        Approve(),
    )

    on_withdraw = Seq(
        Assert(App.globalGet(success) == Int(1)),
        (feeAmt := ScratchVar()).store( (Min(App.globalGet(raised), App.globalGet(goal)) * App.globalGet(fee_bps)) / Int(10000) ),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.Payment,
            TxnField.receiver: App.globalGet(admin),
            TxnField.amount: feeAmt.load(),
        }),
        InnerTxnBuilder.Submit(),
        (bal := ScratchVar()).store( Balance(Global.current_application_address()) ),
        (payout := ScratchVar()).store( bal.load() - feeAmt.load() - Global.min_txn_fee() ),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.Payment,
            TxnField.receiver: sender,
            TxnField.amount: payout.load(),
        }),
        InnerTxnBuilder.Submit(),
        If(App.globalGet(deposit) > Int(0)).Then(Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.Payment,
                TxnField.receiver: sender,
                TxnField.amount: App.globalGet(deposit),
            }),
            InnerTxnBuilder.Submit(),
            App.globalPut(deposit, Int(0)),
        )),
        Approve(),
    )

    on_claim_tokens = Seq(
        Assert(App.globalGet(success) == Int(1)),
        (exists, val) = read_box(sender),
        Assert(exists),
        (contrib := ScratchVar()).store(Btoi(val)),
        (amt_tokens := ScratchVar()).store( (contrib.load() * App.globalGet(rate)) / Int(1_000_000) ),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: App.globalGet(token_id),
            TxnField.asset_receiver: sender,
            TxnField.asset_amount: amt_tokens.load(),
        }),
        InnerTxnBuilder.Submit(),
        del_box(sender),
        Approve(),
    )

    on_claim_refund = Seq(
        ensure_after_deadline(),
        Assert(App.globalGet(success) == Int(0)),
        (exists, val) = read_box(sender),
        Assert(exists),
        (amount := ScratchVar()).store(Btoi(val)),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.Payment,
            TxnField.receiver: sender,
            TxnField.amount: amount.load(),
        }),
        InnerTxnBuilder.Submit(),
        del_box(sender),
        Approve(),
    )

    on_finalize_failure = Seq(
        ensure_after_deadline(),
        Assert(App.globalGet(success) == Int(0)),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: App.globalGet(token_id),
            TxnField.asset_receiver: sender,
            TxnField.asset_close_to: sender,
            TxnField.asset_amount: Int(0),
        }),
        InnerTxnBuilder.Submit(),
        If(App.globalGet(deposit) > Int(0)).Then(Seq(
            (half := ScratchVar()).store(App.globalGet(deposit) / Int(2)),
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.Payment,
                TxnField.receiver: App.globalGet(admin),
                TxnField.amount: half.load(),
            }),
            InnerTxnBuilder.Submit(),
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.Payment,
                TxnField.receiver: sender,
                TxnField.amount: App.globalGet(deposit) - half.load(),
            }),
            InnerTxnBuilder.Submit(),
            App.globalPut(deposit, Int(0)),
        )),
        Approve(),
    )

    program = Cond(
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.DeleteApplication, Return(Txn.sender() == Global.creator_address())],
        [Txn.on_completion() == OnComplete.UpdateApplication, Return(Txn.sender() == Global.creator_address())],
        [Txn.on_completion() == OnComplete.NoOp, Seq(
            Cond(
                [Txn.application_args[0] == Bytes("contribute"), on_contribute],
                [Txn.application_args[0] == Bytes("claim_tokens"), on_claim_tokens],
                [Txn.application_args[0] == Bytes("claim_refund"), on_claim_refund],
                [Txn.application_args[0] == Bytes("withdraw"), on_withdraw],
                [Txn.application_args[0] == Bytes("record_deposit"), on_record_deposit],
                [Txn.application_args[0] == Bytes("finalize_failure"), on_finalize_failure],
            ),
            Return(Int(1))
        )]
    )
    return program

def get_clear():
    return Return(Int(1))
