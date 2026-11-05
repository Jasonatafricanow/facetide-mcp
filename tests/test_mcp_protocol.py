"""Integration smoke test through real stdio MCP transport, not only imports."""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPProtocolTest(unittest.TestCase):
    def test_stdio_initialize_tool_list_and_snapshot(self):
        async def verify(db_path):
            params = StdioServerParameters(
                command=sys.executable, args=["-m", "facetide"],
                env={**os.environ, "FACETIDE_DB_PATH": str(db_path),
                     "FACETIDE_EVIDENCE_FILE": "",
                     "FACETIDE_MRMEM_DIR": "", "FACETIDE_MRMEM_USER_ID": ""},
            )
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tool_names = {tool.name for tool in (await session.list_tools()).tools}
                    self.assertTrue({"facetide_get_snapshot", "facetide_prepare_review",
                        "facetide_save_review", "facetide_upsert_goal", "facetide_get_history",
                        "facetide_get_compilation_batch", "facetide_compile_batch", "facetide_publish_source_bundle",
                        "facetide_get_state_context", "facetide_compile_state_report", "facetide_get_state_report"} <= tool_names)
                    result = await session.call_tool("facetide_get_snapshot", {})
                    self.assertFalse(result.isError)
                    # JSON result may appear in structuredContent on newer SDKs.
                    self.assertTrue(result.structuredContent or result.content)
        with tempfile.TemporaryDirectory() as d:
            asyncio.run(asyncio.wait_for(verify(Path(d) / "data.sqlite3"), timeout=20))


if __name__ == "__main__":
    unittest.main()
