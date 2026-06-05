#!/usr/bin/env node
/*
 * Element/Matrix sensitive-intake proof.
 *
 * This test drives the actual user intake surface, not only direct APIs:
 *   1. login to dashboard and Element through Keycloak;
 *   2. create a Matrix-linked ticket from the bot DM;
 *   3. request protected account fields through the ticket requester-info path;
 *   4. verify Element receives a /secure-intake/ link;
 *   5. submit the secure form in the browser;
 *   6. verify dashboard ticket context contains only refs/status, not values.
 *
 * Secrets come from environment variables. Generated form values are never
 * printed and screenshots are taken before fill / after submit only.
 */

const { chromium } = require("playwright");

const dashboardUrl = (process.env.DASHBOARD_URL || "https://127.0.0.1:25443").replace(/\/$/, "");
const dashboardUser = process.env.DASHBOARD_USER || "demo_account_1";
const dashboardPassword = process.env.DASHBOARD_PASSWORD || "";
const opsChatUrl = (process.env.OPS_CHAT_URL || "https://127.0.0.1:3303").replace(/\/$/, "");
const opsChatUser = process.env.OPS_CHAT_USER || "";
const opsChatPassword = process.env.OPS_CHAT_PASSWORD || "";
const opsChatRoomId = process.env.OPS_CHAT_ROOM_ID || "";
const marker = process.env.OPS_CHAT_SENSITIVE_MARKER || `ops-chat-sensitive-${Date.now()}`;
const ignoreHttpsErrors = /^(1|true|yes|on)$/i.test(process.env.PLAYWRIGHT_IGNORE_HTTPS_ERRORS || "");
const screenshotDir = process.env.PLAYWRIGHT_SCREENSHOT_DIR || "";

function requireSecret(name, value) {
  if (!value) throw new Error(`${name} is required`);
}

async function maybeScreenshot(page, name) {
  if (!screenshotDir) return;
  await page.screenshot({ path: `${screenshotDir.replace(/[\\/]$/, "")}/${name}.png`, fullPage: true });
}

async function clickText(page, pattern, which = "first") {
  return await page.evaluate(({ source, which }) => {
    const regex = new RegExp(source, "i");
    const els = Array.from(document.querySelectorAll("button,[role='button'],a,span,div"));
    const visible = els.filter((el) => {
      const text = (el.innerText || el.textContent || "").trim();
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      return regex.test(text) && rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    });
    const target = which === "last" ? visible[visible.length - 1] : visible[0];
    if (!target) return false;
    target.click();
    return true;
  }, { source: pattern.source, which }).catch(() => false);
}

async function dismissNoise(page) {
  for (const pattern of [/Dismiss/i, /Not now/i, /Maybe later/i, /^Later$/i, /^OK$/i, /^Cancel$/i, /^Done$/i]) {
    await clickText(page, pattern, "first");
    await page.waitForTimeout(250);
  }
}

async function clearDialogs(page) {
  for (let i = 0; i < 8; i += 1) {
    const dialogText = await page.locator("#mx_Dialog_Container").innerText().catch(() => "");
    const dialogVisible = await page.locator("#mx_Dialog_Container .mx_Dialog_background, #mx_Dialog_Container [role='dialog']").first().isVisible().catch(() => false);
    if (!dialogText.trim() && !dialogVisible) return;
    if (/Use Single Sign On to continue|Single Sign On/i.test(dialogText)) {
      await clickText(page, /^Single Sign On$/i, "last");
      await page.waitForTimeout(3000);
      if (await page.locator('input[name="username"]').isVisible().catch(() => false)) {
        await page.locator('input[name="username"]').fill(opsChatUser);
        await page.locator('input[name="password"]').fill(opsChatPassword);
        await page.locator('button[type="submit"], input[type="submit"]').first().click();
        await page.waitForTimeout(10000);
      }
      continue;
    }
    let clicked = false;
    for (const pattern of [/^Done$/i, /^OK$/i, /^Dismiss$/i, /^Continue$/i, /^Skip$/i, /^Cancel$/i]) {
      const button = page.locator("#mx_Dialog_Container button, #mx_Dialog_Container [role='button']").filter({ hasText: pattern }).last();
      if (await button.isVisible().catch(() => false)) {
        await button.click({ force: true }).catch(() => {});
        clicked = true;
        await page.waitForTimeout(1200);
        break;
      }
    }
    if (!clicked) {
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(800);
    }
  }
}

