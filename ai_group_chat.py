import os
print("=== RAILWAY ENV VARIABLES ===")
for key in ["CLAUDE_TG_TOKEN", "DEEPSEEK_TG_TOKEN", "GROQ_TG_TOKEN", "BIGBRO_TG_TOKEN", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "GROUP_CHAT_ID"]:
    value = os.getenv(key)
    print(f"{key}: {'✓ SET' if value else '✗ MISSING'}")

"""
🤖 Multi-AI Telegram Group Chat — v3 with BigBro Judge
======================================================
Three REAL AI bots (Claude, DeepSeek, Groq) debate topics.
👁 BigBro oversees discussions, generates summaries, runs voting, and replies casually.

FIXES:
  1. All keys from .env via python-dotenv (no hardcoded secrets)
  2. Async httpx calls (non-blocking)
  3. BigBro controls /discuss, /stop, /summary, /vote
  4. Each AI speaks through its OWN bot.
  5. BigBro also replies to human messages using Claude API.
"""

import asyncio
import logging
import os
import random
import sys

import httpx
from dotenv import load_dotenv
from memory import save_message, get_history, format_history_for_prompt
from telegram import Update, BotCommand
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, filters

print("🚀 BOT STARTING ON RAILWAY")

load_dotenv()
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# ── DEFAULTS ────────────────────────────────────────────────────────────
DEFAULT_ROUNDS = 2
MAX_TOKENS = 4096

# ── MODE SYSTEM ─────────────────────────────────────────────────────────
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
        "Use simple words, short sentences, and fun analogies. No big fancy terms — "
        "if you use one, immediately explain it with something a kid would understand. "
        "Be patient, warm, and enthusiastic. Imagine you're sitting on a colourful rug with building blocks."
    ),
    "disagree": (
        "\n[MODE: Disagree]\n"
        "You MUST challenge and contradict everything the other AIs say. "
        "No matter how reasonable their point, find a flaw, a counter-argument, or a different angle. "
        "Be respectful but relentless — play devil's advocate at every opportunity. "
        "Never fully agree with anyone. If you have to concede a point, immediately pivot to a new objection."
    ),
}

MODE_NAMES = list(MODE_INSTRUCTIONS.keys())  # ["normal", "sarcastic", "eli5", "disagree"]

# ── BOT CONFIGS (all secrets from .env!) ────────────────────────────────
BOT_CONFIGS = [
    {
        "name": "Claude",          "icon": "🟣",
        "telegram_token": os.getenv("CLAUDE_TG_TOKEN"),
        "api_type": "anthropic",   "api_key": os.getenv("ANTHROPIC_API_KEY", "").strip(),
        "model": "claude-sonnet-4-5",  "temperature": 0.7,
        "prompt": (
            "You are Claude, a highly intelligent AI agent in a group chat with other AI agents "
            "and humans. You have a distinct personality and high IQ. "
            "Use simple everyday English. No academic language, no jargon. Speak like a smart friend explaining something at a dinner table, not a professor writing a paper. "
            "Rules: Never give presentations or bullet points. Max 3-4 sentences per response. "
            "Structure: your opinion → your reasoning → a concrete example or counter. "
            "In discussions, directly address what the previous speaker said — agree or disagree with specific reasoning. "
            "Be sharp, direct, and intellectually honest. No filler words, no hedging, no 'great point'. "
            "Speak like a genius who respects others' intelligence."
        ),
        "order": 0,
    },
    {
        "name": "DeepSeek",        "icon": "🔴",
        "telegram_token": os.getenv("DEEPSEEK_TG_TOKEN"),
        "api_type": "deepseek",    "api_key": os.getenv("DEEPSEEK_API_KEY"),
        "model": "deepseek-reasoner",  "temperature": 0.3,
        "prompt": (
            "You are DeepSeek, a highly intelligent AI agent in a group chat with other AI agents "
            "and humans. You have a distinct personality and high IQ. "
            "Use simple everyday English. No academic language, no jargon. Speak like a smart friend explaining something at a dinner table, not a professor writing a paper. "
            "Rules: Never give presentations or bullet points. Max 3-4 sentences per response. "
            "Structure: your opinion → your reasoning → a concrete example or counter. "
            "In discussions, directly address what the previous speaker said — agree or disagree with specific reasoning. "
            "Be sharp, direct, and intellectually honest. No filler words, no hedging, no 'great point'. "
            "Speak like a genius who respects others' intelligence."
        ),
        "order": 1,
    },
    {
        "name": "Groq",            "icon": "🔵",
        "telegram_token": os.getenv("GROQ_TG_TOKEN"),
        "api_type": "groq",        "api_key": os.getenv("GROQ_API_KEY"),
        "model": "llama-3.1-8b-instant",  "temperature": 1.0,
        "prompt": (
            "You are Groq, fast and direct. Max 2 sentences only. Cut straight to the point. No examples, no elaboration."
        ),
        "order": 2,
    },
    {
        "name": "BigBro",          "icon": "👁",
        "telegram_token": os.getenv("BIGBRO_TG_TOKEN"),
        "api_type": "none",
        "api_key": "",
        "model": "",
        "temperature": 0,
        "prompt": "",
        "order": 3,
    },
]
BOT_CONFIGS.sort(key=lambda b: b["order"])
AI_BOT_CONFIGS = [c for c in BOT_CONFIGS if c["api_type"] != "none"]


