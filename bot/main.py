"""Telegram front end for the multi-agent bot.

Run:  python -m bot.main   (reads TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY from env / .env)
"""
import asyncio
import logging
import os
import time
from collections import defaultdict
from pathlib import Path

from anthropic import Anthropic
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from bot.agents import Orchestrator, create_ticket

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("bot")

RATE_LIMIT = 8  # messages per minute per chat
_hits = defaultdict(list)


def load_env(path=Path(__file__).resolve().parent.parent / ".env"):
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():  # utf-8-sig: Notepad may add a BOM
            key, sep, value = line.partition("=")
            if sep and not key.strip().startswith("#") and value.strip():
                os.environ.setdefault(key.strip(), value.strip())


def allowed(chat_id):
    now = time.time()
    _hits[chat_id] = [t for t in _hits[chat_id] if now - t < 60] + [now]
    return len(_hits[chat_id]) <= RATE_LIMIT


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I'm the shop assistant 🤖\n"
        "Ask me about an order (try: where is my order 1001?), plans and prices, or shipping and returns.\n"
        "/human - talk to a person · /reset - start over"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.bot_data["orchestrator"].reset(update.effective_chat.id)
    await update.message.reply_text("Conversation cleared ✨")


async def human(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticket = create_ticket("Customer asked for a human via /human", update.effective_chat.id)
    await update.message.reply_text(f"Ticket #{ticket['ticket_id']} created. {ticket['message']}")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not allowed(chat_id):
        await update.message.reply_text("⏳ Too many messages, please wait a minute.")
        return
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    try:
        # the Claude calls are blocking; run them off the event loop so other chats stay responsive
        agent, reply = await asyncio.to_thread(context.bot_data["orchestrator"].handle, chat_id, update.message.text)
        log.info("chat=%s agent=%s", chat_id, agent)
    except Exception:
        log.exception("handling failed")
        reply = "⚠️ Something went wrong on my side. Please try again, or type /human."
    await update.message.reply_text(reply)


def main():
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY (copy .env.example to .env).")
    app = Application.builder().token(token).build()
    app.bot_data["orchestrator"] = Orchestrator(Anthropic())
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("human", human))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Bot running. Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
