from database import fetchall, fetchrow, execute, fetchval, json_dumps


async def list_skills(category=None, enabled_only=True):
    """List agent skills with optional filters."""
    where = []
    params = []
    if enabled_only:
        where.append("enabled = true")
    if category:
        where.append("category = $1")
        params.append(category)

    wh = " WHERE " + " AND ".join(where) if where else ""
    rows = await fetchall(f"SELECT * FROM agent_skills{wh} ORDER BY name", *params)
    return rows or []


async def get_skill(skill_id):
    """Get a single skill by ID."""
    row = await fetchrow("SELECT * FROM agent_skills WHERE id = $1", skill_id)
    return row


async def create_skill(name, prompt_template, description=None, category=None):
    """Create a new agent skill."""
    skill_id = await fetchval(
        "INSERT INTO agent_skills (name, description, category, prompt_template) "
        "VALUES ($1, $2, $3, $4) RETURNING id",
        name, description, category, prompt_template,
    )
    return {"id": skill_id, "name": name}


async def update_skill(skill_id, **kwargs):
    """Update an existing skill."""
    allowed = {"name", "description", "category", "prompt_template", "enabled", "assigned_to_all"}
    fields = []
    params = []
    idx = 1
    for k, v in kwargs.items():
        if k in allowed:
            fields.append(f"{k} = ${idx}")
            params.append(v)
            idx += 1
    if not fields:
        return {"error": "No valid fields to update"}

    fields.append("updated_at = NOW()")
    params.append(skill_id)
    await execute(
        f"UPDATE agent_skills SET {', '.join(fields)} WHERE id = ${idx}",
        *params,
    )
    return {"status": "updated", "id": skill_id}


async def delete_skill(skill_id):
    """Delete a skill."""
    await execute("DELETE FROM agent_skills WHERE id = $1", skill_id)
    return {"status": "deleted", "id": skill_id}


async def assign_skill_to_agent(agent_id, skill_id):
    """Assign a skill to a specific agent."""
    await execute(
        "INSERT INTO agent_skill_mappings (agent_id, skill_id) VALUES ($1, $2) "
        "ON CONFLICT DO NOTHING",
        agent_id, skill_id,
    )


async def get_agent_skills(agent_id):
    """Get all skills available to an agent (global + assigned)."""
    # Global skills
    globals_rows = await fetchall(
        "SELECT * FROM agent_skills WHERE enabled = true AND assigned_to_all = true"
    )
    # Agent-specific skills
    agent_rows = await fetchall(
        "SELECT s.* FROM agent_skills s "
        "JOIN agent_skill_mappings m ON s.id = m.skill_id "
        "WHERE m.agent_id = $1 AND s.enabled = true",
        agent_id,
    )
    # Deduplicate by name
    seen = set()
    skills = []
    for s in (globals_rows or []) + (agent_rows or []):
        if s["name"] not in seen:
            seen.add(s["name"])
            skills.append(s)
    return skills


async def render_skill(skill_id, context):
    """Render a skill's prompt_template with context variables."""
    skill = await get_skill(skill_id)
    if not skill:
        return {"error": "Skill not found"}

    template = skill["prompt_template"]
    # Simple variable substitution
    for key, value in (context or {}).items():
        template = template.replace("{" + key + "}", str(value))
    return {"name": skill["name"], "rendered": template}