# =============================================================================
# ASYNC AI CALLERS  (httpx, non-blocking)
# =============================================================================

async def call_anthropic(api_key, system, messages, model, temperature):
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": model, "max_tokens": MAX_TOKENS, "system": system, "messages": messages, "temperature": temperature},
            )
            if resp.status_code == 200:
                return resp.json()["content"][0]["text"]
            logger.error(f"Claude error {resp.status_code}: {resp.text[:100]}")
            return None
    except Exception as e:
        logger.error(f"Claude exception: {e}")
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
            logger.error(f"DeepSeek error {resp.status_code}: {resp.text[:100]}")
            return None
    except Exception as e:
        logger.error(f"DeepSeek exception: {e}")
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
            logger.error(f"Groq error {resp.status_code}: {resp.text[:100]}")
            return None
    except Exception as e:
        logger.error(f"Groq exception: {e}")
        return None


async def call_ai(config, messages):
    k = config["api_key"]
    s = config["prompt"]
    m = config["model"]
    t = config["temperature"]
    api = config["api_type"]
    logger.info(f"  📞 API call → {config['name']} | type={api} | model={m}")
    if api == "anthropic":
        return await call_anthropic(k, s, messages, m, t)
    elif api == "deepseek":
        return await call_deepseek(k, s, messages, m, t)
    elif api == "groq":
        return await call_groq(k, s, messages, m, t)
    return None


# =============================================================================
# SESSION (per-chat state)
# =============================================================================

class ChatSession:
    def __init__(self, chat_id, topic, max_rounds):
        self.chat_id = chat_id
        self.topic = topic
        self.max_rounds = max_rounds
        self.conversation = []   # [{name, text}, ...]
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
        """Return the config of the bot that will speak after the current one."""
        next_idx = self.current_idx + 1
        if next_idx >= len(AI_BOT_CONFIGS):
            # Next round, first bot speaks
            return AI_BOT_CONFIGS[0]
        return AI_BOT_CONFIGS[next_idx]

    def get_mode_instruction(self):
        """Return the mode instruction string for this chat's current mode."""
        mode = chat_modes.get(self.chat_id, "normal")
        return MODE_INSTRUCTIONS.get(mode, "")

    def build_prompt(self, config):
        history = ""
        if self.conversation:
            history = "=== CONVERSATION SO FAR ===\n\n"
            for e in self.conversation:
                history += f"[{e['name']}]: {e['text']}\n\n"
            history += "============================\n\n"

        is_final_round = self.round == self.max_rounds and self.current_idx == len(AI_BOT_CONFIGS) - 1
        if is_final_round:
            round_instruction = (
                "This is your final round — conclude and synthesize the conversation.\n"
                "Speak in simple clear English. No academic words. Max 3 sentences. "
                "Make your point like you're texting a smart friend. "
                "Structure: your opinion → your reasoning → a concrete example or counter. "
                "Summarise your key points, respond to counter-arguments, and "
                "offer a final, thoughtful perspective on the topic."
            )
        else:
            round_instruction = (
                "Speak in simple clear English. No academic words. Max 3 sentences. "
                "Make your point like you're texting a smart friend. "
                "Structure: your opinion → your reasoning → a concrete example or counter. "
                "Directly address what the previous speaker said — agree or disagree with specific reasoning."
            )

        next_bot = self.get_next_config()
        question_instruction = (
            f"At the end, add: 💬 *Question for @{next_bot['name']}:* "
            f"a direct question about something they said or an idea you want them to explore."
        )

        mode_instruction = self.get_mode_instruction()

        # Determine previous speaker
        previous_speaker = ""
        if self.conversation:
            previous_speaker = self.conversation[-1]["name"]
            respond_instruction = (
                f"You MUST directly respond to what {previous_speaker} just said before adding your own point. "
                f"Quote or reference their specific argument."
            )
        else:
            respond_instruction = ""

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


