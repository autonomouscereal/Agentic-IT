---
name: report-phish
description: >
  Phishing email reporting system for internal Mailcow SMTP delivery with optional
  Wazuh SIEM alert forwarding. Supports InternalEmailBackend with modular SIEM connector
  (Wazuh or Null), dual-path alert forwarding, and complete fault tolerance.
  Use when reporting phishing emails, configuring the report-phish backend,
  integrating SIEM alerting with email reports, or testing the phishing pipeline.
when_to_use: >
  Report phishing email, configure report-phish backend, SIEM alert forwarding,
  InternalEmailBackend, phishing report testing, case management integration,
  email client integration (Outlook/Gmail add-on).
disable-model-invocation: false
user-invocable: true
argument-hint: "optional: wazuh|null|status"
---

# Report Phish Skill

**Version:** 2.0 | **Last Updated:** 2026-04-29

---

## Overview

Phishing email reporting system that delivers reports via internal Mailcow SMTP with optional Wazuh SIEM alert forwarding. The system supports:

- **Internal Email Routing**: Sends phishing reports to internal security teams via Mailcow SMTP
- **Modular SIEM Integration**: Wazuh connector with dual-path forwarding (API + syslog UDP) or NullConnector for SIEM-free deployments
- **Optional Case Management**: Creates tickets in external case management systems if configured
- **Email Client Integration**: Works with Outlook, Gmail, and other email clients

## Current Validation Notes

Latest platform bridge rerun, verified 2026-05-13 UTC:

- Summary file on AI server:
  `/tmp/platform_full_test_summary_20260512_232845.txt`.
- Report-phish reporter/report tests: PASS.
- Report-phish SMTP sink test: PASS.
- The test SMTP sink uses `socketserver` instead of the removed stdlib
  `smtpd` module, so it works on Python 3.12+ lab hosts.
- Keep report-phish credentials in the vault or environment references; do not
  add plaintext SMTP/API secrets to skills, docs, `.env`, examples, or tests.

$ARGUMENTS

---

## Quick Start

### Installation

```bash
pip install report-phish
```

Or use directly from the skill directory:

```python
import sys
sys.path.insert(0, "C:/Users/cereal/.agents/skills/report-phish")
from backends.internal_email import InternalEmailBackend
```

---

## Backend: Internal Email

The internal email backend sends phishing reports to configured distribution groups via SMTP.

### Configuration

```python
from report_phish.backends.internal_email import InternalEmailBackend

backend = InternalEmailBackend({
    "host": "localhost",           # Mailcow SMTP host
    "port": 25,                    # SMTP port
    "use_tls": False,              # Use STARTTLS (True/False)
    "from_email": "noreply@company.com",
    "phishing_dist_group": "security-team@company.com",
    "incident_dist_group": "soc-incident@company.com",  # Optional CC
    "create_cases": True,          # Enable case creation
    "case_api_url": "https://your-case-system/api",
    "case_api_key": "your-api-key-here"
})
```

### Usage

```python
# Report a phishing email
result = backend.report({
    "headers": {
        "from": "attacker@example.com",
        "to": "victim@company.com",
        "subject": "Urgent: Account Locked!",
        "date": "2026-04-24 12:00:00",
        "Received-SPF": "fail"
    },
    "body": "Click this link to unlock your account: http://evil.com/...",
    "subject": "Urgent: Account Locked!",
    "message_id": "<unique-id@company.com>"
})

print(f"Success: {result['success']}")
print(f"Message: {result['message']}")
```

### Output Format

```json
{
  "success": true,
  "message": "Internal phishing report sent to security-team@company.com",
  "backend": "internal_email",
  "email_id": "<unique-id@company.com>",
  "timestamp": 1745500800.0,
  "distribution_group": "security-team@company.com",
  "case_created": false
}
```

---

## Integration Examples

### Outlook Add-in (VBA)

```vba
Sub ReportPhishing()
    Dim mail As MailItem
    Set mail = ActiveInspector.CurrentItem
    
    ' Convert to MIME format and send via SMTP
    Dim backend As Object
    Set backend = CreateObject("Scripting.FileSystemObject")
    
    ' Note: VBA requires COM wrapper for Python
    ' Consider using PowerShell script instead
End Sub
```

### Gmail Add-on (JavaScript)

