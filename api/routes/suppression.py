"""
Routes for the suppression list — checked before any enrichment (see
api/suppression_db.py). Lets an operator import existing clients and
opt-outs, review what is currently blocked, and remove an entry by hand.
"""
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from api import suppression_db

router = APIRouter()


class SuppressionEntry(BaseModel):
    email: str | None = None
    linkedin_url: str | None = None
    domaine: str | None = None
    motif: str = "non précisé"


@router.get("/suppression")
def list_suppression():
    return suppression_db.list_entries()


@router.post("/suppression")
def add_suppression(body: SuppressionEntry):
    added = suppression_db.add_entry(
        email=body.email, linkedin_url=body.linkedin_url,
        domaine=body.domaine, motif=body.motif,
    )
    if not added:
        raise HTTPException(status_code=400, detail="Aucun identifiant fourni (email, linkedin_url ou domaine)")
    return {"ok": True}


@router.delete("/suppression/{row_id}")
def delete_suppression(row_id: int):
    if not suppression_db.delete_entry(row_id):
        raise HTTPException(status_code=404, detail="Entrée introuvable")
    return {"ok": True}


@router.post("/suppression/import")
async def import_suppression(file: UploadFile = File(...)):
    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    return suppression_db.import_csv(text)
