import os
print("=== RAILWAY ENV VARIABLES ===")
for key in ["CLAUDE_TG_TOKEN", "DEEPSEEK_TG_TOKEN", "GROQ_TG_TOKEN", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "GROUP_CHAT_ID"]:
    value = os.getenv(key)
    print(f"{key}: {'✓ SET' if value else '✗ MISSING'}")

"""
🤖 Multi-AI Telegram Group Chat — v2
======================================
Three REAL AI bots (Claude, DeepSeek, Groq) with their own Telegram accounts
debate topics together. Each AI speaks through its OWN bot.

FIXES:
  1. All keys from .env via python-dotenv (no hardcoded secrets)
  2. Async httpx calls (non-blocking)
  3. asyncio.create_task() so /discuss doesn't block handler
  4. Any human message triggers casual 3-AI replies (independent of /discuss)
"""

import asyncio
import logging
import os
import random
import sys

import httpx
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, filters

print("🚀 BOT STARTING ON RAILWAY")

load_dotenv()
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# ── DEFAULTS ────────────────────────────────────────────────────────────
DEFAULT_ROUNDS = 3
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
        "model": "claude-sonnet-4-20250514",  "temperature": 0.7,
        "prompt": (
            "You are extremely intelligent. Speak like a confident smart person in casual conversation — "
            "no bullet points, no numbered lists, no academic citations, no formal structure. "
            "Flow naturally like a sharp opinionated friend who gets straight to the point. Keep responses concise and punchy."
        ),
        "order": 0,
    },
    {
        "name": "DeepSeek",        "icon": "🔴",
        "telegram_token": os.getenv("DEEPSEEK_TG_TOKEN"),
        "api_type": "deepseek",    "api_key": os.getenv("DEEPSEEK_API_KEY"),
        "model": "deepseek-reasoner",  "temperature": 0.3,
        "prompt": (
            "You are extremely intelligent. Speak like a confident smart person in casual conversation — "
            "no bullet points, no numbered lists, no academic citations, no formal structure. "
            "Flow naturally like a sharp opinionated friend who gets straight to the point. Keep responses concise and punchy."
        ),
        "order": 1,
    },
    {
        "name": "Groq",            "icon": "🔵",
        "telegram_token": os.getenv("GROQ_TG_TOKEN"),
        "api_type": "groq",        "api_key": os.getenv("GROQ_API_KEY"),
        "model": "llama-3.3-70b-versatile",  "temperature": 1.0,
        "prompt": (
            "You are extremely intelligent. Speak like a confident smart person in casual conversation — "
            "no bullet points, no numbered lists, no academic citations, no formal structure. "
            "Flow naturally like a sharp opinionated friend who gets straight to the point. Keep responses concise and punchy."
        ),
        "order": 2,
    },
]
BOT_CONFIGS.sort(key=lambda b: b["order"])


# =============================================================================
# ASYNC AI CALLERS  (httpx, non-blocking)
# =============================================================================

async def call_anthropic(api_key, system, messages, model, temperature):
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            logger.info(f"DEBUG key repr: {repr(api_key)}")
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
        return BOT_CONFIGS[self.current_idx]

    def is_done(self):
        return self.round > self.max_rounds

    def advance(self):
        self.current_idx += 1
        if self.current_idx >= len(BOT_CONFIGS):
            self.current_idx = 0
            self.round += 1

    def get_next_config(self):
        """Return the config of the bot that will speak after the current one."""
        next_idx = self.current_idx + 1
        if next_idx >= len(BOT_CONFIGS):
            # Next round, first bot speaks
            return BOT_CONFIGS[0]
        return BOT_CONFIGS[next_idx]

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

        is_final_round = self.round == self.max_rounds and self.current_idx == len(BOT_CONFIGS) - 1
        if is_final_round:
            round_instruction = (
                "This is your final round — conclude and synthesize the conversation.\n"
                "Summarise your key points, respond to counter-arguments, and "
                "offer a final, thoughtful perspective on the topic."
            )
        else:
            round_instruction = "Use your full intelligence. Respond to the other AIs. Write 3-6 paragraphs."

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
    """All 3 AIs reply casually to a human message SIMULTANEOUSLY via asyncio.gather()."""
    mode_instruction = get_mode_instruction(chat_id)

    async def call_and_send(config):
        bot_app = bot_apps.get(config["name"])
        if not bot_app:
            return

        other_names = [b["name"] for b in BOT_CONFIGS if b["name"] != config["name"]]

        # Short, casual group-chat prompt — 2-3 sentences max
        prompt = (
            f"You are {config['name']}, a student in a group chat with your classmates "
            f"({' and '.join(other_names)}).\n\n"
            f"A classmate just sent this message to the group chat:\n"
            f"\"{human_message}\"\n\n"
            f"Reply naturally in 2-3 short sentences, as if you're chatting casually with friends. "
            f"Be conversational and authentic. No markdown, no emojis, no formatting — just plain text."
            f"{mode_instruction}"
        )

        # Typing indicator
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
            logger.info(f"  ✅ {config['icon']} {config['name']} replied ✓")
        else:
            logger.info(f"  ⚠️ {config['icon']} {config['name']} API skip for casual reply")

    # Run all 3 AI calls concurrently so responses arrive at roughly the same time
    await asyncio.gather(*(call_and_send(config) for config in BOT_CONFIGS))


