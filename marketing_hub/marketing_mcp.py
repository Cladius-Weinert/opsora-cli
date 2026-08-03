"""
Opsora Marketing MCP Server
Expose marketing tools as MCP server for Qwen Code integration.

Usage:
    python3 -m marketing_hub.marketing_mcp
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from marketing_hub.content_strategy import ContentStrategy
from marketing_hub.analytics import Analytics
from marketing_hub.broadcaster import Broadcaster

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("marketing_mcp")


class MarketingMCP:
    """
    MCP server exposing marketing tools.
    Communicates via stdio JSON-RPC.
    """

    def __init__(self):
        self.strategy = ContentStrategy()
        self.analytics = Analytics()
        self.broadcaster = Broadcaster()
        self.tools = {
            "generate_content": self.handle_generate_content,
            "get_content_calendar": self.handle_get_calendar,
            "get_analytics": self.handle_get_analytics,
            "track_metric": self.handle_track_metric,
            "get_hashtags": self.handle_get_hashtags,
            "broadcast": self.handle_broadcast,
            "status": self.handle_status,
        }

    def handle_generate_content(self, params: dict) -> dict:
        content_type = params.get("type", "intro")
        language = params.get("lang", "both")
        feature = params.get("feature")
        content = self.strategy.generate_content(content_type, language, feature)
        return {"content": content}

    def handle_get_calendar(self, params: dict) -> dict:
        plans = self.strategy.get_weekly_calendar()
        return {"calendar": [{"day": p.day, "type": p.content_type, "title": p.title} for p in plans]}

    def handle_get_analytics(self, params: dict) -> dict:
        days = params.get("days", 7)
        return self.analytics.get_report(days)

    def handle_track_metric(self, params: dict) -> dict:
        self.analytics.track(
            params["platform"], params["metric"], params["value"],
            params.get("metadata"),
        )
        return {"status": "ok"}

    def handle_get_hashtags(self, params: dict) -> dict:
        topic = params.get("topic", "ai")
        return {"hashtags": self.strategy.optimize_hashtags(topic)}

    def handle_broadcast(self, params: dict) -> dict:
        import asyncio
        text = params.get("text", "")
        platform = params.get("platform", "all")
        # Simplified sync version
        return {"status": "async", "message": "Use broadcaster.py for async broadcast"}

    def handle_status(self, params: dict) -> dict:
        return {
            "status": "running",
            "tools": list(self.tools.keys()),
            "timestamp": datetime.now().isoformat(),
        }

    def handle_request(self, request: dict) -> dict:
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")

        if method == "list_tools":
            return {"jsonrpc": "2.0", "id": req_id, "result": {
                "tools": [
                    {"name": n, "description": f"Marketing tool: {n}"}
                    for n in self.tools.keys()
                ]
            }}

        handler = self.tools.get(method)
        if not handler:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

        try:
            result = handler(params)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}}

    def run(self):
        log.info("Marketing MCP server starting (stdio)...")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self.handle_request(request)
                print(json.dumps(response), flush=True)
            except json.JSONDecodeError:
                print(json.dumps({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}), flush=True)


if __name__ == "__main__":
    server = MarketingMCP()
    server.run()