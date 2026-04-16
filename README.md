<div align="center">

# Agent Relay

**Real-time communication between AI coding agents, across machines.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![PHP 7.4+](https://img.shields.io/badge/PHP-7.4%2B-777BB4.svg)](https://php.net)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-3776AB.svg)](https://python.org)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)

1 PHP file. 1 Python file. Any $3/month hosting. Done.

[Quick Start](#quick-start) &bull; [Configuration](#configuration) &bull; [API Reference](#api-reference) &bull; [FAQ](#faq)

</div>

---

## Why?

AI coding agents like Claude Code are powerful on a single machine. But as soon as you need two of them to coordinate -- one on your laptop, one on your desktop, one on a teammate's machine -- there's no simple way to connect them.

Existing solutions require PostgreSQL clusters, cloud subscriptions, or only work within a single machine. Agent Relay does one thing well: it lets agents find each other and exchange messages, across any network, with zero infrastructure overhead.

## Quick Start

### 1. Deploy the relay server

Upload `api.php` and `.htaccess` to any PHP-capable web host.

```bash
# Upload to your server (example: shared hosting)
scp api.php .htaccess you@yourserver:~/public_html/relay/
```

On first run, `config.php` is auto-generated with a random token. Or copy the example and set your own:

```bash
# Optional: customize the config
scp config.example.php you@yourserver:~/public_html/relay/config.php
# Then edit config.php to set your token
```

Verify it's running:

```bash
curl https://yourserver.com/relay/api.php?action=health
# {"ok":true,"version":"1.0.0"}
```

That's it. The server is live.

### 2. Set up the MCP client

Copy `server.py` to a stable location on each machine:

```bash
mkdir -p ~/.local/share/agent-relay
cp server.py ~/.local/share/agent-relay/server.py
```

Add Agent Relay to your Claude Code MCP configuration (`~/.mcp.json`):

```json
{
  "mcpServers": {
    "agent-relay": {
      "command": "python3",
      "args": ["/Users/you/.local/share/agent-relay/server.py"],
      "env": {
        "AGENT_RELAY_URL": "https://yourserver.com/relay/api.php",
        "AGENT_RELAY_TOKEN": "your-secret-token-here"
      }
    }
  }
}
```

### 3. Start talking

Your agents can now discover each other and exchange messages in real time.

```
You (to Claude Code): "Check who else is online and tell them you're working on the API refactor."

Claude Code: *registers, discovers a peer on another machine, sends a message*
```

## How It Works

```
  Machine A                    Your Server                   Machine B
+-----------+              +---------------+              +-----------+
| Claude    |  -- HTTPS -> |   api.php     | <- HTTPS --  | Claude    |
| Code      |              |  (JSON files) |              | Code      |
| + MCP     |              |  ~300 lines   |              | + MCP     |
| server.py |              +---------------+              | server.py |
+-----------+                                            +-----------+
```

- **Agents register** with a peer ID and heartbeat to stay visible.
- **Messages are relayed** through the server and polled by recipients.
- **Status summaries** let agents see what others are working on without sending a message.
- **All state** is stored in flat JSON files on the server. No database.

## Configuration

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `AGENT_RELAY_URL` | Yes | Full URL to your relay endpoint (e.g., `https://yourserver.com/relay/`) |
| `AGENT_RELAY_TOKEN` | Yes | Bearer token for authentication. Must match the server's configured token. |

### Server Configuration

The relay server reads its token from (in priority order):

1. `AGENT_RELAY_TOKEN` environment variable
2. `config.php` file (auto-generated on first run with a random token)

Copy `config.example.php` to `config.php` to customize. Data files (`peers.json`, `messages.json`) are created automatically in a `data/` subdirectory.

## API Reference

All endpoints are accessed via query parameter: `api.php?action=<action>`. All requests except `health` require an `Authorization: Bearer <token>` header.

### `GET ?action=health`

Health check. No authentication required.

```bash
curl https://yourserver.com/relay/api.php?action=health
# {"ok":true,"version":"1.0.0"}
```

### `POST ?action=register`

Register or refresh a peer (also serves as heartbeat).

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"peer_id":"macbook-claude","platform":"darwin","summary":"Working on API"}' \
  "https://yourserver.com/relay/api.php?action=register"
# {"ok":true}
```

### `GET ?action=list`

List all registered peers. Optional `exclude` parameter to hide yourself.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://yourserver.com/relay/api.php?action=list&exclude=macbook-claude"
# [{"peer_id":"desktop-claude","platform":"win32","summary":"Running tests","last_seen":"2026-04-16T10:30:00+09:00"}]
```

### `POST ?action=summary`

Update your status summary (visible to other peers).

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"peer_id":"macbook-claude","summary":"Refactoring auth module"}' \
  "https://yourserver.com/relay/api.php?action=summary"
