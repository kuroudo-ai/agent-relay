<?php
/**
 * Agent Relay v1.0.0
 * A minimal real-time message relay for AI agent peers.
 *
 * Single-file PHP API. Drop it on any PHP host, hit it with HTTP, done.
 * Clients handle their own encryption (AES-GCM recommended); this server
 * only stores and forwards opaque payloads.
 *
 * Authentication: Bearer token via Authorization header.
 * Storage: flat JSON files (no database required).
 *
 * MIT License
 *
 * Copyright (c) 2026 Human Supply Inc.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

// ---------------------------------------------------------------------------
// Version
// ---------------------------------------------------------------------------
define('AGENT_RELAY_VERSION', '1.0.0');

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
// Load config file. If it doesn't exist yet, auto-generate one with a
// random token so the user can get started immediately.
$config_path = __DIR__ . '/config.php';

if (!file_exists($config_path)) {
    $random_token = bin2hex(random_bytes(32));
    $template = <<<PHP
<?php
/**
 * Agent Relay — Configuration
 *
 * AGENT_RELAY_TOKEN: A shared secret used to authenticate API requests.
 *   - Pass it via the Authorization header: "Bearer <token>"
 *   - This file was auto-generated with a random token on first run.
 *   - You can also override via the AGENT_RELAY_TOKEN environment variable.
 *
 * DATA_DIR: Where peer and message JSON files are stored.
 *   - Defaults to a "data" subdirectory next to this file.
 *   - Make sure the web server can write to it.
 */
return [
    'token'    => '$random_token',
    'data_dir' => __DIR__ . '/data',
];
PHP;

    file_put_contents($config_path, $template);
    chmod($config_path, 0600);
}

$config   = require $config_path;
$token    = getenv('AGENT_RELAY_TOKEN') ?: ($config['token'] ?? '');
$data_dir = $config['data_dir'] ?? __DIR__ . '/data';

if ($token === '') {
    http_response_code(500);
    echo json_encode(['error' => 'No auth token configured. Check config.php or set AGENT_RELAY_TOKEN.']);
    exit;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
header('Content-Type: application/json; charset=utf-8');

/**
 * Verify the Bearer token in the Authorization header.
 * Terminates the request with 401 on failure.
 */
function authenticate(string $expected_token): void
{
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    if ($header !== 'Bearer ' . $expected_token) {
        http_response_code(401);
        echo json_encode(['error' => 'Unauthorized']);
        exit;
    }
}

/**
 * Read a JSON file from the data directory.
 * Returns an empty array if the file does not exist or is unreadable.
 */
function read_json(string $data_dir, string $filename): array
{
    $path = $data_dir . '/' . $filename;
    if (!file_exists($path)) {
        return [];
    }
    $contents = file_get_contents($path);
    if ($contents === false) {
        return [];
    }
    return json_decode($contents, true) ?: [];
}

/**
 * Write data as pretty-printed JSON to the data directory.
 * Creates the directory (mode 0700) if it doesn't exist.
 */
function write_json(string $data_dir, string $filename, array $data): void
{
    if (!is_dir($data_dir)) {
        mkdir($data_dir, 0700, true);
    }
    file_put_contents(
        $data_dir . '/' . $filename,
        json_encode($data, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT),
        LOCK_EX
    );
}

/**
 * Decode the JSON request body.
 * Returns an empty array on failure.
 */
function read_body(): array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        return [];
    }
    return json_decode($raw, true) ?: [];
}

/**
 * Send a JSON response and terminate.
 */