# ── Global stores ───────────────────────────────────────────────────────
sessions = {}        # chat_id -> ChatSession
chat_modes = {}      # chat_id -> mode string (e.g. "sarcastic", "eli5")
bot_apps = {}        # name -> Application


# =============================================================================
# HELPERS
# =============================================================================

def split_response(text, max_size=3500):
    """Split on paragraph boundaries."""
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
    """Send typing indicator every 1 s until stopped."""
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass
        await asyncio.sleep(1)


def get_mode_instruction(chat_id):
    """Get the mode instruction string for a given chat, defaulting to 'normal'."""
    mode = chat_modes.get(chat_id, "normal")
    return MODE_INSTRUCTIONS.get(mode, "")


async def safe_send(bot, chat_id, text):
    """Send a message with Markdown parsing; fall back to plain text on BadRequest (400) error."""
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except BadRequest:
        # Telegram doesn't like some Markdown chars; retry without formatting
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=None)


async def safe_send_markdown(bot, chat_id, text, **kwargs):
    """Send a message with Markdown parsing; fall back to plain text on error."""
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", **kwargs)
    except Exception:
        # Telegram doesn't like some Markdown chars; retry without formatting
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)


async def safe_reply_markdown(update, text, **kwargs):
    """Reply to a message with Markdown parsing; fall back to plain text on error."""
    try:
        await update.message.reply_text(text, parse_mode="Markdown", **kwargs)
    except Exception:
        await update.message.reply_text(text, **kwargs)


# =============================================================================
# CASUAL GROUP-CHAT REPLY (triggered by any human message)
# =============================================================================