async function settleElement(page) {
  for (let i = 0; i < 10; i += 1) {
    const body = await page.locator("body").innerText().catch(() => "");
    if (/Confirm your digital identity|reset your digital identity|Verify this device|Confirm encryption setup/i.test(body)) {
      await page.keyboard.press("Escape").catch(() => {});
      await clickText(page, /Can't confirm\?|Can.t confirm\?|Skip|Later|Cancel|Done/i, "last");
      await page.waitForTimeout(1500);
      continue;
    }
    if (/Use Single Sign On to continue|Single Sign On/i.test(body)) {
      if (await clickText(page, /^Single Sign On$/i, "first")) {
        await page.waitForTimeout(3000);
        if (await page.locator('input[name="username"]').isVisible().catch(() => false)) {
          await page.locator('input[name="username"]').fill(opsChatUser);
          await page.locator('input[name="password"]').fill(opsChatPassword);
          await page.locator('button[type="submit"], input[type="submit"]').first().click();
          await page.waitForTimeout(10000);
        }
        continue;
      }
    }
    await dismissNoise(page);
    await clearDialogs(page);
    return;
  }
}

async function dashboardLogin(page) {
  requireSecret("DASHBOARD_PASSWORD", dashboardPassword);
  await page.goto(`${dashboardUrl}/login`, { waitUntil: "domcontentloaded" });
  await page.locator('input[name="username"], input#username').first().fill(dashboardUser);
  await page.locator('input[name="password"], input#password').first().fill(dashboardPassword);
  await page.locator('button[type="submit"], input[type="submit"]').first().click();
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.getByText(/Agentic Operations|Overview|Tickets|Agents/i).first().waitFor({ state: "visible", timeout: 60000 });
}

async function elementLogin(page) {
  requireSecret("OPS_CHAT_USER", opsChatUser);
  requireSecret("OPS_CHAT_PASSWORD", opsChatPassword);
  await page.goto(opsChatUrl, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});
  const signIn = page.getByRole("link", { name: /^Sign in$/i }).first();
  if (await signIn.isVisible().catch(() => false)) {
    await signIn.click();
    await page.waitForLoadState("networkidle").catch(() => {});
  }
  const keycloak = page.getByText(/Sign in with Keycloak|Keycloak/i).first();
  await keycloak.waitFor({ state: "visible", timeout: 60000 });
  await keycloak.click();
  await page.locator('input[name="username"]').waitFor({ state: "visible", timeout: 60000 });
  await page.locator('input[name="username"]').fill(opsChatUser);
  await page.locator('input[name="password"]').fill(opsChatPassword);
  await page.locator('button[type="submit"], input[type="submit"]').first().click();
  await page.waitForTimeout(10000);
  const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
  if (/Can't connect to homeserver|Cannot reach homeserver|login provider is unavailable|missing_session|No session cookie/i.test(body)) {
    throw new Error(`Element login failed: ${body.slice(0, 600)}`);
  }
  await settleElement(page);
}

async function composer(page) {
  await settleElement(page);
  await clearDialogs(page);
  await dismissNoise(page);
  const selectors = [
    'textarea[placeholder*="Message"]',
    '[contenteditable="true"]',
    '[role="textbox"]',
    'div[aria-label*="Send a message"]',
  ];
  for (const selector of selectors) {
    const loc = page.locator(selector).last();
    if (await loc.isVisible().catch(() => false)) return loc;
  }
  const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 1200);
  throw new Error(`Element composer not found. url=${page.url()} body=${body}`);
}

async function handleDirectMessagesDialog(page) {
  const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
  if (!/Direct Messages|Start a conversation with someone|Recent Conversations/i.test(body)) return;
  const botRow = page.getByText(/@agentic-ops:agentic-ops\.local/i).last();
  if (await botRow.isVisible().catch(() => false)) {
    await botRow.click({ force: true }).catch(() => {});
    await page.waitForTimeout(1500);
  } else {
    await clickText(page, /Agentic Ops Agent|@agentic-ops:agentic-ops\.local/i, "last");
    await page.waitForTimeout(1500);
  }
  const go = page.getByRole("button", { name: /Go|Start|Chat|Done|Continue/i }).last();
  if (await go.isVisible().catch(() => false)) {
    await go.click({ force: true }).catch(() => {});
    await page.waitForTimeout(4000);
  } else {
    await page.keyboard.press("Enter").catch(() => {});
    await page.waitForTimeout(4000);
  }
  if (await page.getByText(/Start a chat with this new contact/i).first().isVisible().catch(() => false)) {
    const cont = page.getByRole("button", { name: /^Continue$/i }).last();
    if (await cont.isVisible().catch(() => false)) await cont.click({ force: true });
    else await clickText(page, /^Continue$/i, "last");
    await page.waitForTimeout(5000);
  }
}

