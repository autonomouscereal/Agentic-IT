from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse
import os
from pathlib import Path

from services import sensitive_intake

router = APIRouter(prefix="/api/sensitive-intake", tags=["sensitive-intake"])


@router.post("/request")
async def create_sensitive_request(body: dict = Body(...)):
    result = await sensitive_intake.create_request(
        body.get("fields") or [],
        purpose=body.get("purpose") or "",
        ticket_id=body.get("ticket_id"),
        session_id=body.get("session_id"),
        requested_by=body.get("requested_by") or "agent",
        requester_name=body.get("requester_name"),
        requester_email=body.get("requester_email"),
        channel=body.get("channel") or "dashboard",
        expires_hours=body.get("expires_hours"),
        metadata=body.get("metadata") or {},
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    result.pop("token", None)
    return result


@router.get("/form/{token}")
async def get_sensitive_form(token: str):
    result = await sensitive_intake.get_request_by_token(token)
    if not result:
        raise HTTPException(status_code=404, detail="form not found")
    return result


@router.post("/submit/{token}")
async def submit_sensitive_form(token: str, body: dict = Body(...)):
    result = await sensitive_intake.submit_request(
        token,
        body.get("values") or {},
        submitted_by=body.get("submitted_by") or "secure-form",
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/requests")
async def list_sensitive_requests(ticket_id: int = None, session_id: int = None, limit: int = 50):
    return {
        "requests": await sensitive_intake.list_requests(ticket_id=ticket_id, session_id=session_id, limit=limit)
    }


@router.get("/requests/{request_ref}")
async def get_sensitive_request(request_ref: str):
    result = await sensitive_intake.get_request_by_ref(request_ref)
    if not result:
        raise HTTPException(status_code=404, detail="request not found")
    return result


@router.get("/page/{token}")
async def sensitive_form_page(token: str):
    frontend_dir = os.getenv("FRONTEND_DIR", "/frontend")
    path = Path(frontend_dir) / "secure_intake.html"
    if path.exists():
        return FileResponse(str(path))
    raise HTTPException(status_code=404, detail="secure intake page not found")