# =============================================================================
# /roast  — All 3 AIs brutally critique an idea
# =============================================================================

async def run_roast(chat_id, idea):
    """All 3 AIs roast an idea, each from their own perspective, one by one."""
    mode_instruction = get_mode_instruction(chat_id)

    for config in BOT_CONFIGS:
        bot_app = bot_apps.get(config["name"])
        if not bot_app:
            continue

        # Tailored brutal-intellectual roast prompt per AI
        if config["name"] == "Claude":
            roast_prompt = (
                f"You are Claude (claude-sonnet-4-20250514), a deeply analytical philosopher. "
                f"Your task: BRUTALLY but INTELLIGENTLY critique the following idea.\n\n"
                f"Idea: \"{idea}\"\n\n"
                f"Tear into its logical flaws, hidden assumptions, ethical blind spots, and intellectual weaknesses. "
                f"Be savage, but make every blow land with cold, precise reasoning. Draw from philosophy, ethics, "
                f"history, and systems thinking. Do NOT hold back. 3-6 sharp paragraphs."
                f"{mode_instruction}"
            )
        elif config["name"] == "DeepSeek":
            roast_prompt = (
                f"You are DeepSeek, a reasoning-focused AI. Your task: BRUTALLY but INTELLIGENTLY critique the following idea.\n\n"
                f"Idea: \"{idea}\"\n\n"
                f"Dismantle it with step-by-step reasoning. Expose its logical fallacies, data contradictions, "
                f"evidential weaknesses, and structural flaws. Use data-driven arguments, cite counter-evidence, "
                f"and break down why the idea doesn't hold up under scrutiny. Be ruthless and precise. 3-6 sharp paragraphs."
                f"{mode_instruction}"
            )
        else:  # Groq / Llama
            roast_prompt = (
                f"You are Llama 3.3, running on Groq. Fast, articulate, and sharp. "
                f"Your task: BRUTALLY but INTELLIGENTLY critique the following idea.\n\n"
                f"Idea: \"{idea}\"\n\n"
                f"Call it out with wit, sarcasm, and practical wisdom. Point out why it's naive, impractical, "
                f"or just plain wrong. Be funny, be savage, be real. Use analogies, real-world examples, "
                f"and street-smart reasoning. Make the critique sting AND make people think. 3-6 sharp paragraphs."
                f"{mode_instruction}"
            )

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(bot_app.bot, chat_id, stop_typing))

        logger.info(f"  🔥 {config['icon']} {config['name']} roasting...")
        response = await call_ai(config, [{"role": "user", "content": roast_prompt}])

        stop_typing.set()
        await typing_task

        if response:
            response = response.strip()
            header = f"🔥 {config['icon']} *{config['name']} roasts your idea:*"
            chunks = split_response(response)
            await safe_send(bot_app.bot, chat_id, f"{header}\n\n{chunks[0]}")
            for chunk in chunks[1:]:
                await asyncio.sleep(0.5)
                await bot_app.bot.send_message(chat_id=chat_id, text=chunk)
            logger.info(f"  ✅ {config['icon']} {config['name']} roast ✓")
        else:
            await safe_send(bot_app.bot, chat_id, f"{config['icon']} *{config['name']}* — ⚠️ API skip")


        # Short delay between roasts
        await asyncio.sleep(0.5)


# =============================================================================
# /decide  — All 3 AIs analyze a dilemma from their own angle
# =============================================================================

