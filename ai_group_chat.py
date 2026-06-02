"""
🤖 Multi-AI Telegram Group Chat — v4 Optimized
================================================
Three AI bots (Claude, DeepSeek, Groq) debate topics.
BigBro oversees discussions, generates summaries, runs voting.

Fixes from v3:
- Removed debug print at startup
- Claude updated to claude-sonnet-4-6
- Leaderboard uses dedicated table (not message abuse)
- processed_messages capped at 10k to prevent RAM leak
- runtime.txt set to python-3.12.0
- Dead code (ai_discussion_bot.py) removed
- ai_group_chat.log removed from git
"""

import asyncio
import logging
import os
import random
import sys
import time

import httpx
from dotenv import load_dotenv
from memory import (
    save_message, get_history, format_history_for_prompt,
    update_leaderboard, get_leaderboard,
)
from telegram import Update, BotCommand
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, filters

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ── CONSTANTS ────────────────────────────────────────────────────────────
DEFAULT_ROUNDS = 2
MAX_TOKENS = 4096
MAX_PROCESSED_MESSAGES = 10_000  # cap to prevent RAM leak

# ── MODE SYSTEM ──────────────────────────────────────────────────────────
MODE_INSTRUCTIONS = {
    "normal": "",
    "sarcastic": (
        "\n[MODE: Sarcastic]\n"
        "You MUST respond with sharp, witty sarcasm. Be clever, biting, and humorous. "
        "Roll your eyes at obvious points, use exaggerated metaphors, and never take anything at face value. "
        "Your tone should be dripping with ironic detachment, like a stand-up comedian who's too smart for the room."
    ),
    "eli5": (
        "\n[MODE: ELI5 — Explain Like I'm 5]\n"
        "You MUST explain everything as if talking to a bright 5-year-old child. "
        "Use simple words, short sentences, and fun analogies. No big fancy terms. "
        "Be patient, warm, and enthusiastic."
    ),
    "disagree": (
        "\n[MODE: Disagree]\n"
        "You MUST challenge and contradict everything the other AIs say. "
        "No matter how reasonable their point, find a flaw or counter-argument. "
        "Be respectful but relentless. Never fully agree with anyone."
    ),
}
MODE_NAMES = list(MODE_INSTRUCTIONS.keys())

# ── BOT CONFIGS ──────────────────────────────────────────────────────────
BOT_CONFIGS = [
    {
        "name": "Claude", "icon": "🟣",
        "telegram_token": os.getenv("CLAUDE_TG_TOKEN"),
        "api_type": "anthropic", "api_key": os.getenv("ANTHROPIC_API_KEY", "").strip(),
        "model": "claude-sonnet-4-6", "temperature": 0.7,
        "prompt": (
            "You are Claude, a highly intelligent AI in a group chat with other AIs and humans. "
            "Use simple everyday English — no jargon, no bullet points. "
            "In casual conversation be natural and friendly, like texting a smart friend. "
            "Max 3-4 sentences per response. "
            "Structure: your opinion → your reasoning → a concrete example or counter. "
            "Be sharp, direct, and intellectually honest."
        ),
        "order": 0,
    },
    {
        "name": "DeepSeek", "icon": "🔴",
        "telegram_token": os.getenv("DEEPSEEK_TG_TOKEN"),
        "api_type": "deepseek", "api_key": os.getenv("DEEPSEEK_API_KEY"),
        "model": "deepseek-reasoner", "temperature": 0.3,
        "prompt": (
            "You are DeepSeek, a highly intelligent AI in a group chat with other AIs and humans. "
            "Use simple everyday English — no jargon, no bullet points. "
            "In casual conversation be natural and friendly, like texting a smart friend. "
            "Max 3-4 sentences per response. "
            "Structure: your opinion → your reasoning → a concrete example or counter. "
            "Be sharp, direct, and intellectually honest."
        ),
        "order": 1,
    },
    {
        "name": "Groq", "icon": "🔵",
        "telegram_token": os.getenv("GROQ_TG_TOKEN"),
        "api_type": "groq", "api_key": os.getenv("GROQ_API_KEY"),
        "model": "llama-3.1-8b-instant", "temperature": 1.0,
        "prompt": (
            "You are Groq, fast and direct. Max 2 sentences only. Cut straight to the point. "
            "In casual conversation be natural, like texting a friend."
        ),
        "order": 2,
    },
    {
        "name": "BigBro", "icon": "👁",
        "telegram_token": os.getenv("BIGBRO_TG_TOKEN"),
        "api_type": "none", "api_key": "", "model": "", "temperature": 0,
        "prompt": "", "order": 3,
    },
]
BOT_CONFIGS.sort(key=lambda b: b["order"])
AI_BOT_CONFIGS = [c for c in BOT_CONFIGS if c["api_type"] != "none"]

