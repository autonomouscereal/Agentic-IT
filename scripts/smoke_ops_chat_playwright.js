#!/usr/bin/env node
/*
 * Browser-level smoke for the Agentic Operations dashboard and Ops Chat.
 *
 * Requires the Playwright npm package to be available in NODE_PATH or the
 * current working directory. The API container includes Playwright; operator
 * workstations can run `npm install playwright && npx playwright install
 * chromium` in a temporary directory.
 *
 * Secrets are read from environment variables and are never printed.
 */

const { chromium } = require("playwright");

const dashboardUrl = process.env.DASHBOARD_URL || "https://127.0.0.1:25443";
const dashboardUser = process.env.DASHBOARD_USER || "demo_account_1";
const dashboardPassword = process.env.DASHBOARD_PASSWORD || "";
const opsChatUrl = process.env.OPS_CHAT_URL || "https://127.0.0.1:3303";
const opsChatUser = process.env.OPS_CHAT_USER || "";
const opsChatPassword = process.env.OPS_CHAT_PASSWORD || "";
const opsChatRoomId = process.env.OPS_CHAT_ROOM_ID || "";
const sendChatMessage = /^(1|true|yes|on)$/i.test(process.env.OPS_CHAT_SEND_MESSAGE || "");
const testOutbound = /^(1|true|yes|on)$/i.test(process.env.OPS_CHAT_TEST_OUTBOUND || "");
const chatMarker = process.env.OPS_CHAT_MARKER || `ops-chat-playwright-${Date.now()}`;
const chatMessage = process.env.OPS_CHAT_TEST_MESSAGE || `I cannot log into my Keycloak account demo_account_1 before a customer call. Please create a traceable ticket and help me. Marker ${chatMarker}`;
const ignoreHttpsErrors = /^(1|true|yes|on)$/i.test(process.env.PLAYWRIGHT_IGNORE_HTTPS_ERRORS || "");
const screenshotDir = process.env.PLAYWRIGHT_SCREENSHOT_DIR || "";
const dashboardServiceToken = process.env.DASHBOARD_SERVICE_TOKEN || "";
const allowIdentityReset = /^(1|true|yes|on)$/i.test(process.env.OPS_CHAT_ALLOW_IDENTITY_RESET || "false");

function requireSecret(name, value) {
  if (!value) {
    throw new Error(`${name} is required`);
  }
}

async function maybeScreenshot(page, name) {
  if (!screenshotDir) return;
  const path = `${screenshotDir.replace(/[\\/]$/, "")}/${name}.png`;
  await page.screenshot({ path, fullPage: true });
}

async function dismissIfVisible(page, pattern) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const button = page.getByRole("button", { name: pattern }).first();
    if (await button.isVisible().catch(() => false)) {
      await button.click({ force: true }).catch(() => {});
      await page.waitForTimeout(500);
      continue;
    }
    const text = page.getByText(pattern).first();
    if (await text.isVisible().catch(() => false)) {
      await text.click({ force: true }).catch(() => {});
      await page.waitForTimeout(500);
    }
  }
}