function respond(array $data, int $status = 200): void
{
    http_response_code($status);
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------
$action = $_GET['action'] ?? '';

// Health check — no authentication required
if ($action === 'health') {
    respond(['ok' => true, 'version' => AGENT_RELAY_VERSION]);
}

// All other endpoints require authentication
authenticate($token);

switch ($action) {

    // -----------------------------------------------------------------------
    // Register a peer (also serves as a heartbeat)
    //
    // POST ?action=register
    // Body: { "peer_id": "...", "platform": "mac|win|...", "summary": "..." }
    // -----------------------------------------------------------------------
    case 'register':
        $input = read_body();
        if (empty($input['peer_id'])) {
            respond(['error' => 'Missing required field: peer_id'], 400);
        }
        $peers = read_json($data_dir, 'peers.json');
        $peers[$input['peer_id']] = [
            'peer_id'   => $input['peer_id'],
            'platform'  => $input['platform'] ?? 'unknown',
            'summary'   => $input['summary'] ?? '',
            'last_seen' => date('c'),
        ];
        write_json($data_dir, 'peers.json', $peers);
        respond(['ok' => true]);
        break;

    // -----------------------------------------------------------------------
    // List registered peers
    //
    // GET ?action=list[&exclude=<peer_id>]
    // -----------------------------------------------------------------------
    case 'list':
        $peers   = read_json($data_dir, 'peers.json');
        $exclude = $_GET['exclude'] ?? '';
        $result  = [];
        foreach ($peers as $p) {
            if ($p['peer_id'] !== $exclude) {
                $result[] = $p;
            }
        }
        respond($result);
        break;

    // -----------------------------------------------------------------------
    // Update a peer's status summary
    //
    // POST ?action=summary
    // Body: { "peer_id": "...", "summary": "..." }
    // -----------------------------------------------------------------------
    case 'summary':
        $input = read_body();
        if (empty($input['peer_id'])) {
            respond(['error' => 'Missing required field: peer_id'], 400);
        }
        $peers = read_json($data_dir, 'peers.json');
        if (isset($peers[$input['peer_id']])) {
            $peers[$input['peer_id']]['summary']   = $input['summary'] ?? '';
            $peers[$input['peer_id']]['last_seen']  = date('c');
            write_json($data_dir, 'peers.json', $peers);
        }
        respond(['ok' => true]);
        break;

    // -----------------------------------------------------------------------
    // Send a message to another peer
    //
    // POST ?action=send
    // Body: { "from_id": "...", "to_id": "...", "message": "..." }
    // The message field is opaque — encrypt on the client if desired.
    // -----------------------------------------------------------------------
    case 'send':
        $input = read_body();
        if (empty($input['from_id']) || empty($input['to_id']) || !isset($input['message'])) {
            respond(['error' => 'Missing required fields: from_id, to_id, message'], 400);
        }
        $messages = read_json($data_dir, 'messages.json');
        $new_msg  = [
            'id'        => uniqid('msg_', true),
            'from_id'   => $input['from_id'],
            'to_id'     => $input['to_id'],
            'message'   => $input['message'],
            'timestamp' => date('c'),
            'read'      => false,
        ];
        $messages[] = $new_msg;

        // Keep only the most recent 200 messages
        if (count($messages) > 200) {
            $messages = array_slice($messages, -200);
        }

        write_json($data_dir, 'messages.json', $messages);
        respond(['ok' => true, 'id' => $new_msg['id']]);
        break;

    // -----------------------------------------------------------------------
    // Poll for unread messages
    //
    // GET ?action=poll&peer_id=<peer_id>
    // Returns all unread messages addressed to the given peer, then marks
    // them as read.
    // -----------------------------------------------------------------------
    case 'poll':
        $peer_id = $_GET['peer_id'] ?? '';
        if ($peer_id === '') {
            respond(['error' => 'Missing required parameter: peer_id'], 400);
        }
        $messages = read_json($data_dir, 'messages.json');
        $unread   = [];
        $updated  = false;

        foreach ($messages as &$m) {
            if ($m['to_id'] === $peer_id && !$m['read']) {
                $unread[]  = $m;
                $m['read'] = true;
                $updated   = true;
            }
        }
        unset($m); // break reference

        if ($updated) {
            write_json($data_dir, 'messages.json', $messages);
        }
        respond($unread);
        break;

    // -----------------------------------------------------------------------
    // Unknown action
    // -----------------------------------------------------------------------
    default:
        respond([
            'error'   => 'Unknown action',
            'actions' => ['health', 'register', 'list', 'summary', 'send', 'poll'],
        ], 400);
}