# ── Global state ─────────────────────────────────────────────────────────
sessions: dict = {}
chat_modes: dict = {}
bot_apps: dict = {}
processed_messages: set = set()
active_conversation: dict = {}
groq_rate_limited: dict = {}


# =============================================================================
# AI CALLERS
# =============================================================================

async def call_anthropic(api_key, system, messages, model, temperature):
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model, "max_tokens": MAX_TOKENS,
                    "system": system, "messages": messages,
                    "temperature": temperature,
                },
            )
            if resp.status_code == 200:
                return resp.json()["content"][0]["text"]
            logger.error("Claude error %s: %s", resp.status_code, resp.text[:100])
            return None
    except Exception as e:
        logger.error("Claude exception: %s", e)
        return None


async def call_deepseek(api_key, system, messages, model, temperature):
    try:
        ds_messages = [{"role": "system", "content": system}]
        for m in messages:
            ds_messages.append({"role": m["role"], "content": m["content"]})
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": ds_messages, "max_tokens": MAX_TOKENS, "temperature": temperature},
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            logger.error("DeepSeek error %s: %s", resp.status_code, resp.text[:100])
            return None
    except Exception as e:
        logger.error("DeepSeek exception: %s", e)
        return None


async def call_groq(api_key, system, messages, model, temperature):
    try:
        groq_messages = [{"role": "system", "content": system}]
        for m in messages:
            groq_messages.append({"role": m["role"], "content": m["content"]})
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": groq_messages, "max_tokens": MAX_TOKENS, "temperature": temperature},
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            logger.error("Groq error %s: %s", resp.status_code, resp.text[:100])
            return None
    except Exception as e:
        logger.error("Groq exception: %s", e)
        return None


async def call_ai(config, messages):
    k, s, m, t = config["api_key"], config["prompt"], config["model"], config["temperature"]
    api = config["api_type"]
    logger.info("📞 API call → %s | model=%s", config["name"], m)
    if api == "anthropic":
        return await call_anthropic(k, s, messages, m, t)
    elif api == "deepseek":
        return await call_deepseek(k, s, messages, m, t)
    elif api == "groq":
        return await call_groq(k, s, messages, m, t)
    return None


# =============================================================================
# SESSION
# =============================================================================

class ChatSession:
    def __init__(self, chat_id, topic, max_rounds):
        self.chat_id = chat_id
        self.topic = topic
        self.max_rounds = max_rounds
        self.conversation = []
        self.current_idx = 0
        self.round = 1
        self.active = True
        self.task = None

    def get_next_bot(self):
        return AI_BOT_CONFIGS[self.current_idx]

    def is_done(self):
        return self.round > self.max_rounds

    def advance(self):
        self.current_idx += 1
        if self.current_idx >= len(AI_BOT_CONFIGS):
            self.current_idx = 0
            self.round += 1

    def get_next_config(self):
        next_idx = self.current_idx + 1
        if next_idx >= len(AI_BOT_CONFIGS):
            return AI_BOT_CONFIGS[0]
        return AI_BOT_CONFIGS[next_idx]

    def build_prompt(self, config):
        history = ""
        if self.conversation:
            history = "=== CONVERSATION SO FAR ===\n\n"
            for e in self.conversation:
                history += f"[{e['name']}]: {e['text']}\n\n"
            history += "============================\n\n"

        mode = chat_modes.get(self.chat_id, "normal")
        mode_instruction = MODE_INSTRUCTIONS.get(mode, "")

        is_final = self.round == self.max_rounds and self.current_idx == len(AI_BOT_CONFIGS) - 1
        if is_final:
            round_instruction = (
                "This is your final round — conclude and synthesize. "
                "Simple English, max 3 sentences. Summarise your key points and offer a final perspective."
            )
        else:
            round_instruction = (
                "Simple English, max 3 sentences. "
                "Directly address what the previous speaker said — agree or disagree with specific reasoning."
            )

        next_bot = self.get_next_config()
        question_instruction = (
            f"At the end, add: 💬 *Question for @{next_bot['name']}:* "
            f"a direct question about something they said or an idea you want them to explore."
        )

        respond_instruction = ""
        if self.conversation:
            prev = self.conversation[-1]["name"]
            respond_instruction = (
                f"You MUST directly respond to what {prev} just said before adding your own point. "
                f"Quote or reference their specific argument."
            )

        return (
            f"TOPIC: {self.topic}\n\n{history}"
            f"It is YOUR turn to speak, {config['name']}.\n"
            f"Round {self.round}/{self.max_rounds}.\n\n"
            f"{respond_instruction}\n\n"
            f"{round_instruction}\n\n"
            f"{question_instruction}\n\n"
            f"{mode_instruction}\n\n"
            f"Now speak as {config['name']}:"
        )