```javascript
function reportPhishing(emailData) {
  return fetch('http://localhost:23456/report', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      headers: emailData.headers,
      body: emailData.body,
      subject: emailData.subject
    })
  }).then(response => response.json());
}
```

### PowerShell Script

```powershell
# Use Python via CLI for Outlook integration
python "C:\Users\cereal\.agents\skills\report-phish\cli.py" `
  --host localhost `
  --port 25 `
  --dist-group security-team@company.com `
  --subject $Subject `
  --from $From `
  --body $Body
```

---

## Full Email Header Format

When reporting, the full email headers should be included:

```
Return-Path: <attacker@example.com>
Received: from mail.example.com (mail.example.com [192.0.2.1])
    by your-server.company.com with ESMTPS id ABC123
    for <victim@company.com>;
    Thu, 24 Apr 2026 12:00:00 +0000 (UTC)
Authentication-Results: company.com;
    dkim=neutral (no signature) header.d=example.com header.s=default header.b="abc123";
    spf=fail (company.com: domain of attacker@example.com does not designate 192.0.2.1 as permitted sender) smtp.mailfrom=attacker@example.com;
    dmarc=fail (p=none dis=none) header.from=example.com
From: "Support" <attacker@example.com>
To: victim@company.com
Subject: Urgent: Account Locked!
Date: Thu, 24 Apr 2026 12:00:00 +0000
Message-ID: <abc123@example.com>

Click this link to unlock your account: http://evil.com/...
```

---

## Case Management Integration

When `create_cases` is enabled, the backend will create cases in your reporting system:

```python
backend = InternalEmailBackend({
    "host": "localhost",
    "port": 25,
    "phishing_dist_group": "security-team@company.com",
    "incident_dist_group": "soc-incident@company.com",
    "create_cases": True,
    "case_api_url": "https://thehive.example.com/api",
    "case_api_key": "your-api-key"
})

result = backend.report(email_data)
# Returns case_id if successful
```

**Case Data Sent:**
```json
{
  "title": "Phishing Report: Urgent: Account Locked!",
  "description": "...full report format...",
  "severity": "medium",
  "category": "phishing",
  "source": "internal_email",
  "metadata": { ...original email data... }
}
```

---

## Status Check

```python
status = backend.get_status()
print(status)
# {
#   "status": "configured",
#   "backend": "internal_email",
#   "smtp_host": "localhost",
#   "smtp_port": 25,
#   "distribution_group": "security-team@company.com",
#   "create_cases": False
# }
```

---

## CLI Interface

A simple CLI is available for command-line reporting:

```bash
python -m report_phish.cli --help

# Report a phishing email from a file
python -m report_phish.cli --file phishing.eml

# Report with inline data
python -m report_phish.cli \
  --from "attacker@example.com" \
  --to "victim@company.com" \
  --subject "Test Phishing" \
  --body "This is a test"
```

---

## Configuration File

Create `report_phish.json` in your home directory:

```json
{
  "smtp_host": "localhost",
  "smtp_port": 25,
  "use_tls": false,
  "from_email": "noreply@company.com",
  "phishing_dist_group": "security-team@company.com",
  "create_cases": true,
  "case_api_url": "https://your-system/api",
  "case_api_key": "your-key"
}
```

---

## Testing

```python
# Test the backend without actually sending emails
backend = InternalEmailBackend({
    "host": "localhost",
    "port": 25,
    "phishing_dist_group": "security-team@company.com"
})

# Check if SMTP is reachable
import smtplib
try:
    with smtplib.SMTP("localhost", 25) as server:
        code, msg = server.ehlo()
        print(f"SMTP OK: {code}")
except Exception as e:
    print(f"SMTP Error: {e}")
```

---

## Integration with Mailcow

The Report Phish module is designed to work with the Mailcow email server:

1. Deploy Mailcow on `localhost` (port 25)
2. Configure internal distribution groups in your DNS/Mailcow
3. Set up case management API endpoint if desired

**Mailcow Configuration:**
- SMTP Host: `localhost`
- SMTP Port: `25`
- Distribution Groups: Configure in Mailcow admin panel

---

## Security Considerations

1. **Use TLS**: Enable STARTTLS when sending to external distribution groups
2. **API Keys**: Store API keys securely, not in version control
3. **Rate Limiting**: Implement rate limiting if reporting from user-facing apps
4. **Log Sanitization**: Remove sensitive data from logs before storage

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | April 24, 2026 | Initial release with internal email backend |