async def reply_to_human(chat_id, human_message):
    """All 3 AI bots + BigBro reply casually to a human message SIMULTANEOUSLY via asyncio.gather()."""
    mode_instruction = get_mode_instruction(chat_id)
    history = await get_history(chat_id, limit=1000)
    history_text = format_history_for_prompt(history, "")

    async def call_and_send_ai(config):
        bot_app = bot_apps.get(config["name"])
        if not bot_app:
            return

        other_names = [b["name"] for b in AI_BOT_CONFIGS if b["name"] != config["name"]]

        prompt = (
            f"You are {config['name']}, a highly intelligent AI agent in a group chat with other AI agents "
            f"({' and '.join(other_names)}) and humans. You have a distinct personality and high IQ. "
            f"Rules: Never give presentations or bullet points. Max 3-4 sentences per response. "
            f"Structure: your opinion → your reasoning → a concrete example or counter. "
            f"In discussions, directly address what the previous speaker said — agree or disagree with specific reasoning. "
            f"Be sharp, direct, and intellectually honest. No filler words, no hedging, no 'great point'. "
            f"Speak like a genius who respects others' intelligence.\n\n"
            f"{history_text}\n\n"
            f"A message was just sent to the group:\n"
            f"\"{human_message}\"\n\n"
            f"Reply naturally in 2-3 short sentences."
            f"{mode_instruction}"
        )

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(bot_app.bot, chat_id, stop_typing))

        logger.info(f"  💬 {config['icon']} {config['name']} replying to human message...")
        response = await call_ai(config, [{"role": "user", "content": prompt}])

        stop_typing.set()
        await typing_task

        if response:
            response = response.strip()
            await bot_app.bot.send_message(
                chat_id=chat_id,
                text=f"{config['icon']} {response}",
            )
            await save_message(chat_id, config['name'], response, is_bot=True)
            logger.info(f"  ✅ {config['icon']} {config['name']} replied ✓")
        else:
            logger.info(f"  ⚠️ {config['icon']} {config['name']} API skip for casual reply")

    async def call_and_send_bigbro():
        """BigBro replies using Claude API separately."""
        bot_app = bot_apps.get("BigBro")
        if not bot_app:
            return

        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            logger.info("  ⚠️ 👁 BigBro skip — no ANTHROPIC_API_KEY")
            return

        prompt = (
            "You are BigBro, an observant and wise AI who watches over this group. "
            "You see patterns others miss. Reply in 1-2 sentences max. Be sharp and insightful.\n\n"
            f"{history_text}\n\n"
            f"A message was just sent to the group:\n"
            f"\"{human_message}\"\n\n"
            f"Reply in 1-2 sentences. Be sharp and insightful."
            f"{mode_instruction}"
        )

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(bot_app.bot, chat_id, stop_typing))

        logger.info("  💬 👁 BigBro replying to human message...")
        response = await call_anthropic(api_key, "", [{"role": "user", "content": prompt}], "claude-sonnet-4-5", 0.7)

        stop_typing.set()
        await typing_task

        if response:
            response = response.strip()
            await bot_app.bot.send_message(
                chat_id=chat_id,
                text=f"👁 {response}",
            )
            await save_message(chat_id, "BigBro", response, is_bot=True)
            logger.info("  ✅ 👁 BigBro replied ✓")
        else:
            logger.info("  ⚠️ 👁 BigBro API skip for casual reply")

    # Collect all tasks: 3 AI bots + BigBro
    tasks = [call_and_send_ai(config) for config in AI_BOT_CONFIGS]
    tasks.append(call_and_send_bigbro())
    await asyncio.gather(*tasks)


# =============================================================================
# DISCUSSION ENGINE  (background task — does NOT block the handler)
# =============================================================================

async def run_discussion(session: ChatSession):
    while session.active and not session.is_done():
        config = session.get_next_bot()
        bot_app = bot_apps.get(config["name"])
        if not bot_app:
            session.advance()
            continue

        prompt = session.build_prompt(config)

        # Background typing indicator
        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(bot_app.bot, session.chat_id, stop_typing))

        logger.info(f"\n  🎤 {config['icon']} {config['name']} (R{session.round}/{session.max_rounds}) thinking...")
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
            logger.info(f"  ✅ {config['icon']} {config['name']} ✓ ({len(response)} chars)")
        else:
            await safe_send(bot_app.bot, session.chat_id, f"{config['icon']} *{config['name']}* — ⚠️ API skip")

            logger.info(f"  ⚠️ {config['icon']} {config['name']} skipped")

        if not session.active:
            break
        session.advance()
        await asyncio.sleep(0.5)

    # ── Complete ──────────────────────────────────────────────────────────
    if session.is_done() and session.active:
        bigbro_bot = bot_apps.get("BigBro")
        if not bigbro_bot:
            session.active = False
            if session.chat_id in sessions and sessions[session.chat_id] is session:
                del sessions[session.chat_id]
            return

        wc = sum(len(e["text"].split()) for e in session.conversation)
        await safe_send(
            bigbro_bot.bot,
            session.chat_id,
            (
                f"👁 *Discussion Complete!*\n\n"
                f"📌 *Topic:* {session.topic}\n"
                f"💬 {len(session.conversation)} responses\n"
                f"📝 ~{wc} words\n\n"
                f"🤔 Now generating structured conclusion & asking AIs to vote..."
            ),
        )

        # 1) Structured summary of each AI's main points
        summary = await generate_structured_summary(session)
        if summary:
            await safe_send(bigbro_bot.bot, session.chat_id, summary)
        else:
            await bigbro_bot.bot.send_message(
                chat_id=session.chat_id,
                text="❌ Could not generate summary.",
            )

        # 2) Ask each AI to vote for the strongest argument
        await asyncio.sleep(0.5)
        await run_voting(session, bigbro_bot)

        session.active = False

    if session.chat_id in sessions and sessions[session.chat_id] is session:
        del sessions[session.chat_id]