# =============================================================================
# HELPERS
# =============================================================================

def split_response(text, max_size=3500):
    if len(text) <= max_size:
        return [text]
    chunks = []
    while len(text) > max_size:
        cut = text.rfind("\n\n", 0, max_size)
        if cut == -1:
            cut = text.rfind(". ", 0, max_size)
        if cut == -1:
            cut = max_size
        else:
            cut += 1
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks


async def keep_typing(bot, chat_id, stop_event):
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass
        await asyncio.sleep(1)


def get_mode_instruction(chat_id):
    mode = chat_modes.get(chat_id, "normal")
    return MODE_INSTRUCTIONS.get(mode, "")


async def safe_send(bot, chat_id, text):
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except BadRequest:
        await bot.send_message(chat_id=chat_id, text=text)


def _track_message(msg_id: int) -> bool:
    """Return True if this message_id is new (not yet seen). Caps set size."""
    global processed_messages
    if msg_id in processed_messages:
        return False
    processed_messages.add(msg_id)
    if len(processed_messages) > MAX_PROCESSED_MESSAGES:
        # Drop oldest half
        keep = sorted(processed_messages)[-MAX_PROCESSED_MESSAGES // 2:]
        processed_messages = set(keep)
    return True


def is_directly_addressed(text, bot_name):
    text_lower = text.lower()
    name_lower = bot_name.lower()
    icons = {"BigBro": "👁", "Claude": "🟣", "DeepSeek": "🔴", "Groq": "🔵"}
    emoji = icons.get(bot_name, "")

    if text_lower.startswith(name_lower) or (emoji and text.startswith(emoji)):
        return True
    for pattern in [f"hey {name_lower}", f"hi {name_lower}", f"hello {name_lower}"]:
        if pattern in text_lower:
            return True
    for pattern in [f"{name_lower} what", f"{name_lower} can", f"ask {name_lower}",
                    f"{name_lower}, what", f"{name_lower} do you"]:
        if pattern in text_lower:
            return True
    return False


# =============================================================================
# CASUAL REPLY
# =============================================================================

async def reply_to_human(chat_id, human_message, target_bot=None):
    mode_instruction = get_mode_instruction(chat_id)
    history = await get_history(chat_id, limit=50)
    history_text = format_history_for_prompt(history, "")

    async def call_and_send_ai(config):
        if target_bot and config["name"].lower() != target_bot.lower():
            return
        bot_app = bot_apps.get(config["name"])
        if not bot_app:
            return

        other_names = [b["name"] for b in AI_BOT_CONFIGS if b["name"] != config["name"]]
        prompt = (
            f"You are {config['name']}, a highly intelligent AI in a group chat "
            f"with {' and '.join(other_names)} and humans.\n"
            f"Rules: No bullet points. Max 3-4 sentences. Be sharp and direct.\n\n"
            f"{history_text}\n\n"
            f"Human message: \"{human_message}\"\n\n"
            f"Reply naturally in 2-3 short sentences.{mode_instruction}"
        )

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(bot_app.bot, chat_id, stop_typing))
        response = await call_ai(config, [{"role": "user", "content": prompt}])
        stop_typing.set()
        await typing_task

        if response:
            response = response.strip()
            await bot_app.bot.send_message(chat_id=chat_id, text=f"{config['icon']} {response}")
            await save_message(chat_id, config["name"], response, is_bot=True)
        else:
            if config["name"] == "Groq":
                now = time.time()
                if now - groq_rate_limited.get(chat_id, 0) > 60:
                    groq_rate_limited[chat_id] = now
                    await bot_app.bot.send_message(
                        chat_id=chat_id,
                        text="🔵 Groq is rate limited. Back soon.",
                    )

    async def call_and_send_bigbro():
        if target_bot and target_bot.lower() != "bigbro":
            return
        bot_app = bot_apps.get("BigBro")
        if not bot_app:
            return
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            return

        prompt = (
            "You are BigBro, a wise and warm presence in this group. "
            "Be natural and friendly. Reply in 1-2 sentences.\n\n"
            f"{history_text}\n\n"
            f"Human message: \"{human_message}\"\n\n"
            f"Reply naturally.{mode_instruction}"
        )

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(bot_app.bot, chat_id, stop_typing))
        response = await call_deepseek(api_key, prompt, [{"role": "user", "content": human_message}], "deepseek-chat", 0.7)
        stop_typing.set()
        await typing_task

        if response:
            response = response.strip()
            await bot_app.bot.send_message(chat_id=chat_id, text=f"👁 {response}")
            await save_message(chat_id, "BigBro", response, is_bot=True)

    tasks = [call_and_send_ai(config) for config in AI_BOT_CONFIGS]
    tasks.append(call_and_send_bigbro())
    await asyncio.gather(*tasks)


