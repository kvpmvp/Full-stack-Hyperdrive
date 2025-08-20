import os
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Form, Depends, HTTPException, Body, Query
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from dotenv import load_dotenv

# Absolute imports to avoid package resolution issues
from backend.database import Base, engine, get_db
from backend.models import Project
from backend.schemas import ProjectCreate
from backend.contracts_bridge import (
    ensure_deploy_if_requested,
    build_contribution_txn,
    build_claim_tokens_txn,
    build_refund_txn,
    get_network_hint,
    # NEW: used by the new deploy endpoints
    build_deploy_group,
    compute_escrow_address,
    get_algod,
)
from algosdk import transaction  # used for wait_for_confirmation

# Optional legacy broadcast client (not required for the new finalize)
try:
    from backend.broadcast_api import algod_client
except Exception:
    algod_client = None  # guarded below

load_dotenv()

app = FastAPI(title="Hyperdrive")

app.mount(
    "/static",
    StaticFiles(directory=str((os.path.dirname(__file__)) + "/static")),
    name="static",
)
templates = Jinja2Templates(directory=str((os.path.dirname(__file__)) + "/templates"))
# disable template caching in dev to avoid stale pages
try:
    templates.env.cache = {}
except Exception:
    pass

# Create DB tables
Base.metadata.create_all(bind=engine)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "projects": projects, "network": get_network_hint()},
    )


@app.get("/create", response_class=HTMLResponse)
def create_form(request: Request):
    return templates.TemplateResponse(
        "create.html", {"request": request, "network": get_network_hint()}
    )


