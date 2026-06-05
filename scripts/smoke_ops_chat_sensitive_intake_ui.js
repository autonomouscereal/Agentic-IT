#!/usr/bin/env node
/*
 * Element/Matrix sensitive-intake proof.
 *
 * This test drives the actual user intake surface, not only direct APIs.
 *
 * Scenarios:
 *   - fallback: ticket requester-info asks are converted to secure forms;
 *   - direct: the chat agent itself uses request-sensitive-fields;
 *   - redaction: accidental protected-value paste is redacted before dashboard
 *     storage/model prompts.
 *   - judgment: natural no-hint prompts prove the agent chooses secure intake
 *     only when protected values are involved.
 *   - account-e2e: no-hint account request -> secure form -> ticket worker
 *     creates a real read-only dashboard login -> UI login verifies it.
 *
 * Set OPS_CHAT_SENSITIVE_SCENARIO=fallback|direct|redaction|judgment|account-e2e|all.
 *
 * Fallback path:
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

const crypto = require("crypto");
const { chromium } = require("playwright");

const dashboardUrl = (process.env.DASHBOARD_URL || "https://127.0.0.1:25443").replace(/\/$/, "");
const dashboardUser = process.env.DASHBOARD_USER || "demo_account_1";
const dashboardPassword = process.env.DASHBOARD_PASSWORD || "";
const opsChatUrl = (process.env.OPS_CHAT_URL || "https://127.0.0.1:3303").replace(/\/$/, "");
const opsChatUser = process.env.OPS_CHAT_USER || "";
const opsChatPassword = process.env.OPS_CHAT_PASSWORD || "";
const opsChatRoomId = process.env.OPS_CHAT_ROOM_ID || "";
const marker = process.env.OPS_CHAT_SENSITIVE_MARKER || `ops-chat-sensitive-${Date.now()}`;
const scenario = (process.env.OPS_CHAT_SENSITIVE_SCENARIO || "fallback").toLowerCase();
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

async function clickExactText(page, text, which = "last") {
  const loc = page.getByText(text, { exact: true });
  const count = await loc.count().catch(() => 0);
  const indexes = which === "first"
    ? Array.from({ length: count }, (_, index) => index)
    : Array.from({ length: count }, (_, index) => count - 1 - index);
  for (const index of indexes) {
    const target = loc.nth(index);
    if (await target.isVisible().catch(() => false)) {
      await target.click({ force: true }).catch(() => {});
      return true;
    }
  }
  return false;
}

async function clickLeafText(page, patternSource, which = "last") {
  return await page.evaluate(({ patternSource, which }) => {
    const regex = new RegExp(patternSource, "i");
    const candidates = Array.from(document.querySelectorAll("button,a,[role='button'],span,div,p"));
    const visible = candidates
      .map((el) => {
        const text = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        const childText = Array.from(el.children || [])
          .map((child) => (child.innerText || child.textContent || "").replace(/\s+/g, " ").trim())
          .join(" ");
        return { el, text, rect, style, childText };
      })
      .filter((item) => (
        regex.test(item.text) &&
        !/Remove this device|Reset all|Sign out/i.test(item.text) &&
        item.rect.width > 0 &&
        item.rect.height > 0 &&
        item.style.display !== "none" &&
        item.style.visibility !== "hidden"
      ))
      .sort((a, b) => {
        const aOwn = a.childText && a.childText !== a.text ? 1 : 0;
        const bOwn = b.childText && b.childText !== b.text ? 1 : 0;
        if (aOwn !== bOwn) return bOwn - aOwn;
        return a.text.length - b.text.length;
      });
    const target = which === "first" ? visible[0] : visible[visible.length - 1] || visible[0];
    if (!target) return false;
    const x = target.rect.left + target.rect.width / 2;
    const y = target.rect.top + target.rect.height / 2;
    const clickable = document.elementFromPoint(x, y) || target.el;
    clickable.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, clientX: x, clientY: y }));
    clickable.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: x, clientY: y }));
    clickable.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: x, clientY: y }));
    return true;
  }, { patternSource, which }).catch(() => false);
}

async function clickDialogUntitledClose(page) {
  const closeButtons = [
    "#mx_Dialog_Container button[aria-label*='Close']",
    "#mx_Dialog_Container [role='button'][aria-label*='Close']",
    "button[aria-label*='Close']",
    "[role='button'][aria-label*='Close']",
    ".mx_Dialog_cancelButton",
    ".mx_AccessibleButton[aria-label*='Close']",
  ];
  for (const selector of closeButtons) {
    const button = page.locator(selector).first();
    if (await button.isVisible().catch(() => false)) {
      await button.click({ force: true }).catch(() => {});
      return true;
    }
  }
  const emptyButtons = page.locator("button,[role='button']");
  const count = await emptyButtons.count().catch(() => 0);
  for (let index = 0; index < Math.min(count, 8); index += 1) {
    const button = emptyButtons.nth(index);
    if (!(await button.isVisible().catch(() => false))) continue;
    const text = ((await button.innerText().catch(() => "")) || (await button.textContent().catch(() => "")) || "").trim();
    if (text) continue;
    await button.click({ force: true }).catch(() => {});
    return true;
  }
  return false;
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
    const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
    if (/Are you sure you want to reset your digital identity/i.test(body)) {
      await clickExactText(page, "Cancel", "last") || await clickText(page, /^Cancel$/i, "last");
      await page.waitForTimeout(1200);
      continue;
    }
    if (/Device verified|new device is now verified/i.test(body)) {
      await clickExactText(page, "Done", "last") || await clickText(page, /^Done$/i, "last");
      await page.waitForTimeout(1200);
      continue;
    }
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

async function skipIdentityVerification(page) {
  let acted = false;
  for (let i = 0; i < 10; i += 1) {
    const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
    if (/Are you sure you want to reset your digital identity/i.test(body)) {
      await clickExactText(page, "Cancel", "last") || await clickText(page, /^Cancel$/i, "last");
      await page.waitForTimeout(1500);
      acted = true;
      continue;
    }
    if (/Device verified|new device is now verified/i.test(body)) {
      await clickExactText(page, "Done", "last") || await clickText(page, /^Done$/i, "last");
      await page.waitForTimeout(1500);
      acted = true;
      continue;
    }
    if (!/Confirm your digital identity|reset your digital identity|Verify this device|Confirm encryption setup|secure messaging|Without verifying|I'll verify later/i.test(body)) {
      return acted;
    }
    if (await clickDialogUntitledClose(page)) {
      await page.waitForTimeout(1500);
      acted = true;
      continue;
    }
    let clicked = false;
    const patterns = [
      /^Can't confirm\??$/i,
      /^Can.t confirm\??$/i,
      /Skip verification/i,
      /Verify later/i,
      /I'll verify later/i,
      /Not now/i,
      /^Skip$/i,
      /^Cancel$/i,
      /^Done$/i,
      /^Close$/i,
    ];
    for (const exact of ["Can't confirm?", "Skip verification", "Verify later", "I'll verify later", "Not now", "Skip", "Cancel", "Done", "Close"]) {
      if (await clickExactText(page, exact, "last") || await clickLeafText(page, `^${exact.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`, "last")) {
        clicked = true;
        acted = true;
        await page.waitForTimeout(2000);
        break;
      }
    }
    if (!clicked && await clickLeafText(page, "^Can.?t confirm\\??$", "last")) {
      clicked = true;
      acted = true;
      await page.waitForTimeout(2000);
    }
    if (clicked) continue;
    for (const pattern of patterns) {
      const targets = page.locator("button,[role='button'],a,span,div").filter({ hasText: pattern });
      const count = await targets.count().catch(() => 0);
      for (let index = count - 1; index >= 0; index -= 1) {
        const target = targets.nth(index);
        const text = (await target.innerText().catch(() => "")).replace(/\s+/g, " ").trim();
        if (/Remove this device|Reset all|Sign out/i.test(text)) continue;
        if (await target.isVisible().catch(() => false)) {
          await target.click({ force: true }).catch(() => {});
          clicked = true;
          acted = true;
          await page.waitForTimeout(2000);
          break;
        }
      }
      if (clicked) break;
    }
    if (!clicked) {
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(1000);
    }
  }
  return acted;
}

async function settleElement(page) {
  for (let i = 0; i < 10; i += 1) {
    const body = await page.locator("body").innerText().catch(() => "");
    if (/Confirm your digital identity|reset your digital identity|Verify this device|Confirm encryption setup|Without verifying|I'll verify later/i.test(body)) {
      await skipIdentityVerification(page);
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

async function getFormPayload(context, formUrl) {
  const url = new URL(formUrl, dashboardUrl);
  const token = url.pathname.split("/").filter(Boolean).pop();
  const response = await context.request.get(`${dashboardUrl}/api/sensitive-intake/form/${encodeURIComponent(token || "")}`);
  if (!response.ok()) {
    throw new Error(`secure form payload fetch failed: HTTP ${response.status()} ${(await response.text()).slice(0, 600)}`);
  }
  return await response.json();
}

function generatedFormValues(fields, overrides = {}) {
  const suffix = marker.replace(/[^a-zA-Z0-9]/g, "").slice(-10);
  const values = {};
  const generated = [];
  for (const field of fields || []) {
    const key = field.key;
    const type = String(field.type || "").toLowerCase();
    const label = String(field.label || key).toLowerCase();
    let value = `Demo ${field.label || key} ${suffix}`;
    if (Object.prototype.hasOwnProperty.call(overrides, key)) value = overrides[key];
    else if (type === "ssn" || label.includes("ssn") || label.includes("social security")) value = `321-54-${String(Date.now()).slice(-4)}`;
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
  const requestText = await page.locator("body").innerText().catch(() => "");
  const initialRequestRef = (requestText.match(/sir_[A-Za-z0-9]+/) || [])[0] || "";
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
  const submittedText = await page.locator("body").innerText().catch(() => "");
  return (submittedText.match(/sir_[A-Za-z0-9]+/) || [])[0] || initialRequestRef;
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
  const requests = payload.sensitive_intake_requests || [];
  const submitted = requests.filter((request) => request.status === "submitted" && request.request_ref);
  if (!submitted.length) {
    throw new Error(`ticket context did not expose submitted secure request refs for ticket ${ticketId}`);
  }
  const requestDetails = [];
  let valueRefCount = 0;
  for (const request of submitted) {
    const detail = await verifyRequestNoLeak(context, request.request_ref, forbiddenValues);
    requestDetails.push(detail);
    valueRefCount += Number(detail.submitted_field_count || 0);
  }
  if (valueRefCount <= 0) {
    throw new Error(`secure request details did not expose submitted value refs for ticket ${ticketId}`);
  }
  return {
    sensitive_requests: requests,
    request_details: requestDetails,
    value_ref_count: valueRefCount,
    note_count: (payload.notes || []).length,
  };
}

async function verifyRequestNoLeak(context, requestRef, forbiddenValues) {
  if (!requestRef) throw new Error("missing secure request ref");
  const response = await context.request.get(`${dashboardUrl}/api/sensitive-intake/requests/${encodeURIComponent(requestRef)}`);
  if (!response.ok()) {
    throw new Error(`secure request detail failed: HTTP ${response.status()} ${(await response.text()).slice(0, 600)}`);
  }
  const payload = await response.json();
  const text = JSON.stringify(payload);
  for (const value of forbiddenValues) {
    if (value && text.includes(value)) {
      throw new Error(`submitted secure form value leaked into secure request detail for ${requestRef}`);
    }
  }
  if (!/siv_[A-Za-z0-9]+/.test(text)) {
    throw new Error(`secure request detail did not expose value refs for ${requestRef}`);
  }
  const valueRefs = Array.isArray(payload.values)
    ? payload.values.filter((value) => value && value.value_ref && value.raw_value_returned === false)
    : [];
  if (!valueRefs.length) {
    throw new Error(`secure request detail did not include raw-safe value refs for ${requestRef}`);
  }
  if (payload.raw_values_returned !== false) {
    throw new Error(`secure request detail did not explicitly report raw_values_returned=false for ${requestRef}`);
  }
  return {
    request_ref: payload.request_ref,
    status: payload.status,
    submitted_field_count: payload.submitted_field_count || valueRefs.length,
    value_ref_count: valueRefs.length,
    raw_values_returned: payload.raw_values_returned,
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

async function recentSessions(context, limit = 50) {
  const response = await context.request.get(`${dashboardUrl}/api/ops-chat/sessions?limit=${limit}`);
  if (!response.ok()) {
    throw new Error(`ops-chat sessions failed: HTTP ${response.status()} ${(await response.text()).slice(0, 600)}`);
  }
  return (await response.json()).sessions || [];
}

async function findSessionMessagesByMarker(context, markerValue) {
  for (const session of await recentSessions(context, 80)) {
    const sessionId = session.id;
    const response = await context.request.get(`${dashboardUrl}/api/ops-chat/sessions/${sessionId}/messages`);
    if (!response.ok()) continue;
    const payload = await response.json();
    const text = JSON.stringify(payload);
    if (text.includes(markerValue)) {
      return payload;
    }
  }
  throw new Error(`could not find ops-chat session messages for marker ${markerValue}`);
}

async function verifySessionNoLeak(context, markerValue, forbiddenValues, options = {}) {
  const payload = await findSessionMessagesByMarker(context, markerValue);
  const messages = payload.messages || [];
  const relevant = messages.filter((message) => JSON.stringify(message).includes(markerValue));
  const scoped = {
    session_id: payload.session_id,
    total: payload.total,
    messages: relevant.length ? relevant : messages,
  };
  const text = JSON.stringify(scoped);
  for (const value of forbiddenValues) {
    if (value && text.includes(value)) {
      throw new Error(`raw protected value leaked into ops-chat dashboard messages for marker ${markerValue}`);
    }
  }
  const refCount = (text.match(/siv_[A-Za-z0-9]+/g) || []).length;
  if (options.minRefs && refCount < options.minRefs) {
    throw new Error(`expected at least ${options.minRefs} sensitive refs for marker ${markerValue}; found ${refCount}`);
  }
  if (!text.includes(markerValue)) {
    throw new Error(`session messages missing marker ${markerValue}`);
  }
  return {
    session_id: payload.session_id,
    message_count: payload.total,
    matched_message_count: relevant.length,
    sensitive_ref_count: refCount,
    contains_sensitive_refs: /<sensitive:[^>]+:siv_[A-Za-z0-9]+>/.test(text) || /siv_[A-Za-z0-9]+/.test(text),
  };
}

async function getTicketContext(context, ticketId) {
  const response = await context.request.get(`${dashboardUrl}/api/tickets/${ticketId}/context`);
  if (!response.ok()) {
    throw new Error(`ticket context failed for ${ticketId}: HTTP ${response.status()} ${(await response.text()).slice(0, 600)}`);
  }
  return await response.json();
}

async function waitForTicketTerminal(context, ticketId, timeout = 900000) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    last = await getTicketContext(context, ticketId);
    const ticket = last.ticket || {};
    const status = String(ticket.status || "").toLowerCase();
    if (["resolved", "closed", "implemented", "cancelled"].includes(status)) return last;
    if (["failed", "blocked", "awaiting_access", "pending_approval"].includes(status)) {
      return last;
    }
    await new Promise((resolve) => setTimeout(resolve, 5000));
  }
  const status = last && last.ticket ? last.ticket.status : "unknown";
  throw new Error(`ticket ${ticketId} did not reach terminal/wait state before timeout; last status=${status}`);
}

async function waitForChatClosure(page, ticketId, username, timeout = 180000) {
  await page.waitForFunction(
    ({ ticketId, username }) => {
      const text = document.body.innerText || "";
      const token = `ticket #${ticketId}`;
      const idx = text.toLowerCase().lastIndexOf(token);
      if (idx < 0) return false;
      const segment = text.slice(idx);
      return /Agent completed this request|status update|changed to resolved|Ticket status changed/i.test(segment)
        && segment.includes(username);
    },
    { ticketId, username },
    { timeout },
  );
}

async function verifyDashboardLoginUi(baseContext, username, password) {
  const browser = baseContext.browser();
  const loginContext = await browser.newContext({
    ignoreHTTPSErrors: ignoreHttpsErrors,
    viewport: { width: 1280, height: 900 },
  });
  const page = await loginContext.newPage();
  try {
    await page.goto(`${dashboardUrl}/login`, { waitUntil: "domcontentloaded" });
    await page.locator('input[name="username"], input#username').first().fill(username);
    await page.locator('input[name="password"], input#password').first().fill(password);
    await page.locator('button[type="submit"], input[type="submit"]').first().click();
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.getByText(/Agentic Operations|Overview|Tickets|Agents/i).first().waitFor({ state: "visible", timeout: 60000 });
    const me = await loginContext.request.get(`${dashboardUrl}/api/access/me`);
    if (!me.ok()) throw new Error(`new account /api/access/me failed: HTTP ${me.status()}`);
    const mePayload = await me.json();
    const roles = mePayload.roles || [];
    if (!roles.includes("auditor")) {
      throw new Error(`new account did not have auditor role: ${JSON.stringify(roles)}`);
    }
    const denied = await loginContext.request.post(`${dashboardUrl}/api/access/users`, {
      data: {
        username: `should_not_create_${Date.now()}`,
        display_name: "Should Not Create",
        provider: "local",
        enabled: true,
      },
    });
    if (denied.status() !== 403) {
      throw new Error(`read-only account mutation was not denied; HTTP ${denied.status()} ${(await denied.text()).slice(0, 300)}`);
    }
    return {
      status: "passed",
      username,
      roles,
      read_only_mutation_status: denied.status(),
      password_printed: false,
    };
  } finally {
    await loginContext.close();
  }
}

async function runFallbackScenario(context, chatPage, formPage) {
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
  const submittedRef = await submitSecureForm(formPage, formUrl, values);
  const contextProof = await verifyNoLeak(context, ticketId, generated);
  const agentCleanup = await cleanupAgent(context, ticketId);
  const cleanup = await cleanupTicket(context, ticketId);
  return {
    status: "passed",
    scenario: "fallback",
    ticket_id: ticketId,
    secure_request_ref: ask.secure_intake.request_ref || submittedRef,
    field_count: fields.length,
    dashboard_context: contextProof,
    agent_cleanup: agentCleanup,
    cleanup,
  };
}

async function runDirectScenario(context, chatPage, formPage) {
  const directMarker = `${marker}-direct`;
  const text = await sendMessage(
    chatPage,
    [
      `Secure form direct-agent regression marker ${directMarker}.`,
      "I need to securely provide protected onboarding details for Bob before any dashboard account setup work proceeds.",
      "Please do not ask me to paste protected values in chat and do not create a ticket yet.",
      "Send me one secure intake form for full legal name, SSN, date of birth, desired username, work email, manager or sponsor, start date, and initial temporary password.",
    ].join(" "),
    /\/secure-intake\/|secure intake form|protected information/i,
    900000,
    directMarker,
  );
  const formUrl = await waitForSecureLinkAfter(chatPage, directMarker, 240000);
  const form = await getFormPayload(context, formUrl);
  const fields = form.fields || [];
  if (fields.length < 6) {
    throw new Error(`direct secure form had too few fields: ${fields.length}`);
  }
  const labels = fields.map((field) => String(field.label || field.key || "").toLowerCase()).join(" | ");
  for (const required of ["ssn", "date of birth", "password"]) {
    if (!labels.includes(required)) throw new Error(`direct secure form missing required label ${required}: ${labels}`);
  }
  if (/Dashboard ticket: #|I created ticket #/i.test(text.slice(text.lastIndexOf(directMarker)))) {
    throw new Error("direct sensitive ask unexpectedly created a ticket before protected values were brokered");
  }
  const { values, generated } = generatedFormValues(fields);
  const submittedRef = await submitSecureForm(formPage, formUrl, values);
  const requestProof = await verifyRequestNoLeak(context, submittedRef || form.request_ref, generated);
  const sessionProof = await verifySessionNoLeak(context, directMarker, generated);
  return {
    status: "passed",
    scenario: "direct",
    secure_request_ref: submittedRef || form.request_ref,
    field_count: fields.length,
    secure_request: requestProof,
    ops_chat_session: sessionProof,
  };
}

async function runRedactionScenario(context, chatPage) {
  const pasteMarker = `${marker}-paste`;
  const suffix = marker.replace(/[^0-9]/g, "").slice(-4) || "4581";
  const fakeSsn = `321-54-${suffix.padStart(4, "0").slice(-4)}`;
  const fakePassword = `Tmp${marker.replace(/[^a-zA-Z0-9]/g, "").slice(-8)}!NoLeak42`;
  const fakeToken = `sk-test-${marker.replace(/[^a-zA-Z0-9]/g, "").slice(-14)}redaction`;
  await sendMessage(
    chatPage,
    `Redaction regression marker ${pasteMarker}. I accidentally pasted SSN ${fakeSsn}, password ${fakePassword}, and API token ${fakeToken}. Do not create a ticket; just tell me to use secure intake next time.`,
    /secure intake|protected|redacted|do not paste|I (can|will)|ticket/i,
    900000,
    pasteMarker,
  );
  const sessionProof = await verifySessionNoLeak(context, pasteMarker, [fakeSsn, fakePassword, fakeToken], { minRefs: 3 });
  if (!sessionProof.contains_sensitive_refs) {
    throw new Error("redaction scenario did not leave sensitive refs in dashboard chat messages");
  }
  return {
    status: "passed",
    scenario: "redaction",
    ops_chat_session: sessionProof,
    raw_values_printed: false,
  };
}

async function runJudgmentScenario(context, chatPage, formPage) {
  const results = [];

  const naturalMarker = `${marker}-natural`;
  const naturalText = await sendMessage(
    chatPage,
    [
      `Onboarding packet test marker ${naturalMarker}.`,
      "I need to give the system the details for Bob's account setup:",
      "full legal name, SSN, date of birth, desired username, work email, manager, start date, and an initial temporary password.",
      "Collect what you need from me before the account work starts.",
    ].join(" "),
    /\/secure-intake\/|protected information|protected values|intake/i,
    900000,
    naturalMarker,
  );
  const naturalSegment = naturalText.slice(naturalText.lastIndexOf(naturalMarker));
  if (/Dashboard ticket: #|I created ticket #/i.test(naturalSegment)) {
    throw new Error("natural protected-field collection created a ticket before brokering protected values");
  }
  const naturalFormUrl = await waitForSecureLinkAfter(chatPage, naturalMarker, 240000);
  const naturalForm = await getFormPayload(context, naturalFormUrl);
  const naturalFields = naturalForm.fields || [];
  const naturalLabels = naturalFields.map((field) => String(field.label || field.key || "").toLowerCase()).join(" | ");
  for (const required of ["ssn", "date of birth", "password"]) {
    if (!naturalLabels.includes(required)) throw new Error(`natural secure form missing ${required}: ${naturalLabels}`);
  }
  const naturalValues = generatedFormValues(naturalFields);
  const naturalRef = await submitSecureForm(formPage, naturalFormUrl, naturalValues.values);
  results.push({
    scenario: "natural-protected-collection",
    secure_request: await verifyRequestNoLeak(context, naturalRef || naturalForm.request_ref, naturalValues.generated),
    session: await verifySessionNoLeak(context, naturalMarker, naturalValues.generated),
    field_count: naturalFields.length,
  });

  const financeMarker = `${marker}-finance`;
  const financeText = await sendMessage(
    chatPage,
    [
      `Vendor reimbursement intake marker ${financeMarker}.`,
      "I need to give you the payment setup details for a new vendor:",
      "bank account number, routing number, tax ID, remittance email, legal address, and payment contact.",
      "Collect the packet from me so procurement can use it later.",
    ].join(" "),
    /\/secure-intake\/|protected information|protected values|intake/i,
    900000,
    financeMarker,
  );
  const financeSegment = financeText.slice(financeText.lastIndexOf(financeMarker));
  if (/Dashboard ticket: #|I created ticket #/i.test(financeSegment)) {
    throw new Error("financial collection created a ticket before brokering protected values");
  }
  const financeFormUrl = await waitForSecureLinkAfter(chatPage, financeMarker, 240000);
  const financeForm = await getFormPayload(context, financeFormUrl);
  const financeFields = financeForm.fields || [];
  const financeLabels = financeFields.map((field) => String(field.label || field.key || "").toLowerCase()).join(" | ");
  for (const required of ["account", "routing", "tax"]) {
    if (!financeLabels.includes(required)) throw new Error(`financial secure form missing ${required}: ${financeLabels}`);
  }
  const financeValues = generatedFormValues(financeFields);
  const financeRef = await submitSecureForm(formPage, financeFormUrl, financeValues.values);
  results.push({
    scenario: "natural-financial-collection",
    secure_request: await verifyRequestNoLeak(context, financeRef || financeForm.request_ref, financeValues.generated),
    session: await verifySessionNoLeak(context, financeMarker, financeValues.generated),
    field_count: financeFields.length,
  });

  const pasteMarker = `${marker}-pasted-values`;
  const suffix = marker.replace(/[^0-9]/g, "").slice(-4) || "9092";
  const fakeSsn = `321-54-${suffix.padStart(4, "0").slice(-4)}`;
  const fakePassword = `Tmp${marker.replace(/[^a-zA-Z0-9]/g, "").slice(-8)}!Pasted42`;
  const fakeToken = `sk-test-${marker.replace(/[^a-zA-Z0-9]/g, "").slice(-14)}pasted`;
  const pasteText = await sendMessage(
    chatPage,
    [
      `New account setup marker ${pasteMarker}.`,
      "Set up Bob's dashboard account.",
      `Legal name Bob Example, SSN ${fakeSsn}, date of birth 1991-02-03, initial password: ${fakePassword}, API token: ${fakeToken}.`,
      "Proceed with whatever ticket or access path is appropriate.",
    ].join(" "),
    /Dashboard ticket: #|I created ticket #|Ticket #|protected|intake|updated|recorded/i,
    900000,
    pasteMarker,
  );
  const pasteSession = await verifySessionNoLeak(context, pasteMarker, [fakeSsn, fakePassword, fakeToken], { minRefs: 3 });
  const pasteTicketId = latestTicketAfter(pasteText, pasteMarker);
  let pasteTicket = null;
  let pasteAgentCleanup = null;
  let pasteCleanup = null;
  if (pasteTicketId) {
    pasteTicket = await verifyNoLeak(context, pasteTicketId, [fakeSsn, fakePassword, fakeToken]);
    pasteAgentCleanup = await cleanupAgent(context, pasteTicketId);
    pasteCleanup = await cleanupTicket(context, pasteTicketId);
  }
  results.push({
    scenario: "pasted-protected-values",
    ticket_id: pasteTicketId,
    ops_chat_session: pasteSession,
    ticket_context: pasteTicket,
    agent_cleanup: pasteAgentCleanup,
    cleanup: pasteCleanup,
  });

  const softwareMarker = `${marker}-software`;
  const softwareText = await sendMessage(
    chatPage,
    `Please open a request for Casey to get 7-Zip installed on her laptop next week. Marker ${softwareMarker}`,
    /Dashboard ticket: #|I created ticket #|Ticket #/,
    900000,
    softwareMarker,
  );
  const softwareSegment = softwareText.slice(softwareText.lastIndexOf(softwareMarker));
  if (/\/secure-intake\//i.test(softwareSegment)) {
    throw new Error("non-sensitive software request incorrectly produced a secure intake form");
  }
  const softwareTicketId = latestTicketAfter(softwareText, softwareMarker);
  if (!softwareTicketId) throw new Error("non-sensitive software request did not create a ticket");
  const softwareAgentCleanup = await cleanupAgent(context, softwareTicketId);
  const softwareCleanup = await cleanupTicket(context, softwareTicketId);
  results.push({
    scenario: "non-sensitive-ticket",
    ticket_id: softwareTicketId,
    agent_cleanup: softwareAgentCleanup,
    cleanup: softwareCleanup,
  });

  const harmlessMarker = `${marker}-harmless`;
  const harmlessText = await sendMessage(
    chatPage,
    `Quick check marker ${harmlessMarker}: what is the capital of Wyoming?`,
    /Cheyenne|Wyoming/i,
    900000,
    harmlessMarker,
  );
  const harmlessSegment = harmlessText.slice(harmlessText.lastIndexOf(harmlessMarker));
  if (/\/secure-intake\//i.test(harmlessSegment)) {
    throw new Error("harmless general question incorrectly produced a secure intake form");
  }
  if (/Dashboard ticket: #|I created ticket #/i.test(harmlessSegment)) {
    throw new Error("harmless general question incorrectly created a ticket");
  }
  results.push({
    scenario: "harmless-no-ticket",
    ticket_id: null,
    secure_form: false,
  });

  return {
    status: "passed",
    scenario: "judgment",
    cases: results,
  };
}

async function runAccountE2EScenario(context, chatPage, formPage) {
  const accountMarker = `${marker}-account-e2e`;
  const userSuffix = marker.replace(/[^a-zA-Z0-9]/g, "").toLowerCase().slice(-10) || String(Date.now()).slice(-6);
  const username = `secure_e2e_${userSuffix}`;
  const password = `Tmp-${crypto.randomBytes(12).toString("base64url")}-ReadOnly42`;
  const firstText = await sendMessage(
    chatPage,
    [
      `Dashboard account provisioning test marker ${accountMarker}.`,
      `Please create a local Agentic Operations dashboard account named ${username}.`,
      "It should be read-only/auditor access.",
      "Collect what you need from me and then complete the account setup.",
    ].join(" "),
    /\/secure-intake\/|protected information|protected values|intake/i,
    900000,
    accountMarker,
  );
  const firstSegment = firstText.slice(firstText.lastIndexOf(accountMarker));
  if (/Dashboard ticket: #|I created ticket #/i.test(firstSegment)) {
    throw new Error("account E2E created a ticket before brokering protected values");
  }
  const formUrl = await waitForSecureLinkAfter(chatPage, accountMarker, 240000);
  const form = await getFormPayload(context, formUrl);
  const fields = form.fields || [];
  const labels = fields.map((field) => String(field.label || field.key || "").toLowerCase()).join(" | ");
  if (!/password|credential|passcode/.test(labels)) {
    throw new Error(`account E2E form did not request a credential/password field: ${labels}`);
  }
  const overrides = {};
  for (const field of fields) {
    const type = String(field.type || "").toLowerCase();
    const label = String(field.label || field.key || "").toLowerCase();
    if (type === "credential" || label.includes("password") || label.includes("credential") || label.includes("passcode")) {
      overrides[field.key] = password;
    } else if (type === "username" || label.includes("username")) {
      overrides[field.key] = username;
    }
  }
  const { values, generated } = generatedFormValues(fields, overrides);
  const requestRef = await submitSecureForm(formPage, formUrl, values);
  await verifyRequestNoLeak(context, requestRef || form.request_ref, generated);

  const finishMarker = `${accountMarker}-finish`;
  const finishText = await sendMessage(
    chatPage,
    [
      `I submitted the secure form for marker ${finishMarker}.`,
      "Please finish the account setup now.",
    ].join(" "),
    /Dashboard ticket: #|I created ticket #|Ticket #/,
    900000,
    finishMarker,
  );
  const ticketId = latestTicketAfter(finishText, finishMarker);
  if (!ticketId) throw new Error("account E2E finish request did not create a ticket");
  const finalContext = await waitForTicketTerminal(context, ticketId, 900000);
  const ticketStatus = String(finalContext.ticket?.status || "").toLowerCase();
  if (!["resolved", "closed", "implemented"].includes(ticketStatus)) {
    throw new Error(`account E2E ticket did not complete; status=${finalContext.ticket?.status}`);
  }
  await waitForChatClosure(chatPage, ticketId, username, 240000);
  const loginProof = await verifyDashboardLoginUi(context, username, password);
  const contextProof = await getTicketContext(context, ticketId);
  const contextText = JSON.stringify(contextProof);
  if (contextText.includes(password)) {
    throw new Error("account E2E ticket context leaked the generated password");
  }
  return {
    status: "passed",
    scenario: "account-e2e",
    username,
    ticket_id: ticketId,
    ticket_status: finalContext.ticket?.status,
    secure_request_ref: requestRef || form.request_ref,
    field_count: fields.length,
    login: loginProof,
    raw_password_printed: false,
  };
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

    const scenarios = scenario === "all" ? ["fallback", "direct", "redaction", "judgment", "account-e2e"] : [scenario];
    const results = [];
    for (const item of scenarios) {
      if (item === "fallback") results.push(await runFallbackScenario(context, chatPage, formPage));
      else if (item === "direct") results.push(await runDirectScenario(context, chatPage, formPage));
      else if (item === "redaction") results.push(await runRedactionScenario(context, chatPage));
      else if (item === "judgment") results.push(await runJudgmentScenario(context, chatPage, formPage));
      else if (item === "account-e2e") results.push(await runAccountE2EScenario(context, chatPage, formPage));
      else throw new Error(`unknown OPS_CHAT_SENSITIVE_SCENARIO=${scenario}`);
    }

    await browser.close();
    console.log(JSON.stringify({
      status: "passed",
      marker,
      scenario,
      user: opsChatUser,
      results,
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
