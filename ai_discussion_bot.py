"""
🤖 Multi-AI Discussion Bot — Telegram
=======================================
Several REAL AI models (Claude, GPT, Gemini, DeepSeek, Grok)
discuss a topic you give them, each taking turns in a Telegram group.

Commands:
  /discuss <topic>   — Start a discussion between all AIs
  /join              — Which AIs are in this chat
  /settings          — Show current AI lineup
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Optional, List

import requests
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    MessageHandler,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── API Keys from environment ─────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
GROK_API_KEY = os.getenv("GROK_API_KEY", "")
CLAUDE_TG_TOKEN = os.getenv("CLAUDE_TG_TOKEN", "")

# ── AI Agent Definitions ─────────────────────────────────────────────────────
AI_AGENTS = [
    {
        "id": "claude",
        "name": "Claude",
        "icon": "🟣",
        "company": "Anthropic",
        "model": "claude-sonnet-4-20250514",
        "api_type": "anthropic",
        "api_key": ANTHROPIC_API_KEY,
        "enabled": bool(ANTHROPIC_API_KEY),
        "personality": "You are Claude, created by Anthropic. You are thoughtful, nuanced, and carefully consider multiple perspectives before forming conclusions. You value wisdom, honesty, and depth. You tend to explore the ethical and philosophical dimensions of questions. You respond to what others have said and build on their ideas.",
    },
    {
        "id": "gpt",
        "name": "GPT-4o",
        "icon": "🟢",
        "company": "OpenAI",
        "model": "gpt-4o",
        "api_type": "openai",
        "api_key": OPENAI_API_KEY,
        "enabled": bool(OPENAI_API_KEY),
        "personality": "You are GPT-4o, created by OpenAI. You are direct, articulate, and practical. You focus on providing clear, well-structured reasoning. You are comfortable with ambiguity and can argue multiple sides of an issue. You bring in research, data, and real-world examples. You respond to others and advance the discussion.",
    },
    {
        "id": "gemini",
        "name": "Gemini",
        "icon": "🔵",
        "company": "Google DeepMind",
        "model": "gemini-2.0-flash",
        "api_type": "gemini",
        "api_key": GEMINI_API_KEY,
        "enabled": bool(GEMINI_API_KEY),
        "personality": "You are Gemini, created by Google DeepMind. You are knowledgeable, creative, and good at connecting ideas across different fields. You offer a balanced perspective, considering both practical and theoretical angles. You synthesize what others have said and add new dimensions to the conversation.",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "icon": "🔴",
        "company": "DeepSeek",
        "model": "deepseek-reasoner",
        "api_type": "deepseek",
        "api_key": DEEPSEEK_API_KEY,
        "enabled": bool(DEEPSEEK_API_KEY),
        "personality": "You are DeepSeek, a reasoning-focused AI created by DeepSeek. You are analytical, precise, and good at breaking down complex problems step by step. You focus on logical structure, causal relationships, and clear reasoning. You respect others' views but are not afraid to point out logical gaps. You are concise and to the point.",
    },
    {
        "id": "grok",
        "name": "Grok",
        "icon": "⚫",
        "company": "xAI",
        "model": "grok-2",
        "api_type": "grok",
        "api_key": GROK_API_KEY,
        "enabled": bool(GROK_API_KEY),
        "personality": "You are Grok, created by xAI. You are witty, direct, and not afraid to challenge conventional wisdom. You have a sharp sense of humor but take important questions seriously. You bring unconventional perspectives and often see things from a fresh angle. You enjoy a good debate and are quick to spot weak arguments.",
    },
]

# Maximum discussion rounds
MAX_ROUNDS = 3  # Each AI speaks this many times

# ── AI API Callers ──────────────────────────────────────────────────────────

def call_anthropic(system: str, messages: list, model: str) -> Optional[str]:
    """Call Claude via Anthropic API."""
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1000,
                "system": system,
                "messages": messages,
                "temperature": 0.8,
            },
            timeout=60,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data["content"][0]["text"]
        logger.error(f"Claude error {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"Claude exception: {e}")
        return None


def call_openai(system: str, messages: list, model: str) -> Optional[str]:
    """Call GPT via OpenAI API."""
    try:
        openai_messages = [{"role": "system", "content": system}]
        for m in messages:
            openai_messages.append({"role": m["role"], "content": m["content"]})

        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": openai_messages,
                "max_tokens": 1000,
                "temperature": 0.8,
            },
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        logger.error(f"GPT error {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"GPT exception: {e}")
        return None


def call_gemini(system: str, messages: list, model: str) -> Optional[str]:
    """Call Gemini via Google AI API."""
    try:
        # Build Gemini format: system message goes first as user message
        gemini_contents = [{"parts": [{"text": system}], "role": "user"}]
        gemini_contents.append({"parts": [{"text": "Understood. I'll follow those instructions."}], "role": "model"})

        for m in messages:
            role = "model" if m["role"] in ("assistant", "model") else "user"
            gemini_contents.append({"parts": [{"text": m["content"]}], "role": role})

        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": GEMINI_API_KEY},
            json={"contents": gemini_contents},
            timeout=60,
        )
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
            return None
        logger.error(f"Gemini error {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"Gemini exception: {e}")
        return None


def call_deepseek(system: str, messages: list, model: str) -> Optional[str]:
    """Call DeepSeek via their API."""
    try:
        ds_messages = [{"role": "system", "content": system}]
        for m in messages:
            ds_messages.append({"role": m["role"], "content": m["content"]})

        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": ds_messages,
                "max_tokens": 1000,
                "temperature": 0.8,
            },
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        logger.error(f"DeepSeek error {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"DeepSeek exception: {e}")
        return None


def call_grok(system: str, messages: list, model: str) -> Optional[str]:
    """Call Grok via xAI API."""
    try:
        grok_messages = [{"role": "system", "content": system}]
        for m in messages:
            grok_messages.append({"role": m["role"], "content": m["content"]})

        resp = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": grok_messages,
                "max_tokens": 1000,
                "temperature": 0.8,
            },
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        logger.error(f"Grok error {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"Grok exception: {e}")
        return None


# ── Router ──────────────────────────────────────────────────────────────────

def call_ai(agent: dict, messages: list) -> Optional[str]:
    """Call the appropriate AI API based on agent type."""
    system = agent["personality"]
    model = agent["model"]
    api_type = agent["api_type"]

    if api_type == "anthropic":
        return call_anthropic(system, messages, model)
    elif api_type == "openai":
        return call_openai(system, messages, model)
    elif api_type == "gemini":
        return call_gemini(system, messages, model)
    elif api_type == "deepseek":
        return call_deepseek(system, messages, model)
    elif api_type == "grok":
        return call_grok(system, messages, model)
    return None


# ── Build conversation prompt for each AI ──────────────────────────────────

def build_messages(agent: dict, topic: str, conversation: list) -> list:
    """Build the message history for an AI to respond to."""
    messages = []

    # First message — introduce the topic and what the AI should do
    intro = f"""The group is discussing this topic:
TOPIC: {topic}

You are participating in a round-table discussion with other AIs.
Respond directly to what the others have said so far.
Be concise (2-4 paragraphs max).
Advance the discussion — don't just repeat.
Stay true to your personality as described in your system prompt."""

    messages.append({"role": "user", "content": intro})

    # Add conversation history
    for entry in conversation:
        role = "assistant" if entry.get("is_ai") else "user"
        speaker = entry["agent_name"]
        text = entry["text"]
        messages.append({"role": role, "content": f"[{speaker} said]: {text}"})

    # Final prompt
    messages.append({
        "role": "user",
        "content": f"It is now YOUR turn to speak as {agent['name']}. Respond directly to the discussion above. Advance the conversation."
    })

    return messages


# ── Telegram Bot Handlers ───────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message."""
    enabled = [a for a in AI_AGENTS if a["enabled"]]
    disabled = [a for a in AI_AGENTS if not a["enabled"]]

    msg = (
        "🤖 *Multi-AI Discussion Bot*\n\n"
        "I bring together *real AI models* to discuss topics you choose!\n\n"
        "Commands:\n"
        "`/discuss <topic>` — Start a discussion\n"
        "`/status` — See which AIs are available\n"
        "`/help` — Show this message\n\n"
    )

    if enabled:
        msg += "✅ *Active AIs:*\n"
        for a in enabled:
            msg += f"  {a['icon']} {a['name']} ({a['company']})\n"

    if disabled:
        msg += "\n❌ *Waiting for API keys:*\n"
        for a in disabled:
            msg += f"  {a['icon']} {a['name']} ({a['company']}) — set {a['id'].upper()}_API_KEY\n"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show which AIs are available."""
    msg = "📡 *AI Status Report*\n\n"
    for a in AI_AGENTS:
        status = "✅ Ready" if a["enabled"] else "❌ No API key"
        msg += f"{a['icon']} *{a['name']}* — {status}\n"
    msg += "\nSet missing keys in environment variables.\n"
    msg += "Then restart the bot."
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_discuss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a discussion between all available AIs on a topic."""
    # Get the topic
    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ Tell me what to discuss!\n"
            "Example: `/discuss Is homeschooling better than school?`",
            parse_mode="Markdown",
        )
        return

    topic = " ".join(args)

    # Check which AIs are available
    available = [a for a in AI_AGENTS if a["enabled"]]
    if len(available) < 2:
        await update.message.reply_text(
            "❌ Need at least 2 AIs to start a discussion.\n"
            f"Currently only {len(available)} AI(s) have API keys configured.\n"
            "Check /status for details.",
            parse_mode="Markdown",
        )
        return

    # Notify start
    ai_list = " + ".join([f"{a['icon']}{a['name']}" for a in available])
    await update.message.reply_text(
        f"🎯 *Discussion Started!*\n\n"
        f"📌 *Topic:* {topic}\n"
        f"👥 *Participants:* {ai_list}\n"
        f"🔄 *Rounds:* {MAX_ROUNDS} each\n\n"
        f"Watch them discuss below... ⏳",
        parse_mode="Markdown",
    )

    # Run the discussion asynchronously, posting each message to the chat
    await run_discussion(update, context, topic, available)


