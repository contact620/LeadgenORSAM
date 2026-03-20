"""Template CRUD + run routes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api import templates
from api.pipeline_runner import start_job

router = APIRouter(tags=["templates"])


class TemplateCreate(BaseModel):
    name: str
    apollo_url: str
    max_leads: int = 200
    skip_gpt: bool = False


@router.get("/templates")
async def list_templates():
    return templates.list_templates()


@router.post("/templates")
async def create_template(body: TemplateCreate):
    return templates.create_template(
        name=body.name,
        apollo_url=body.apollo_url,
        max_leads=body.max_leads,
        skip_gpt=body.skip_gpt,
    )


@router.put("/templates/{tpl_id}")
async def update_template(tpl_id: str, body: TemplateCreate):
    result = templates.update_template(tpl_id, body.name, body.apollo_url, body.max_leads, body.skip_gpt)
    if not result:
        raise HTTPException(status_code=404, detail="Template not found")
    return result


@router.delete("/templates/{tpl_id}")
async def delete_template(tpl_id: str):
    if not templates.delete_template(tpl_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True}


@router.post("/templates/{tpl_id}/run")
async def run_template(tpl_id: str):
    tpl = templates.get_template(tpl_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")

    job_id = start_job(
        url=tpl["apollo_url"],
        max_leads=tpl["max_leads"],
        skip_gpt=tpl["skip_gpt"],
    )
    templates.increment_usage(tpl_id)
    return {"job_id": job_id}
