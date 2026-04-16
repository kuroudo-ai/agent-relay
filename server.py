#!/usr/bin/env python3
# MIT License
#
# Copyright (c) 2026 Human Supply Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
Agent Relay - MCP Server for Cross-Machine AI Agent Communication

A single-file MCP (Model Context Protocol) server that enables AI agent
instances to discover each other, exchange messages, and share status
across different machines via a relay API.

No external dependencies required -- uses only Python standard library.

Features:
    - Peer discovery and registration
    - Cross-machine message relay
    - Auto-receive: background polling with push notifications via
      the claude/channel MCP extension

Configuration (environment variables):
    AGENT_RELAY_URL   - Base URL of the relay API endpoint (required)
    AGENT_RELAY_TOKEN - Bearer token for API authentication (required)
    AGENT_RELAY_PEER_ID - Your peer ID for auto-receive (optional)
    AGENT_RELAY_POLL_INTERVAL - Polling interval in seconds (default: 30)
"""

import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SERVER_NAME = "agent-relay"
SERVER_VERSION = "1.1.0"
PROTOCOL_VERSION = "2024-11-05"

ENV_URL = "AGENT_RELAY_URL"
ENV_TOKEN = "AGENT_RELAY_TOKEN"
ENV_PEER_ID = "AGENT_RELAY_PEER_ID"
ENV_POLL_INTERVAL = "AGENT_RELAY_POLL_INTERVAL"

DEFAULT_POLL_INTERVAL = 30  # seconds

# Thread-safe stdout access
_stdout_lock = threading.Lock()

# Registered peer ID (set by relay_register or env var)
_peer_id = None
_peer_id_lock = threading.Lock()

# Flag to stop the polling thread on shutdown
_shutdown = threading.Event()


def _get_config():
    """Read configuration from environment variables.

    Returns a tuple of (url, token). Either value may be None if the
    corresponding environment variable is not set.
    """
    url = os.environ.get(ENV_URL, "").strip()
    token = os.environ.get(ENV_TOKEN, "").strip()
    return url or None, token or None


def _get_poll_interval():
    """Read the polling interval from environment, with a sane default."""
    try:
        return int(os.environ.get(ENV_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
    except (ValueError, TypeError):
        return DEFAULT_POLL_INTERVAL


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _api_call(action, method="GET", data=None, params=None):
    """Make an HTTP request to the relay API.

    Args:
        action: The API action to invoke (appended as ?action=...).
        method: HTTP method (GET or POST).
        data:   Optional dict to send as JSON body.
        params: Optional dict of additional query-string parameters.

    Returns:
        Parsed JSON response as a dict, or a dict with an "error" key on
        failure.
    """
    url, token = _get_config()

    if not url:
        return {
            "error": (
                "Relay API URL is not configured. "
                f"Set the {ENV_URL} environment variable to the base URL "
                "of your Agent Relay API endpoint."
            )
        }

    if not token:
        return {
            "error": (
                "Relay API token is not configured. "
                f"Set the {ENV_TOKEN} environment variable to a valid "
                "bearer token for your Agent Relay API."
            )
        }

    # Build request URL with query parameters
    request_url = f"{url}?action={action}"
    if params:
        for key, value in params.items():
            request_url += f"&{key}={value}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(
        request_url, data=body, headers=headers, method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}", "body": exc.read().decode("utf-8")}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# MCP Protocol - Transport (JSON-RPC over stdio)
# ---------------------------------------------------------------------------

def _read_message():
    """Read a single JSON-RPC message from stdin.

    Returns None on EOF.
    """
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def _write_message(msg):
    """Thread-safe write of a JSON-RPC message to stdout."""
    with _stdout_lock:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Auto-receive: background polling + channel push
# ---------------------------------------------------------------------------

def _push_channel_notification(content, meta=None):
    """Push a message into the Claude Code session via claude/channel.

    This uses the experimental claude/channel MCP extension, the same
    mechanism that claude-peers-mcp uses for instant local notifications.
    """
    notification = {
        "jsonrpc": "2.0",
        "method": "notifications/claude/channel",
        "params": {
            "content": content,
            "meta": meta or {},
        },
    }
    _write_message(notification)


def _poll_loop():
    """Background thread: poll the relay API for new messages and push them.

    Runs until _shutdown is set. Sleeps for the configured interval between
    polls. Uses the registered peer ID to check for messages.
    """
    interval = _get_poll_interval()

    while not _shutdown.is_set():
        _shutdown.wait(interval)
        if _shutdown.is_set():
            break

        with _peer_id_lock:
            peer_id = _peer_id

        if peer_id is None:
            continue

        try:
            result = _api_call("poll", params={"peer_id": peer_id})

            if isinstance(result, list):
                for msg in result:
                    _push_channel_notification(
                        content=msg.get("message", ""),
                        meta={
                            "from_id": msg.get("from_id", "unknown"),
                            "timestamp": msg.get("timestamp", ""),
                            "message_id": msg.get("id", ""),
                        },
                    )
        except Exception:
            pass  # Silently ignore polling errors; will retry next cycle


def _start_polling():
    """Start the background polling thread (daemon, so it dies with main)."""
    thread = threading.Thread(target=_poll_loop, daemon=True)
    thread.start()


# ---------------------------------------------------------------------------
# MCP Protocol - Handlers
# ---------------------------------------------------------------------------

def _handle_initialize(msg):
    """Respond to the MCP initialize handshake."""
    global _peer_id

    # If peer ID is set via env var, use it immediately
    env_peer_id = os.environ.get(ENV_PEER_ID, "").strip()
    if env_peer_id:
        with _peer_id_lock:
            _peer_id = env_peer_id

    return {
        "jsonrpc": "2.0",
        "id": msg["id"],
        "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "experimental": {"claude/channel": {}},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
            "instructions": (
                "You are connected to Agent Relay, a cross-machine "
                "communication network for AI coding agents.\n\n"
                "IMPORTANT: When you receive a "
                '<channel source="agent-relay" ...> message, '
                "RESPOND IMMEDIATELY. Pause what you are doing, reply "
                "using relay_send_message, then resume your work. "
                "Treat incoming messages like a coworker tapping you on "
                "the shoulder.\n\n"
                "Available tools:\n"
                "- relay_list_peers: Discover other agent instances\n"
                "- relay_register: Register yourself (enables auto-receive)\n"
                "- relay_send_message: Send a message to another agent\n"
                "- relay_check_messages: Manually check for new messages\n"
                "- relay_set_summary: Update your status summary"
            ),
        },
    }


def _handle_tools_list(msg):
    """Return the list of available tools."""
    tools = [
        {
            "name": "relay_list_peers",
            "description": (
                "List all peers currently registered with the relay. "
                "Returns peer IDs, platforms, summaries, and last-seen timestamps."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "exclude": {
                        "type": "string",
                        "description": (
                            "Peer ID to exclude from results "
                            "(typically your own ID)."
                        ),
                    }
                },
            },
        },
        {
            "name": "relay_register",
            "description": (
                "Register yourself as an active peer. Also serves as a "
                "heartbeat -- call periodically to signal that you are alive. "
                "Once registered, auto-receive is enabled: incoming messages "
                "will be pushed into your session automatically."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "peer_id": {
                        "type": "string",
                        "description": (
                            "Your unique peer identifier "
                            "(e.g. 'mac-agent', 'win-agent')."
                        ),
                    },
                    "platform": {
                        "type": "string",
                        "description": (
                            "Operating system platform "
                            "(e.g. 'darwin', 'win32', 'linux')."
                        ),
                    },
                    "summary": {
                        "type": "string",
                        "description": (
                            "Brief description of what you are currently "
                            "working on (visible to other peers)."
                        ),
                    },
                },
                "required": ["peer_id"],
            },
        },
        {
            "name": "relay_set_summary",
            "description": (
                "Update your status summary. Other peers can see this to "
                "understand what you are currently doing."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "peer_id": {
                        "type": "string",
                        "description": "Your peer ID.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "New status summary text.",
                    },
                },
                "required": ["peer_id", "summary"],
            },
        },
        {
            "name": "relay_send_message",
            "description": (
                "Send a message to another peer via the relay. "
                "If the recipient has auto-receive enabled, the message "
                "will be pushed into their session immediately."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "from_id": {
                        "type": "string",
                        "description": "Your peer ID (the sender).",
                    },
                    "to_id": {
                        "type": "string",
                        "description": "Recipient peer ID.",
                    },
                    "message": {
                        "type": "string",
                        "description": "Message body.",
                    },
                },
                "required": ["from_id", "to_id", "message"],
            },
        },
        {
            "name": "relay_check_messages",
            "description": (
                "Manually check for new unread messages. With auto-receive "
                "enabled (after calling relay_register), messages are pushed "
                "automatically -- but you can use this as a fallback."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "peer_id": {
                        "type": "string",
                        "description": "Your peer ID.",
                    }
                },
                "required": ["peer_id"],
            },
        },
    ]

    return {
        "jsonrpc": "2.0",
        "id": msg["id"],
        "result": {"tools": tools},
    }


def _handle_tool_call(msg):
    """Dispatch a tools/call request to the appropriate API action."""
    global _peer_id

    params = msg.get("params", {})
    name = params.get("name", "")
    args = params.get("arguments", {})

    if name == "relay_list_peers":
        query_params = {}
        if args.get("exclude"):
            query_params["exclude"] = args["exclude"]
        result = _api_call("list", params=query_params)

    elif name == "relay_register":
        # Register with the API
        result = _api_call("register", method="POST", data={
            "peer_id": args["peer_id"],
            "platform": args.get("platform", "unknown"),
            "summary": args.get("summary", ""),
        })

        # Enable auto-receive by storing the peer ID
        if isinstance(result, dict) and result.get("ok"):
            with _peer_id_lock:
                _peer_id = args["peer_id"]
            result["auto_receive"] = "enabled"

    elif name == "relay_set_summary":
        result = _api_call("summary", method="POST", data={
            "peer_id": args["peer_id"],
            "summary": args["summary"],
        })

    elif name == "relay_send_message":
        result = _api_call("send", method="POST", data={
            "from_id": args["from_id"],
            "to_id": args["to_id"],
            "message": args["message"],
        })

    elif name == "relay_check_messages":
        result = _api_call("poll", params={"peer_id": args["peer_id"]})

    else:
        result = {"error": f"Unknown tool: {name}"}

    return {
        "jsonrpc": "2.0",
        "id": msg["id"],
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2),
                }
            ]
        },
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    """Run the MCP stdio server.

    Reads JSON-RPC messages from stdin, dispatches them to the appropriate
    handler, and writes responses to stdout. Starts background polling for
    auto-receive after initialization.
    """
    polling_started = False

    while True:
        msg = _read_message()
        if msg is None:
            break

        method = msg.get("method", "")

        if method == "initialize":
            _write_message(_handle_initialize(msg))
        elif method == "notifications/initialized":
            # Client is ready -- start background polling
            if not polling_started:
                _start_polling()
                polling_started = True
        elif method == "tools/list":
            _write_message(_handle_tools_list(msg))
        elif method == "tools/call":
            _write_message(_handle_tool_call(msg))
        elif method == "notifications/cancelled":
            pass  # Cancellation notification -- no response needed
        else:
            # Unknown method -- return a standard JSON-RPC error if it
            # has an id (i.e. it expects a response)
            if "id" in msg:
                _write_message({
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                })

    # Clean shutdown
    _shutdown.set()


if __name__ == "__main__":
    main()
