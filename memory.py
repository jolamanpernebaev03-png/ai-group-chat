"""
memory.py — Supabase-backed chat history
==========================================

Tables needed (run in Supabase SQL editor):

    CREATE TABLE messages (
        id bigserial primary key,
        chat_id text,
        sender text,
        text text,
        is_bot boolean default false,
        created_at timestamp default now()
    );

    CREATE TABLE leaderboard (
        id bigserial primary key,
        bot_name text unique,
        wins integer default 0,
        total_debates integer default 0,
        updated_at timestamp default now()
    );
"""

import os
import httpx
from datetime import datetime

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}


async def save_message(chat_id: int, sender: str, text: str, is_bot: bool = False) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SUPABASE_URL}/rest/v1/messages",
                headers=HEADERS,
                json={
                    "chat_id": str(chat_id),
                    "sender": sender,
                    "text": text,
                    "is_bot": is_bot,
                    "created_at": datetime.utcnow().isoformat(),
                },
            )
        return resp.status_code == 201
    except Exception:
        return False


async def get_history(chat_id: int, limit: int = 100) -> list:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/messages",
                headers={**HEADERS, "Prefer": ""},
                params={
                    "chat_id": f"eq.{chat_id}",
                    "order": "created_at.desc",
                    "limit": limit,
                },
            )
        if resp.status_code == 200:
            return list(reversed(resp.json()))
        return []
    except Exception:
        return []


def format_history_for_prompt(messages: list, current_bot: str) -> str:
    if not messages:
        return ""
    lines = ["=== CONVERSATION HISTORY ==="]
    for msg in messages:
        sender = msg.get("sender", "Unknown")
        text = msg.get("text", "")
        lines.append(f"[{sender}]: {text}")
    lines.append("=== END OF HISTORY ===")
    return "\n".join(lines)


async def update_leaderboard(winner_name: str, all_participants: list) -> None:
    """Update the leaderboard table using upsert on bot_name."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            for bot in all_participants:
                wins = 1 if bot == winner_name else 0
                await client.post(
                    f"{SUPABASE_URL}/rest/v1/leaderboard",
                    headers={**HEADERS, "Prefer": "resolution=merge-duplicates"},
                    json={
                        "bot_name": bot,
                        "wins": wins,
                        "total_debates": 1,
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                )
    except Exception:
        pass


async def get_leaderboard() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/leaderboard",
                headers={**HEADERS, "Prefer": ""},
                params={"order": "wins.desc"},
            )
        if resp.status_code == 200:
            return {
                row["bot_name"]: {"wins": row["wins"], "total": row["total_debates"]}
                for row in resp.json()
            }
        return {}
    except Exception:
        return {}
