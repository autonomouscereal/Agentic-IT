import os
import json
import asyncio
from datetime import datetime, timedelta
from database import fetchall, fetchrow, execute, fetchval, json_dumps

AGENT_HEARTBEAT_INTERVAL = int(os.getenv("AGENT_HEARTBEAT_INTERVAL", "15"))
AGENT_STALLED_THRESHOLD = int(os.getenv("AGENT_STALLED_THRESHOLD", "120"))

# Import broadcast function (will be set when routes module loads)
broadcast_fn = None

def set_broadcast(fn):
    global broadcast_fn
    broadcast_fn = fn

async def spawn_agent(ticket_id: int, model: str = "qwen/qwen3.6-27b"):
    """Create a new agent record for a ticket. Creates a placeholder ticket if needed."""
    # Ensure ticket exists
    ticket = await fetchrow("SELECT id, title FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        await execute("""
            INSERT INTO tickets (itop_ref, itop_class, title, status)
            VALUES ($1, 'Incident', $2, 'New')
        """, f"LOCAL-{ticket_id}", f"Ticket {ticket_id}")
        ticket = await fetchrow("SELECT id, title FROM tickets WHERE id = $1", ticket_id)

    agent_id = await fetchval("""
        INSERT INTO agents (ticket_id, model, status, started_at, heartbeat, assigned_by)
        VALUES ($1, $2, 'spawned', NOW(), NOW(), 'dashboard')
        RETURNING id
    """, ticket_id, model)

    await execute("UPDATE tickets SET agent_id = $1, updated_at = NOW() WHERE id = $2",
                 agent_id, ticket_id)

    await execute("""
        INSERT INTO audit_log (actor, action, target, details)
        VALUES ($1, $2, $3, $4)
    """, "orchestrator", "agent_spawned", f"ticket_{ticket_id}", json_dumps({
        "agent_id": agent_id, "ticket_id": ticket_id, "model": model
    }))

    if broadcast_fn:
        await broadcast_fn({"type": "agent_spawned", "agent_id": agent_id,
                           "ticket_id": ticket_id, "model": model})

    return {"status": "spawned", "agent_id": agent_id, "ticket_id": ticket_id}

async def update_heartbeat(agent_id: int):
    """Update agent heartbeat timestamp."""
    await execute("""
        UPDATE agents SET heartbeat = NOW(), status = 'running'
        WHERE id = $1
    """, agent_id)

async def check_agent_status(agent_id: int):
    """Get detailed agent status."""
    agent = await fetchrow("""
        SELECT a.*,
               EXTRACT(EPOCH FROM (NOW() - a.heartbeat)) AS seconds_since_heartbeat,
               EXTRACT(EPOCH FROM (NOW() - a.started_at)) AS running_seconds
        FROM agents a WHERE a.id = $1
    """, agent_id)
    if not agent:
        return None

    if agent["seconds_since_heartbeat"] and agent["seconds_since_heartbeat"] > AGENT_STALLED_THRESHOLD:
        if agent["status"] not in ("finished", "failed", "stopped", "terminated"):
            agent["stalled"] = True
    else:
        agent["stalled"] = False

    return agent

async def monitor_loop():
    """Background agent monitoring loop - detects stalled agents."""
    print(f"Agent monitor loop started (interval: {AGENT_HEARTBEAT_INTERVAL}s)")
    while True:
        try:
            # Get all active agents
            agents = await fetchall("""
                SELECT id, status, heartbeat, ticket_id
                FROM agents
                WHERE status IN ('spawned', 'running', 'working')
            """)

            for agent in agents:
                seconds_idle = await fetchval("""
                    SELECT EXTRACT(EPOCH FROM (NOW() - heartbeat))
                    FROM agents WHERE id = $1
                """, agent["id"])

                if seconds_idle and seconds_idle > AGENT_STALLED_THRESHOLD:
                    print(f"Agent {agent['id']} stalled ({seconds_idle:.0f}s idle)")

                    # Mark as stalled
                    await execute("""
                        UPDATE agents SET status = 'stalled',
                                         error_message = $1
                        WHERE id = $2
                    """, f"Stalled after {seconds_idle:.0f}s without heartbeat", agent["id"])

                    await execute("""
                        INSERT INTO audit_log (actor, action, target, details)
                        VALUES ($1, $2, $3, $4)
                    """, "monitor", "agent_stalled", f"agent_{agent['id']}", json_dumps({
                        "agent_id": agent["id"], "idle_seconds": seconds_idle,
                        "ticket_id": agent["ticket_id"]
                    }))

                    if broadcast_fn:
                        await broadcast_fn({"type": "agent_stalled",
                            "agent_id": agent["id"], "ticket_id": agent["ticket_id"],
                            "idle_seconds": seconds_idle})

        except Exception as e:
            print(f"Agent monitor error: {e}")

        await asyncio.sleep(AGENT_HEARTBEAT_INTERVAL)

async def heartbeat_endpoint(agent_id: int):
    """API endpoint for agents to report heartbeat."""
    agent = await fetchrow("SELECT id, status FROM agents WHERE id = $1", agent_id)
    if not agent:
        return {"error": "Agent not found", "valid": False}
    if agent["status"] in ("stopped", "terminated", "failed"):
        return {"error": "Agent is stopped", "valid": False}

    await update_heartbeat(agent_id)
    return {"status": "ok", "agent_id": agent_id, "valid": True}
