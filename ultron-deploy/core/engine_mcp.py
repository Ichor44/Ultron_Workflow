from core import engine, skills, proposals, review
from core.mcp_dynamic import (
    get_agent_connection_count,
    get_agent_status_report,
    toggle_agent_server,
    cleanup_agent_connections,
    _agent_mcp_manager
)

import asyncio
import json


class AgentWithMCP(engine.Agent):
    def __init__(self, config, auto_approve=False):
        super().__init__(config, auto_approve)
        # Initialize MCP manager for this agent instance
        self.mcp_manager = _agent_mcp_manager

    @staticmethod
    def _run_async(coro):
        """Run a coroutine to completion from the synchronous tool-call path.

        engine.Agent._handle_tool() invokes handlers synchronously, while the
        MCP manager exposes async methods (toggle_server, cleanup_excess_connections).
        This bridges the two: uses asyncio.run() when no loop is running, and
        runs on a dedicated thread when called from inside a running loop
        (e.g. the web UI's async request handler).
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        import threading
        result = {}

        def _runner():
            result["value"] = asyncio.run(coro)

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join()
        return result["value"]

    def _define_tools(self):
        """Override to add MCP-specific tools"""
        tools = super()._define_tools()

        # Add MCP management tools (skipped if already present)
        mcp_tools = [
            self._tool("list_mcp_servers",
                       "List all MCP servers configured and their connection status"),
            self._tool("toggle_mcp_server",
                       "Toggle the connection state of an MCP server (connect/disconnect)",
                       {"server_id": {"type": "string", "description": "ID of the MCP server to toggle"}},
                       ["server_id"]),
            self._tool("execute_with_mcp",
                       "Execute a task using available MCP connections",
                       {"task": {"type": "string", "description": "Task description"},
                        "server_requirements": {"type": "array", "items": {"type": "string"},
                                                "description": "Optional hint about which MCP servers to use"}},
                       ["task"]),
        ]

        # Add tools if they don't already exist
        for tool in mcp_tools:
            if not any(t["name"] == tool["name"] for t in tools):
                tools.append(tool)

        return tools

    def _tool_dispatch(self):
        """Merge base tool handlers with the MCP-specific handlers.

        Without this, engine.Agent._handle_tool() has no handler for the MCP
        tools registered in _define_tools() and returns "Unknown tool: ...".
        """
        d = super()._tool_dispatch()
        d["list_mcp_servers"] = lambda a: json.dumps(self.list_mcp_servers(), indent=2, default=str)
        d["toggle_mcp_server"] = lambda a: json.dumps(
            self._run_async(self.toggle_mcp_server(a.get("server_id", ""))), indent=2, default=str)
        d["execute_with_mcp"] = lambda a: json.dumps(
            self._run_async(self.execute_with_mcp(a.get("task", ""), a.get("server_requirements"))),
            indent=2, default=str)
        return d

    def list_mcp_servers(self):
        """List all MCP servers and their status"""
        return self.mcp_manager.get_status_report()

    async def toggle_mcp_server(self, server_id: str):
        """Toggle an MCP server connection"""
        return await self.mcp_manager.toggle_server(server_id)

    async def execute_with_mcp(self, task: str, server_requirements=None):
        """Execute task using MCP connections"""
        active_servers = self.mcp_manager.get_active_servers()

        if not active_servers:
            return {"error": "No active MCP connections available"}

        # Filter servers if requirements specified
        if server_requirements:
            active_servers = [s for s in active_servers
                            if any(req.lower() in s.lower() for req in server_requirements)]

        # Check connection limits
        await self.mcp_manager.cleanup_excess_connections()

        return {
            "task": task,
            "servers_used": active_servers,
            "message": f"Task would be executed using {len(active_servers)} MCP server(s)",
            "connection_count": self.mcp_manager.get_connection_count()
        }


def _print_briefing():
    """Print system briefing."""
    pass  # Implementation would go here


def cmd_chat(goal, use_mock, auto, speak):
    """Enhanced chat command with MCP support"""
    import config
    import sys
    
    cfg = config.load_config()
    if use_mock:
        cfg["provider"] = "mock"
    if not cfg["provider"]:
        print("No LLM provider configured.")
        print("Set OPENAI_API_KEY / ANTHROPIC_API_KEY, or run with --mock to try the workflow offline.")
        sys.exit(1)
    
    # Create agent with MCP integration
    agent = AgentWithMCP(cfg, auto_approve=auto)
    from core import voice

    def say(text):
        if speak:
            import os as _os
            prev = _os.environ.get("VOICE_ENABLED")
            _os.environ["VOICE_ENABLED"] = "true"
            try:
                voice.speak(text)
            finally:
                _os.environ.pop("VOICE_ENABLED", None) if prev is None else _os.environ.__setitem__("VOICE_ENABLED", prev)

    # Interactive chat loop
    if goal is None:
        from core import memory, notify
        _print_briefing()
        due = memory.due_reminders()
        if due:
            notify.notify_due_reminders(due)
        print("\n(Type 'exit' or 'quit' to leave.)\n")
        while True:
            try:
                goal = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAt your service. Goodbye.")
                break
            if not goal:
                continue
            if goal in ("exit", "quit"):
                print("At your service. Goodbye.")
                break
            answer = agent.continue_chat(goal)
            print("\nAGENT: %s" % answer)
            say(answer)
        return

    # Single goal execution
    print("Ultron is working on: %s\n" % goal)
    answer = agent.run(goal)
    print("\nAGENT: %s" % answer)
    say(answer)


def cmd_brief():
    """Enhanced brief command with MCP status"""
    from core import memory
    
    print("Ultron online. Good sir.")
    
    # Get system briefing (basic info)
    _print_briefing()
    
    # Get MCP status
    try:
        mcp_status = _agent_mcp_manager.get_status_report()
        print("\nMCP Connection Status:")
        print("  Total configured servers: %d" % mcp_status.get("total_configured_servers", 0))
        print("  Active connections: %d" % mcp_status.get("active_connections", 0))
        print("  Inactive connections: %d" % mcp_status.get("inactive_connections", 0))
        print("  Max allowed connections: %d" % mcp_status.get("max_connections", 0))
        print("  Auto-reconnect: %s" % ("enabled" if mcp_status.get("auto_reconnect") else "disabled"))
        
        if mcp_status.get("active_connections", 0) > mcp_status.get("max_connections", 0) and mcp_status.get("max_connections") > 0:
            print("  ⚠️  WARNING: Exceeding maximum connection limit!")
    except Exception as e:
        print("\nMCP Connection Status: Unable to retrieve (%s)" % str(e))
    
    print("\nDue reminders:")
    due = memory.due_reminders()
    if due:
        for r in due:
            print("  ! %s" % r["text"])
    else:
        print("  none")
    
    print("\nAll pending reminders:")
    print(memory.list_reminders())
    
    print("\nWhat I know about you:")
    print(memory.recall_fact(""))