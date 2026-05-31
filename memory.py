import os
import httpx
from datetime import datetime

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal"
}

async def init_db():
    """Create messages table if it doesn't exist via Supabase REST API."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/init_messages_table",
            headers=HEADERS,
            json={}
        )
    return resp.status_code

async def save_message(chat_id: int, sender: str, text: str, is_bot: bool = False):
    """Save a message to Supabase."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/messages",
            headers=HEADERS,
            json={
                "chat_id": str(chat_id),
                "sender": sender,
                "text": text,
                "is_bot": is_bot,
                "created_at": datetime.utcnow().isoformat()
            }
        )
    return resp.status_code == 201

async def get_history(chat_id: int, limit: int = 100):
    """Get last N messages for a chat."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/messages",
            headers={**HEADERS, "Prefer": ""},
            params={
                "chat_id": f"eq.{chat_id}",
                "order": "created_at.desc",
                "limit": limit
            }
        )
    if resp.status_code == 200:
        messages = resp.json()
        return list(reversed(messages))
    return []

def format_history_for_prompt(messages: list, current_bot: str) -> str:
    """Format message history for AI prompt."""
    if not messages:
        return ""
    lines = ["=== CONVERSATION HISTORY ==="]
    for msg in messages:
        sender = msg.get("sender", "Unknown")
        text = msg.get("text", "")
        lines.append(f"[{sender}]: {text}")
    lines.append("=== END OF HISTORY ===")
    return "\n".join(lines)