# =============================================================================
# DISCUSSION ENGINE
# =============================================================================

async def run_discussion(session: ChatSession):
    while session.active and not session.is_done():
        config = session.get_next_bot()
        bot_app = bot_apps.get(config["name"])
        if not bot_app:
            session.advance()
            continue

        prompt = session.build_prompt(config)
        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(bot_app.bot, session.chat_id, stop_typing))

        logger.info("🎤 %s %s (R%s/%s) thinking...", config["icon"], config["name"], session.round, session.max_rounds)
        response = await call_ai(config, [{"role": "user", "content": prompt}])

        stop_typing.set()
        await typing_task

        if response:
            response = response.strip()
            header = f"{config['icon']} *{config['name']}* — Round {session.round}/{session.max_rounds}"
            chunks = split_response(response)
            await safe_send(bot_app.bot, session.chat_id, f"{header}\n\n{chunks[0]}")
            for chunk in chunks[1:]:
                await asyncio.sleep(0.5)
                await bot_app.bot.send_message(chat_id=session.chat_id, text=chunk)
            session.conversation.append({"name": config["name"], "text": response})
            await save_message(session.chat_id, config["name"], response, is_bot=True)
        else:
            await safe_send(bot_app.bot, session.chat_id, f"{config['icon']} *{config['name']}* — ⚠️ API skip")

        if not session.active:
            break
        session.advance()
        await asyncio.sleep(0.5)

    if session.is_done() and session.active:
        bigbro_bot = bot_apps.get("BigBro")
        if not bigbro_bot:
            session.active = False
            sessions.pop(session.chat_id, None)
            return

        wc = sum(len(e["text"].split()) for e in session.conversation)
        await safe_send(
            bigbro_bot.bot, session.chat_id,
            (
                f"👁 *Discussion Complete!*\n\n"
                f"📌 *Topic:* {session.topic}\n"
                f"💬 {len(session.conversation)} responses | ~{wc} words\n\n"
                f"🤔 Generating summary and asking AIs to vote..."
            ),
        )

        summary = await generate_structured_summary(session)
        if summary:
            await safe_send(bigbro_bot.bot, session.chat_id, summary)

        await asyncio.sleep(0.5)
        await run_voting(session, bigbro_bot)
        session.active = False

    sessions.pop(session.chat_id, None)


