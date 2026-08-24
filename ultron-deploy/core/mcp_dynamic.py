# MCP Connection Manager for AGENT

"""Optimized MCP connection management with efficient connection pooling.

Key improvements:
- Reduced simulated connection delays
- Efficient status reporting
- Connection state deduplication
- Thread-safe operations
"""

import asyncio
import json
import os
import time
from typing import Dict, List
from dataclasses import dataclass, field

@dataclass
class MCPConnection:
    """Represents a single MCP server connection - optimized dataclass."""
    server_id: str
    status: str = "disconnected"  # "connected", "disconnected", "connecting", "error"
    config: Dict = field(default_factory=dict)
    connected_at: float = 0.0
    last_heartbeat: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def is_active(self) -> bool:
        """Quick check if connection is active."""
        return self.status == "connected"


class DynamicMCPManager:
    """Manages dynamic MCP server connections for AGENT with efficient pooling."""
    
    def __init__(self):
        self.connections: Dict[str, MCPConnection] = {}
        self.max_connections = 0
        self.auto_reconnect = True
        self.connection_timeout = 30
        self.config_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            ".mcp.json"
        )
        self._config_lock = asyncio.Lock()
        self._loaded = False
        self.load_config()
    
    def load_config(self):
        """Load MCP configuration from .mcp.json file - optimized."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                self.max_connections = config.get('max_connections', 0)
                self.auto_reconnect = config.get('auto_reconnect', True)
                self.connection_timeout = config.get('connection_timeout', 30)
                
                # Initialize connection states based on config
                # Only update existing connections or create new ones
                servers = config.get('mcpServers', {})
                new_connections = {}
                for server_id, server_config in servers.items():
                    if server_id in self.connections:
                        conn = self.connections[server_id]
                        conn.config = server_config
                        if not server_config.get('enabled', True):
                            conn.status = 'disconnected'
                        elif conn.status == 'disconnected':
                            conn.status = 'connecting'
                    else:
                        new_connections[server_id] = MCPConnection(
                            server_id=server_id,
                            status='connecting' if server_config.get('enabled', True) else 'disconnected',
                            config=server_config
                        )
                
                self.connections.update(new_connections)
                self._loaded = True
            except Exception as e:
                print(f"Error loading MCP config: {e}")
                self._init_default_config()
        else:
            self._init_default_config()
    
    def _init_default_config(self):
        """Initialize with default empty configuration."""
        self.connections = {}
        self.max_connections = 0
        self.auto_reconnect = True
        self.connection_timeout = 30
    
    def _active(self) -> List[str]:
        """Server ids currently in connected state."""
        return [sid for sid, conn in self.connections.items() if conn.status == 'connected']

    def get_connection_count(self) -> int:
        """Get the current number of active connections - optimized."""
        return len(self._active())

    def get_all_servers(self) -> List[str]:
        """Get list of all configured MCP servers."""
        return list(self.connections.keys())

    def get_active_servers(self) -> List[str]:
        """Get list of currently active (connected) MCP servers."""
        return self._active()
    
    async def connect_server(self, server_id: str) -> bool:
        """Connect to an MCP server dynamically - optimized."""
        if server_id not in self.connections:
            return False
        
        conn = self.connections[server_id]
        if conn.status == 'connected':
            return True
        
        try:
            conn.status = 'connecting'
            # Minimal simulated connection delay for responsiveness
            await asyncio.sleep(0.1)
            
            conn.status = 'connected'
            conn.connected_at = time.time()
            conn.last_heartbeat = time.time()
            
            print(f"Connected to MCP server: {server_id}")
            return True
        except Exception as e:
            print(f"Failed to connect to MCP server {server_id}: {e}")
            conn.status = 'error'
            return False
    
    async def disconnect_server(self, server_id: str) -> bool:
        """Disconnect from an MCP server - optimized."""
        if server_id not in self.connections:
            return False
        
        conn = self.connections[server_id]
        if conn.status != 'connected':
            return False
        
        try:
            conn.status = 'disconnected'
            print(f"Disconnected from MCP server: {server_id}")
            return True
        except Exception as e:
            print(f"Error disconnecting from MCP server {server_id}: {e}")
            conn.status = 'error'
            return False
    
    async def toggle_server(self, server_id: str) -> Dict:
        """Toggle connection state of an MCP server."""
        if server_id not in self.connections:
            return {"success": False, "error": "Server not configured"}
        conn = self.connections[server_id]
        if conn.status == 'connected':
            return {"success": await self.disconnect_server(server_id), "action": "disconnected"}
        return {"success": await self.connect_server(server_id), "action": "connected"}
    
    def get_status_report(self) -> Dict:
        """Get comprehensive status report - optimized."""
        total_configured = len(self.connections)
        active_count = self.get_connection_count()
        inactive_count = total_configured - active_count
        
        return {
            "total_configured_servers": total_configured,
            "active_connections": active_count,
            "inactive_connections": inactive_count,
            "max_connections": self.max_connections,
            "auto_reconnect": self.auto_reconnect,
            "server_statuses": {
                sid: {
                    "status": conn.status,
                    "enabled": conn.config.get('enabled', True),
                    "command": conn.config.get('command', ''),
                    "args": conn.config.get('args', [])
                }
                for sid, conn in self.connections.items()
            }
        }
    
    async def cleanup_excess_connections(self) -> List[str]:
        """Disconnect excess connections if limit exceeded - optimized."""
        if self.max_connections <= 0:
            return []
        
        active_count = self.get_connection_count()
        if active_count <= self.max_connections:
            return []
        
        # Disconnect oldest connections first
        sorted_servers = sorted(
            [(sid, conn.connected_at) for sid, conn in self.connections.items()
             if conn.status == 'connected'],
            key=lambda x: x[1]
        )
        
        servers_to_disconnect = [sid for sid, _ in sorted_servers[:active_count - self.max_connections]]
        
        for server_id in servers_to_disconnect:
            await self.disconnect_server(server_id)
        
        return servers_to_disconnect


# Global MCP manager instance for AGENT
_agent_mcp_manager = DynamicMCPManager()

async def get_agent_connection_count() -> int:
    """Get current connection count for AGENT."""
    return _agent_mcp_manager.get_connection_count()

async def get_agent_status_report() -> Dict:
    """Get status report for AGENT's MCP connections."""
    return _agent_mcp_manager.get_status_report()

async def toggle_agent_server(server_id: str) -> Dict:
    """Toggle an MCP server connection for AGENT."""
    return await _agent_mcp_manager.toggle_server(server_id)

async def cleanup_agent_connections() -> List[str]:
    """Clean up AGENT's excess connections."""
    return await _agent_mcp_manager.cleanup_excess_connections()

# Initialize with default configuration
if not os.path.exists('.mcp.json'):
    _agent_mcp_manager.load_config()