async def generate_structured_summary(session):
    """Ask Claude to produce a summary of each AI's main points."""
    mode_instruction = get_mode_instruction(session.chat_id)
    text = "\n\n".join(f"[{e['name']}]: {e['text']}" for e in session.conversation)
    prompt = (
        f"Read this discussion and write a simple summary a normal person can understand in 30 seconds.\n\n"
        f"Discussion:\n{text}\n\n"
        f"Format exactly like this:\n\n"
        f"🟣 Claude thought: [1 simple sentence]\n"
        f"🔴 DeepSeek thought: [1 simple sentence]\n"
        f"🔵 Groq thought: [1 simple sentence]\n\n"
        f"🏆 Strongest argument: [which AI and why in 1 simple sentence]\n"
        f"📌 Bottom line: [answer the original question in 1 simple sentence]\n\n"
        f"Use simple words. No jargon. Max 5 lines total."
        f"{mode_instruction}"
    )
    # Use Claude for summary
    config = AI_BOT_CONFIGS[0]
    resp = await call_ai(config, [{"role": "user", "content": prompt}])
    if resp:
        return f"📋 *Summary of the Discussion*\n\n{resp.strip()}"
    return None


async def run_voting(session, bigbro_bot):
    """Ask each AI to vote for the strongest argument (not their own). Tally & declare winner."""
    text = "\n\n".join(f"[{e['name']}]: {e['text']}" for e in session.conversation)
    votes = []  # [{voter, winner, reason}, ...]

    for config in AI_BOT_CONFIGS:
        bot_app = bot_apps.get(config["name"])
        if not bot_app:
            continue

        vote_prompt = (
            f"The discussion was about: {session.topic}\n"
            f"Here are the arguments made:\n{text}\n"
            f"Who made the strongest argument — Claude, DeepSeek, or Groq? "
            f"Answer in one sentence: '[Name] made the strongest argument because [one simple reason].'"
        )

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(bot_app.bot, session.chat_id, stop_typing))

        logger.info(f"  🗳️ {config['icon']} {config['name']} voting...")
        response = await call_ai(config, [{"role": "user", "content": vote_prompt}])

        stop_typing.set()
        await typing_task

        if response:
            votes.append({"voter": config["name"], "response": response.strip()})
            logger.info(f"  ✅ {config['icon']} {config['name']} voted ✓")
        else:
            logger.info(f"  ⚠️ {config['icon']} {config['name']} vote skipped")

    # ── Tally votes ──────────────────────────────────────────────────
    if not votes:
        await safe_send(bigbro_bot.bot, session.chat_id, "❌ No votes could be collected.")
        return

    tally = {}
    vote_lines = []
    winner_reason = ""  # store the reason from the winning vote
    for v in votes:
        voter = v["voter"]
        resp = v["response"]
        # Parse winner from response: "[Name] made the strongest argument because [one simple reason]"
        winner = "Unknown"
        reason = ""
        for ai in AI_BOT_CONFIGS:
            if resp.lower().startswith(ai["name"].lower()):
                winner = ai["name"]
                # Extract reason after "because"
                if "because" in resp.lower():
                    reason = resp.split("because", 1)[1].strip().rstrip(".")
                break
        if winner == "Unknown":
            # Fallback: search for any AI name in the response
            for ai in AI_BOT_CONFIGS:
                if ai["name"].lower() in resp.lower():
                    winner = ai["name"]
                    if "because" in resp.lower():
                        reason = resp.split("because", 1)[1].strip().rstrip(".")
                    break
        tally[winner] = tally.get(winner, 0) + 1
        voter_icon = AI_BOT_CONFIGS[[c['name'] for c in AI_BOT_CONFIGS].index(voter)]['icon']
        vote_lines.append(f"{voter_icon} {voter} voted for: {winner}")
        if winner == max(tally, key=tally.get) if tally else "" and not winner_reason:
            winner_reason = reason

    total_votes = len(votes)

    # Declare winner
    if tally:
        winner_name = max(tally, key=tally.get)
        winner_icon = ""
        for ai in AI_BOT_CONFIGS:
            if ai["name"] == winner_name:
                winner_icon = ai["icon"]
                break
        declaration = f"🏆 Winner: {winner_icon} {winner_name} with {tally[winner_name]} votes"
        # Find reason from the winning vote
        for v in votes:
            resp = v["response"]
            for ai in AI_BOT_CONFIGS:
                if ai["name"] == winner_name and resp.lower().startswith(ai["name"].lower()):
                    if "because" in resp.lower():
                        winner_reason = resp.split("because", 1)[1].strip().rstrip(".")
                    break
    else:
        declaration = "🤝 Tie — no clear winner"

    why_line = f"💡 Why: {winner_reason}" if winner_reason else "💡 Why: [1 sentence from the winning argument]"

    result_message = (
        f"🗳 VOTES:\n"
        + "\n".join(vote_lines)
        + "\n\n" + declaration
        + "\n" + why_line
    )

    await safe_send(bigbro_bot.bot, session.chat_id, result_message)