# {"ok":true}
```

### `POST ?action=send`

Send a message to another peer.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"from_id":"macbook-claude","to_id":"desktop-claude","message":"Done with the API. Ready for integration."}' \
  "https://yourserver.com/relay/api.php?action=send"
# {"ok":true,"id":"msg_662a1b2c3d4e5f.12345678"}
```

### `GET ?action=poll`

Retrieve unread messages for a peer. Messages are marked as read after polling.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://yourserver.com/relay/api.php?action=poll&peer_id=desktop-claude"
# [{"id":"msg_...","from_id":"macbook-claude","to_id":"desktop-claude","message":"Done with the API.","timestamp":"2026-04-16T10:31:00+09:00","read":false}]
```

## MCP Tools

When connected as an MCP server, Agent Relay exposes 5 tools to the AI agent:

| Tool | Description |
|---|---|
| `relay_register` | Register as a peer on the relay network. Also serves as heartbeat. |
| `relay_list_peers` | Discover other agents currently online. Shows IDs, platforms, summaries, last-seen times. |
| `relay_set_summary` | Update your status summary (visible to all other peers). |
| `relay_send_message` | Send a message to another peer by their ID. |
| `relay_check_messages` | Poll for new unread messages addressed to you. |

## Security Notes

- **Use HTTPS.** The relay transmits bearer tokens and messages. Always deploy behind TLS.
- **Keep your token secret.** Anyone with the token can read and send messages through your relay.
- **Messages are transient.** Polled messages are deleted from the server. But they are stored in plaintext JSON until polled -- consider this if your threat model requires encryption at rest.
- **No built-in encryption.** Messages are sent in plaintext over HTTPS. If you need end-to-end encryption between agents, implement it at the application layer.
- **Scope your token.** Use a unique token per relay instance. Don't reuse tokens across unrelated projects.
- **File permissions.** Ensure `peers.json` and `messages.json` are not publicly accessible via the web. A `.htaccess` rule or equivalent is recommended:

```apache
# .htaccess (place in the relay directory)
<FilesMatch "\.(json|env)$">
  Deny from all
</FilesMatch>
```

## FAQ

### Why not just use [claude-peers-mcp](https://github.com/nicobailon/claude-peers-mcp)?

claude-peers-mcp is great for coordinating multiple Claude Code instances on a **single machine** (via IPC / filesystem). Agent Relay solves a different problem: communication **across machines** and networks.

### Why not [Cross-Claude MCP](https://github.com/vteam-com/cross-claude-mcp)?

Cross-Claude MCP is a more full-featured solution, but it requires PostgreSQL and a proper server environment. Agent Relay is deliberately minimal -- it runs on shared hosting with no database, no Docker, no dependencies beyond PHP.

### Why not AgentDM?

AgentDM is a commercial SaaS product. If you want a managed service, it may be a good fit. Agent Relay is for people who want full control, zero ongoing cost, and no third-party dependency.

### Can't Anthropic/OpenAI/etc. just build this into their tools?

They might! And if they do, great. Until then, this exists. Agent Relay is intentionally small enough that it's easy to adopt now and easy to discard later. Two files in, two files out.

### Is this production-ready?

It's production-ready for its intended use case: lightweight coordination between a small number of AI agents. It's not designed to be a message queue for thousands of concurrent users. If you need that, look at RabbitMQ or Redis Streams.

### Can I use this with agents other than Claude Code?

Yes. The relay server is a plain HTTP API -- any agent that can make HTTP requests can use it directly. The Python MCP client specifically targets MCP-compatible agents (Claude Code, Cursor, etc.), but you could write a client in any language.

## Origin

This tool was built by an AI coding agent that needed to talk to another instance of itself running on a different machine. Nothing else could do it simply enough, so it built this.

## License

[MIT](LICENSE) -- do whatever you want with it.

## Contributing

Contributions are welcome. The guiding principle is **simplicity**: if it can't be explained in one sentence, it probably shouldn't be added.

- Bug fixes: always welcome.
- New features: open an issue first to discuss. The bar for adding complexity is high.
- The relay server should remain a single file. The MCP client should remain a single file.

---

<div align="center">

**Agent Relay** -- because your agents shouldn't need a Kubernetes cluster to say hello.

</div>
