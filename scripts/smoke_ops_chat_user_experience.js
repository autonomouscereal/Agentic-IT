#!/usr/bin/env node
/*
 * End-user Ops Chat UX proof through Element.
 *
 * This drives the real browser UI: Keycloak login, direct message to the
 * Matrix appservice bot, first-turn general answer, contextual follow-up,
 * operational ticket creation, cancellation of the correct ticket, and a new
 * replacement ticket in the same room.
 */

const { chromium } = require("playwright");

const opsChatUrl = process.env.OPS_CHAT_URL || "https://127.0.0.1:3303";
const opsChatUser = process.env.OPS_CHAT_USER || "";
const opsChatPassword = process.env.OPS_CHAT_PASSWORD || "";
const ignoreHttpsErrors = /^(1|true|yes|on)$/i.test(process.env.PLAYWRIGHT_IGNORE_HTTPS_ERRORS || "");
const marker = process.env.OPS_CHAT_UX_MARKER || `ops-chat-ux-${Date.now()}`;
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
    await page.waitForTimeout(300);
  }
}

async function clearDialogs(page) {
  for (let i = 0; i < 8; i += 1) {
    const dialogText = await page.locator("#mx_Dialog_Container").innerText().catch(() => "");
    const dialogVisible = await page.locator("#mx_Dialog_Container .mx_Dialog_background, #mx_Dialog_Container [role='dialog']").first().isVisible().catch(() => false);
    if (!dialogText.trim() && !dialogVisible) return;
    if (!dialogText.trim() && dialogVisible) {
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(1000);
      continue;
    }
    if (/Confirm encryption setup/i.test(dialogText)) {
      await page.getByRole("button", { name: /^Confirm$/i }).last().click({ force: true }).catch(async () => {
        await clickText(page, /^Confirm$/i, "last");
      });
      await page.waitForTimeout(3000);
      continue;
    }
    if (/Use Single Sign On to continue|Single Sign On/i.test(dialogText)) {
      await page.getByRole("button", { name: /Single Sign On/i }).last().click({ force: true }).catch(async () => {
        await clickText(page, /Single Sign On/i, "last");
      });
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
        await page.waitForTimeout(1500);
        break;
      }
    }
    if (!clicked) {
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(1000);
    }
  }
}