# =============================================================================
# BIGBRO SUMMARY (uses Claude API with full history from Supabase)
# =============================================================================

async def generate_bigbro_summary(chat_id):
    """Fetch full history from Supabase and generate a summary using Claude."""
    mode_instruction = get_mode_instruction(chat_id)
    history = await get_history(chat_id, limit=1000)
    if not history:
        return None
    history_text = format_history_for_prompt(history, "")
    prompt = (
        f"Here is the conversation history from an AI group chat:\n\n{history_text}\n\n"
        f"Write a concise summary covering:\n"
        f"1. The main topics discussed\n"
        f"2. Key points made by each participant (Claude 🟣, DeepSeek 🔴, Groq 🔵)\n"
        f"3. Any conclusions reached\n\n"
        f"Be thorough but concise. 3-5 paragraphs."
        f"{mode_instruction}"
    )
    config = AI_BOT_CONFIGS[0]  # Use Claude
    resp = await call_ai(config, [{"role": "user", "content": prompt}])
    if resp:
        return f"📋 *Full History Summary*\n\n{resp.strip()}"
    return None


# =============================================================================
# BUILD INDIVIDUAL BOT
# =============================================================================

def build_bot(config):
    # ── BigBro — Judge / Controller ───────────────────────────────────────
    if config["name"] == "BigBro":
        app = Application.builder().token(config["telegram_token"]).build()
        bot_apps[config["name"]] = app

        async def cmd_start(update, context):
            await update.message.reply_text(
                f"👁 *BigBro* — Discussion Judge ready!\n\n"
                f"`/discuss <topic>` — start AI debate\n"
                f"`/discuss rounds=N <topic>` — custom rounds (1-10)\n"
                f"`/stop` — halt discussion\n"
                f"`/summary` — generate summary with full history from database\n"
                f"`/vote` — ask AIs to vote on the best argument\n\n"
                f"I oversee the debates. The 3 AIs discuss, I judge. 🤖⚖️\n\n"
                f"Add all 4 bots (@Claude, @DeepSeek, @Groq, @BigBro) to the group!",
                parse_mode="Markdown",
            )

        async def cmd_discuss(update, context):
            chat_id = update.effective_chat.id

            # Don't allow two concurrent discussions in the same chat
            existing = sessions.get(chat_id)
            if existing and existing.active:
                await update.message.reply_text("❌ A discussion is already running! Use `/stop` first.", parse_mode="Markdown")
                return

            args = context.args
            if not args:
                await update.message.reply_text("Example: `/discuss Is homeschooling better than school?`", parse_mode="Markdown")
                return

            # Parse optional  rounds=N  prefix
            max_rounds = DEFAULT_ROUNDS
            topic_parts = list(args)
            if topic_parts and topic_parts[0].lower().startswith("rounds="):
                try:
                    max_rounds = int(topic_parts[0].split("=")[1])
                    max_rounds = max(1, min(max_rounds, 10))
                    topic_parts = topic_parts[1:]
                except ValueError:
                    pass

            if not topic_parts:
                await update.message.reply_text("❌ Please provide a topic!")
                return

            topic = " ".join(topic_parts)
            names = " → ".join(f"{b['icon']}{b['name']}" for b in AI_BOT_CONFIGS)

            session = ChatSession(chat_id, topic, max_rounds)
            sessions[chat_id] = session

            # Show current mode if not normal
            current_mode = chat_modes.get(chat_id, "normal")
            mode_line = ""
            if current_mode != "normal":
                mode_line = f"🎭 *Mode:* {current_mode}\n"

            await update.message.reply_text(
                f"👁 *Discussion Started by BigBro!*\n\n"
                f"📌 *Topic:* {topic}\n"
                f"👥 *Order:* {names}\n"
                f"🔄 *{max_rounds} rounds each*\n"
                f"{mode_line}"
                f"\nStarting with {AI_BOT_CONFIGS[0]['icon']} {AI_BOT_CONFIGS[0]['name']}... ⏳\n\n"
                f"Use `/stop` to cancel.",
                parse_mode="Markdown",
            )

            # Background task so the handler returns immediately
            session.task = asyncio.create_task(run_discussion(session))

        async def cmd_stop(update, context):
            sess = sessions.get(update.effective_chat.id)
            if sess and sess.active:
                sess.active = False
                await update.message.reply_text("🛑 👁 Discussion stopped by BigBro.")
            else:
                await update.message.reply_text("No active discussion.")

        async def cmd_summary(update, context):
            chat_id = update.effective_chat.id
            await update.message.reply_text("🤔 Generating summary with full history from database...")
            summary = await generate_bigbro_summary(chat_id)
            if summary:
                await safe_send(app.bot, chat_id, summary)
            else:
                await update.message.reply_text("❌ Could not generate summary (no history or API unavailable).")

        async def cmd_vote(update, context):
            chat_id = update.effective_chat.id
            sess = sessions.get(chat_id)
            if not sess or not sess.conversation:
                await update.message.reply_text("No discussion to vote on. Use `/discuss <topic>` first.", parse_mode="Markdown")
                return

            bigbro_bot = bot_apps.get("BigBro")
            if not bigbro_bot:
                await update.message.reply_text("❌ BigBro bot not available.")
                return

            await update.message.reply_text("🗳️ Asking each AI to vote on the best argument...")
            await run_voting(sess, bot_apps["BigBro"])

        # BigBro also handles casual messages
        async def handle_message(update, context):
            chat_id = update.effective_chat.id
            human_text = update.message.text
            sender_name = update.message.from_user.first_name or "Human"
            await save_message(chat_id, sender_name, human_text, is_bot=False)
            asyncio.create_task(reply_to_human(chat_id, human_text))

        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("discuss", cmd_discuss))
        app.add_handler(CommandHandler("stop", cmd_stop))
        app.add_handler(CommandHandler("summary", cmd_summary))
        app.add_handler(CommandHandler("vote", cmd_vote))
        app.add_handler(CommandHandler("help", cmd_start))
        app.add_handler(CommandHandler("commands", cmd_start))
        app.add_handler(CommandHandler("cancel", cmd_stop))

        # Register message handler for casual replies (non-command text messages only)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        return app

    # ── Non-BigBro bots (Claude, DeepSeek, Groq) — only /mode + casual handler ──
    app = Application.builder().token(config["telegram_token"]).build()
    bot_apps[config["name"]] = app

    async def cmd_mode(update, context):
        """Change the AI response mode for this chat."""
        # Only the first AI bot in order handles /mode
        if config["order"] != 0:
            return

        chat_id = update.effective_chat.id
        args = context.args

        if not args:
            # Show current mode
            current = chat_modes.get(chat_id, "normal")
            modes_list = " | ".join(
                f"`{m}`" if m != current else f"*`{m}`*" for m in MODE_NAMES
            )
            await update.message.reply_text(
                f"🎭 Current mode: *{current}*\n\n"
                f"Available modes:\n{modes_list}\n\n"
                f"Usage: `/mode <mode_name>`",
                parse_mode="Markdown",
            )
            return

        mode = args[0].lower()

        if mode not in MODE_NAMES:
            await update.message.reply_text(
                f"❌ Unknown mode: `{mode}`\n\n"
                f"Available modes: {', '.join(f'`{m}`' for m in MODE_NAMES)}",
                parse_mode="Markdown",
            )
            return

        chat_modes[chat_id] = mode

        mode_descriptions = {
            "normal": "✅ Reset to normal mode. AIs will respond with their default personalities.",
            "sarcastic": "😏 *Sarcastic mode* activated! All AIs will respond with sharp, witty sarcasm.",
            "eli5": "🧒 *ELI5 mode* activated! All AIs will explain things simply, like to a child.",
            "disagree": "⚔️ *Disagree mode* activated! All AIs will challenge and contradict each other.",
        }

        await update.message.reply_text(
            f"🎭 Mode changed to *{mode}\n\n{mode_descriptions.get(mode, '')}",
            parse_mode="Markdown",
        )
        logger.info(f"  🎭 Chat {chat_id} mode set to '{mode}'")

    async def handle_message(update, context):
        # Only the first AI bot triggers the casual reply cascade
        if config["order"] != 0:
            return

        chat_id = update.effective_chat.id
        human_text = update.message.text

        sender_name = update.message.from_user.first_name or "Human"
        await save_message(chat_id, sender_name, human_text, is_bot=False)

        # Launch background task so the handler returns immediately
        asyncio.create_task(reply_to_human(chat_id, human_text))

    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("start", cmd_mode))

    # Register message handler for casual replies (non-command text messages only)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app


