from fastapi import APIRouter, Body, Query
from database import json_dumps
from services import skill_manager
from services.event_logger import log_event

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
async def list_skills(category: str = Query(None), enabled_only: bool = True):
    skills = await skill_manager.list_skills(category=category, enabled_only=enabled_only)
    return {"skills": skills, "total": len(skills)}


@router.post("")
async def create_skill(
    name: str = Body(...),
    prompt_template: str = Body(...),
    description: str = Body(None),
    category: str = Body(None),
):
    result = await skill_manager.create_skill(name, prompt_template, description, category)
    await log_event("agent", "info", "dashboard", "skill_created", name)
    return result


@router.put("/{skill_id}")
async def update_skill(
    skill_id: int,
    name: str = Body(None),
    description: str = Body(None),
    category: str = Body(None),
    prompt_template: str = Body(None),
    enabled: bool = Body(None),
    assigned_to_all: bool = Body(None),
):
    kwargs = {}
    if name is not None:
        kwargs["name"] = name
    if description is not None:
        kwargs["description"] = description
    if category is not None:
        kwargs["category"] = category
    if prompt_template is not None:
        kwargs["prompt_template"] = prompt_template
    if enabled is not None:
        kwargs["enabled"] = enabled
    if assigned_to_all is not None:
        kwargs["assigned_to_all"] = assigned_to_all

    result = await skill_manager.update_skill(skill_id, **kwargs)
    await log_event("agent", "info", "dashboard", "skill_updated", f"skill_{skill_id}")
    return result


@router.delete("/{skill_id}")
async def delete_skill(skill_id: int):
    result = await skill_manager.delete_skill(skill_id)
    await log_event("agent", "info", "dashboard", "skill_deleted", f"skill_{skill_id}")
    return result


@router.post("/{skill_id}/render")
async def render_skill(skill_id: int, context: dict = Body({})):
    return await skill_manager.render_skill(skill_id, context)


@router.get("/agent/{agent_id}")
async def get_agent_skills(agent_id: int):
    skills = await skill_manager.get_agent_skills(agent_id)
    return {"skills": skills, "total": len(skills)}


@router.get("/{skill_id}")
async def get_skill(skill_id: int):
    skill = await skill_manager.get_skill(skill_id)
    if not skill:
        return {"error": "Skill not found"}
    return skill