async function settleElement(page) {
  for (let i = 0; i < 8; i += 1) {
    const body = await page.locator("body").innerText().catch(() => "");
    if (/Confirm your digital identity|reset your digital identity/i.test(body)) {
      await page.keyboard.press("Escape").catch(() => {});
      if (/Can't confirm\?|Can.t confirm\?/i.test(body)) {
        await page.getByText(/Can't confirm\?|Can.t confirm\?/i).first().click({ force: true }).catch(async () => {
          await clickText(page, /Can't confirm\?|Can.t confirm\?/i, "first");
        });
        await page.waitForTimeout(1500);
      }
      if (/Are you sure you want to reset your digital identity/i.test(await page.locator("body").innerText().catch(() => ""))) {
        await page.getByRole("button", { name: /^Continue$/i }).first().click({ force: true }).catch(async () => {
          await clickText(page, /^Continue$/i, "first");
        });
        await page.waitForTimeout(5000);
        continue;
      }
      if (/Remove this device/i.test(await page.locator("body").innerText().catch(() => ""))) {
        await page.getByText(/Remove this device/i).first().click({ force: true }).catch(async () => {
          await clickText(page, /Remove this device/i, "first");
        });
        await page.waitForTimeout(2500);
      }
      await clickText(page, /^(Cancel|Skip|Later|Continue|Done)$/i, "last");
      await page.waitForTimeout(2500);
      continue;
    }
    if (/Are you sure you want to reset your digital identity/i.test(body)) {
      await clickText(page, /^Continue$/i, "first");
      await page.waitForTimeout(5000);
      continue;
    }
    if (/Enter your account password|Confirm reset/i.test(body)) {
      if (await page.locator('input[type="password"]').isVisible().catch(() => false)) {
        await page.locator('input[type="password"]').fill(opsChatPassword);
        await clickText(page, /^(Continue|Reset|Confirm)$/i, "first");
        await page.waitForTimeout(8000);
        continue;
      }
    }
    if (/Save your Security Key|Security Key|Recovery Key|Download|Copy/i.test(body)) {
      await clickText(page, /^(Continue|Done|Skip)$/i, "last");
      await page.waitForTimeout(3000);
      continue;
    }
    if (/Device verified/i.test(body)) {
      await clickText(page, /^Done$/i, "last");
      await page.waitForTimeout(2000);
      continue;
    }
    if (/Confirm encryption setup/i.test(body)) {
      await page.getByRole("button", { name: /^Confirm$/i }).last().click({ force: true }).catch(async () => {
        await clickText(page, /^Confirm$/i, "last");
      });
      await page.waitForTimeout(4000);
      continue;
    }
    if (/Use Single Sign On to continue|Single Sign On/i.test(body)) {
      if (await clickText(page, /^Single Sign On$/i, "first")) {
        await page.waitForTimeout(4000);
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

async function login(page) {
  requireSecret("OPS_CHAT_USER", opsChatUser);
  requireSecret("OPS_CHAT_PASSWORD", opsChatPassword);
  await page.goto(opsChatUrl, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});
  if (!page.url().includes("#/login")) {
    const signIn = page.getByRole("link", { name: /^Sign in$/i }).first();
    if (await signIn.isVisible().catch(() => false)) {
      await signIn.click();
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
  await page.waitForTimeout(12000);
  const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
  if (/Can't connect to homeserver|Cannot reach homeserver|login provider is unavailable|missing_session|No session cookie/i.test(body)) {
    throw new Error(`Element login failed: ${body.slice(0, 600)}`);
  }
  await settleElement(page);
}

async function openAgentDm(page) {
  await page.goto(`${opsChatUrl.replace(/\/$/, "")}/#/user/@agentic-ops:agentic-ops.local`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(5000);
  await settleElement(page);
  await clearDialogs(page);
  const sendMessage = page.getByRole("button", { name: /Send message|Message/i }).first();
  if (await sendMessage.isVisible().catch(() => false)) {
    await sendMessage.click({ force: true });
    await page.waitForTimeout(5000);
  }
  if (!(await page.locator('textarea[placeholder*="Message"], [aria-label*="Message"], [contenteditable="true"], [role="textbox"], div[aria-label*="Send a message"]').last().isVisible().catch(() => false))) {
    await clickText(page, /Send message/i, "last");
    await page.waitForTimeout(5000);
  }
  if (await page.getByText(/Start a chat with this new contact/i).first().isVisible().catch(() => false)) {
    const cont = page.getByRole("button", { name: /^Continue$/i }).last();
    if (await cont.isVisible().catch(() => false)) await cont.click({ force: true });
    else await clickText(page, /^Continue$/i, "last");
    await page.waitForTimeout(5000);
  }
  await settleElement(page);
  await clearDialogs(page);
  await composer(page);
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
  const dialog = await page.locator("#mx_Dialog_Container").innerText().catch(() => "");
  throw new Error(`Element composer not found. url=${page.url()} dialog=${dialog.replace(/\s+/g, " ").slice(0, 800)} body=${body}`);
}

async function sendMessage(page, message, expectPattern, timeout = 180000, options = {}) {
  await settleElement(page);
  await clearDialogs(page);
  await dismissNoise(page);
  const before = await page.locator("body").innerText().catch(() => "");
  const beforeTicketCount = Array.from(before.matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi)).length;
  const input = await composer(page);
  await clearDialogs(page);
  await input.click({ force: true });
  await input.fill(message).catch(async () => input.type(message));
  await page.keyboard.press("Enter");
  const typingSeen = await page.getByText(/typing/i).first().isVisible({ timeout: 5000 }).catch(() => false);
  await page.waitForFunction(
    ({ source, beforeText, ticketCountMustIncrease, beforeTicketCount }) => {
      const regex = new RegExp(source, "i");
      const text = document.body.innerText || "";
      if (text.length <= beforeText.length || !regex.test(text)) return false;
      if (ticketCountMustIncrease) {
        const count = Array.from(text.matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi)).length;
        return count > beforeTicketCount;
      }
      return true;
    },
    { source: expectPattern.source, beforeText: before, ticketCountMustIncrease: !!options.ticketCountMustIncrease, beforeTicketCount },
    { timeout },
  );
  await page.waitForTimeout(1000);
  const body = (await page.locator("body").innerText()).replace(/\s+/g, " ");
  return { body, before: before.replace(/\s+/g, " "), typingSeen };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ ignoreHTTPSErrors: ignoreHttpsErrors, viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  try {
    await login(page);
    await openAgentDm(page);
    await maybeScreenshot(page, "ops-chat-ux-open");

    const china = await sendMessage(
      page,
      `hi can you tell me the price of watermelon in china? Marker ${marker}`,
      /watermelon|RMB|China|kg|USD|US\$/,
    );
    if (
      /Agentic Ops is connected\. Send me an operational request/i.test(china.body)
      && !/Agentic Ops is connected\. Send me an operational request/i.test(china.before)
    ) {
      throw new Error("blanket connected message appeared as the first user-facing answer");
    }
    if (/US\/usr\/bin\/bash|usr\/bin\/bash/i.test(china.body)) {
      throw new Error("shell expansion artifact appeared in currency answer");
    }

    const africa = await sendMessage(page, "what about in africa", /Africa|Kenya|Egypt|South Africa|kg/);
    const watermelon = await sendMessage(
      page,
      "okay, can you put in a ticket to purchase a watermelon for alice's birthday present on Friday",
      /Dashboard ticket: #|I created ticket #/,
      180000,
      { ticketCountMustIncrease: true },
    );
    const ticketMatches = Array.from(watermelon.body.matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi));
    const watermelonTicket = ticketMatches.length ? Number(ticketMatches[ticketMatches.length - 1][1]) : null;
    if (!watermelonTicket) throw new Error("watermelon request did not expose a dashboard ticket id");

    const cancel = await sendMessage(
      page,
      "Nevermind cancel that ticket she is allergic to watermelons",
      new RegExp(`cancelled ticket #${watermelonTicket}|canceled ticket #${watermelonTicket}|ticket #${watermelonTicket} has been cancelled|updated ticket #${watermelonTicket}|ticket #${watermelonTicket} status update`, "i"),
    );
    if (/I created ticket #/i.test(cancel.body.slice(cancel.body.lastIndexOf("Nevermind")))) {
      throw new Error("cancellation looked like a ticket-created response");
    }

    const pizza = await sendMessage(
      page,
      "can you instead order pizza or put in a ticket to order pizza",
      /Dashboard ticket: #|I created ticket #/,
      180000,
      { ticketCountMustIncrease: true },
    );
    const allTicketMatches = Array.from(pizza.body.matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi));
    const pizzaTicket = allTicketMatches.length ? Number(allTicketMatches[allTicketMatches.length - 1][1]) : null;
    if (!pizzaTicket || pizzaTicket === watermelonTicket) {
      throw new Error(`pizza request did not create a distinct ticket. watermelon=${watermelonTicket} pizza=${pizzaTicket}`);
    }

    await maybeScreenshot(page, "ops-chat-ux-complete");
    await browser.close();
    console.log(JSON.stringify({
      status: "passed",
      marker,
      user: opsChatUser,
      typing_seen: {
        china: china.typingSeen,
        africa: africa.typingSeen,
        watermelon: watermelon.typingSeen,
        cancel: cancel.typingSeen,
        pizza: pizza.typingSeen,
      },
      tickets: { watermelon: watermelonTicket, pizza: pizzaTicket },
    }, null, 2));
  } catch (error) {
    await maybeScreenshot(page, "ops-chat-ux-failed").catch(() => {});
    await browser.close();
    console.error(JSON.stringify({ status: "failed", marker, error: String(error && error.message || error) }, null, 2));
    process.exit(2);
  }
})();