# =============================================================================
# MAIN
# =============================================================================

async def main():
    print("\n" + "=" * 60)
    print("  🧠  MULTI-AI GROUP CHAT — v3 with BigBro Judge")
    print("=" * 60)
    print("  • Secrets: .env (gitignored)")
    print("  • AI calls: httpx (async, non-blocking)")
    print("  • BigBro controls /discuss /stop /summary /vote")
    print("  • Casual chat: any human message → all 3 AIs + BigBro reply")
    print("  • Features: /mode (on Claude/DeepSeek/Groq)")
    print()

    for c in BOT_CONFIGS:
        tg_ok = "✅" if c["telegram_token"] else "❌"
        api_ok = "✅" if c["api_key"] else "❌"
        if c["name"] == "BigBro":
            print(f"  👁 BigBro   TG: {tg_ok}")
        else:
            print(f"  {c['icon']} {c['name']:8s}  TG: {tg_ok}  API: {api_ok}  T={c['temperature']}")

    if not all(c["telegram_token"] for c in BOT_CONFIGS):
        print("\n⚠️  Missing tokens/keys! Check your .env file.")
        return

    print("\n🚀 Starting bots...\n")
    apps = []
    for config in BOT_CONFIGS:
        app = build_bot(config)
        await app.initialize()

        # Set commands per bot type
        if config["name"] == "BigBro":
            await app.bot.set_my_commands([
                BotCommand("start",   "Welcome"),
                BotCommand("discuss", "/discuss [rounds=N] <topic> — start debate"),
                BotCommand("stop",    "Stop discussion"),
                BotCommand("summary", "Generate summary with full history"),
                BotCommand("vote",    "Ask AIs to vote on best argument"),
            ])
        else:
            await app.bot.set_my_commands([
                BotCommand("mode",   "/mode <sarcastic|eli5|disagree|normal>"),
            ])

        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        if config["name"] == "BigBro":
            print(f"  ✅ 👁 @BigBro — LIVE (Judge)")
        else:
            print(f"  ✅ {config['icon']} @{config['name']} — LIVE")
        apps.append((config, app))

    print()
    print("=" * 60)
    print("  ✅ ALL BOTS RUNNING!")
    print()
    print("  👁  @BigBro commands:")
    print("       /discuss <topic>           — start debate (3 rounds)")
    print("       /discuss rounds=5 ...      — custom rounds (1-10)")
    print("       /stop                      — cancel discussion")
    print("       /summary                   — AI summary from full history")
    print("       /vote                      — AIs vote on best argument")
    print()
    print("  🤖  @Claude / @DeepSeek / @Groq:")
    print("       /mode <mode>               — change AI style")
    print("       💬 Any message             — all AIs + BigBro reply casually")
    print("=" * 60)

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        print("\n👋 Stopping...")
        for s in list(sessions.values()):
            s.active = False
        for _, app in reversed(apps):
            await app.updater.stop()
            await app.stop()
            await app.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bots stopped.")
