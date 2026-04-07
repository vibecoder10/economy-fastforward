#!/bin/bash
# Shared Telegram notification helper
# Source this file to get notify_telegram() function
# Reads bot token and chat ID from Claude Channels config

_TG_TOKEN=$(cat ~/.claude/channels/telegram/.env 2>/dev/null | grep TELEGRAM_BOT_TOKEN | cut -d= -f2)
_TG_CHAT_ID=$(ls ~/.claude/channels/telegram/approved/ 2>/dev/null | head -1)

notify_telegram() {
  local message="$1"
  [ -z "$_TG_TOKEN" ] || [ -z "$_TG_CHAT_ID" ] && return 0
  curl -s -X POST "https://api.telegram.org/bot${_TG_TOKEN}/sendMessage" \
    -H "Content-Type: application/json" \
    -d "{\"chat_id\": \"${_TG_CHAT_ID}\", \"text\": $(echo "$message" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))'), \"parse_mode\": \"Markdown\"}" > /dev/null 2>&1 || true
}

send_telegram_video() {
  local file_path="$1"
  local caption="$2"
  [ -z "$_TG_TOKEN" ] || [ -z "$_TG_CHAT_ID" ] && return 0
  [ ! -f "$file_path" ] && return 0
  curl -s -X POST "https://api.telegram.org/bot${_TG_TOKEN}/sendVideo" \
    -F "chat_id=${_TG_CHAT_ID}" \
    -F "video=@${file_path}" \
    -F "caption=${caption}" \
    -F "parse_mode=Markdown" > /dev/null 2>&1 || true
}

send_telegram_photo() {
  local file_path="$1"
  local caption="$2"
  [ -z "$_TG_TOKEN" ] || [ -z "$_TG_CHAT_ID" ] && return 0
  [ ! -f "$file_path" ] && return 0
  curl -s -X POST "https://api.telegram.org/bot${_TG_TOKEN}/sendPhoto" \
    -F "chat_id=${_TG_CHAT_ID}" \
    -F "photo=@${file_path}" \
    -F "caption=${caption}" \
    -F "parse_mode=Markdown" > /dev/null 2>&1 || true
}
