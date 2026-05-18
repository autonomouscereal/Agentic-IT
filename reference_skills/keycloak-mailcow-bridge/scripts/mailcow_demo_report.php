<?php
// Hidden endpoint used by the Roundcube Report Phish plugin.
// It records reported-message evidence in Mailcow quarantine and submits the
// work item to the Agentic Operations intake flow.

error_reporting(E_ERROR);
require_once __DIR__ . '/inc/vars.inc.php';

$dashboard_base = rtrim(getenv('DASHBOARD_API_BASE') ?: 'http://127.0.0.1:25480', '/');
$expected_token = getenv('REPORT_PHISH_TOKEN') ?: '';

function respond_json($status, $payload) {
  http_response_code($status);
  header('Content-Type: application/json');
  echo json_encode($payload);
  exit;
}

function pdo_connect_report() {
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

function post_json_report($url, $payload) {
  $ch = curl_init($url);
  curl_setopt_array($ch, array(
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_POST => true,
    CURLOPT_HTTPHEADER => array('Content-Type: application/json'),
    CURLOPT_POSTFIELDS => json_encode($payload),
    CURLOPT_TIMEOUT => 20,
  ));
  $body = curl_exec($ch);
  $status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
  $err = curl_error($ch);
  curl_close($ch);
  if ($body === false || $status >= 400) {
    return array('ok' => false, 'status' => $status, 'error' => $err ?: $body);
  }
  $decoded = json_decode($body, true);
  return is_array($decoded) ? array('ok' => true, 'data' => $decoded) : array('ok' => true, 'data' => array());
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
  respond_json(405, array('ok' => false, 'error' => 'method_not_allowed'));
}

$provided_token = $_SERVER['HTTP_X_REPORT_PHISH_TOKEN'] ?? '';
if ($expected_token === '' || !hash_equals($expected_token, $provided_token)) {
  respond_json(401, array('ok' => false, 'error' => 'unauthorized'));
}

$payload = json_decode(file_get_contents('php://input'), true);
if (!is_array($payload)) {
  respond_json(400, array('ok' => false, 'error' => 'invalid_json'));
}

$recipient = trim((string)($payload['mailbox'] ?? ''));
$sender = trim((string)($payload['sender'] ?? 'unknown'));
$subject = trim((string)($payload['subject'] ?? '(no subject)'));
$message_id = trim((string)($payload['message_id'] ?? ''));
$raw = (string)($payload['raw'] ?? '');

if ($recipient === '') {
  respond_json(400, array('ok' => false, 'error' => 'missing_mailbox'));
}
if ($message_id === '') {
  $message_id = '<roundcube-report-' . bin2hex(random_bytes(8)) . '@mailcow.local>';
}
if ($raw === '') {
  $raw = "From: {$sender}\r\nTo: {$recipient}\r\nSubject: {$subject}\r\nMessage-ID: {$message_id}\r\n\r\n";
}

$qid = substr(hash('sha256', $message_id . '|' . microtime(true)), 0, 32);

try {
  $pdo = pdo_connect_report();
  $stmt = $pdo->prepare(
    'INSERT INTO quarantine (id, orig_to, qhash, qsubject, qfrom, qdate, qsize, qaction, qreason, qscanner, qdata)
     VALUES (?, ?, ?, ?, ?, NOW(), ?, ?, ?, ?, ?)'
  );
  $stmt->execute(array(
    $qid,
    $recipient,
    $qid,
    $subject,
    $sender,
    (string)strlen($raw),
    'reject',
    'reported_phish',
    'roundcube-report-phish',
    $raw,
  ));

  $ticket_text = "User clicked the Roundcube Report Phish button.\n\n"
    . "Mailbox: {$recipient}\n"
    . "Sender: {$sender}\n"
    . "Subject: {$subject}\n"
    . "Message-ID: {$message_id}\n"
    . "Mailcow quarantine id: {$qid}\n\n"
    . "Requested workflow: validate the reported message, preserve evidence, verify Mailcow quarantine visibility, "
    . "sync to the ticket provider when available, and complete approval-gated follow-up actions.";
  $intake = post_json_report($dashboard_base . '/api/intake/submit', array(
    'title' => 'Reported phishing email: ' . $subject,
    'message' => $ticket_text,
    'requester_name' => $recipient,
    'requester_email' => $recipient,
    'channel' => 'mailcow-roundcube-report-phish',
    'category' => 'phishing',
    'sync_provider' => true,
    'auto_assign' => true,
    'attachments' => array(array(
      'filename' => 'reported-message.eml',
      'content_type' => 'message/rfc822',
      'storage_ref' => 'mailcow-quarantine://' . $qid,
      'size_bytes' => strlen($raw),
      'metadata' => array(
        'message_id' => $message_id,
        'mailcow_quarantine_id' => $qid,
        'sender' => $sender,
        'recipient' => $recipient,
      ),
    )),
  ));

  respond_json(200, array(
    'ok' => true,
    'quarantine_id' => $qid,
    'message_id' => $message_id,
    'intake' => $intake,
  ));
} catch (Throwable $exc) {
  respond_json(500, array('ok' => false, 'error' => 'report_failed'));
}
