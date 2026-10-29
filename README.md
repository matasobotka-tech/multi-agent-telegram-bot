# Multi-Agent AI Support Bot for Telegram

A Python Telegram bot where a **router agent** sends each customer message to one of three
**specialist agents**, each with its own tools:

| Agent | Tools | Handles |
|---|---|---|
| `orders` | `get_order_status`, `create_ticket` | order status, tracking, ETA |
| `sales` | `list_products`, `create_ticket` | plans, prices, recommendations |
| `support` | `search_knowledge_base`, `create_ticket` | shipping, returns, payment, hours |

- LLM: Claude (Anthropic API) with tool use; agents only answer from tool data, never invent orders or prices
- per-chat conversation memory (last 6 turns), `/reset`, `/human` handoff to a person (ticket)
- tool errors are fed back to the model instead of crashing, tool-loop limit, refusal handling
- rate limiting per chat, logging of which agent handled each message
- blocking LLM calls run off the event loop, so many chats stay responsive
- 11 unit tests with a fake LLM client (`python -m unittest`) - no API key needed

Stack: Python 3.11+, python-telegram-bot 22, anthropic SDK.
Developed AI-assisted (Claude Code), reviewed and tested by hand.

## Run
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY
python -m bot.main
```
Windows (PowerShell): `python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt; Copy-Item .env.example .env; python -m bot.main`

Try: "where is my order 1001?", "which plan is best for a team of 5?", "how do returns work?", "/human".

Demo data (orders, products, knowledge base) lives in `bot/agents.py`; in production it would come
from the shop's database or API.
