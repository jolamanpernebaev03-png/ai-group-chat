#!/bin/bash
# ============================================================
# Uzum Sourcing Bot — Startup Script
# ============================================================
# Usage: ./start_bot.sh
# Or run in background: nohup ./start_bot.sh &

export CLAUDE_TG_TOKEN="8571365851:AAGfAkL_s7koS0kds09me6DJBFBSSxa-oqk"
export DEEPSEEK_API_KEY="sk-f13b0ba2dd9b4e14a38b27cdceef86f3"
export TELEGRAM_CHAT_ID="687396965"

cd "$(dirname "$0")"
echo "🚀 Starting Uzum Sourcing Bot..."
python3 uzum_bot.py