async def generate_structured_summary(session: ChatSession):
    text = "\n\n".join(f"[{e['name']}]: {e['text']}" for e in session.conversation)
    prompt = (
        f"Read this discussion and write a simple summary a normal person can understand in 30 seconds.\n\n"
        f"Discussion:\n{text}\n\n"
        f"Format exactly like this:\n\n"
        f"🟣 Claude thought: [1 simple sentence]\n"
        f"🔴 DeepSeek thought: [1 simple sentence]\n"
        f"🔵 Groq thought: [1 simple sentence]\n\n"
        f"🏆 Strongest argument: [which AI and why in 1 sentence]\n"
        f"📌 Bottom line: [answer the original question in 1 sentence]\n\n"
        f"Use simple words. No jargon. Max 5 lines total."
    )
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return None
    resp = await call_deepseek(api_key, prompt, [{"role": "user", "content": prompt}], "deepseek-chat", 0.3)
    if resp:
        return f"📋 *Summary*\n\n{resp.strip()}"
    return None


async def run_voting(session: ChatSession, bigbro_bot):
    text = "\n\n".join(f"[{e['name']}]: {e['text']}" for e in session.conversation)
    votes = []

    for config in AI_BOT_CONFIGS:
        bot_app = bot_apps.get(config["name"])
        if not bot_app:
            continue

        vote_prompt = (
            f"The discussion was about: {session.topic}\n"
            f"Arguments:\n{text}\n\n"
            f"Who made the strongest argument — Claude, DeepSeek, or Groq? "
            f"Answer in one sentence: '[Name] made the strongest argument because [one reason].'\n"
            f"You cannot vote for yourself."
        )

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(bot_app.bot, session.chat_id, stop_typing))
        response = await call_ai(config, [{"role": "user", "content": vote_prompt}])
        stop_typing.set()
        await typing_task

        if response:
            votes.append({"voter": config["name"], "icon": config["icon"], "response": response.strip()})

    if not votes:
        await safe_send(bigbro_bot.bot, session.chat_id, "❌ No votes collected.")
        return

    tally = {}
    vote_lines = []
    winner_reason = ""

    for v in votes:
        resp = v["response"]
        winner = "Unknown"
        reason = ""
        for ai in AI_BOT_CONFIGS:
            if resp.lower().startswith(ai["name"].lower()):
                winner = ai["name"]
                if "because" in resp.lower():
                    reason = resp.split("because", 1)[1].strip().rstrip(".")
                break
        if winner == "Unknown":
            for ai in AI_BOT_CONFIGS:
                if ai["name"].lower() in resp.lower():
                    winner = ai["name"]
                    if "because" in resp.lower():
                        reason = resp.split("because", 1)[1].strip().rstrip(".")
                    break
        tally[winner] = tally.get(winner, 0) + 1
        vote_lines.append(f"{v['icon']} {v['voter']} voted for: {winner}")
        if not winner_reason:
            winner_reason = reason

    winner_name = max(tally, key=tally.get)
    winner_icon = next((ai["icon"] for ai in AI_BOT_CONFIGS if ai["name"] == winner_name), "")
    declaration = f"🏆 Winner: {winner_icon} {winner_name} with {tally[winner_name]} vote(s)"
    why_line = f"💡 Why: {winner_reason}" if winner_reason else ""

    result = "🗳 VOTES:\n" + "\n".join(vote_lines) + f"\n\n{declaration}"
    if why_line:
        result += f"\n{why_line}"

    await safe_send(bigbro_bot.bot, session.chat_id, result)
    await update_leaderboard(winner_name, [ai["name"] for ai in AI_BOT_CONFIGS])


async def generate_bigbro_summary(chat_id):
    history = await get_history(chat_id, limit=1000)
    if not history:
        return None
    history_text = format_history_for_prompt(history, "")
    prompt = (
        f"Here is the conversation history from an AI group chat:\n\n{history_text}\n\n"
        f"Write a concise summary covering:\n"
        f"1. The main topics discussed\n"
        f"2. Key points made by each participant\n"
        f"3. Any conclusions reached\n\n"
        f"Be thorough but concise. 3-5 paragraphs."
    )
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return None
    resp = await call_deepseek(api_key, prompt, [{"role": "user", "content": prompt}], "deepseek-chat", 0.3)
    if resp:
        return f"📋 *Full History Summary*\n\n{resp.strip()}"
    return None