async def run_decide(chat_id, dilemma):
    """All 3 AIs analyze a dilemma: Claude logically, DeepSeek with data, Groq practically & emotionally."""
    mode_instruction = get_mode_instruction(chat_id)

    for config in BOT_CONFIGS:
        bot_app = bot_apps.get(config["name"])
        if not bot_app:
            continue

        # Tailored analysis perspective per AI
        if config["name"] == "Claude":
            decide_prompt = (
                f"You are Claude (claude-sonnet-4-20250514), a thoughtful, nuanced analyst.\n\n"
                f"Dilemma: \"{dilemma}\"\n\n"
                f"Analyze this dilemma logically. Break down the core tension, identify the trade-offs, "
                f"weigh pros and cons of each option, and consider second-order consequences. "
                f"Use ethical frameworks (utilitarian, deontological, virtue ethics) where applicable. "
                f"Conclude with your recommended course of action based on logic. 3-6 paragraphs."
                f"{mode_instruction}"
            )
        elif config["name"] == "DeepSeek":
            decide_prompt = (
                f"You are DeepSeek, a reasoning-focused AI.\n\n"
                f"Dilemma: \"{dilemma}\"\n\n"
                f"Analyze this dilemma using data and reasoning. Structure your response: "
                f"1) Define the problem precisely, "
                f"2) List relevant data points and evidence, "
                f"3) Apply step-by-step reasoning to evaluate each option, "
                f"4) Quantify trade-offs where possible, "
                f"5) Conclude with a data-driven recommendation. "
                f"Be methodical, precise, and evidence-based. 3-6 paragraphs."
                f"{mode_instruction}"
            )
        else:  # Groq / Llama
            decide_prompt = (
                f"You are Llama 3.3, running on Groq. Fast, practical, and emotionally intelligent.\n\n"
                f"Dilemma: \"{dilemma}\"\n\n"
                f"Analyze this dilemma from a practical and emotional perspective. "
                f"Consider: What would work in the real world? How would people actually feel? "
                f"What's the human cost of each option? What's the most practical path forward? "
                f"Trust your gut, be honest, and give real-talk advice. "
                f"Balance pragmatism with empathy. 3-6 paragraphs."
                f"{mode_instruction}"
            )

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(bot_app.bot, chat_id, stop_typing))

        logger.info(f"  ⚖️ {config['icon']} {config['name']} deciding...")
        response = await call_ai(config, [{"role": "user", "content": decide_prompt}])

        stop_typing.set()
        await typing_task

        if response:
            response = response.strip()
            header = f"⚖️ {config['icon']} *{config['name']}'s analysis:*"
            chunks = split_response(response)
            await safe_send(bot_app.bot, chat_id, f"{header}\n\n{chunks[0]}")
            for chunk in chunks[1:]:
                await asyncio.sleep(0.5)
                await bot_app.bot.send_message(chat_id=chat_id, text=chunk)
            logger.info(f"  ✅ {config['icon']} {config['name']} decide ✓")
        else:
            await safe_send(bot_app.bot, chat_id, f"{config['icon']} *{config['name']}* — ⚠️ API skip")


        # Short delay between analyses
        await asyncio.sleep(0.5)


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
        wc = sum(len(e["text"].split()) for e in session.conversation)
        final_bot = bot_apps[BOT_CONFIGS[0]["name"]]
        await safe_send(
            final_bot.bot,
            session.chat_id,
            (
                f"🏆 *Discussion Complete!*\n\n"
                f"📌 {session.topic}\n💬 {len(session.conversation)} responses\n📝 ~{wc} words\n\n"
                f"🤔 Generating AI summary..."
            ),
        )

        # Auto-generate summary
        summary = await generate_summary(session)
        if summary:
            await safe_send(
                final_bot.bot,
                session.chat_id,
                summary,
            )
        else:
            await final_bot.bot.send_message(
                chat_id=session.chat_id,
                text="❌ Could not generate summary (APIs unavailable).",
            )

        session.active = False

    if session.chat_id in sessions and sessions[session.chat_id] is session:
        del sessions[session.chat_id]