@app.post("/projects", response_class=HTMLResponse)
def create_project(
    request: Request,
    name: str = Form(...),
    creator: str = Form(...),
    category: str = Form(...),
    goal_algo: float = Form(...),  # human ALGOs
    token_asset_id: int = Form(...),
    token_rate: float = Form(...),  # tokens per 1 ALGO
    token_pool: int = Form(...),  # integer amount of tokens to deposit into contract
    description: str = Form(""),
    problem: str = Form(""),
    solution: str = Form(""),
    business_model: str = Form(""),
    investment_ask: str = Form(""),
    incentive_pool: str = Form(""),
    contact_email: str = Form(""),
    project_link: str = Form(""),
    deploy_now: str = Form("no"),
    db: Session = Depends(get_db),
):
    # Store DB record
    project = Project(
        name=name,
        creator=creator,
        category=category,
        goal_microalgos=int(goal_algo * 1_000_000),
        token_asset_id=token_asset_id,
        token_rate_per_algo=float(token_rate),
        token_pool=token_pool,
        description=description,
        problem=problem,
        solution=solution,
        business_model=business_model,
        investment_ask=investment_ask,
        incentive_pool=incentive_pool,
        contact_email=contact_email,
        project_link=project_link,
        deadline_at=datetime.utcnow() + timedelta(days=60),
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # (Server-side deploy is optional; client-signed deploy is available on project page)
    if deploy_now.lower() == "yes":
        try:
            app_id, app_address = ensure_deploy_if_requested(project)
            project.app_id = app_id
            project.escrow_address = app_address
            db.commit()
        except Exception as e:
            # Keep project record; surface error back to UI
            return templates.TemplateResponse(
                "create.html",
                {
                    "request": request,
                    "error": f"Project saved, but deploy failed: {e}",
                    "network": get_network_hint(),
                },
                status_code=400,
            )

    return RedirectResponse(url=f"/projects/{project.id}", status_code=303)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return templates.TemplateResponse(
        "project_detail.html",
        {"request": request, "p": project, "network": get_network_hint()},
    )


# === NEW: CLIENT-SIGNED DEPLOY FLOW (paths used by wallet.js) ===

@app.post("/api/projects/{project_id}/deploy/build")
def api_deploy_build(project_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """
    Build the unsigned ApplicationCreate txn (client signs with Pera/Defly).
    Returns: {"group": ["base64UnsignedTxn"], "message": "..."}
    """
    p = db.get(Project, project_id)
    if not p:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    creator_address = (payload or {}).get("creator_address")
    if not creator_address:
        return JSONResponse({"error": "creator_address required"}, status_code=400)

    try:
        blob = build_deploy_group(p, creator_address)
        if not isinstance(blob, dict) or not blob.get("group"):
            return JSONResponse({"error": "build_deploy_group returned no 'group'."}, status_code=500)
        return JSONResponse(blob)
    except Exception as e:
        return JSONResponse({"error": f"build_deploy_group failed: {e}"}, status_code=400)


@app.post("/api/projects/{project_id}/deploy/finalize")
def api_deploy_finalize(project_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """
    After the wallet signs/sends the create-app txn, wait for confirmation,
    extract the new app_id, compute escrow address, store them on the project.
    Body: {"txId": "<first tx id from the signed group>"}
    """
    p = db.get(Project, project_id)
    if not p:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    txid = (payload or {}).get("txId")
    if not txid:
        return JSONResponse({"error": "txId required"}, status_code=400)

    try:
        client = get_algod()
        # Wait for confirmation (increase rounds if TestNet is slow)
        result = transaction.wait_for_confirmation(client, txid, 12)
        app_id = result.get("application-index")
        if not app_id:
            # Some nodes nest differently; be explicit
            pending = client.pending_transaction_info(txid)
            app_id = pending.get("application-index") or pending.get("txn", {}).get("apid")
        if not app_id:
            return JSONResponse({"error": f"Could not determine application id from txid {txid}."}, status_code=400)

        escrow = None
        try:
            escrow = compute_escrow_address(p, int(app_id))
        except Exception:
            escrow = None

        p.app_id = int(app_id)
        if escrow:
            p.escrow_address = escrow
        db.commit()

        return JSONResponse({"app_id": int(app_id), "escrow": escrow})
    except Exception as e:
        return JSONResponse({"error": f"finalize_deploy failed: {e}"}, status_code=400)


# === LEGACY: keep existing endpoints for backward compatibility ===

@app.post("/api/projects/{project_id}/build_deploy")
def api_build_deploy_legacy(
    project_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """
    Legacy path kept for compatibility. Prefer /api/projects/{id}/deploy/build
    """
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")

    creator = (payload or {}).get("creator_address")
    if not creator:
        raise HTTPException(status_code=400, detail="creator_address required")

    try:
        blob = build_deploy_group(p, creator)
        if not isinstance(blob, dict) or not blob.get("group"):
            return JSONResponse({"error": "build_deploy_group returned no 'group'."}, status_code=500)
        return JSONResponse(blob)
    except Exception as e:
        return JSONResponse({"error": f"build_deploy_group failed: {e}"}, status_code=500)


@app.post("/api/projects/{project_id}/finalize_deploy")
def api_finalize_deploy_legacy(
    project_id: int,
    txid: str = Query(..., description="TxID of the application create transaction"),
    db: Session = Depends(get_db),
):
    """
    Legacy path kept for compatibility. Prefer /api/projects/{id}/deploy/finalize (JSON body).
    """
    # If available, use server's shared algod; otherwise use our helper
    client = algod_client if algod_client is not None else get_algod()

    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        result = transaction.wait_for_confirmation(client, txid, 12)
        app_id = result.get("application-index")
        if not app_id:
            pending = client.pending_transaction_info(txid)
            app_id = pending.get("application-index") or pending.get("txn", {}).get("apid")
        if not app_id:
            raise HTTPException(status_code=400, detail=f"Could not determine app-id from txid {txid}.")

        escrow = None
        try:
            escrow = compute_escrow_address(p, int(app_id))
        except Exception:
            escrow = None

        p.app_id = int(app_id)
        if escrow:
            p.escrow_address = escrow
        db.commit()

        return JSONResponse({"ok": True, "app_id": int(app_id), "escrow_address": escrow})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"finalize_deploy failed: {e}")


# === API for building transactions (unsigned) ===

@app.post("/api/projects/{project_id}/build_contribution")
def api_build_contribution(
    project_id: int, data: dict = Body(...), db: Session = Depends(get_db)
):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    sender = data.get("from_address")
    amount_algo = float(data.get("amount_algo", 0))
    if not sender or amount_algo <= 0:
        raise HTTPException(status_code=400, detail="from_address and positive amount_algo required")
    blob = build_contribution_txn(p, sender, amount_algo)
    return JSONResponse(blob)


@app.post("/api/projects/{project_id}/build_claim_tokens")
def api_build_claim_tokens(
    project_id: int, data: dict = Body(...), db: Session = Depends(get_db)
):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    claimer = data.get("address")
    if not claimer:
        raise HTTPException(status_code=400, detail="address required")
    blob = build_claim_tokens_txn(p, claimer)
    return JSONResponse(blob)


@app.post("/api/projects/{project_id}/build_refund")
def api_build_refund(
    project_id: int, data: dict = Body(...), db: Session = Depends(get_db)
):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    addr = data.get("address")
    if not addr:
        raise HTTPException(status_code=400, detail="address required")
    blob = build_refund_txn(p, addr)
    return JSONResponse(blob)
