<?php
// Lab webmail surface for the Agentic Operations Mailcow demo.
// Uses Mailcow IMAP/SMTP for real local mail and writes reported messages to
// the Mailcow quarantine table so the admin UI has visible remediation evidence.

error_reporting(E_ERROR);
session_start();

require_once __DIR__ . '/inc/vars.inc.php';

$imap_host = getenv('DEMO_WEBMAIL_IMAP_HOST') ?: '127.0.0.1';
$imap_port = getenv('DEMO_WEBMAIL_IMAP_PORT') ?: '143';
$smtp_host = getenv('DEMO_WEBMAIL_SMTP_HOST') ?: '127.0.0.1';
$smtp_port = getenv('DEMO_WEBMAIL_SMTP_PORT') ?: '25';
$dashboard_base = rtrim(getenv('DASHBOARD_API_BASE') ?: 'http://127.0.0.1:25480', '/');

function h($value) {
  return htmlspecialchars((string)$value, ENT_QUOTES, 'UTF-8');
}

function pdo_connect_demo() {
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

function imap_mailbox($folder = 'INBOX') {
  global $imap_host, $imap_port;
  return '{' . $imap_host . ':' . $imap_port . '/imap/notls}' . $folder;
}

function imap_open_demo($folder = 'INBOX') {
  if (empty($_SESSION['webmail_user']) || empty($_SESSION['webmail_pass'])) {
    return false;
  }
  return @imap_open(imap_mailbox($folder), $_SESSION['webmail_user'], $_SESSION['webmail_pass']);
}

function smtp_read_line($fp) {
  $line = '';
  while (($part = fgets($fp, 515)) !== false) {
    $line .= $part;
    if (strlen($part) >= 4 && $part[3] === ' ') {
      break;
    }
  }
  return $line;
}

function smtp_cmd($fp, $cmd, $expect_prefix = null) {
  if ($cmd !== null) {
    fwrite($fp, $cmd . "\r\n");
  }
  $response = smtp_read_line($fp);
  if ($expect_prefix !== null && substr($response, 0, strlen($expect_prefix)) !== $expect_prefix) {
    throw new Exception('SMTP command failed');
  }
  return $response;
}

function smtp_send_demo($from, $to, $subject, $body) {
  global $smtp_host, $smtp_port;
  $fp = fsockopen($smtp_host, (int)$smtp_port, $errno, $errstr, 15);
  if (!$fp) {
    throw new Exception('SMTP connection failed');
  }
  smtp_cmd($fp, null, '220');
  smtp_cmd($fp, 'HELO mailcow-demo.local', '250');
  smtp_cmd($fp, 'MAIL FROM:<' . $from . '>', '250');
  foreach (preg_split('/[,;\s]+/', $to, -1, PREG_SPLIT_NO_EMPTY) as $recipient) {
    smtp_cmd($fp, 'RCPT TO:<' . $recipient . '>', '250');
  }
  smtp_cmd($fp, 'DATA', '354');
  $message_id = '<demo-webmail-' . bin2hex(random_bytes(8)) . '@mailcow.local>';
  $headers = array(
    'From: ' . $from,
    'To: ' . $to,
    'Subject: ' . str_replace(array("\r", "\n"), ' ', $subject),
    'Message-ID: ' . $message_id,
    'Date: ' . date(DATE_RFC2822),
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=UTF-8',
  );
  $safe_body = preg_replace('/^\./m', '..', $body);
  fwrite($fp, implode("\r\n", $headers) . "\r\n\r\n" . $safe_body . "\r\n.\r\n");
  smtp_read_line($fp);
  smtp_cmd($fp, 'QUIT');
  fclose($fp);
  return $message_id;
}

function post_json($url, $payload) {
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

function report_message($msgno) {
  global $dashboard_base;
  $imap = imap_open_demo('INBOX');
  if (!$imap) {
    throw new Exception('IMAP login expired');
  }
  $overview = imap_fetch_overview($imap, (string)$msgno, 0);
  if (!$overview) {
    throw new Exception('Message not found');
  }
  $item = $overview[0];
  $headers = imap_fetchheader($imap, $msgno, FT_PREFETCHTEXT);
  $body = imap_body($imap, $msgno, FT_PEEK);
  $raw = $headers . "\r\n" . $body;
  $message_id = trim((string)($item->message_id ?? ''));
  if ($message_id === '') {
    $message_id = '<mailcow-demo-' . bin2hex(random_bytes(8)) . '@mailcow.local>';
  }
  $qid = substr(hash('sha256', $message_id . '|' . microtime(true)), 0, 32);
  $sender = trim((string)($item->from ?? 'unknown'));
  $recipient = $_SESSION['webmail_user'];
  $subject = trim((string)($item->subject ?? '(no subject)'));

  $pdo = pdo_connect_demo();
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
    'demo-webmail',
    $raw,
  ));

  @imap_createmailbox($imap, imap_utf7_encode(imap_mailbox('Junk')));
  @imap_mail_copy($imap, (string)$msgno, 'Junk');
  imap_setflag_full($imap, (string)$msgno, '\\Seen');
  imap_close($imap);

  $ticket_text = "User clicked the Mailcow webmail Report Phish button.\n\n"
    . "Mailbox: {$recipient}\n"
    . "Sender: {$sender}\n"
    . "Subject: {$subject}\n"
    . "Message-ID: {$message_id}\n"
    . "Mailcow quarantine id: {$qid}\n\n"
    . "Requested workflow: validate the reported message, preserve evidence, verify Mailcow quarantine visibility, "
    . "sync to the ticket provider when available, and complete approval-gated follow-up actions.";
  $intake = post_json($dashboard_base . '/api/intake/submit', array(
    'title' => 'Reported phishing email: ' . $subject,
    'message' => $ticket_text,
    'requester_name' => $recipient,
    'requester_email' => $recipient,
    'channel' => 'mailcow-webmail-report-phish',
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
  return array(
    'qid' => $qid,
    'message_id' => $message_id,
    'sender' => $sender,
    'subject' => $subject,
    'intake' => $intake,
  );
}

$flash = null;
$error = null;

try {
  if (($_POST['action'] ?? '') === 'login') {
    $user = trim((string)($_POST['user'] ?? ''));
    $pass = (string)($_POST['pass'] ?? '');
    $imap = @imap_open(imap_mailbox('INBOX'), $user, $pass);
    if (!$imap) {
      throw new Exception('Mailbox login failed');
    }
    imap_close($imap);
    $_SESSION['webmail_user'] = $user;
    $_SESSION['webmail_pass'] = $pass;
    header('Location: /webmail');
    exit;
  }
  if (($_POST['action'] ?? '') === 'logout') {
    session_destroy();
    header('Location: /webmail');
    exit;
  }
  if (($_POST['action'] ?? '') === 'send') {
    if (empty($_SESSION['webmail_user'])) {
      throw new Exception('Login required');
    }
    $message_id = smtp_send_demo($_SESSION['webmail_user'], trim((string)$_POST['to']), trim((string)$_POST['subject']), (string)$_POST['body']);
    $flash = 'Message sent through Mailcow SMTP: ' . $message_id;
  }
  if (($_POST['action'] ?? '') === 'report') {
    $result = report_message((int)$_POST['msgno']);
    $ticket = $result['intake']['data']['ticket']['id'] ?? null;
    $change = $result['intake']['data']['change_id'] ?? null;
    $agent = $result['intake']['data']['auto_assignment']['agent_id'] ?? null;
    $bits = array('Mailcow quarantine id ' . $result['qid']);
    if ($ticket) { $bits[] = 'ticket #' . $ticket; }
    if ($change) { $bits[] = 'approval gate #' . $change; }
    if ($agent) { $bits[] = 'agent #' . $agent; }
    $flash = 'Reported phishing message. ' . implode(', ', $bits) . '.';
  }
} catch (Throwable $e) {
  $error = $e->getMessage();
}

$logged_in = !empty($_SESSION['webmail_user']);
$messages = array();
if ($logged_in) {
  $imap = imap_open_demo('INBOX');
  if ($imap) {
    $ids = imap_search($imap, 'ALL');
    if ($ids) {
      rsort($ids);
      foreach (array_slice($ids, 0, 40) as $id) {
        $ov = imap_fetch_overview($imap, (string)$id, 0);
        if ($ov) {
          $messages[] = array('msgno' => $id, 'overview' => $ov[0]);
        }
      }
    }
    imap_close($imap);
  } else {
    $error = 'IMAP session failed; log out and back in.';
  }
}
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mailcow Demo Webmail</title>
  <style>
    :root { color-scheme: dark; --bg:#071013; --panel:#0e1a1f; --line:#24424a; --text:#e8f2f4; --muted:#9fb5bb; --accent:#42d392; --warn:#ffc857; --bad:#ff6b6b; }
    body { margin:0; font:14px/1.45 system-ui,Segoe UI,sans-serif; background:var(--bg); color:var(--text); }
    header, main { max-width:1180px; margin:0 auto; padding:20px; }
    header { display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid var(--line); }
    h1 { font-size:22px; margin:0; letter-spacing:0; }
    h2 { font-size:16px; margin:24px 0 10px; color:#cfe8ed; }
    .muted { color:var(--muted); }
    .panel { border:1px solid var(--line); background:var(--panel); padding:16px; border-radius:8px; margin-top:16px; }
    input, textarea { width:100%; box-sizing:border-box; padding:10px; margin:6px 0 12px; color:var(--text); background:#091418; border:1px solid var(--line); border-radius:6px; }
    textarea { min-height:110px; resize:vertical; }
    button { border:0; border-radius:6px; padding:9px 12px; background:#23424a; color:var(--text); cursor:pointer; }
    button.primary { background:var(--accent); color:#062017; font-weight:700; }
    button.warn { background:var(--warn); color:#211800; font-weight:700; }
    table { width:100%; border-collapse:collapse; table-layout:fixed; }
    th, td { border-bottom:1px solid var(--line); padding:10px; text-align:left; vertical-align:top; overflow-wrap:anywhere; }
    th { color:#b8d4da; font-size:12px; text-transform:uppercase; }
    .ok { border-left:4px solid var(--accent); }
    .err { border-left:4px solid var(--bad); }
    .actions { width:150px; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Mailcow Demo Webmail</h1>
      <div class="muted">Local IMAP/SMTP with Report Phish -> Agentic Operations intake -> Mailcow quarantine evidence</div>
    </div>
    <?php if ($logged_in): ?>
      <form method="post"><input type="hidden" name="action" value="logout"><button>Log out <?= h($_SESSION['webmail_user']) ?></button></form>
    <?php endif; ?>
  </header>
  <main>
    <?php if ($flash): ?><div class="panel ok"><?= h($flash) ?></div><?php endif; ?>
    <?php if ($error): ?><div class="panel err"><?= h($error) ?></div><?php endif; ?>

    <?php if (!$logged_in): ?>
      <form class="panel" method="post">
        <input type="hidden" name="action" value="login">
        <h2>Mailbox Login</h2>
        <label>Email</label>
        <input name="user" placeholder="demo_account_1@mailcow.local" autocomplete="username" required>
        <label>Password</label>
        <input name="pass" type="password" autocomplete="current-password" required>
        <button class="primary" type="submit">Log in</button>
      </form>
    <?php else: ?>
      <section class="panel">
        <h2>Compose Local Test Email</h2>
        <form method="post">
          <input type="hidden" name="action" value="send">
          <label>To</label>
          <input name="to" value="<?= h($_SESSION['webmail_user']) ?>" required>
          <label>Subject</label>
          <input name="subject" value="Demo phishing lure <?= h(date('H:i:s')) ?>" required>
          <label>Body</label>
          <textarea name="body">Please review this urgent portal notice: https://login-update.example.invalid/session</textarea>
          <button class="primary" type="submit">Send Through Mailcow</button>
        </form>
      </section>

      <section class="panel">
        <h2>Inbox</h2>
        <?php if (!$messages): ?>
          <p class="muted">No messages in INBOX yet. Send a local test email above and refresh.</p>
        <?php else: ?>
          <table>
            <thead><tr><th>From</th><th>Subject</th><th>Date</th><th class="actions">Action</th></tr></thead>
            <tbody>
              <?php foreach ($messages as $row): $ov = $row['overview']; ?>
                <tr>
                  <td><?= h($ov->from ?? '') ?></td>
                  <td><?= h($ov->subject ?? '(no subject)') ?></td>
                  <td><?= h($ov->date ?? '') ?></td>
                  <td>
                    <form method="post">
                      <input type="hidden" name="action" value="report">
                      <input type="hidden" name="msgno" value="<?= h($row['msgno']) ?>">
                      <button class="warn" type="submit">Report Phish</button>
                    </form>
                  </td>
                </tr>
              <?php endforeach; ?>
            </tbody>
          </table>
        <?php endif; ?>
      </section>
    <?php endif; ?>
  </main>
</body>
</html>
