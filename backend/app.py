import os
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from .database import Base, engine, get_db
from .models import Project
from .schemas import ProjectCreate
from .contracts_bridge import ensure_deploy_if_requested, build_contribution_txn, build_claim_tokens_txn, build_refund_txn, get_network_hint

load_dotenv()

app = FastAPI(title="Hyperdrive")
app.mount("/static", StaticFiles(directory=str((os.path.dirname(__file__)) + "/static")), name="static")
templates = Jinja2Templates(directory=str((os.path.dirname(__file__)) + "/templates"))

# Create DB tables
Base.metadata.create_all(bind=engine)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return templates.TemplateResponse("index.html", {"request": request, "projects": projects, "network": get_network_hint()})


@app.get("/create", response_class=HTMLResponse)
def create_form(request: Request):
    return templates.TemplateResponse("create.html", {"request": request, "network": get_network_hint()})


@app.post("/projects", response_class=HTMLResponse)
def create_project(
    request: Request,
    name: str = Form(...),
    creator: str = Form(...),
    category: str = Form(...),
    goal_algo: float = Form(...),  # human ALGOs
    token_asset_id: int = Form(...),
    token_rate: float = Form(...),  # tokens per 1 ALGO
    token_pool: int = Form(...),    # integer amount of tokens to deposit into contract
    description: str = Form(""),
    problem: str = Form(""),
    solution: str = Form(""),
    business_model: str = Form(""),
    investment_ask: str = Form(""),
    incentive_pool: str = Form(""),
    contact_email: str = Form(""),
    project_link: str = Form(""),
    deploy_now: str = Form("no"),
    db: Session = Depends(get_db)
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

    # Optionally create the on-chain app immediately
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
                    "network": get_network_hint()
                },
                status_code=400
            )

    return RedirectResponse(url=f"/projects/{project.id}", status_code=303)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return templates.TemplateResponse("project_detail.html", {"request": request, "p": project, "network": get_network_hint()})


# === API for building transactions (unsigned) ===

@app.post("/api/projects/{project_id}/build_contribution")
def api_build_contribution(project_id: int, data: dict, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    sender = data.get("from_address")
    amount_algo = float(data.get("amount_algo", 0))
    if not sender or amount_algo <= 0:
        raise HTTPException(400, "from_address and positive amount_algo required")
    blob = build_contribution_txn(p, sender, amount_algo)
    return JSONResponse(blob)


@app.post("/api/projects/{project_id}/build_claim_tokens")
def api_build_claim_tokens(project_id: int, data: dict, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    claimer = data.get("address")
    if not claimer:
        raise HTTPException(400, "address required")
    blob = build_claim_tokens_txn(p, claimer)
    return JSONResponse(blob)


@app.post("/api/projects/{project_id}/build_refund")
def api_build_refund(project_id: int, data: dict, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    addr = data.get("address")
    if not addr:
        raise HTTPException(400, "address required")
    blob = build_refund_txn(p, addr)
    return JSONResponse(blob)
