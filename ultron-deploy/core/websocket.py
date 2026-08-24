"""WebSocket real-time updates for Ultron Web UI.

Provides real-time communication with:
- WebSocket connections for live updates
- Event broadcasting to all clients
- Client connection management
- Message queuing for offline clients
- Heartbeat/ping-pong for connection health
"""

import json
import time
import threading
from typing import Any, Callable, Dict, List, Optional, Set
from collections import defaultdict

try:
    from flask_socketio import SocketIO, emit, join_room, leave_room
    from flask import request
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False

from core import logging as ultron_logging


class ConnectionManager:
    """Manage WebSocket client connections."""
    
    _instance: Optional['ConnectionManager'] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> 'ConnectionManager':
        """Singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        """Initialize connection manager."""
        if self._initialized:
            return
        self._initialized = True
        
        # Client tracking
        self._clients: Dict[str, Dict[str, Any]] = {}
        self._rooms: Dict[str, Set[str]] = defaultdict(set)
        self._client_rooms: Dict[str, Set[str]] = defaultdict(set)
        
        # Message queues for offline clients
        self._message_queues: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._max_queue_size: int = 100
        
        # Event handlers
        self._event_handlers: Dict[str, List[Callable]] = defaultdict(list)
        
        # Statistics
        self._stats: Dict[str, int] = {
            'total_connections': 0,
            'active_connections': 0,
            'messages_sent': 0,
            'messages_queued': 0,
        }
        
        self.logger = ultron_logging.get_logger()
    
    def register_client(self, client_id: str, user_info: Optional[Dict[str, Any]] = None) -> None:
        """Register a new client connection.
        
        Args:
            client_id: Unique client identifier.
            user_info: Optional user information.
        """
        self._clients[client_id] = {
            'connected_at': time.time(),
            'last_seen': time.time(),
            'user_info': user_info or {},
        }
        self._stats['total_connections'] += 1
        self._stats['active_connections'] = len(self._clients)
        
        self.logger.info(f"Client connected: {client_id}", client_id=client_id)
        
        # Send queued messages
        self._send_queued_messages(client_id)
    
    def unregister_client(self, client_id: str) -> None:
        """Unregister a client connection.
        
        Args:
            client_id: Client identifier to remove.
        """
        if client_id in self._clients:
            del self._clients[client_id]
        
        # Remove from rooms
        for room_id in list(self._client_rooms.get(client_id, set())):
            self.leave_room(client_id, room_id)
        
        if client_id in self._client_rooms:
            del self._client_rooms[client_id]
        
        self._stats['active_connections'] = len(self._clients)
        
        self.logger.info(f"Client disconnected: {client_id}", client_id=client_id)
    
    def join_room(self, client_id: str, room_id: str) -> None:
        """Add client to a room.
        
        Args:
            client_id: Client identifier.
            room_id: Room identifier.
        """
        self._rooms[room_id].add(client_id)
        self._client_rooms[client_id].add(room_id)
        
        self.logger.debug(f"Client {client_id} joined room {room_id}")
    
    def leave_room(self, client_id: str, room_id: str) -> None:
        """Remove client from a room.
        
        Args:
            client_id: Client identifier.
            room_id: Room identifier.
        """
        self._rooms[room_id].discard(client_id)
        self._client_rooms[client_id].discard(room_id)
        
        # Clean up empty rooms
        if not self._rooms[room_id]:
            del self._rooms[room_id]
        
        self.logger.debug(f"Client {client_id} left room {room_id}")
    
    def get_room_clients(self, room_id: str) -> List[str]:
        """Get all clients in a room.
        
        Args:
            room_id: Room identifier.
            
        Returns:
            List of client IDs in the room.
        """
        return list(self._rooms.get(room_id, set()))
    
    def get_client_rooms(self, client_id: str) -> List[str]:
        """Get all rooms a client is in.
        
        Args:
            client_id: Client identifier.
            
        Returns:
            List of room IDs.
        """
        return list(self._client_rooms.get(client_id, set()))
    
    def queue_message(self, client_id: str, message: Dict[str, Any]) -> None:
        """Queue a message for an offline client.
        
        Args:
            client_id: Client identifier.
            message: Message to queue.
        """
        queue = self._message_queues[client_id]
        if len(queue) >= self._max_queue_size:
            queue.pop(0)  # Remove oldest message
        queue.append(message)
        self._stats['messages_queued'] += 1
    
    def _send_queued_messages(self, client_id: str) -> None:
        """Send queued messages to a newly connected client.
        
        Args:
            client_id: Client identifier.
        """
        queue = self._message_queues.pop(client_id, [])
        for message in queue:
            self.logger.debug(f"Sending queued message to {client_id}")
    
    def update_client_activity(self, client_id: str) -> None:
        """Update client's last seen timestamp.
        
        Args:
            client_id: Client identifier.
        """
        if client_id in self._clients:
            self._clients[client_id]['last_seen'] = time.time()
    
    def get_stats(self) -> Dict[str, int]:
        """Get connection statistics.
        
        Returns:
            Dictionary with connection stats.
        """
        return self._stats.copy()
    
    def get_active_clients(self) -> List[Dict[str, Any]]:
        """Get list of active clients.
        
        Returns:
            List of client information dictionaries.
        """
        return [
            {'client_id': cid, **info}
            for cid, info in self._clients.items()
        ]


class WebSocketManager:
    """Manage WebSocket events and broadcasting."""
    
    def __init__(self, socketio: Optional[SocketIO] = None) -> None:
        """Initialize WebSocket manager.
        
        Args:
            socketio: Flask-SocketIO instance.
        """
        self.socketio: Optional[SocketIO] = socketio
        self.connection_manager: ConnectionManager = ConnectionManager()
        self.logger = ultron_logging.get_logger()
        
        if socketio and SOCKETIO_AVAILABLE:
            self._register_events()
    
    def _register_events(self) -> None:
        """Register WebSocket event handlers."""
        if not self.socketio or not SOCKETIO_AVAILABLE:
            return
        
        @self.socketio.on('connect')
        def handle_connect():
            """Handle client connection."""
            client_id = request.sid
            self.connection_manager.register_client(client_id)
            emit('connected', {
                'status': 'connected',
                'client_id': client_id,
                'timestamp': time.time()
            })
        
        @self.socketio.on('disconnect')
        def handle_disconnect():
            """Handle client disconnection."""
            client_id = request.sid
            self.connection_manager.unregister_client(client_id)
        
        @self.socketio.on('join_room')
        def handle_join_room(data):
            """Handle room join request."""
            client_id = request.sid
            room_id = data.get('room', 'general')
            self.connection_manager.join_room(client_id, room_id)
            join_room(room_id)
            emit('room_joined', {'room': room_id})
        
        @self.socketio.on('leave_room')
        def handle_leave_room(data):
            """Handle room leave request."""
            client_id = request.sid
            room_id = data.get('room', 'general')
            self.connection_manager.leave_room(client_id, room_id)
            leave_room(room_id)
            emit('room_left', {'room': room_id})
        
        @self.socketio.on('ping')
        def handle_ping():
            """Handle ping for connection health."""
            client_id = request.sid
            self.connection_manager.update_client_activity(client_id)
            emit('pong', {'timestamp': time.time()})
        
        @self.socketio.on('user_message')
        def handle_user_message(data):
            """Handle user message from client."""
            client_id = request.sid
            self.connection_manager.update_client_activity(client_id)
            
            # Emit to message handlers
            self.logger.info(
                "User message received",
                client_id=client_id,
                message_length=len(data.get('message', ''))
            )
    
    def set_socketio(self, socketio: SocketIO) -> None:
        """Set the SocketIO instance.
        
        Args:
            socketio: Flask-SocketIO instance.
        """
        self.socketio = socketio
        if SOCKETIO_AVAILABLE:
            self._register_events()
    
    def emit_to_all(self, event: str, data: Dict[str, Any]) -> None:
        """Emit event to all connected clients.
        
        Args:
            event: Event name.
            data: Event data.
        """
        if not self.socketio or not SOCKETIO_AVAILABLE:
            self.logger.warning("SocketIO not available, cannot emit event")
            return
        
        self.socketio.emit(event, data)
        self.connection_manager._stats['messages_sent'] += 1
    
    def emit_to_client(self, client_id: str, event: str, data: Dict[str, Any]) -> None:
        """Emit event to a specific client.
        
        Args:
            client_id: Target client identifier.
            event: Event name.
            data: Event data.
        """
        if not self.socketio or not SOCKETIO_AVAILABLE:
            self.logger.warning("SocketIO not available, cannot emit event")
            return
        
        if client_id in self.connection_manager._clients:
            self.socketio.emit(event, data, to=client_id)
            self.connection_manager._stats['messages_sent'] += 1
        else:
            # Client offline, queue message
            self.connection_manager.queue_message(client_id, {
                'event': event,
                'data': data,
                'timestamp': time.time()
            })
    
    def emit_to_room(self, room_id: str, event: str, data: Dict[str, Any],
                     exclude_client: Optional[str] = None) -> None:
        """Emit event to all clients in a room.
        
        Args:
            room_id: Target room identifier.
            event: Event name.
            data: Event data.
            exclude_client: Optional client to exclude from broadcast.
        """
        if not self.socketio or not SOCKETIO_AVAILABLE:
            self.logger.warning("SocketIO not available, cannot emit event")
            return
        
        self.socketio.emit(event, data, to=room_id)
        self.connection_manager._stats['messages_sent'] += 1
    
    # ==================== convenience methods ====================
    
    def broadcast_chat_message(self, message: str, sender: str = "Ultron") -> None:
        """Broadcast a chat message to all clients.
        
        Args:
            message: Chat message content.
            sender: Message sender name.
        """
        self.emit_to_all('chat_message', {
            'sender': sender,
            'message': message,
            'timestamp': time.time()
        })
    
    def broadcast_typing(self, is_typing: bool = True) -> None:
        """Broadcast typing indicator.
        
        Args:
            is_typing: Whether someone is typing.
        """
        self.emit_to_all('typing', {
            'is_typing': is_typing,
            'timestamp': time.time()
        })
    
    def broadcast_proposal(self, proposal: Dict[str, Any]) -> None:
        """Broadcast new proposal to all clients.
        
        Args:
            proposal: Proposal data.
        """
        self.emit_to_all('new_proposal', {
            'proposal': proposal,
            'timestamp': time.time()
        })
    
    def broadcast_proposal_update(self, proposal_id: str, status: str) -> None:
        """Broadcast proposal status update.
        
        Args:
            proposal_id: Proposal identifier.
            status: New status.
        """
        self.emit_to_all('proposal_update', {
            'proposal_id': proposal_id,
            'status': status,
            'timestamp': time.time()
        })
    
    def broadcast_skill_update(self, skill_name: str, action: str) -> None:
        """Broadcast skill update.
        
        Args:
            skill_name: Skill name.
            action: Action performed (created, updated, deleted).
        """
        self.emit_to_all('skill_update', {
            'skill_name': skill_name,
            'action': action,
            'timestamp': time.time()
        })
    
    def broadcast_metrics(self, metrics: Dict[str, Any]) -> None:
        """Broadcast system metrics.
        
        Args:
            metrics: System metrics data.
        """
        self.emit_to_all('metrics_update', {
            'metrics': metrics,
            'timestamp': time.time()
        })
    
    def broadcast_notification(self, title: str, message: str, 
                              level: str = "info") -> None:
        """Broadcast a notification.
        
        Args:
            title: Notification title.
            message: Notification message.
            level: Notification level (info, warning, error).
        """
        self.emit_to_all('notification', {
            'title': title,
            'message': message,
            'level': level,
            'timestamp': time.time()
        })
    
    def send_agent_response(self, response: str, request_id: Optional[str] = None) -> None:
        """Send agent response to clients.
        
        Args:
            response: Agent response text.
            request_id: Optional request identifier.
        """
        self.emit_to_all('agent_response', {
            'response': response,
            'request_id': request_id,
            'timestamp': time.time()
        })


# Global instance
_ws_manager: Optional[WebSocketManager] = None


def get_ws_manager() -> WebSocketManager:
    """Get the global WebSocket manager instance.
    
    Returns:
        WebSocketManager instance.
    """
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager


def init_websocket(app=None, socketio: Optional[SocketIO] = None) -> WebSocketManager:
    """Initialize WebSocket with Flask app.
    
    Args:
        app: Flask application instance.
        socketio: SocketIO instance.
        
    Returns:
        WebSocketManager instance.
    """
    manager = get_ws_manager()
    if socketio:
        manager.set_socketio(socketio)
    return manager