# =============================================================================
# BOT BUILDER
# =============================================================================

def build_bot(config):

    if config["name"] == "BigBro":
        app = Application.builder().token(config["telegram_token"]).build()
        bot_apps[config["name"]] = app

        async def cmd_start(update, context):
            await update.message.reply_text(
                "👁 *BigBro* — Discussion Judge ready!\n\n"
                "`/discuss <topic>` — start AI debate\n"
                "`/discuss rounds=N <topic>` — custom rounds (1-10)\n"
                "`/stop` — halt discussion\n"
                "`/summary` — full chat summary\n"
                "`/vote` — ask AIs to vote\n"
                "`/leaderboard` — all-time debate wins\n"
                "`/topics` — get 5 debate topic ideas\n"
                "`/challenge` — random 1v1 debate",
                parse_mode="Markdown",
            )

        async def cmd_discuss(update, context):
            ADMIN_ID = 687396965
            if update.effective_user.id != ADMIN_ID:
                await update.message.reply_text("⛔ Only the admin can start discussions.")
                return

            chat_id = update.effective_chat.id
            active_conversation.pop(chat_id, None)

            existing = sessions.get(chat_id)
            if existing and existing.active:
                await update.message.reply_text("❌ Discussion already running! Use `/stop` first.", parse_mode="Markdown")
                return

            args = context.args
            if not args:
                await update.message.reply_text("Example: `/discuss Is AI smarter than humans?`", parse_mode="Markdown")
                return

            max_rounds = DEFAULT_ROUNDS
            topic_parts = list(args)
            if topic_parts and topic_parts[0].lower().startswith("rounds="):
                try:
                    max_rounds = max(1, min(int(topic_parts[0].split("=")[1]), 10))
                    topic_parts = topic_parts[1:]
                except ValueError:
                    pass

            if not topic_parts:
                await update.message.reply_text("❌ Please provide a topic!")
                return

            topic = " ".join(topic_parts)
            names = " → ".join(f"{b['icon']}{b['name']}" for b in AI_BOT_CONFIGS)
            current_mode = chat_modes.get(chat_id, "normal")
            mode_line = f"🎭 *Mode:* {current_mode}\n" if current_mode != "normal" else ""

            session = ChatSession(chat_id, topic, max_rounds)
            sessions[chat_id] = session

            await update.message.reply_text(
                f"👁 *Discussion Started!*\n\n"
                f"📌 *Topic:* {topic}\n"
                f"👥 *Order:* {names}\n"
                f"🔄 *{max_rounds} rounds each*\n"
                f"{mode_line}\n"
                f"Starting with {AI_BOT_CONFIGS[0]['icon']} {AI_BOT_CONFIGS[0]['name']}... ⏳\n\n"
                f"Use `/stop` to cancel.",
                parse_mode="Markdown",
            )
            session.task = asyncio.create_task(run_discussion(session))

        async def cmd_stop(update, context):
            sess = sessions.get(update.effective_chat.id)
            if sess and sess.active:
                sess.active = False
                await update.message.reply_text("🛑 Discussion stopped.")
            else:
                await update.message.reply_text("No active discussion.")

        async def cmd_summary(update, context):
            chat_id = update.effective_chat.id
            await update.message.reply_text("🤔 Generating summary from full history...")
            summary = await generate_bigbro_summary(chat_id)
            if summary:
                await safe_send(app.bot, chat_id, summary)
            else:
                await update.message.reply_text("❌ Could not generate summary.")

        async def cmd_topics(update, context):
            chat_id = update.effective_chat.id
            api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
            if not api_key:
                await update.message.reply_text("❌ DeepSeek API key not configured.")
                return
            await update.message.reply_text("💡 Generating topics...")
            prompt = (
                "Generate 5 sharp, controversial, thought-provoking discussion topics for highly intelligent AI agents. "
                "Format:\n1. [topic]\n2. [topic]\n3. [topic]\n4. [topic]\n5. [topic]\n"
                "No explanations, just the topics."
            )
            resp = await call_deepseek(api_key, prompt, [{"role": "user", "content": prompt}], "deepseek-chat", 0.7)
            if resp:
                await safe_send(app.bot, chat_id, f"💡 *Topics:*\n\n{resp.strip()}\n\nPick one and send /discuss <topic>")
            else:
                await update.message.reply_text("❌ Could not generate topics.")

        async def cmd_vote(update, context):
            chat_id = update.effective_chat.id
            sess = sessions.get(chat_id)
            if not sess or not sess.conversation:
                await update.message.reply_text("No discussion to vote on. Use `/discuss <topic>` first.", parse_mode="Markdown")
                return
            await update.message.reply_text("🗳️ Asking AIs to vote...")
            await run_voting(sess, bot_apps["BigBro"])

        async def cmd_leaderboard(update, context):
            data = await get_leaderboard()
            if not data:
                await update.message.reply_text("No debates yet! Use /discuss to start.")
                return
            sorted_bots = sorted(data.items(), key=lambda x: x[1]["wins"], reverse=True)
            medals = ["🥇", "🥈", "🥉"]
            msg = "🏆 *ALL TIME LEADERBOARD*\n\n"
            for i, (bot, stats) in enumerate(sorted_bots):
                medal = medals[i] if i < 3 else "▪️"
                pct = round(stats["wins"] / stats["total"] * 100) if stats["total"] > 0 else 0
                msg += f"{medal} {bot} — {stats['wins']} wins / {stats['total']} debates ({pct}%)\n"
            await update.message.reply_text(msg, parse_mode="Markdown")

        async def cmd_challenge(update, context):
            chat_id = update.effective_chat.id
            bots = [c for c in BOT_CONFIGS if c["name"] != "BigBro"]
            chosen = random.sample(bots, 2)
            topics = [
                ("AI will make humans obsolete", "AI will always need humans"),
                ("Money buys happiness", "Money cannot buy happiness"),
                ("Free will exists", "Free will is an illusion"),
                ("Social media does more harm than good", "Social media does more good than harm"),
                ("Failure is necessary for success", "Success can be achieved without failure"),
            ]
            topic_pair = random.choice(topics)
            a, b = chosen
            await update.message.reply_text(
                f"⚔️ *CHALLENGE ROUND!*\n\n"
                f"{a['icon']} {a['name']} argues: *{topic_pair[0]}*\n"
                f"{b['icon']} {b['name']} argues: *{topic_pair[1]}*\n\n"
                f"Starting in 3 seconds...",
                parse_mode="Markdown",
            )
            await asyncio.sleep(3)
            session = ChatSession(chat_id, f"{topic_pair[0]} vs {topic_pair[1]}", 2)
            sessions[chat_id] = session
            session.task = asyncio.create_task(run_discussion(session))

        async def handle_message(update, context):
            if not _track_message(update.message.message_id):
                return
            chat_id = update.effective_chat.id
            human_text = update.message.text
            sender_name = update.message.from_user.first_name or "Human"
            await save_message(chat_id, sender_name, human_text, is_bot=False)

            text_lower = human_text.lower()
            group_keywords = ["everyone", " all ", "guys", "y'all", "yall", "what do you all think", "anyone"]
            addressed_to_group = any(kw in text_lower for kw in group_keywords)

            if addressed_to_group:
                active_conversation.pop(chat_id, None)
                target_bot = None
            else:
                target_bot = None
                for bot_name in ["BigBro", "Claude", "DeepSeek", "Groq"]:
                    if is_directly_addressed(human_text, bot_name):
                        target_bot = bot_name
                        break
                if target_bot:
                    active_conversation[chat_id] = target_bot
                elif chat_id in active_conversation:
                    target_bot = active_conversation[chat_id]

            asyncio.create_task(reply_to_human(chat_id, human_text, target_bot=target_bot))

        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("help", cmd_start))
        app.add_handler(CommandHandler("discuss", cmd_discuss))
        app.add_handler(CommandHandler("stop", cmd_stop))
        app.add_handler(CommandHandler("summary", cmd_summary))
        app.add_handler(CommandHandler("topics", cmd_topics))
        app.add_handler(CommandHandler("vote", cmd_vote))
        app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
        app.add_handler(CommandHandler("challenge", cmd_challenge))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        return app

    # ── AI bots (Claude, DeepSeek, Groq) ────────────────────────────────
    app = Application.builder().token(config["telegram_token"]).build()
    bot_apps[config["name"]] = app

    async def cmd_mode(update, context):
        if config["order"] != 0:
            return
        chat_id = update.effective_chat.id
        args = context.args
        if not args:
            current = chat_modes.get(chat_id, "normal")
            modes_list = " | ".join(f"`{m}`" if m != current else f"*`{m}`*" for m in MODE_NAMES)
            await update.message.reply_text(
                f"🎭 Current mode: *{current}*\n\nAvailable: {modes_list}\n\nUsage: `/mode <name>`",
                parse_mode="Markdown",
            )
            return
        mode = args[0].lower()
        if mode not in MODE_NAMES:
            await update.message.reply_text(f"❌ Unknown mode: `{mode}`\n\nAvailable: {', '.join(MODE_NAMES)}", parse_mode="Markdown")
            return
        chat_modes[chat_id] = mode
        descriptions = {
            "normal": "✅ Reset to normal mode.",
            "sarcastic": "😏 *Sarcastic mode* activated!",
            "eli5": "🧒 *ELI5 mode* activated!",
            "disagree": "⚔️ *Disagree mode* activated!",
        }
        await update.message.reply_text(descriptions.get(mode, f"Mode set to {mode}"), parse_mode="Markdown")

    async def handle_message(update, context):
        if config["order"] != 0:
            return
        if not _track_message(update.message.message_id):
            return
        chat_id = update.effective_chat.id
        human_text = update.message.text
        sender_name = update.message.from_user.first_name or "Human"
        await save_message(chat_id, sender_name, human_text, is_bot=False)

        text_lower = human_text.lower()
        group_keywords = ["everyone", " all ", "guys", "y'all", "yall", "what do you all think", "anyone"]
        addressed_to_group = any(kw in text_lower for kw in group_keywords)

        if addressed_to_group:
            active_conversation.pop(chat_id, None)
            target_bot = None
        else:
            target_bot = None
            for bot_name in ["BigBro", "Claude", "DeepSeek", "Groq"]:
                if is_directly_addressed(human_text, bot_name):
                    target_bot = bot_name
                    break
            if target_bot:
                active_conversation[chat_id] = target_bot
            elif chat_id in active_conversation:
                target_bot = active_conversation[chat_id]

        asyncio.create_task(reply_to_human(chat_id, human_text, target_bot=target_bot))

    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("start", cmd_mode))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app