async function openAgentDm(page) {
  if (opsChatRoomId) {
    await page.goto(`${opsChatUrl}/#/room/${opsChatRoomId}`, { waitUntil: "domcontentloaded" });
  } else {
    await page.goto(`${opsChatUrl}/#/user/@agentic-ops:agentic-ops.local`, { waitUntil: "domcontentloaded" });
  }
  await page.waitForTimeout(5000);
  await settleElement(page);
  const roomBody = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
  if (/can't be previewed|Join the discussion|Do you want to join it/i.test(roomBody)) {
    const joinButton = page.getByRole("button", { name: /Join the discussion|^Join$/i }).last();
    if (await joinButton.isVisible().catch(() => false)) {
      await joinButton.click({ force: true });
    } else {
      const joinControl = page.locator("button,[role='button']").filter({ hasText: /Join the discussion|^Join$/i }).last();
      if (await joinControl.isVisible().catch(() => false)) {
        await joinControl.click({ force: true });
      } else {
        await clickText(page, /Join the discussion|^Join$/i, "last");
      }
    }
    await page.waitForTimeout(6000);
    await settleElement(page);
    if (!(await page.locator('textarea[placeholder*="Message"], [contenteditable="true"], [role="textbox"], div[aria-label*="Send a message"]').last().isVisible().catch(() => false))) {
      await page.goto(`${opsChatUrl}/#/user/@agentic-ops:agentic-ops.local`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(5000);
      await settleElement(page);
    }
  }
  const sendMessage = page.getByRole("button", { name: /Send message|Message/i }).first();
  if (await sendMessage.isVisible().catch(() => false)) {
    await sendMessage.click({ force: true });
    await page.waitForTimeout(5000);
  }
  await handleDirectMessagesDialog(page);
  if (await page.getByText(/Start a chat with this new contact/i).first().isVisible().catch(() => false)) {
    const cont = page.getByRole("button", { name: /^Continue$/i }).last();
    if (await cont.isVisible().catch(() => false)) await cont.click({ force: true });
    else await clickText(page, /^Continue$/i, "last");
    await page.waitForTimeout(5000);
  }
  await composer(page);
}

async function sendMessage(page, message, expectPattern, timeout = 600000, anchorText = "") {
  const before = await page.locator("body").innerText().catch(() => "");
  const input = await composer(page);
  await input.click({ force: true });
  await input.fill(message).catch(async () => input.type(message));
  await page.keyboard.press("Enter");
  await page.waitForFunction(
    ({ source, beforeText, anchorText }) => {
      const regex = new RegExp(source, "i");
      const text = document.body.innerText || "";
      if (text.length <= beforeText.length) return false;
      if (!anchorText) return regex.test(text);
      const idx = text.lastIndexOf(anchorText);
      if (idx < 0) return false;
      return regex.test(text.slice(idx));
    },
    { source: expectPattern.source, beforeText: before, anchorText },
    { timeout },
  );
  await page.waitForTimeout(1000);
  return (await page.locator("body").innerText()).replace(/\s+/g, " ");
}

function latestTicketAfter(text, markerValue) {
  const segment = String(text || "").slice(String(text || "").lastIndexOf(markerValue));
  const matches = Array.from(segment.matchAll(/(?:Dashboard ticket: #|I created ticket #|Ticket #)(\d+)/gi));
  return matches.length ? Number(matches[matches.length - 1][1]) : null;
}

async function waitForSecureLinkAfter(page, anchorText, timeout = 240000) {
  await page.waitForFunction(
    ({ anchorText }) => {
      const text = document.body.innerText || "";
      const idx = text.lastIndexOf(anchorText);
      if (idx < 0) return false;
      const segment = text.slice(idx);
      return /\/secure-intake\/[A-Za-z0-9_-]+/.test(segment);
    },
    { anchorText },
    { timeout },
  );
  const text = await page.locator("body").innerText();
  const segment = text.slice(text.lastIndexOf(anchorText));
  const match = segment.match(/https?:\/\/[^\s"'<>]+\/secure-intake\/[A-Za-z0-9_-]+|\/secure-intake\/[A-Za-z0-9_-]+/);
  if (!match) throw new Error("secure intake link appeared but could not be extracted");
  const raw = match[0].replace(/[)\].,;]+$/, "");
  return raw.startsWith("/") ? `${dashboardUrl}${raw}` : raw;
}

async function requestSecureInfo(context, ticketId) {
  const response = await context.request.post(`${dashboardUrl}/api/tickets/${ticketId}/request-info`, {
    data: {
      question: `Please collect these details securely for Bob: full legal name, SSN, date of birth, desired username, work email address, required role, manager or sponsor, start date, and initial password. Marker ${marker}.`,
      requested_by: "playwright-sensitive-intake-ui",
      contact_method: "matrix",
      recipient: opsChatUser,
      context: "Element UI regression for secure requester information. Raw values must not be requested through chat.",
    },
  });
  if (!response.ok()) {
    throw new Error(`request-info failed: HTTP ${response.status()} ${(await response.text()).slice(0, 600)}`);
  }
  const payload = await response.json();
  if (!payload.secure_intake || !payload.secure_intake.form_url) {
    throw new Error(`request-info did not return secure_intake: ${JSON.stringify(payload).slice(0, 1000)}`);
  }
  return payload;
}

function generatedFormValues(fields) {
  const suffix = marker.replace(/[^a-zA-Z0-9]/g, "").slice(-10);
  const values = {};
  const generated = [];
  for (const field of fields || []) {
    const key = field.key;
    const type = String(field.type || "").toLowerCase();
    const label = String(field.label || key).toLowerCase();
    let value = `Demo ${field.label || key} ${suffix}`;
    if (type === "ssn" || label.includes("ssn") || label.includes("social security")) value = `321-54-${String(Date.now()).slice(-4)}`;
    else if (type === "dob" || label.includes("birth")) value = "1991-02-03";
    else if (type === "credential" || label.includes("password")) value = `Tmp${suffix}!DemoPass42`;
    else if (type === "email" || label.includes("email")) value = `bob.${suffix.toLowerCase()}@example.invalid`;
    else if (type === "username" || label.includes("username")) value = `bob_${suffix.toLowerCase()}`;
    else if (type === "date" || label.includes("date")) value = "2026-06-15";
    values[key] = value;
    generated.push(value);
  }
  return { values, generated };
}

async function submitSecureForm(page, formUrl, values) {
  await page.goto(formUrl, { waitUntil: "domcontentloaded" });
  await page.getByText(/Secure Intake|secure intake|protected/i).first().waitFor({ state: "visible", timeout: 60000 });
  await maybeScreenshot(page, "secure-intake-form-requested");
  for (const [key, value] of Object.entries(values)) {
    const selector = `[name="${key}"], #${key}`;
    const input = page.locator(selector).first();
    if (await input.isVisible().catch(() => false)) {
      await input.fill(value);
      continue;
    }
    const field = page.locator("input, textarea, select").filter({ has: page.locator(`[name="${key}"]`) }).first();
    if (await field.isVisible().catch(() => false)) await field.fill(value);
  }
  const submit = page.getByRole("button", { name: /Submit|Send secure/i }).first();
  if (await submit.isVisible().catch(() => false)) await submit.click({ force: true });
  else await page.locator('button[type="submit"], input[type="submit"]').first().click({ force: true });
  await page.getByText(/was submitted successfully|protected field\(s\) were stored|Raw values are not displayed/i).first().waitFor({ state: "visible", timeout: 60000 });
  await maybeScreenshot(page, "secure-intake-form-submitted");
}

async function verifyNoLeak(context, ticketId, forbiddenValues) {
  const response = await context.request.get(`${dashboardUrl}/api/tickets/${ticketId}/context`);
  if (!response.ok()) {
    throw new Error(`ticket context failed: HTTP ${response.status()} ${(await response.text()).slice(0, 600)}`);
  }
  const payload = await response.json();
  const text = JSON.stringify(payload);
  for (const value of forbiddenValues) {
    if (value && text.includes(value)) {
      throw new Error(`submitted secure form value leaked into ticket context for ticket ${ticketId}`);
    }
  }
  if (!/sir_[A-Za-z0-9]+/.test(text) || !/siv_[A-Za-z0-9]+/.test(text)) {
    throw new Error(`ticket context did not expose secure request/value refs for ticket ${ticketId}`);
  }
  return {
    sensitive_requests: payload.sensitive_intake_requests || [],
    note_count: (payload.notes || []).length,
  };
}

async function cleanupTicket(context, ticketId) {
  if (!ticketId || !/^(1|true|yes|on)$/i.test(process.env.OPS_CHAT_SENSITIVE_CLEANUP || "true")) return null;
  const response = await context.request.post(`${dashboardUrl}/api/tickets/${ticketId}/status`, {
    data: {
      status: "cancelled",
      actor: "playwright-sensitive-intake-ui",
      reason: `Sensitive intake UI smoke complete for marker ${marker}.`,
      close_provider: false,
    },
  }).catch(() => null);
  if (!response || !response.ok()) return { status: "cleanup_failed", ticket_id: ticketId };
  return await response.json();
}

async function cleanupAgent(context, ticketId) {
  if (!ticketId || !/^(1|true|yes|on)$/i.test(process.env.OPS_CHAT_SENSITIVE_CLEANUP || "true")) return null;
  const response = await context.request.get(`${dashboardUrl}/api/tickets/${ticketId}/context`).catch(() => null);
  if (!response || !response.ok()) return { status: "agent_cleanup_skipped", reason: "context_unavailable" };
  const payload = await response.json();
  const agentId = payload?.ticket?.agent_id;
  if (!agentId) return { status: "agent_cleanup_skipped", reason: "no_agent" };
  const stop = await context.request.post(`${dashboardUrl}/api/agents/${agentId}/stop`, {
    data: {
      reason: `Stopping synthetic sensitive-intake UI smoke agent for marker ${marker}.`,
    },
  }).catch(() => null);
  if (!stop || !stop.ok()) return { status: "agent_cleanup_failed", agent_id: agentId };
  return await stop.json();
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    ignoreHTTPSErrors: ignoreHttpsErrors,
    viewport: { width: 1440, height: 1000 },
  });
  const dashboardPage = await context.newPage();
  const chatPage = await context.newPage();
  const formPage = await context.newPage();
  try {
    await dashboardLogin(dashboardPage);
    await elementLogin(chatPage);
    await openAgentDm(chatPage);

    const ticketMarker = `${marker}-ticket`;
    const createText = await sendMessage(
      chatPage,
      `Please create a traceable ticket for a dashboard account setup dry run for Bob. Do not collect protected values in chat. Marker ${ticketMarker}`,
      /Dashboard ticket: #|I created ticket #|Ticket #/,
      600000,
      ticketMarker,
    );
    const ticketId = latestTicketAfter(createText, ticketMarker);
    if (!ticketId) throw new Error("Element ticket creation did not expose a ticket id");

    const ask = await requestSecureInfo(context, ticketId);
    const anchor = `Ticket #${ticketId}`;
    const formUrl = await waitForSecureLinkAfter(chatPage, anchor, 240000);
    if (!formUrl.includes("/secure-intake/")) throw new Error(`unexpected secure form URL: ${formUrl}`);

    const fields = ask.secure_intake.fields || [];
    const { values, generated } = generatedFormValues(fields);
    await submitSecureForm(formPage, formUrl, values);
    const contextProof = await verifyNoLeak(context, ticketId, generated);
    const agentCleanup = await cleanupAgent(context, ticketId);
    const cleanup = await cleanupTicket(context, ticketId);

    await browser.close();
    console.log(JSON.stringify({
      status: "passed",
      marker,
      user: opsChatUser,
      ticket_id: ticketId,
      secure_request_ref: ask.secure_intake.request_ref,
      field_count: fields.length,
      dashboard_context: contextProof,
      agent_cleanup: agentCleanup,
      cleanup,
      screenshots: screenshotDir || null,
      raw_values_printed: false,
    }, null, 2));
  } catch (error) {
    await maybeScreenshot(chatPage, "ops-chat-sensitive-failed").catch(() => {});
    await browser.close();
    console.error(JSON.stringify({ status: "failed", marker, error: String(error && error.message || error) }, null, 2));
    process.exit(2);
  }
})();
