<?php
/**
 * Agent Relay — Configuration
 *
 * Copy this file to config.php and edit the values below.
 * If you skip this step, config.php will be auto-generated on first run
 * with a random token.
 *
 * AGENT_RELAY_TOKEN environment variable, if set, takes precedence over
 * the token defined here.
 */
return [
    // Shared secret for Bearer token authentication.
    // Generate one with: php -r "echo bin2hex(random_bytes(32)) . PHP_EOL;"
    'token'    => 'CHANGE_ME',

    // Directory where peer and message JSON files are stored.
    // Must be writable by the web server process.
    'data_dir' => __DIR__ . '/data',
];