function ticketMentions(text) {
  const pattern = /(?:Dashboard ticket: #|I created ticket #|I updated ticket #|Agent completed this request for ticket #|Ticket #)(\d+)/gi;
  return Array.from(String(text || "").matchAll(pattern)).map((match) => Number(match[1]));
}

function ticketMentionsAfterMarker(text, marker) {
  const fullText = String(text || "");
  const markerIndex = marker ? fullText.lastIndexOf(marker) : -1;
  if (markerIndex < 0) return [];
  return ticketMentions(fullText.slice(markerIndex));
}

async function lookupTicketByMarker(marker) {
  if (!dashboardServiceToken || !marker) return null;
  const baseUrl = dashboardUrl.replace(/\/$/, "");
  const response = await fetch(`${baseUrl}/api/search/global?q=${encodeURIComponent(marker)}&limit=10`, {
    headers: { "X-Dashboard-Service-Token": dashboardServiceToken },
  }).catch(() => null);
  if (!response || !response.ok) return null;
  const payload = await response.json().catch(() => null);
  const result = (payload?.results || []).find((item) => item.type === "ticket" && Number(item.id));
  return result ? Number(result.id) : null;
}

async function waitForTicketMentionAfter(page, beforeCount, marker = "") {
  await page.waitForFunction(
    ({ beforeCount, marker }) => {
      const text = document.body.innerText || "";
      if (marker && text.includes(marker)) {
        const segment = text.slice(text.lastIndexOf(marker));
        const pattern = /(?:Dashboard ticket: #|I created ticket #|I updated ticket #|Agent completed this request for ticket #|Ticket #)(\d+)/gi;
        if (Array.from(segment.matchAll(pattern)).length > 0) return true;
      }
      const pattern = /(?:Dashboard ticket: #|I created ticket #|I updated ticket #|Agent completed this request for ticket #|Ticket #)(\d+)/gi;
      return Array.from(text.matchAll(pattern)).length > beforeCount;
    },
    { beforeCount, marker },
    { timeout: 180000 },
  );
  const text = (await page.locator("body").innerText()).replace(/\s+/g, " ");
  const markerTicketId = await lookupTicketByMarker(marker);
  if (markerTicketId) return markerTicketId;
  const markerMentions = ticketMentionsAfterMarker(text, marker);
  const mentions = markerMentions.length ? markerMentions : ticketMentions(text);
  const ticketId = mentions[mentions.length - 1];
  if (!ticketId) throw new Error("Ops Chat did not expose a dashboard ticket id after the message");
  return ticketId;
}

async function dismissElementIdentityModals(page) {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
    if (/Confirm encryption setup/i.test(body)) {
      const cancelled = await clickDialogButton(page, /^Cancel$/i, "last")
        || await clickElementRoleButtonByText(page, /^Cancel$/i, "last")
        || await clickVisibleElementText(page, /^Cancel$/i, "last");
      if (cancelled) {
        await page.waitForTimeout(1500);
        continue;
      }
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(1000);
      continue;
    }
    if (/Verify this device/i.test(body)) {
      const later = await clickDialogButton(page, /^Later$/i, "last")
        || await clickElementRoleButtonByText(page, /^Later$/i, "last")
        || await clickVisibleElementText(page, /^Later$/i, "last");
      if (later) {
        await page.waitForTimeout(1500);
        continue;
      }
    }
    if (/Are you sure\?|Without verifying|I'll verify later/i.test(body)) {
      const later = await clickDialogButton(page, /^I'll verify later$/i, "last")
        || await clickElementRoleButtonByText(page, /^I'll verify later$/i, "last")
        || await clickVisibleElementText(page, /^I'll verify later$/i, "last");
      if (later) {
        await page.waitForTimeout(2500);
        continue;
      }
    }
    if (/Are you sure you want to reset your digital identity/i.test(body)) {
      if (allowIdentityReset) {
        const continueButton = page.getByRole("button", { name: /^Continue$/i }).first();
        if (await continueButton.isVisible().catch(() => false)) {
          await continueButton.click({ force: true });
          await page.waitForTimeout(8000);
          continue;
        }
        const resetClicked = await clickVisibleElementText(page, /^Continue$/i, "first");
        if (resetClicked) {
          await page.waitForTimeout(8000);
          continue;
        }
      } else {
        await page.keyboard.press("Escape").catch(() => {});
        await page.waitForTimeout(1000);
        const afterEscape = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
        if (!/Are you sure you want to reset your digital identity/i.test(afterEscape)) {
          continue;
        }
        const cancelClicked = await clickVisibleElementText(page, /^Cancel$/i, "last");
        if (cancelClicked) {
          await page.waitForTimeout(1500);
          continue;
        }
      }
    }
    if (/Enter your account password|Confirm reset/i.test(body) && allowIdentityReset) {
      if (await page.locator('input[type="password"]').isVisible().catch(() => false)) {
        await page.locator('input[type="password"]').fill(opsChatPassword);
        const confirmClicked = await clickVisibleElementText(page, /^(Continue|Reset|Confirm)$/i, "first");
        if (confirmClicked) {
          await page.waitForTimeout(10000);
          continue;
        }
      }
    }
    if (/Save your Security Key|Security Key|Recovery Key|Download|Copy/i.test(body) && allowIdentityReset) {
      const continueClicked = await clickVisibleElementText(page, /^(Continue|Done|Skip)$/i, "last");
      if (continueClicked) {
        await page.waitForTimeout(5000);
        continue;
      }
    }
    if (/Confirm your digital identity/i.test(body)) {
      const closed = await clickDialogUntitledClose(page);
      if (closed) {
        await page.waitForTimeout(1500);
        continue;
      }
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(1000);
      const afterEscape = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
      if (!/Confirm your digital identity/i.test(afterEscape)) {
        continue;
      }
      const cantConfirm = page.getByText(/Can't confirm\?|Can.t confirm\?/i).first();
      if (await cantConfirm.isVisible().catch(() => false)) {
        await cantConfirm.click({ force: true });
        await page.waitForTimeout(1500);
        continue;
      }
      const laterClicked = await clickVisibleElementText(page, /^(Skip|Later|Cancel)$/i, "last");
      if (laterClicked) {
        await page.waitForTimeout(1500);
        continue;
      }
    }
    if (/Device verified/i.test(body)) {
      const doneClicked = await clickVisibleElementText(page, /^Done$/i, "last");
      if (doneClicked) {
        await page.waitForTimeout(1500);
        continue;
      }
    }
    break;
  }
}

async function dashboardLogin(page) {
  requireSecret("DASHBOARD_PASSWORD", dashboardPassword);
  await page.goto(dashboardUrl, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});
  if (!page.url().includes("/login")) {
    await page.goto(`${dashboardUrl.replace(/\/$/, "")}/login`, { waitUntil: "domcontentloaded" });
  }
  await page.locator('input[name="username"], input#username').first().fill(dashboardUser);
  await page.locator('input[name="password"], input#password').first().fill(dashboardPassword);
  await page.locator('button[type="submit"], input[type="submit"]').first().click();
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.getByText(/Agentic Operations|Overview|Tickets|Agents/i).first().waitFor({ state: "visible", timeout: 60000 });
  await maybeScreenshot(page, "dashboard-login");
  return page.url();
}

async function opsChatLoginAndProbe(page) {
  requireSecret("OPS_CHAT_USER", opsChatUser);
  requireSecret("OPS_CHAT_PASSWORD", opsChatPassword);
  await page.goto(opsChatUrl, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});
  if (!page.url().includes("#/login")) {
    const signInLink = page.getByRole("link", { name: /^Sign in$/i }).first();
    if (await signInLink.isVisible().catch(() => false)) {
      await signInLink.click();
      await page.waitForLoadState("networkidle").catch(() => {});
    }
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
    throw new Error(`Ops Chat login landed in error state: ${body.slice(0, 500)}`);
  }
  await settleElementIdentity(page);
  try {
    await page.getByText(/Home|Start chat|No chats yet|Search|Send a Direct Message|Rooms|People/i).first().waitFor({ state: "visible", timeout: 90000 });
  } catch (error) {
    const finalBody = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 800);
    throw new Error(`Ops Chat login did not reach the Element home screen. url=${page.url()} body=${finalBody}`);
  }
  await dismissIfVisible(page, /Dismiss|Not now|Maybe later/i);
  const matrixProbe = await page.evaluate(async () => {
    const response = await fetch("/_matrix/client/versions", { credentials: "same-origin" });
    return { ok: response.ok, status: response.status, body: (await response.text()).slice(0, 200) };
  });
  if (!matrixProbe.ok) {
    throw new Error(`same-origin Matrix probe failed: ${JSON.stringify(matrixProbe)}`);
  }
  await maybeScreenshot(page, "ops-chat-login");
  return { url: page.url(), matrixProbe };
}

async function settleElementIdentity(page) {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
    if (
      /Home|Start chat|No chats yet|Search|Send a Direct Message|Rooms|People/i.test(body)
      && !/Confirm encryption setup|Verify this device|Without verifying|I'll verify later|Confirm your digital identity|Are you sure you want to reset your digital identity|Use Single Sign On to continue|Device verified/i.test(body)
    ) {
      return;
    }
    if (/Confirm encryption setup|Verify this device|Without verifying|I'll verify later/i.test(body)) {
      await dismissElementIdentityModals(page);
      await page.waitForTimeout(1000);
      continue;
    }
    if (/Confirm your digital identity|Are you sure you want to reset your digital identity/i.test(body)) {
      await dismissElementIdentityModals(page);
      await page.waitForTimeout(1500);
      const cant = page.getByText(/Can't confirm\?|Can.t confirm\?/i).first();
      if (await cant.isVisible().catch(() => false)) {
        await cant.click({ force: true });
        await page.waitForTimeout(750);
      }
    }
    if (/Device verified/i.test(body)) {
      const clickedDone = await clickElementRoleButtonByText(page, /^Done$/i);
      if (clickedDone) {
        await page.waitForTimeout(3000);
        continue;
      }
      const done = page.getByRole("button", { name: /Done/i }).last();
      if (await done.isVisible().catch(() => false)) {
        await done.click({ force: true });
        await page.waitForTimeout(3000);
        continue;
      }
      const doneRole = page.locator('[role="button"]').filter({ hasText: /^Done$/i }).last();
      if (await doneRole.isVisible().catch(() => false)) {
        await doneRole.click({ force: true });
        await page.waitForTimeout(3000);
        continue;
      }
      const doneText = page.getByText(/^Done$/i).last();
      if (await doneText.isVisible().catch(() => false)) {
        await doneText.click({ force: true });
        await page.waitForTimeout(3000);
        continue;
      }
    }
    if (/Use Single Sign On to continue|Single Sign On/i.test(body)) {
      const clickedSso = await clickElementRoleButtonByText(page, /^Single Sign On$/i);
      if (clickedSso) {
        await page.waitForTimeout(3000);
        if (await page.locator('input[name="username"]').isVisible().catch(() => false)) {
          await page.locator('input[name="username"]').fill(opsChatUser);
          await page.locator('input[name="password"]').fill(opsChatPassword);
          await page.locator('button[type="submit"], input[type="submit"]').first().click();
        }
        await page.waitForTimeout(10000);
        continue;
      }
      const singleSignOn = page.getByRole("button", { name: /Single Sign On/i }).first();
      if (await singleSignOn.isVisible().catch(() => false)) {
        await singleSignOn.click({ force: true });
        await page.waitForTimeout(3000);
        if (await page.locator('input[name="username"]').isVisible().catch(() => false)) {
          await page.locator('input[name="username"]').fill(opsChatUser);
          await page.locator('input[name="password"]').fill(opsChatPassword);
          await page.locator('button[type="submit"], input[type="submit"]').first().click();
        }
        await page.waitForTimeout(10000);
        continue;
      }
      const singleSignOnRole = page.locator('[role="button"]').filter({ hasText: /^Single Sign On$/i }).first();
      if (await singleSignOnRole.isVisible().catch(() => false)) {
        await singleSignOnRole.click({ force: true });
        await page.waitForTimeout(3000);
        if (await page.locator('input[name="username"]').isVisible().catch(() => false)) {
          await page.locator('input[name="username"]').fill(opsChatUser);
          await page.locator('input[name="password"]').fill(opsChatPassword);
          await page.locator('button[type="submit"], input[type="submit"]').first().click();
        }
        await page.waitForTimeout(10000);
        continue;
      }
      const singleSignOnText = page.getByText(/^Single Sign On$/i).first();
      if (await singleSignOnText.isVisible().catch(() => false)) {
        await singleSignOnText.click({ force: true });
        await page.waitForTimeout(3000);
        if (await page.locator('input[name="username"]').isVisible().catch(() => false)) {
          await page.locator('input[name="username"]').fill(opsChatUser);
          await page.locator('input[name="password"]').fill(opsChatPassword);
          await page.locator('button[type="submit"], input[type="submit"]').first().click();
        }
        await page.waitForTimeout(10000);
        continue;
      }
    }
    await page.waitForTimeout(2500);
  }
}

async function clickElementRoleButtonByText(page, pattern, which = "last") {
  return await page.evaluate(({ source, which }) => {
    const regex = new RegExp(source, "i");
    const controls = Array.from(document.querySelectorAll("[role='button'],button"));
    const matches = controls.filter((el) => regex.test((el.innerText || el.textContent || "").trim()));
    const target = which === "first" ? matches[0] : matches[matches.length - 1];
    if (!target) return false;
    target.click();
    return true;
  }, { source: pattern.source, which }).catch(() => false);
}

async function clickDialogButton(page, pattern, which = "last") {
  const buttons = page.locator("#mx_Dialog_Container button, #mx_Dialog_Container [role='button']").filter({ hasText: pattern });
  const count = await buttons.count().catch(() => 0);
  if (count > 0) {
    await buttons.nth(which === "first" ? 0 : count - 1).click({ force: true }).catch(() => {});
    return true;
  }
  return false;
}

async function clickDialogUntitledClose(page) {
  const closeButtons = [
    "#mx_Dialog_Container button[aria-label*='Close']",
    "#mx_Dialog_Container [role='button'][aria-label*='Close']",
    "button[aria-label*='Close']",
    "[role='button'][aria-label*='Close']",
    "#mx_Dialog_Container button",
    "#mx_Dialog_Container [role='button']",
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

async function clickVisibleElementText(page, pattern, which = "last") {
  return await page.evaluate(({ source, which }) => {
    const regex = new RegExp(source, "i");
    const candidates = Array.from(document.querySelectorAll("button,[role='button'],a,span,div"));
    const visible = candidates.filter((el) => {
      const text = (el.innerText || el.textContent || "").trim();
      if (!regex.test(text)) return false;
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
    });
    const target = which === "first" ? visible[0] : visible[visible.length - 1];
    if (!target) return false;
    target.click();
    return true;
  }, { source: pattern.source, which }).catch(() => false);
}

async function acceptElementNewContactPrompt(page) {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
    if (!/Start a chat with this new contact|Confirm inviting them before continuing|currently don't have any chats/i.test(body)) {
      return false;
    }
    const clicked = await clickDialogButton(page, /^Continue$/i, "last")
      || await clickElementRoleButtonByText(page, /^Continue$/i, "last")
      || await clickVisibleElementText(page, /^Continue$/i, "last");
    if (clicked) {
      await page.waitForTimeout(4000);
      continue;
    }
    const buttons = page.locator("button,[role='button']").filter({ hasText: /^Continue$/i });
    const count = await buttons.count().catch(() => 0);
    if (count > 0) {
      await buttons.nth(count - 1).click({ force: true }).catch(() => {});
      await page.waitForTimeout(4000);
      continue;
    }
    return true;
  }
  return true;
}

async function sendOpsChatMessage(page) {
  await dismissIfVisible(page, /Dismiss|Not now|Maybe later/i);
  await dismissElementIdentityModals(page);
  if (opsChatRoomId) {
    await page.goto(`${opsChatUrl.replace(/\/$/, "")}/#/room/${opsChatRoomId}`, { waitUntil: "domcontentloaded" }).catch(() => {});
    await page.waitForTimeout(5000);
    await dismissElementIdentityModals(page);
    await clickExistingAgentRoom(page);
    const roomComposerReady = await page.locator('textarea[placeholder*="Message"], [aria-label*="Message"], [contenteditable="true"], [role="textbox"], div[aria-label*="Send a message"]').last().isVisible().catch(() => false);
    if (roomComposerReady) {
      const message = chatMessage.includes(chatMarker) ? chatMessage : `${chatMessage} Marker ${chatMarker}`;
      const beforeText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
      const beforeMentionCount = ticketMentions(beforeText).length;
      await sendComposerMessage(page, message);
      const ticketId = await waitForTicketMentionAfter(page, beforeMentionCount, chatMarker);
      await maybeScreenshot(page, "ops-chat-message");
      return { marker: chatMarker, ticketId };
    }
  }
  const existingBotRoom = page.getByText(/^Agentic Ops Agent$/i).first();
  if (await existingBotRoom.isVisible().catch(() => false)) {
    const clickedRoom = await clickExistingAgentRoom(page);
    if (!clickedRoom) {
      await existingBotRoom.click({ force: true }).catch(() => {});
    }
    await page.waitForTimeout(3000);
    const existingComposerReady = await page.locator('textarea[placeholder*="Message"], [aria-label*="Message"], [contenteditable="true"], [role="textbox"], div[aria-label*="Send a message"]').last().isVisible().catch(() => false);
    if (existingComposerReady) {
      const message = chatMessage.includes(chatMarker) ? chatMessage : `${chatMessage} Marker ${chatMarker}`;
      const beforeText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
      const beforeMentionCount = ticketMentions(beforeText).length;
      await sendComposerMessage(page, message);
      const ticketId = await waitForTicketMentionAfter(page, beforeMentionCount, chatMarker);
      await maybeScreenshot(page, "ops-chat-message");
      return { marker: chatMarker, ticketId };
    }
  }
  const botProfileUrl = `${opsChatUrl.replace(/\/$/, "")}/#/user/@agentic-ops:agentic-ops.local`;
  await page.goto(botProfileUrl, { waitUntil: "domcontentloaded" }).catch(() => {});
  await page.waitForTimeout(4000);
  await settleElementIdentity(page);
  await dismissElementIdentityModals(page);
  await dismissIfVisible(page, /^OK$/i);
  await dismissIfVisible(page, /Dismiss|Not now|Maybe later/i);
  const sendMessage = page.getByRole("button", { name: /Send message|Message/i }).first();
  if (await sendMessage.isVisible().catch(() => false)) {
    await sendMessage.click({ force: true });
    await page.waitForTimeout(4000);
  }
  await acceptElementNewContactPrompt(page);
  await dismissElementIdentityModals(page);
  await dismissIfVisible(page, /Dismiss|Not now|Maybe later/i);
  await clickElementRoleButtonByText(page, /^Dismiss$/i, "first");
  await page.waitForTimeout(500);
  const clickedLater = await clickElementRoleButtonByText(page, /^Later$/i, "first");
  if (clickedLater) {
    await page.waitForTimeout(1000);
  }
  await acceptElementNewContactPrompt(page);
  await dismissElementIdentityModals(page);
  let directComposerReady = await page.locator('textarea[placeholder*="Message"], [aria-label*="Message"], [contenteditable="true"], [role="textbox"], div[aria-label*="Send a message"]').last().isVisible().catch(() => false);
  if (!directComposerReady) {
    await acceptElementNewContactPrompt(page);
    const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
    if (/Are you sure you want to reset your digital identity|Confirm your digital identity/i.test(body)) {
      await dismissElementIdentityModals(page);
      const sendAgain = page.getByRole("button", { name: /Send message|Message/i }).first();
      if (await sendAgain.isVisible().catch(() => false)) {
        await sendAgain.click({ force: true }).catch(() => {});
        await page.waitForTimeout(4000);
      }
      await acceptElementNewContactPrompt(page);
      await dismissElementIdentityModals(page);
      directComposerReady = await page.locator('textarea[placeholder*="Message"], [aria-label*="Message"], [contenteditable="true"], [role="textbox"], div[aria-label*="Send a message"]').last().isVisible().catch(() => false);
    }
  }
  if (directComposerReady) {
    const message = chatMessage.includes(chatMarker) ? chatMessage : `${chatMessage} Marker ${chatMarker}`;
    const beforeText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
    const beforeMentionCount = ticketMentions(beforeText).length;
    await sendComposerMessage(page, message);
    const ticketId = await waitForTicketMentionAfter(page, beforeMentionCount, chatMarker);
    await maybeScreenshot(page, "ops-chat-message");
    return { marker: chatMarker, ticketId };
  }
  const fallbackBody = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
  const directDialogOpen = /Direct Messages|Start a conversation with someone/i.test(fallbackBody);
  const directMessage = page.getByText(/Send a Direct Message/i).first();
  if (!directDialogOpen && await directMessage.isVisible().catch(() => false)) {
    await directMessage.click({ force: true });
  } else if (!directDialogOpen) {
    await page.getByText(/Start chat|New conversation/i).first().click({ force: true });
  }
  await page.waitForTimeout(1500);
  const searchInputs = [
    'input[placeholder="Search"]',
    'input[placeholder*="Name"]',
    'input[placeholder*="email"]',
    'input[placeholder*="Matrix"]',
    'input[aria-label*="Search"]',
    '[role="combobox"] input',
    '[role="dialog"] [contenteditable="true"]',
    '.mx_Dialog [contenteditable="true"]',
    'input[type="text"]',
  ];
  let addressed = false;
  for (const selector of searchInputs) {
    const input = page.locator(selector).last();
    if (await input.isVisible().catch(() => false)) {
      await input.click({ force: true }).catch(() => {});
      await input.fill("@agentic-ops:agentic-ops.local").catch(async () => {
        await page.keyboard.type("@agentic-ops:agentic-ops.local");
      });
      addressed = true;
      break;
    }
  }
  if (!addressed) {
    const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 1000);
    if (/Are you sure you want to reset your digital identity|Confirm your digital identity/i.test(body)) {
      await dismissElementIdentityModals(page);
      if (/Are you sure you want to reset your digital identity/i.test(await page.locator("body").innerText().catch(() => "")) && allowIdentityReset) {
        await page.locator("button").filter({ hasText: /^Continue$/i }).first().click({ force: true }).catch(() => {});
      }
      await page.waitForTimeout(3000);
      const afterDismiss = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 1000);
      if (!/Are you sure you want to reset your digital identity|Confirm your digital identity/i.test(afterDismiss)) {
        return await sendOpsChatMessage(page);
      }
    }
    throw new Error(`Ops Chat direct-message address field was not found. url=${page.url()} body=${body}`);
  }
  await page.waitForTimeout(1500);
  const go = page.getByRole("button", { name: /Go|Start|Chat|Done/i }).last();
  if (await go.isVisible().catch(() => false)) {
    await go.click({ force: true });
  } else {
    await page.keyboard.press("Enter");
  }
  const continueButton = page.getByRole("button", { name: /Continue/i }).last();
  if (await continueButton.isVisible().catch(() => false)) {
    await continueButton.click({ force: true });
  }
  await page.waitForTimeout(6000);
  await acceptElementNewContactPrompt(page);
  await page.waitForTimeout(3000);
  const message = chatMessage.includes(chatMarker) ? chatMessage : `${chatMessage} Marker ${chatMarker}`;
  const beforeText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
  const beforeMentionCount = ticketMentions(beforeText).length;
  const composers = [
    'textarea[placeholder*="Message"]',
    '[aria-label*="Message"]',
    '[contenteditable="true"]',
    '[role="textbox"]',
    'div[aria-label*="Send a message"]',
  ];
  let sent = false;
  for (const selector of composers) {
    const composer = page.locator(selector).last();
    if (await composer.isVisible().catch(() => false)) {
      await composer.click();
      await composer.fill(message).catch(async () => {
        await composer.type(message);
      });
      await page.keyboard.press("Enter");
      sent = true;
      break;
    }
  }
  if (!sent) {
    const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 1000);
    throw new Error(`Ops Chat message composer was not found. url=${page.url()} body=${body}`);
  }
  const ticketId = await waitForTicketMentionAfter(page, beforeMentionCount, chatMarker);
  await maybeScreenshot(page, "ops-chat-message");
  return { marker: chatMarker, ticketId };
}

async function clickExistingAgentRoom(page) {
  const clicked = await page.evaluate(() => {
    const candidates = Array.from(document.querySelectorAll("button,[role='button'],a,span,div"));
    const match = candidates.find((el) => {
      const text = (el.innerText || el.textContent || "").trim();
      if (text !== "Agentic Ops Agent") return false;
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && rect.x >= 60 && rect.x < 430 && rect.y > 120 && rect.y < 320;
    });
    if (!match) return null;
    const rect = match.getBoundingClientRect();
    match.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: rect.x + rect.width / 2, clientY: rect.y + rect.height / 2 }));
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
  }).catch(() => null);
  if (clicked) {
    await page.waitForTimeout(4000);
    return true;
  }
  return false;
}

