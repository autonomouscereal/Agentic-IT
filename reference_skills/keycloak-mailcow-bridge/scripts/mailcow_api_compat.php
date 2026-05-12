<?php
// Minimal Mailcow API compatibility shim for custom deployments.
// Handles read-only get/domain, get/mailbox, and get/alias endpoints when the
// stock Mailcow json_api.php returns empty bodies in a custom web/API stack.

error_reporting(E_ERROR);
header('Content-Type: application/json');

require_once __DIR__ . '/inc/vars.inc.php';

function respond($status, $payload) {
  http_response_code($status);
  echo json_encode($payload, JSON_UNESCAPED_SLASHES);
  exit;
}

function pdo_connect() {
  global $database_sock, $database_host, $database_name, $database_user, $database_pass;
  if (!empty($database_sock) && file_exists($database_sock)) {
    $dsn = 'mysql:unix_socket=' . $database_sock . ';dbname=' . $database_name . ';charset=utf8mb4';
  } else {
    $dsn = 'mysql:host=' . $database_host . ';dbname=' . $database_name . ';charset=utf8mb4';
  }
  return new PDO($dsn, $database_user, $database_pass, array(
    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
  ));
}

function validate_api_key($pdo) {
  $key = $_SERVER['HTTP_X_API_KEY'] ?? '';
  if ($key === '') {
    respond(401, array('type' => 'error', 'msg' => 'missing api key'));
  }
  $stmt = $pdo->prepare('SELECT access, allow_from, skip_ip_check FROM api WHERE api_key = ? AND active = 1 LIMIT 1');
  $stmt->execute(array($key));
  $row = $stmt->fetch();
  if (!$row) {
    respond(401, array('type' => 'error', 'msg' => 'invalid api key'));
  }
  if ((int)($row['skip_ip_check'] ?? 1) !== 1) {
    $remote = $_SERVER['REMOTE_ADDR'] ?? '';
    $allowed = preg_split('/[,\s]+/', (string)($row['allow_from'] ?? ''), -1, PREG_SPLIT_NO_EMPTY);
    if ($remote === '' || !in_array($remote, $allowed, true)) {
      respond(403, array('type' => 'error', 'msg' => 'api key not allowed from remote address'));
    }
  }
  return $row['access'];
}

function fetch_rows($pdo, $sql, $params) {
  $stmt = $pdo->prepare($sql);
  $stmt->execute($params);
  return $stmt->fetchAll();
}

try {
  if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
    respond(405, array('type' => 'error', 'msg' => 'method not allowed'));
  }

  $pdo = pdo_connect();
  validate_api_key($pdo);

  $resource = strtolower(trim($_GET['resource'] ?? ''));
  $selector = trim(urldecode($_GET['selector'] ?? 'all'));
  if ($selector === '') {
    $selector = 'all';
  }

  if ($resource === 'domain') {
    $fields = 'domain, active, backup_mx, relay_domain, quota, max_recipients, kind, created, modified';
    if ($selector === 'all') {
      respond(200, fetch_rows($pdo, "SELECT $fields FROM domain ORDER BY domain", array()));
    }
    respond(200, fetch_rows($pdo, "SELECT $fields FROM domain WHERE domain = ? ORDER BY domain", array($selector)));
  }

  if ($resource === 'mailbox') {
    $fields = 'username, domain, quota, email_access, active, forced_password_change, storage_used, message_count, kind, created, modified';
    if ($selector === 'all') {
      respond(200, fetch_rows($pdo, "SELECT $fields FROM mailbox ORDER BY domain, username", array()));
    }
    respond(200, fetch_rows(
      $pdo,
      "SELECT $fields FROM mailbox WHERE username = ? OR CONCAT(username, '@', domain) = ? ORDER BY domain, username",
      array($selector, $selector)
    ));
  }

  if ($resource === 'alias') {
    $fields = 'id, address, goto, domain, active, sogo_visible, is_group, is_dynamic, max_recipients, created, modified';
    if ($selector === 'all') {
      respond(200, fetch_rows($pdo, "SELECT $fields FROM alias ORDER BY domain, address", array()));
    }
    respond(200, fetch_rows($pdo, "SELECT $fields FROM alias WHERE address = ? OR domain = ? ORDER BY domain, address", array($selector, $selector)));
  }

  respond(404, array('type' => 'error', 'msg' => 'route not found'));
} catch (Throwable $e) {
  respond(500, array('type' => 'error', 'msg' => 'mailcow compatibility api failed'));
}
