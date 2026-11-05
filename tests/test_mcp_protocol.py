"""Real stdio MCP discovery tests: compact-by-default, opt-in legacy exposure."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from test_agent_handoff import payload

COMPACT = {"facetide_context", "facetide_draft", "facetide_confirm"}
OLD = {
    "facetide_get_snapshot", "facetide_prepare_review", "facetide_publish_source_bundle",
    "facetide_get_compilation_batch", "facetide_compile_batch",
    "facetide_agent_brief", "facetide_stage_agent_review",
    "facetide_get_agent_review", "facetide_confirm_agent_review",
    "facetide_get_state_context", "facetide_compile_state_report",
    "facetide_get_state_report", "facetide_upsert_goal", "facetide_save_review",
    "facetide_get_history",
}


def tool_payload(result):
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(next(part.text for part in result.content if part.type == "text"))


class MCPProtocolTest(unittest.TestCase):
    async def _verify_profile(self, db_path, profile="compact", enable_goal=False):
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "facetide"],
            env={
                **os.environ,
                "FACETIDE_DB_PATH": str(db_path),
                "FACETIDE_EVIDENCE_FILE": "",
                "FACETIDE_MRMEM_DIR": "",
                "FACETIDE_MRMEM_USER_ID": "",
                "FACETIDE_NUTRITION_MCP_URL": "",
                "FACETIDE_BRIDGE_ALLOWED_SOURCES": "",
                "FACETIDE_TOOL_PROFILE": profile,
                "FACETIDE_ENABLE_GOAL_TOOL": "1" if enable_goal else "0",
            },
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                names = {item.name for item in (await session.list_tools()).tools}
                expected = COMPACT | (OLD if profile == "legacy" else
                                      {"facetide_upsert_goal"} if enable_goal else set())
                self.assertEqual(names, expected)
                result = await session.call_tool("facetide_context", {
                    "period_start": "2026-11-01",
                    "period_end": "2026-11-05",
                })
                self.assertFalse(result.isError)
                self.assertTrue(result.structuredContent or result.content)
                if profile == "compact" and not enable_goal:
                    staged = await session.call_tool("facetide_draft", payload())
                    self.assertFalse(staged.isError)
                    draft = tool_payload(staged)
                    confirmed = await session.call_tool("facetide_confirm", {
                        "draft_id": draft["draft_id"], "expected_hash": draft["draft_hash"],
                        "domain_scores": {"career": 3}, "user_confirmed": True,
                    })
                    self.assertFalse(confirmed.isError)
                    newer = await session.call_tool("facetide_draft", payload())
                    self.assertFalse(newer.isError)
                    resumed = await session.call_tool("facetide_context", {
                        "period_start": "2026-11-01", "period_end": "2026-11-05",
                        "history_limit": 1,
                    })
                    self.assertFalse(resumed.isError)
                    context = tool_payload(resumed)
                    self.assertEqual(context["confirmed_review"]["approved_draft"]["draft_id"],
                                     draft["draft_id"])
                    self.assertEqual(context["latest_draft"]["draft_id"],
                                     tool_payload(newer)["draft_id"])
                    self.assertEqual(context["history"]["reviews"][0]["approved_draft"]
                                     ["draft_id"], draft["draft_id"])
                self.assertIn("facetide_reflection_guide",
                              {p.name for p in (await session.list_prompts()).prompts})

    def test_compact_profile_exposes_exactly_three_tools(self):
        with tempfile.TemporaryDirectory() as d:
            asyncio.run(asyncio.wait_for(
                self._verify_profile(Path(d) / "data.sqlite3"), timeout=25))

    def test_opt_in_goal_tool_does_not_expose_legacy_engines(self):
        with tempfile.TemporaryDirectory() as d:
            asyncio.run(asyncio.wait_for(
                self._verify_profile(Path(d) / "data.sqlite3", enable_goal=True),
                timeout=25))

    def test_explicit_legacy_profile_keeps_old_tool_names(self):
        with tempfile.TemporaryDirectory() as d:
            asyncio.run(asyncio.wait_for(
                self._verify_profile(Path(d) / "data.sqlite3", profile="legacy"),
                timeout=25))


if __name__ == "__main__":
    unittest.main()