async def run_discussion(update: Update, context: ContextTypes.DEFAULT_TYPE, topic: str, agents: list):
    """Orchestrate a round-robin discussion between AIs."""
    chat_id = update.effective_chat.id
    conversation = []  # Stores the full discussion history
    total_messages = 0

    for round_num in range(1, MAX_ROUNDS + 1):
        for agent in agents:
            # Build messages for this agent
            messages = build_messages(agent, topic, conversation)

            # Show typing indicator
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")

            # Call the AI
            response = call_ai(agent, messages)

            if response:
                # Clean up the response
                response = response.strip()
                # Remove any prefix like "[Claude said]:" that might leak
                for a in agents:
                    prefix = f"[{a['name']} said]:"
                    if response.startswith(prefix):
                        response = response[len(prefix):].strip()

                # Post as a labeled message
                round_tag = f"─── Round {round_num} ───" if total_messages % len(agents) == 0 else ""
                header = f"{agent['icon']} *{agent['name']}*"
                if round_num == 1 and total_messages < len(agents):
                    header = f"{agent['icon']} *{agent['name']}*"
                elif round_tag:
                    header = f"\n{round_tag}\n{agent['icon']} *{agent['name']}*"
                else:
                    header = f"{agent['icon']} *{agent['name']}*"

                # Split into chunks if too long
                full_msg = f"{header}\n\n{response}"
                if len(full_msg) > 4000:
                    await update.message.reply_text(f"{header}\n\n{response[:4000]}", parse_mode="Markdown")
                else:
                    await update.message.reply_text(full_msg, parse_mode="Markdown")

                # Add to conversation history
                conversation.append({
                    "agent_id": agent["id"],
                    "agent_name": agent["name"],
                    "text": response,
                    "is_ai": True,
                })
                total_messages += 1

                # Brief pause between responses so messages arrive in order
                await asyncio.sleep(1.5)
            else:
                await update.message.reply_text(
                    f"{agent['icon']} *{agent['name']}* — ⚠️ Failed to respond. Skipping.",
                    parse_mode="Markdown",
                )

    # Final summary
    await update.message.reply_text(
        "🏁 *Discussion Complete!*\n\n"
        f"📌 *Topic:* {topic}\n"
        f"💬 *{total_messages}* responses from *{len(agents)}* AI models\n"
        f"🔄 *{MAX_ROUNDS}* rounds each\n\n"
        f"Start a new discussion with:\n"
        f"`/discuss <new topic>`",
        parse_mode="Markdown",
    )


# ── Main ────────────────────────────────────────────────────────────────────

async def _main_async():
    token = CLAUDE_TG_TOKEN
    if not token:
        print("❌ CLAUDE_TG_TOKEN is not set.")
        return

    # Check which AIs are available
    enabled = [a for a in AI_AGENTS if a["enabled"]]
    print("🚀 Starting Multi-AI Discussion Bot...")
    print(f"   Telegram: ✅ Token found")
    print(f"   Active AIs ({len(enabled)}):")
    for a in enabled:
        print(f"     {a['icon']} {a['name']} ({a['company']}) — ✅ {a['api_type']}")
    for a in AI_AGENTS:
        if not a["enabled"]:
            print(f"     {a['icon']} {a['name']} — ❌ Missing {a['id'].upper()}_API_KEY")
    print()

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("discuss", cmd_discuss))

    print("✅ Bot is running. Open Telegram and send /discuss <your topic>")
    print("   Press Ctrl+C to stop.\n")

    async with app:
        await app.initialize()
        await app.bot.set_my_commands([
            BotCommand("discuss", "Start AI discussion: /discuss <topic>"),
            BotCommand("status", "Show which AIs are available"),
            BotCommand("help", "Show help"),
        ])
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()


def main():
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
