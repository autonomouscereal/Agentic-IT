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
const sendChatMessage = /^(1|true|yes|on)$/i.test(process.env.OPS_CHAT_SEND_MESSAGE || "");
const testOutbound = /^(1|true|yes|on)$/i.test(process.env.OPS_CHAT_TEST_OUTBOUND || "");
const chatMarker = process.env.OPS_CHAT_MARKER || `ops-chat-playwright-${Date.now()}`;
const chatMessage = process.env.OPS_CHAT_TEST_MESSAGE || `I cannot log into my Keycloak account demo_account_1 before a customer call. Please create a traceable ticket and help me. Marker ${chatMarker}`;
const ignoreHttpsErrors = /^(1|true|yes|on)$/i.test(process.env.PLAYWRIGHT_IGNORE_HTTPS_ERRORS || "");
const screenshotDir = process.env.PLAYWRIGHT_SCREENSHOT_DIR || "";
const dashboardServiceToken = process.env.DASHBOARD_SERVICE_TOKEN || "";
const allowIdentityReset = !/^(0|false|no|off)$/i.test(process.env.OPS_CHAT_ALLOW_IDENTITY_RESET || "true");

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

async function dismissElementIdentityModals(page) {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
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
      && !/Confirm your digital identity|Are you sure you want to reset your digital identity|Use Single Sign On to continue|Device verified/i.test(body)
    ) {
      return;
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
async function sendOpsChatMessage(page) {
  await dismissIfVisible(page, /Dismiss|Not now|Maybe later/i);
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
  await dismissElementIdentityModals(page);
  await dismissIfVisible(page, /Dismiss|Not now|Maybe later/i);
  await clickElementRoleButtonByText(page, /^Dismiss$/i, "first");
  await page.waitForTimeout(500);
  const clickedLater = await clickElementRoleButtonByText(page, /^Later$/i, "first");
  if (clickedLater) {
    await page.waitForTimeout(1000);
  }
  if (await page.getByText(/Start a chat with this new contact/i).first().isVisible().catch(() => false)) {
    const continueNewContact = page.getByRole("button", { name: /^Continue$/i }).last();
    if (await continueNewContact.isVisible().catch(() => false)) {
      await continueNewContact.click({ force: true });
    } else {
      await clickVisibleElementText(page, /^Continue$/i, "last");
    }
    await page.waitForTimeout(5000);
  }
  await dismissElementIdentityModals(page);
  let directComposerReady = await page.locator('textarea[placeholder*="Message"], [aria-label*="Message"], [contenteditable="true"], [role="textbox"], div[aria-label*="Send a message"]').last().isVisible().catch(() => false);
  if (!directComposerReady) {
    const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
    if (/Are you sure you want to reset your digital identity|Confirm your digital identity/i.test(body)) {
      await dismissElementIdentityModals(page);
      const sendAgain = page.getByRole("button", { name: /Send message|Message/i }).first();
      if (await sendAgain.isVisible().catch(() => false)) {
        await sendAgain.click({ force: true }).catch(() => {});
        await page.waitForTimeout(4000);
      }
      await dismissElementIdentityModals(page);
      directComposerReady = await page.locator('textarea[placeholder*="Message"], [aria-label*="Message"], [contenteditable="true"], [role="textbox"], div[aria-label*="Send a message"]').last().isVisible().catch(() => false);
    }
  }
  if (directComposerReady) {
    const message = chatMessage.includes(chatMarker) ? chatMessage : `${chatMessage} Marker ${chatMarker}`;
    const beforeText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
    const beforeTickets = Array.from(beforeText.matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi)).map((match) => Number(match[1]));
    await sendComposerMessage(page, message);
    await page.waitForFunction(
      ({ beforeTickets }) => {
        const text = document.body.innerText || "";
        const ids = Array.from(text.matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi)).map((match) => Number(match[1]));
        return ids.some((id) => !beforeTickets.includes(id));
      },
      { beforeTickets },
      { timeout: 180000 },
    );
    await maybeScreenshot(page, "ops-chat-message");
    const text = (await page.locator("body").innerText()).replace(/\s+/g, " ");
    const matches = Array.from(text.matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi));
    const match = matches.map((item) => Number(item[1])).find((id) => !beforeTickets.includes(id));
    if (!match) throw new Error("Ops Chat did not expose a newly-created dashboard ticket id after the message");
    return { marker: chatMarker, ticketId: match };
  }
  const directMessage = page.getByText(/Send a Direct Message/i).first();
  if (await directMessage.isVisible().catch(() => false)) {
    await directMessage.click({ force: true });
  } else {
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
    'input[type="text"]',
  ];
  let addressed = false;
  for (const selector of searchInputs) {
    const input = page.locator(selector).last();
    if (await input.isVisible().catch(() => false)) {
      await input.fill("@agentic-ops:agentic-ops.local");
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
  const message = chatMessage.includes(chatMarker) ? chatMessage : `${chatMessage} Marker ${chatMarker}`;
  const beforeText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
  const beforeTickets = Array.from(beforeText.matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi)).map((match) => Number(match[1]));
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
  await page.waitForFunction(
    ({ beforeTickets }) => {
      const text = document.body.innerText || "";
      const ids = Array.from(text.matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi)).map((match) => Number(match[1]));
      return ids.some((id) => !beforeTickets.includes(id));
    },
    { beforeTickets },
    { timeout: 180000 },
  );
  await maybeScreenshot(page, "ops-chat-message");
  const text = (await page.locator("body").innerText()).replace(/\s+/g, " ");
  const matches = Array.from(text.matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi));
  const match = matches.map((item) => Number(item[1])).find((id) => !beforeTickets.includes(id));
  if (!match) throw new Error("Ops Chat did not expose a newly-created dashboard ticket id after the message");
  return { marker: chatMarker, ticketId: match };
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