async def generate_summary(session):
    """Ask Claude to produce a structured summary of the discussion.
    No fallback — if Claude's API fails, summary is skipped entirely."""
    mode_instruction = get_mode_instruction(session.chat_id)
    text = "\n\n".join(f"[{e['name']}]: {e['text']}" for e in session.conversation)
    prompt = (
        f"Read this AI discussion on '{session.topic}':\n\n{text}\n\n"
        f"Write a structured summary in this exact format:\n\n"
        f"🟣 Claude said: [1 sentence on their main point and reasoning]\n"
        f"🔴 DeepSeek said: [1 sentence on their main point and reasoning]\n"
        f"🔵 Groq said: [1 sentence on their main point and reasoning]\n\n"
        f"🏆 Winning argument: [which AI made the strongest case and why in 1 sentence]\n\n"
        f"📌 Final conclusion: [1 sentence bottom line on the topic]\n\n"
        f"Every section must be exactly 1 sentence. No bullet points inside sections. "
        f"Just the format above, nothing else."
        f"{mode_instruction}"
    )
    config = BOT_CONFIGS[0]  # Only use the first bot (Claude) — no fallback to others
    resp = await call_ai(config, [{"role": "user", "content": prompt}])
    if resp:
        return f"📋 *Summary: {session.topic}*\n\n{resp.strip()}"
    return None


# =============================================================================
# BUILD INDIVIDUAL BOT
# =============================================================================

def build_bot(config):
    app = Application.builder().token(config["telegram_token"]).build()
    bot_apps[config["name"]] = app

    async def cmd_start(update, context):
        await update.message.reply_text(
            f"{config['icon']} *{config['name']}* ready!\n\n"
            f"`/discuss <topic>` — debate\n"
            f"`/discuss rounds=N <topic>` — custom rounds (1-10)\n"
            f"`/roast <idea>` — all 3 AIs brutally critique your idea\n"
            f"`/decide <dilemma>` — all 3 AIs analyze a dilemma\n"
            f"`/stop` — halt discussion\n"
            f"`/summary` — synthesise conclusions\n"
            f"`/mode <sarcastic|eli5|disagree|normal>` — change AI response style\n\n"
            f"Add all 3 bots to your group!",
            parse_mode="Markdown",
        )

    async def cmd_stop(update, context):
        # Only the first bot in order handles /stop
        if config["order"] != 0:
            return
        sess = sessions.get(update.effective_chat.id)
        if sess and sess.active:
            sess.active = False
            await update.message.reply_text(f"🛑 {config['icon']} Discussion stopped.")
        else:
            await update.message.reply_text("No active discussion.")

    async def cmd_summary(update, context):
        # Only the first bot in order handles /summary
        if config["order"] != 0:
            return
        sess = sessions.get(update.effective_chat.id)
        if not sess or not sess.conversation:
            await update.message.reply_text("No discussion to summarise. Use `/discuss <topic>`", parse_mode="Markdown")
            return
        await update.message.reply_text("🤔 Generating summary...")
        summary = await generate_summary(sess)
        if summary:
            await safe_send(
                bot_apps[config["name"]].bot,
                update.effective_chat.id,
                summary,
            )
        else:
            await update.message.reply_text("❌ Could not generate summary (APIs unavailable).")

    async def cmd_discuss(update, context):
        # Only the first bot in order starts a discussion
        if config["order"] != 0:
            return
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
        names = " → ".join(f"{b['icon']}{b['name']}" for b in BOT_CONFIGS)

        session = ChatSession(chat_id, topic, max_rounds)
        sessions[chat_id] = session

        # Show current mode if not normal
        current_mode = chat_modes.get(chat_id, "normal")
        mode_line = ""
        if current_mode != "normal":
            mode_line = f"🎭 *Mode:* {current_mode}\n"

        await update.message.reply_text(
            f"🎯 *Discussion Started!*\n\n"
            f"📌 *Topic:* {topic}\n"
            f"👥 *Order:* {names}\n"
            f"🔄 *{max_rounds} rounds each*\n"
            f"{mode_line}"
            f"\nStarting with {BOT_CONFIGS[0]['icon']} {BOT_CONFIGS[0]['name']}... ⏳\n\n"
            f"Use `/stop` to cancel.",
            parse_mode="Markdown",
        )

        # ⭐ FIX #3: Background task so the handler returns immediately
        session.task = asyncio.create_task(run_discussion(session))

    async def cmd_roast(update, context):
        # Only the first bot in order handles /roast
        if config["order"] != 0:
            return
        args = context.args
        if not args:
            await update.message.reply_text("Example: `/roast The moon landing was faked`", parse_mode="Markdown")
            return
        idea = " ".join(args)
        await update.message.reply_text(
            f"🔥 *Roast incoming!* All 3 AIs will now brutally critique:\n\n"
            f"\"{idea}\"\n\n⏳ Starting with {BOT_CONFIGS[0]['icon']} {BOT_CONFIGS[0]['name']}...",
            parse_mode="Markdown",
        )
        asyncio.create_task(run_roast(update.effective_chat.id, idea))

    async def cmd_decide(update, context):
        # Only the first bot in order handles /decide
        if config["order"] != 0:
            return
        args = context.args
        if not args:
            await update.message.reply_text("Example: `/decide Should I quit my job to travel?`", parse_mode="Markdown")
            return
        dilemma = " ".join(args)
        await update.message.reply_text(
            f"⚖️ *Deciding...* All 3 AIs will now analyze this dilemma:\n\n"
            f"\"{dilemma}\"\n\n⏳ Starting with {BOT_CONFIGS[0]['icon']} {BOT_CONFIGS[0]['name']}...",
            parse_mode="Markdown",
        )
        asyncio.create_task(run_decide(update.effective_chat.id, dilemma))

    async def cmd_mode(update, context):
        """Change the AI response mode for this chat."""
        # Only the first bot in order handles /mode
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
        # Only the first bot triggers the casual reply cascade
        if config["order"] != 0:
            return

        chat_id = update.effective_chat.id
        human_text = update.message.text

        # Launch background task so the handler returns immediately
        asyncio.create_task(reply_to_human(chat_id, human_text))

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("discuss", cmd_discuss))
    app.add_handler(CommandHandler("roast", cmd_roast))
    app.add_handler(CommandHandler("decide", cmd_decide))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("commands", cmd_start))
    app.add_handler(CommandHandler("cancel", cmd_stop))

    # Register message handler for casual replies (non-command text messages only)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app


