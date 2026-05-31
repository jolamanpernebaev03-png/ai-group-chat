#!/bin/bash
# Multi-AI Discussion Bot — Start script
# Make sure to set your API keys in environment variables first!

cd "$(dirname "$0")"

# ── Load .env if it exists ──
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# ── Check required ──
if [ -z "$CLAUDE_TG_TOKEN" ]; then
    echo "❌ CLAUDE_TG_TOKEN is not set!"
    echo "   Create a .env file or export it."
    echo "   See .env.example for reference."
    exit 1
fi

ACTIVE_AIS=0
[ -n "$ANTHROPIC_API_KEY" ] && ACTIVE_AIS=$((ACTIVE_AIS + 1))
[ -n "$OPENAI_API_KEY" ]     && ACTIVE_AIS=$((ACTIVE_AIS + 1))
[ -n "$GEMINI_API_KEY" ]     && ACTIVE_AIS=$((ACTIVE_AIS + 1))
[ -n "$DEEPSEEK_API_KEY" ]   && ACTIVE_AIS=$((ACTIVE_AIS + 1))
[ -n "$GROK_API_KEY" ]       && ACTIVE_AIS=$((ACTIVE_AIS + 1))

echo "🤖 Multi-AI Discussion Bot"
echo "========================="
if [ "$ACTIVE_AIS" -ge 2 ]; then
    echo "✅ $ACTIVE_AIS AI models configured"
    echo "🚀 Starting bot..."
    python3 ai_discussion_bot.py
else
    echo "⚠️  Only $ACTIVE_AIS AI(s) configured. Need at least 2."
    echo ""
    echo "Set API keys in .env file:"
    echo "  CLAUDE_TG_TOKEN=..."
    echo "  ANTHROPIC_API_KEY=...   # Claude"
    echo "  OPENAI_API_KEY=...       # GPT-4o"
    echo "  GEMINI_API_KEY=...       # Gemini"
    echo "  DEEPSEEK_API_KEY=...     # DeepSeek"
    echo "  GROK_API_KEY=...         # Grok"
    echo ""
    echo "Or run directly with env vars:"
    echo "  CLAUDE_TG_TOKEN=xxx ANTHROPIC_API_KEY=xxx OPENAI_API_KEY=xxx python3 ai_discussion_bot.py"
    exit 1
fi
