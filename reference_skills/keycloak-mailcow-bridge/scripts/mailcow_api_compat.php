<?php
// Minimal Mailcow API compatibility shim for custom deployments.
// Handles read-only inventory and UI table endpoints when the stock Mailcow
// json_api.php returns empty bodies in a custom web/API stack.

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

function has_session_cookie() {
  return !empty($_COOKIE['MCSESSID']) || !empty($_COOKIE['PHPSESSID']);
}

function validate_api_key($pdo) {
  $key = $_SERVER['HTTP_X_API_KEY'] ?? '';
  if ($key === '') {
    if (has_session_cookie()) {
      return 'session';
    }
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

function scalar_value($pdo, $sql, $params, $default = 0) {
  $stmt = $pdo->prepare($sql);
  $stmt->execute($params);
  $value = $stmt->fetchColumn();
  return ($value === false || $value === null) ? $default : $value;
}

function read_json_body() {
  $raw = file_get_contents('php://input');
  if ($raw === false || trim($raw) === '') {
    return array();
  }
  $decoded = json_decode($raw, true);
  return is_array($decoded) ? $decoded : array();
}

function format_datetime($value) {
  if ($value === null || $value === '') {
    return '';
  }
  return (string)$value;
}

function search_domain($pdo) {
  if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
    respond(405, array('type' => 'error', 'msg' => 'method not allowed'));
  }
  $request = read_json_body();
  $draw = (int)($request['draw'] ?? 0);
  $start = max(0, (int)($request['start'] ?? 0));
  $length = (int)($request['length'] ?? 10);
  if ($length < 0 || $length > 500) {
    $length = 500;
  }
  $search = trim((string)($request['search']['value'] ?? ''));

  $total = (int)scalar_value($pdo, 'SELECT COUNT(*) FROM domain', array(), 0);
  $where = '';
  $params = array();
  if ($search !== '') {
    $where = 'WHERE domain LIKE ? OR tags LIKE ?';
    $params[] = '%' . $search . '%';
    $params[] = '%' . $search . '%';
  }
  $filtered = (int)scalar_value($pdo, "SELECT COUNT(*) FROM domain $where", $params, 0);
  $limit_sql = $length === 0 ? 'LIMIT 0' : 'LIMIT ' . (int)$length . ' OFFSET ' . (int)$start;
  $rows = fetch_rows(
    $pdo,
    "SELECT domain, active, backupmx, backup_mx, relay_domain, relay_all_recipients, relay_unknown_only, quota, max_recipients, tags, created, modified FROM domain $where ORDER BY domain $limit_sql",
    $params
  );

  $data = array();
  foreach ($rows as $row) {
    $domain = $row['domain'];
    $alias_count = (int)scalar_value($pdo, 'SELECT COUNT(*) FROM alias WHERE domain = ?', array($domain), 0);
    $mailbox_count = (int)scalar_value($pdo, 'SELECT COUNT(*) FROM mailbox WHERE domain = ?', array($domain), 0);
    $storage_used = (int)scalar_value($pdo, 'SELECT COALESCE(SUM(storage_used), 0) FROM mailbox WHERE domain = ?', array($domain), 0);
    $message_count = (int)scalar_value($pdo, 'SELECT COALESCE(SUM(message_count), 0) FROM mailbox WHERE domain = ?', array($domain), 0);
    $quota = (string)($row['quota'] ?? '0');
    $tags = trim((string)($row['tags'] ?? ''));
    $max_recipients = (int)($row['max_recipients'] ?? 0);
    $data[] = array(
      'chkbox' => '<input type="checkbox" class="form-check-input" data-id="domain" name="multi_select" value="' . htmlspecialchars($domain, ENT_QUOTES) . '" />',
      'domain_name' => $domain,
      'domain_h_name' => $domain,
      'aliases_in_domain' => $alias_count,
      'max_num_aliases_for_domain' => $max_recipients,
      'mboxes_in_domain' => $mailbox_count,
      'max_num_mboxes_for_domain' => $max_recipients,
      'quota_used_in_domain' => $storage_used,
      'max_quota_for_domain' => (int)$quota,
      'bytes_total' => $storage_used,
      'msgs_total' => $message_count,
      'aliases' => (string)$alias_count,
      'mailboxes' => (string)$mailbox_count,
      'quota' => $storage_used . '/' . $quota,
      'stats' => $message_count . '/' . $storage_used,
      'def_quota_for_mbox' => 0,
      'max_quota_for_mbox' => 0,
      'rl' => '',
      'backupmx' => (int)($row['backupmx'] ?? $row['backup_mx'] ?? 0),
      'relay_all_recipients' => (int)($row['relay_all_recipients'] ?? 0),
      'relay_unknown_only' => (int)($row['relay_unknown_only'] ?? 0),
      'domain_admins' => '',
      'created' => format_datetime($row['created'] ?? ''),
      'modified' => format_datetime($row['modified'] ?? ''),
      'tags' => $tags,
      'active' => (int)($row['active'] ?? 0),
      'action' => '<a href="/edit/domain/' . rawurlencode($domain) . '" class="btn btn-sm btn-secondary">Edit</a>',
    );
  }
  respond(200, array(
    'draw' => $draw,
    'recordsTotal' => $total,
    'recordsFiltered' => $filtered,
    'data' => $data,
  ));
}

function get_quarantine($pdo) {
  if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
    respond(405, array('type' => 'error', 'msg' => 'method not allowed'));
  }
  $rows = fetch_rows($pdo, 'SELECT id, qhash, qsubject, qfrom, orig_to, qdate, qsize, qaction, qreason, qscanner FROM quarantine ORDER BY qdate DESC LIMIT 500', array());
  $data = array();
  foreach ($rows as $row) {
    $created = strtotime((string)($row['qdate'] ?? '')) ?: 0;
    $data[] = array(
      'id' => $row['id'],
      'qid' => $row['qhash'],
      'sender' => $row['qfrom'],
      'subject' => $row['qsubject'],
      'rspamdaction' => $row['qaction'],
      'rcpt' => $row['orig_to'],
      'virus' => '',
      'score' => '',
      'notified' => '',
      'created' => $created,
      'action' => '',
    );
  }
  respond(200, $data);
}

function get_template($pdo) {
  if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
    respond(405, array('type' => 'error', 'msg' => 'method not allowed'));
  }
  $type = strtolower(trim($_GET['type'] ?? ''));
  if ($type !== 'domain' && $type !== 'mailbox') {
    respond(404, array('type' => 'error', 'msg' => 'route not found'));
  }
  $rows = fetch_rows($pdo, 'SELECT id, type, template, attributes, created, modified FROM templates WHERE type = ? ORDER BY id', array($type));
  foreach ($rows as &$row) {
    $attrs = json_decode((string)($row['attributes'] ?? '{}'), true);
    $row['attributes'] = is_array($attrs) ? $attrs : array();
  }
  respond(200, $rows);
}

try {
  $pdo = pdo_connect();
  validate_api_key($pdo);

  $action = strtolower(trim($_GET['action'] ?? ''));
  if ($action === 'search_domain') {
    search_domain($pdo);
  }
  if ($action === 'get_quarantine') {
    get_quarantine($pdo);
  }
  if ($action === 'get_template') {
    get_template($pdo);
  }

  if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
    respond(405, array('type' => 'error', 'msg' => 'method not allowed'));
  }

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
