import unittest
from types import SimpleNamespace as NS

from bot import agents


def text(t, stop="end_turn"):
    return NS(content=[NS(type="text", text=t)], stop_reason=stop)


def tool_call(name, args, id_="t1"):
    return NS(content=[NS(type="tool_use", name=name, input=args, id=id_)], stop_reason="tool_use")


class FakeClient:
    """Returns scripted responses and records every request."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class RouterTests(unittest.TestCase):
    def test_valid_route(self):
        self.assertEqual(agents.route(FakeClient(text("Orders.")), "where is 1001"), "orders")

    def test_unknown_route_falls_back_to_support(self):
        self.assertEqual(agents.route(FakeClient(text("weather")), "hi"), "support")


class AgentTests(unittest.TestCase):
    def test_tool_loop_returns_real_data(self):
        client = FakeClient(tool_call("get_order_status", {"order_id": "1001"}), text("Shipped with DHL."))
        reply = agents.AGENTS["orders"].run(client, [{"role": "user", "content": "order 1001?"}])
        self.assertEqual(reply, "Shipped with DHL.")
        result = client.calls[1]["messages"][-1]["content"][0]
        self.assertEqual(result["tool_use_id"], "t1")
        self.assertIn("DH123456789", result["content"])
        self.assertFalse(result["is_error"])

    def test_tool_error_is_reported_not_raised(self):
        client = FakeClient(tool_call("get_order_status", {"wrong": "x"}), text("Could you send the order id?"))
        agents.AGENTS["orders"].run(client, [{"role": "user", "content": "order?"}])
        self.assertTrue(client.calls[1]["messages"][-1]["content"][0]["is_error"])

    def test_refusal(self):
        reply = agents.AGENTS["support"].run(FakeClient(text("", stop="refusal")), [{"role": "user", "content": "x"}])
        self.assertIn("/human", reply)

    def test_tool_round_limit(self):
        client = FakeClient(*[tool_call("list_products", {}) for _ in range(agents.MAX_TOOL_ROUNDS)])
        self.assertIn("longer than expected", agents.AGENTS["sales"].run(client, [{"role": "user", "content": "x"}]))

    def test_handoff_records_chat(self):
        client = FakeClient(tool_call("create_ticket", {"summary": "angry"}), text("A human will reply."))
        agents.AGENTS["support"].run(client, [{"role": "user", "content": "human!"}], chat_id=42)
        self.assertEqual(agents.TICKETS[-1]["chat_id"], 42)


class ToolTests(unittest.TestCase):
    def test_kb_search(self):
        self.assertEqual(agents.search_knowledge_base("how do returns work")[0]["title"], "Returns")
        self.assertEqual(agents.search_knowledge_base("zzz")[0]["title"], "No match")

    def test_order_lookup(self):
        self.assertEqual(agents.get_order_status("#1002")["status"], "processing")
        self.assertIn("error", agents.get_order_status("9"))


class OrchestratorTests(unittest.TestCase):
    def test_memory_and_routing(self):
        client = FakeClient(text("sales"), text("Business plan fits you."), text("support"), text("Free over 50 EUR."))
        o = agents.Orchestrator(client)
        self.assertEqual(o.handle(1, "which plan for a team?"), ("sales", "Business plan fits you."))
        self.assertEqual(o.handle(1, "and shipping?")[0], "support")
        # second agent call sees the earlier turn
        self.assertEqual(client.calls[3]["messages"][0]["content"], "which plan for a team?")
        o.reset(1)
        self.assertEqual(len(o.history[1]), 0)

    def test_history_is_capped(self):
        o = agents.Orchestrator(FakeClient(*[text("support"), text("ok")] * 10))
        for i in range(10):
            o.handle(7, f"q{i}")
        self.assertEqual(len(o.history[7]), agents.HISTORY_TURNS * 2)


if __name__ == "__main__":
    unittest.main()