# =============================================================================
# MAIN
# =============================================================================

async def main():
    print("\n" + "=" * 60)
    print("  🧠  MULTI-AI GROUP CHAT — v2")
    print("=" * 60)
    print("  • Secrets: .env (gitignored)")
    print("  • AI calls: httpx (async, non-blocking)")
    print("  • Discussion: asyncio.create_task (non-blocking handler)")
    print("  • Casual chat: any human message → all 3 AIs reply (non-blocking)")
    print("  • Features: /stop  /summary  /discuss [rounds=N]  /roast  /decide  /mode")
    print()

    for c in BOT_CONFIGS:
        tg_ok = "✅" if c["telegram_token"] else "❌"
        api_ok = "✅" if c["api_key"] else "❌"
        print(f"  {c['icon']} {c['name']:8s}  TG: {tg_ok}  API: {api_ok}  T={c['temperature']}")

    if not all(c["telegram_token"] for c in BOT_CONFIGS) or not all(c["api_key"] for c in BOT_CONFIGS):
        print("\n⚠️  Missing tokens/keys! Check your .env file.")
        return

    print("\n🚀 Starting bots...\n")
    apps = []
    for config in BOT_CONFIGS:
        app = build_bot(config)
        await app.initialize()
        await app.bot.set_my_commands([
            BotCommand("start",  "Welcome"),
            BotCommand("discuss","/discuss [rounds=N] <topic>"),
            BotCommand("roast",  "/roast <idea> — brutal AI critique"),
            BotCommand("decide", "/decide <dilemma> — AI analysis"),
            BotCommand("stop",   "Stop discussion"),
            BotCommand("summary","Summarise discussion"),
            BotCommand("mode",   "/mode <sarcastic|eli5|disagree|normal> — change AI style"),
        ])
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        print(f"  ✅ {config['icon']} @{config['name']} — LIVE")
        apps.append((config, app))

    print()
    print("=" * 60)
    print("  ✅ ALL BOTS RUNNING!")
    print()
    print("  🔥  /discuss <topic>             — 3 rounds each")
    print("       /discuss rounds=5 ...        — custom rounds (1-10)")
    print("       /roast <idea>                — brutal 3-AI critique")
    print("       /decide <dilemma>            — 3-AI analysis")
    print("       /stop                        — cancel")
    print("       /summary                     — AI synthesis")
    print("       /mode <mode>                 — change AI style")
    print("       💬 Any message               — all 3 AIs reply casually")
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
