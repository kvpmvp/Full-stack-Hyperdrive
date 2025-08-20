from pyteal import *

# Hyperdrive crowdfunding app
# Boxes store each contributor's microAlgo total keyed by the address bytes.

def get_approval():
    # Global state
    goal        = Bytes("goal")         # uint
    token_id    = Bytes("token_id")     # uint (ASA)
    rate        = Bytes("rate")         # uint (tokens per ALGO * 1e6)
    fee_bps     = Bytes("fee_bps")      # uint (e.g. 200 = 2%)
    admin       = Bytes("admin")        # bytes (address)
    start_ts    = Bytes("start_ts")     # uint
    deadline_ts = Bytes("deadline")     # uint
    raised      = Bytes("raised")       # uint
    success     = Bytes("success")      # uint 0/1
    deposit     = Bytes("deposit")      # uint

    sender = Txn.sender()
    now    = Global.latest_timestamp()

    # Box helpers
    def read_box(addr: Expr) -> MaybeValue:
        return App.box_get(addr)  # MaybeValue: .hasValue(), .value()

    def write_box(addr: Expr, amt_uint: Expr) -> Expr:
        return App.box_put(addr, Itob(amt_uint))

    # Helpers
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
            If(
                And(
                    App.globalGet(success) == Int(0),
                    App.globalGet(raised)  >= App.globalGet(goal),
                )
            ).Then(App.globalPut(success, Int(1)))
        )

    # simple min for uints
    def umin(a: Expr, b: Expr) -> Expr:
        return If(a < b, a, b)

    # Create
    on_create = Seq(
        Assert(Txn.application_args.length() == Int(7)),
        App.globalPut(goal,        Btoi(Txn.application_args[0])),
        App.globalPut(token_id,    Btoi(Txn.application_args[1])),
        App.globalPut(rate,        Btoi(Txn.application_args[2])),
        App.globalPut(fee_bps,     Btoi(Txn.application_args[3])),
        App.globalPut(admin,             Txn.application_args[4]),
        App.globalPut(start_ts,    Btoi(Txn.application_args[5])),
        App.globalPut(deadline_ts, Btoi(Txn.application_args[6])),
        App.globalPut(raised, Int(0)),
        App.globalPut(success, Int(0)),
        App.globalPut(deposit, Int(0)),
        Approve(),
    )

    # record_deposit: must be grouped with a prior Payment to app address
    on_record_deposit = Seq(
        Assert(Global.group_size() >= Int(2)),
        Assert(Gtxn[Txn.group_index() - Int(1)].type_enum() == TxnType.Payment),
        Assert(Gtxn[Txn.group_index() - Int(1)].receiver()   == Global.current_application_address()),
        App.globalPut(deposit, App.globalGet(deposit) + Gtxn[Txn.group_index() - Int(1)].amount()),
        Approve(),
    )

    # Contribute: must follow a Payment to app from same sender
    box_contrib = read_box(sender)  # MaybeValue to be evaluated inside Seq

    on_contribute = Seq(
        ensure_before_deadline(),
        Assert(App.globalGet(success) == Int(0)),

        Assert(Gtxn[Txn.group_index() - Int(1)].type_enum() == TxnType.Payment),
        Assert(Gtxn[Txn.group_index() - Int(1)].receiver()   == Global.current_application_address()),
        Assert(Gtxn[Txn.group_index() - Int(1)].sender()     == sender),

        # evaluate MaybeValue first, then use hasValue/value
        box_contrib,
        If(box_contrib.hasValue()).Then(
            write_box(sender, Btoi(box_contrib.value()) + Gtxn[Txn.group_index() - Int(1)].amount())
        ).Else(
            write_box(sender, Gtxn[Txn.group_index() - Int(1)].amount())
        ),

        App.globalPut(raised, App.globalGet(raised) + Gtxn[Txn.group_index() - Int(1)].amount()),
        mark_success_if_goal_met(),
        Approve(),
    )

    # Withdraw: after success -> fee to admin, remainder to caller (creator), refund any deposit
    feeAmt  = ScratchVar(TealType.uint64)
    bal     = ScratchVar(TealType.uint64)
    payout  = ScratchVar(TealType.uint64)

    on_withdraw = Seq(
        Assert(App.globalGet(success) == Int(1)),

        # fee = min(raised, goal) * fee_bps / 10000
        feeAmt.store(
            (umin(App.globalGet(raised), App.globalGet(goal)) * App.globalGet(fee_bps)) / Int(10000)
        ),

        # fee to admin
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.Payment,
            TxnField.receiver:  App.globalGet(admin),
            TxnField.amount:    feeAmt.load(),
        }),
        InnerTxnBuilder.Submit(),

        # payout to caller (creator) = balance - fee - min_txn_fee buffer
        bal.store(Balance(Global.current_application_address())),
        payout.store(bal.load() - feeAmt.load() - Global.min_txn_fee()),

        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.Payment,
            TxnField.receiver:  sender,
            TxnField.amount:    payout.load(),
        }),
        InnerTxnBuilder.Submit(),

        # refund creator deposit (if any)
        If(App.globalGet(deposit) > Int(0)).Then(Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.Payment,
                TxnField.receiver:  sender,
                TxnField.amount:    App.globalGet(deposit),
            }),
            InnerTxnBuilder.Submit(),
            App.globalPut(deposit, Int(0)),
        )),
        Approve(),
    )

    # Claim tokens: after success, transfer ASA proportional to contribution, then zero out box
    box_claim   = read_box(sender)  # evaluate inside Seq
    contrib     = ScratchVar(TealType.uint64)
    amt_tokens  = ScratchVar(TealType.uint64)

    on_claim_tokens = Seq(
        Assert(App.globalGet(success) == Int(1)),

        box_claim,
        Assert(box_claim.hasValue()),
        contrib.store(Btoi(box_claim.value())),
        amt_tokens.store( (contrib.load() * App.globalGet(rate)) / Int(1_000_000) ),

        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum:   TxnType.AssetTransfer,
            TxnField.xfer_asset:  App.globalGet(token_id),
            TxnField.asset_receiver: sender,
            TxnField.asset_amount:   amt_tokens.load(),
        }),
        InnerTxnBuilder.Submit(),

        # Instead of deleting (return-type headaches), just reset to 0
        write_box(sender, Int(0)),
        Approve(),
    )

    # Claim refund: after deadline & not success, return contribution, then zero out box
    box_refund     = read_box(sender)
    amount_refund  = ScratchVar(TealType.uint64)

    on_claim_refund = Seq(
        ensure_after_deadline(),
        Assert(App.globalGet(success) == Int(0)),

        box_refund,
        Assert(box_refund.hasValue()),
        amount_refund.store(Btoi(box_refund.value())),

        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.Payment,
            TxnField.receiver:  sender,
            TxnField.amount:    amount_refund.load(),
        }),
        InnerTxnBuilder.Submit(),

        write_box(sender, Int(0)),
        Approve(),
    )

    # Finalize failure: after deadline & not success, close ASA to caller, split deposit 50/50
    half = ScratchVar(TealType.uint64)

    on_finalize_failure = Seq(
        ensure_after_deadline(),
        Assert(App.globalGet(success) == Int(0)),

        # close-out remaining token balance to caller
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum:    TxnType.AssetTransfer,
            TxnField.xfer_asset:   App.globalGet(token_id),
            TxnField.asset_receiver: sender,
            TxnField.asset_close_to: sender,
            TxnField.asset_amount:  Int(0),
        }),
        InnerTxnBuilder.Submit(),

        # split deposit if present
        If(App.globalGet(deposit) > Int(0)).Then(Seq(
            half.store(App.globalGet(deposit) / Int(2)),

            # half to admin
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.Payment,
                TxnField.receiver:  App.globalGet(admin),
                TxnField.amount:    half.load(),
            }),
            InnerTxnBuilder.Submit(),

            # half back to caller
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.Payment,
                TxnField.receiver:  sender,
                TxnField.amount:    App.globalGet(deposit) - half.load(),
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
                [Txn.application_args[0] == Bytes("contribute"),      on_contribute],
                [Txn.application_args[0] == Bytes("claim_tokens"),    on_claim_tokens],
                [Txn.application_args[0] == Bytes("claim_refund"),    on_claim_refund],
                [Txn.application_args[0] == Bytes("withdraw"),        on_withdraw],
                [Txn.application_args[0] == Bytes("record_deposit"),  on_record_deposit],
                [Txn.application_args[0] == Bytes("finalize_failure"),on_finalize_failure],
            ),
            Return(Int(1))
        )]
    )
    return program

def get_clear():
    return Return(Int(1))
