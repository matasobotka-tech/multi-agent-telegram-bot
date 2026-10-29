"""Multi-agent support bot: a router picks a specialist agent, the agent answers
using its own tools (knowledge base, order lookup, products, human handoff).

Everything here is plain Python, independent of Telegram, so it can be tested
with a fake Claude client.
"""
import json
from collections import defaultdict, deque

MODEL = "claude-opus-5-5"
MAX_TOOL_ROUNDS = 5
HISTORY_TURNS = 6  # user+assistant pairs kept per chat


def call_claude(client, **kwargs):
    return client.beta.messages.create(
        model=MODEL,
        max_tokens=2048,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low"},
        **kwargs,
    )


def text_of(response):
    return "".join(b.text for b in response.content if b.type == "text").strip()


# ------------------------------------------------------------------ demo data
# In a real deployment these come from the client's database / CMS / API.

KNOWLEDGE_BASE = [
    {"title": "Shipping", "text": "Orders ship within 2 business days. EU delivery takes 3-5 days, worldwide 7-14 days. Shipping is free over 50 EUR."},
    {"title": "Returns", "text": "You can return any item within 30 days. Start a return with your order id; refunds arrive within 5 business days after we receive the item."},
    {"title": "Payment", "text": "We accept cards, Apple Pay, Google Pay and bank transfer. Invoices are sent by email after payment."},
    {"title": "Opening hours", "text": "Human support is available Mon-Fri 9:00-17:00 CET. The bot answers 24/7."},
]

ORDERS = {
    "1001": {"status": "shipped", "carrier": "DHL", "tracking": "DH123456789", "eta": "2 days"},
    "1002": {"status": "processing", "carrier": None, "tracking": None, "eta": "ships tomorrow"},
}

PRODUCTS = [
    {"name": "Starter plan", "price_eur": 9, "for": "individuals, 1 chatbot, 500 messages/month"},
    {"name": "Business plan", "price_eur": 49, "for": "small teams, 5 chatbots, 10k messages/month, CRM integration"},
    {"name": "Enterprise", "price_eur": None, "for": "custom volume, SSO, dedicated support - price on request"},
]

TICKETS = []


def search_knowledge_base(query):
    words = {w for w in query.lower().split() if len(w) > 2}
    scored = sorted(
        ((sum(w in (d["title"] + " " + d["text"]).lower() for w in words), d) for d in KNOWLEDGE_BASE),
        key=lambda x: -x[0],
    )
    hits = [d for s, d in scored if s > 0][:2]
    return hits or [{"title": "No match", "text": "Nothing relevant found in the knowledge base."}]


def get_order_status(order_id):
    order = ORDERS.get(str(order_id).strip().lstrip("#"))
    return order or {"error": f"No order with id {order_id}. Ask the customer to double-check it."}


def list_products():
    return PRODUCTS


def create_ticket(summary, chat_id=None):
    TICKETS.append({"id": len(TICKETS) + 1, "summary": summary, "chat_id": chat_id})
    return {"ticket_id": len(TICKETS), "message": "A human will reply within 24 hours."}


# ------------------------------------------------------------------ agents

def tool(name, description, properties, required):
    return {
        "name": name,
        "description": description,
        "input_schema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        "strict": True,
    }


HANDOFF_TOOL = tool(
    "create_ticket",
    "Hand the conversation to a human. Use when the customer asks for a person, is upset, or you can't solve it.",
    {"summary": {"type": "string", "description": "One-sentence summary of the problem for the human agent."}},
    ["summary"],
)

STYLE = (" Reply in the customer's language, in at most 4 short sentences, friendly and concrete."
         " Use only facts from your tools; never invent order data, prices or policies.")


class Agent:
    def __init__(self, name, system, tools, handlers):
        self.name, self.system, self.tools, self.handlers = name, system + STYLE, tools, handlers

    def run(self, client, messages, chat_id=None):
        messages = list(messages)
        for _ in range(MAX_TOOL_ROUNDS):
            response = call_claude(client, system=self.system, messages=messages, tools=self.tools)
            if response.stop_reason == "refusal":
                return "Sorry, I can't help with that. Type /human to reach a person."
            if response.stop_reason != "tool_use":
                return text_of(response) or "Sorry, could you rephrase that?"
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    args = dict(block.input)
                    if block.name == "create_ticket":
                        args["chat_id"] = chat_id
                    output, is_error = self.handlers[block.name](**args), False
                except Exception as e:  # report tool failures to the model instead of crashing
                    output, is_error = {"error": str(e)}, True
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(output, ensure_ascii=False), "is_error": is_error})
            messages.append({"role": "user", "content": results})
        return "This is taking longer than expected - I've noted it, please try again or type /human."


AGENTS = {
    "support": Agent(
        "support",
        "You are the support agent of an online shop. Answer questions about shipping, returns, payment and hours"
        " using search_knowledge_base.",
        [tool("search_knowledge_base", "Search shop policies and FAQ.", {"query": {"type": "string"}}, ["query"]), HANDOFF_TOOL],
        {"search_knowledge_base": search_knowledge_base, "create_ticket": create_ticket},
    ),
    "orders": Agent(
        "orders",
        "You are the order-tracking agent. Look up orders with get_order_status. If the customer has not given an"
        " order id, ask for it.",
        [tool("get_order_status", "Get status, carrier, tracking number and ETA of an order.",
              {"order_id": {"type": "string"}}, ["order_id"]), HANDOFF_TOOL],
        {"get_order_status": get_order_status, "create_ticket": create_ticket},
    ),
    "sales": Agent(
        "sales",
        "You are the sales agent. Recommend the right plan using list_products, based on what the customer needs.",
        [tool("list_products", "List plans with prices and who they are for.", {}, []), HANDOFF_TOOL],
        {"list_products": list_products, "create_ticket": create_ticket},
    ),
}

ROUTER_SYSTEM = (
    "You route customer messages to a specialist. Answer with exactly one word:\n"
    "orders - anything about a specific order, delivery status or tracking\n"
    "sales - plans, prices, which product to buy, upgrades\n"
    "support - everything else (shipping/returns policy, payment, hours, general questions)"
)


def route(client, text, history=()):
    context = "\n".join(f"{m['role']}: {m['content']}" for m in list(history)[-4:])
    response = call_claude(
        client,
        system=ROUTER_SYSTEM,
        messages=[{"role": "user", "content": f"Recent conversation:\n{context or '-'}\n\nNew message: {text}"}],
    )
    word = text_of(response).lower().strip(" .\n")
    return word if word in AGENTS else "support"


class Orchestrator:
    """Keeps short per-chat memory and sends each message to the right agent."""

    def __init__(self, client):
        self.client = client
        self.history = defaultdict(lambda: deque(maxlen=HISTORY_TURNS * 2))

    def reset(self, chat_id):
        self.history.pop(chat_id, None)

    def handle(self, chat_id, text):
        history = self.history[chat_id]
        name = route(self.client, text, history)
        messages = list(history) + [{"role": "user", "content": text}]
        reply = AGENTS[name].run(self.client, messages, chat_id=chat_id)
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        return name, reply