async function sendComposerMessage(page, message) {
  const composers = [
    'textarea[placeholder*="Message"]',
    '[aria-label*="Message"]',
    '[contenteditable="true"]',
    '[role="textbox"]',
    'div[aria-label*="Send a message"]',
  ];
  for (const selector of composers) {
    const composer = page.locator(selector).last();
    if (await composer.isVisible().catch(() => false)) {
      await composer.click();
      await composer.fill(message).catch(async () => {
        await composer.type(message);
      });
      await page.keyboard.press("Enter");
      return;
    }
  }
  throw new Error("Ops Chat message composer was not found");
}

async function verifyOutboundTicketChat(context, page, ticketId) {
  if (!testOutbound) return null;
  requireSecret("DASHBOARD_SERVICE_TOKEN", dashboardServiceToken);
  if (!ticketId) throw new Error("ticketId is required for outbound chat verification");
  const headers = { "X-Dashboard-Service-Token": dashboardServiceToken };
  const question = `What username is affected for marker ${chatMarker}?`;
  const ask = await context.request.post(`${dashboardUrl.replace(/\/$/, "")}/api/tickets/${ticketId}/request-info`, {
    headers,
    data: {
      question,
      requested_by: "playwright-ops-chat-smoke",
      contact_method: "matrix",
      recipient: opsChatUser,
      context: "Browser-level outbound Matrix delivery proof.",
    },
  });
  if (!ask.ok()) {
    throw new Error(`request-info failed: HTTP ${ask.status()} ${(await ask.text()).slice(0, 400)}`);
  }
  await page.getByText(new RegExp(`Ticket #${ticketId} needs your input`, "i")).first().waitFor({ state: "visible", timeout: 90000 });
  const reply = `The affected username is ${opsChatUser}. Marker ${chatMarker}.`;
  await sendComposerMessage(page, reply);
  await page.getByText(/I added your update to ticket #/i).first().waitFor({ state: "visible", timeout: 90000 });
  const contextResponse = await context.request.get(`${dashboardUrl.replace(/\/$/, "")}/api/tickets/${ticketId}/context`, { headers });
  if (!contextResponse.ok()) {
    throw new Error(`ticket context failed: HTTP ${contextResponse.status()} ${(await contextResponse.text()).slice(0, 400)}`);
  }
  const ticketContext = await contextResponse.json();
  const notes = ticketContext.notes || [];
  const hasResponse = notes.some((note) => String(note.body || "").includes(reply));
  if (!hasResponse) {
    throw new Error("chat follow-up was not reflected as a ticket user-response note");
  }
  await maybeScreenshot(page, "ops-chat-outbound");
  return { ticketId, outboundQuestionDelivered: true, userResponseRecorded: true };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    ignoreHTTPSErrors: ignoreHttpsErrors,
    viewport: { width: 1440, height: 1000 },
  });
  try {
    const dashboardPage = await context.newPage();
    const dashboardFinalUrl = await dashboardLogin(dashboardPage);
    const chatPage = await context.newPage();
    const chat = await opsChatLoginAndProbe(chatPage);
    const message = sendChatMessage ? await sendOpsChatMessage(chatPage) : null;
    const outbound = message ? await verifyOutboundTicketChat(context, chatPage, message.ticketId) : null;
    await browser.close();
    console.log(JSON.stringify({
      status: "passed",
      dashboard: { url: dashboardFinalUrl, user: dashboardUser },
      ops_chat: { url: chat.url, user: opsChatUser, matrix_probe: chat.matrixProbe },
      message,
      outbound,
    }, null, 2));
  } catch (error) {
    await browser.close();
    console.error(JSON.stringify({ status: "failed", error: String(error && error.message || error) }, null, 2));
    process.exit(2);
  }
})();