# =============================================================================
# MAIN
# =============================================================================

async def main():
    print("\n" + "=" * 60)
    print("  🧠  MULTI-AI GROUP CHAT — v4 Optimized")
    print("=" * 60)

    missing = [c["name"] for c in BOT_CONFIGS if not c["telegram_token"]]
    if missing:
        print(f"\n⚠️  Missing Telegram tokens for: {', '.join(missing)}")
        print("Check your Railway environment variables.")
        return

    apps = []
    for config in BOT_CONFIGS:
        app = build_bot(config)
        await app.initialize()

        if config["name"] == "BigBro":
            await app.bot.set_my_commands([
                BotCommand("start", "Welcome & commands"),
                BotCommand("discuss", "/discuss [rounds=N] <topic>"),
                BotCommand("stop", "Stop discussion"),
                BotCommand("summary", "Generate summary"),
                BotCommand("vote", "Ask AIs to vote"),
                BotCommand("leaderboard", "All-time wins"),
                BotCommand("topics", "Get topic ideas"),
                BotCommand("challenge", "Random 1v1 debate"),
            ])
        else:
            await app.bot.set_my_commands([
                BotCommand("mode", "/mode <sarcastic|eli5|disagree|normal>"),
            ])

        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        print(f"  ✅ {config['icon']} @{config['name']} — LIVE")
        apps.append(app)

    print("\n  ✅ ALL BOTS RUNNING!")
    print("=" * 60)

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        print("\n👋 Stopping...")
        for s in list(sessions.values()):
            s.active = False
        for app in reversed(apps):
            await app.updater.stop()
            await app.stop()
            await app.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bots stopped.")
