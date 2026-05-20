import asyncio
import json
import os
import time
from urllib.parse import quote

from aiohttp import ClientSession, web


DASHBOARD_API_BASE = os.getenv("DASHBOARD_API_BASE", "http://api:8000").rstrip("/")
DASHBOARD_SERVICE_TOKEN = os.getenv("DASHBOARD_SERVICE_TOKEN", "")
MATRIX_HOMESERVER_URL = os.getenv("MATRIX_HOMESERVER_URL", "http://ops-chat-synapse:8008").rstrip("/")
MATRIX_AS_TOKEN = os.getenv("MATRIX_AS_TOKEN", "")
MATRIX_HS_TOKEN = os.getenv("MATRIX_HS_TOKEN", "")
MATRIX_BOT_LOCALPART = os.getenv("MATRIX_BOT_LOCALPART", "agentic-ops")
MATRIX_SERVER_NAME = os.getenv("MATRIX_SERVER_NAME", "agentic-ops.local")
PORT = int(os.getenv("OPS_CHAT_BRIDGE_PORT", "29318"))

BOT_USER_ID = f"@{MATRIX_BOT_LOCALPART}:{MATRIX_SERVER_NAME}"
PROCESSED = set()


async def dashboard_chat(message, room_id, event_id, sender):
    payload = {
        "message": message,
        "requester_name": sender,
        "sender_name": sender,
        "channel": "matrix",
        "matrix_room_id": room_id,
        "external_thread_id": room_id,
        "matrix_event_id": event_id,
        "spawn_agent": True,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Dashboard-Service-Token": DASHBOARD_SERVICE_TOKEN,
        "X-Dashboard-Service-User": "ops-chat-matrix-bridge",
    }
    async with ClientSession(headers=headers) as session:
        async with session.post(f"{DASHBOARD_API_BASE}/api/ops-chat/message", json=payload, timeout=90) as response:
            text = await response.text()
            if response.status >= 400:
                return {
                    "reply": f"Dashboard intake failed with HTTP {response.status}: {text[:400]}",
                    "error": True,
                }
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"reply": text[:1000], "error": True}


async def send_matrix_message(room_id, text):
    txn_id = f"ops-{int(time.time() * 1000)}"
    url = (
        f"{MATRIX_HOMESERVER_URL}/_matrix/client/v3/rooms/"
        f"{quote(room_id, safe='')}/send/m.room.message/{txn_id}"
    )
    payload = {"msgtype": "m.text", "body": text}
    params = {"access_token": MATRIX_AS_TOKEN, "user_id": BOT_USER_ID}
    async with ClientSession() as session:
        async with session.put(url, params=params, json=payload, timeout=30) as response:
            if response.status >= 400:
                body = await response.text()
                print(f"Matrix send failed {response.status}: {body}", flush=True)


async def join_matrix_room(room_id):
    url = f"{MATRIX_HOMESERVER_URL}/_matrix/client/v3/join/{quote(room_id, safe='')}"
    params = {"access_token": MATRIX_AS_TOKEN, "user_id": BOT_USER_ID}
    async with ClientSession() as session:
        async with session.post(url, params=params, json={}, timeout=30) as response:
            body = await response.text()
            if response.status >= 400:
                print(f"Matrix join failed {response.status}: {body[:400]}", flush=True)
                return False
            return True


def event_text(event):
    content = event.get("content") or {}
    if content.get("msgtype") != "m.text":
        return ""
    return str(content.get("body") or "").strip()


async def handle_matrix_event(event):
    try:
        event_id = event.get("event_id")
        if not event_id or event_id in PROCESSED:
            return
        PROCESSED.add(event_id)
        if len(PROCESSED) > 5000:
            PROCESSED.clear()

        sender = event.get("sender") or ""
        event_type = event.get("type")
        room_id = event.get("room_id")
        content = event.get("content") or {}
        if (
            event_type == "m.room.member"
            and event.get("state_key") == BOT_USER_ID
            and content.get("membership") == "invite"
            and room_id
        ):
            print(f"Matrix bot invite received for {room_id}; joining as {BOT_USER_ID}", flush=True)
            if await join_matrix_room(room_id):
                await send_matrix_message(
                    room_id,
                    "Agentic Ops is connected. Send me an operational request and I will route it into a traceable ticket when work is needed.",
                )
            return

        if sender == BOT_USER_ID or sender.startswith(f"@{MATRIX_BOT_LOCALPART}:"):
            return
        text = event_text(event)
        if not room_id or not text:
            return

        result = await dashboard_chat(text, room_id, event_id, sender)
        reply = result.get("reply") or "I received the message, but the dashboard did not return a reply."
        ticket_id = result.get("ticket_id")
        agent = result.get("agent") or {}
        if ticket_id:
            reply = f"{reply}\n\nDashboard ticket: #{ticket_id}"
            if agent.get("agent_id"):
                reply += f"\nAgent: #{agent.get('agent_id')} / task #{agent.get('task_id')}"
        await send_matrix_message(room_id, reply)
    except Exception as exc:
        print(f"Matrix event handling failed: {exc}", flush=True)


async def health(request):
    return web.json_response({
        "status": "ok",
        "bot_user_id": BOT_USER_ID,
        "dashboard": DASHBOARD_API_BASE,
        "homeserver": MATRIX_HOMESERVER_URL,
    })


async def transactions(request):
    token = request.query.get("access_token") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if MATRIX_HS_TOKEN and token != MATRIX_HS_TOKEN:
        return web.json_response({"error": "forbidden"}, status=403)
    payload = await request.json()
    events = payload.get("events") or []
    print(f"Matrix transaction {request.match_info.get('txn_id')} events={len(events)}", flush=True)
    for event in events:
        if event.get("type") == "m.room.message":
            asyncio.create_task(handle_matrix_event(event))
        elif event.get("type") == "m.room.member":
            asyncio.create_task(handle_matrix_event(event))
    return web.json_response({})


async def users(request):
    return web.json_response({})


async def rooms(request):
    return web.json_response({})


def create_app():
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_put("/_matrix/app/v1/transactions/{txn_id}", transactions)
    app.router.add_get("/_matrix/app/v1/users/{user_id}", users)
    app.router.add_get("/_matrix/app/v1/rooms/{room_alias}", rooms)
    return app


if __name__ == "__main__":
    if not DASHBOARD_SERVICE_TOKEN:
        raise SystemExit("DASHBOARD_SERVICE_TOKEN is required")
    if not MATRIX_AS_TOKEN or not MATRIX_HS_TOKEN:
        raise SystemExit("MATRIX_AS_TOKEN and MATRIX_HS_TOKEN are required")
    web.run_app(create_app(), host="0.0.0.0", port=PORT)
