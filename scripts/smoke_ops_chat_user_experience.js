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

async function clickExactText(page, exact, which = "last") {
  return await page.evaluate(({ exact, which }) => {
    const candidates = Array.from(document.querySelectorAll("button,a,[role='button'],span,div,p"));
    const visible = candidates
      .map((el) => {
        const text = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return { el, text, rect, style };
      })
      .filter((item) => (
        item.text === exact &&
        !/Remove this device|Reset all|Sign out/i.test(item.text) &&
        item.rect.width > 0 &&
        item.rect.height > 0 &&
        item.style.display !== "none" &&
        item.style.visibility !== "hidden"
      ));
    const target = which === "first" ? visible[0] : visible[visible.length - 1] || visible[0];
    if (!target) return false;
    target.el.click();
    return true;
  }, { exact, which }).catch(() => false);
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

async function clickTextRange(page, patternSource, allowDeviceRemoval = false) {
  return await page.evaluate(({ patternSource, allowDeviceRemoval }) => {
    const regex = new RegExp(patternSource, "i");
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const ranges = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const text = (node.nodeValue || "").replace(/\s+/g, " ").trim();
      if (!regex.test(text)) continue;
      const parent = node.parentElement;
      if (!parent) continue;
      const style = window.getComputedStyle(parent);
      if (style.display === "none" || style.visibility === "hidden") continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const rect = range.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) continue;
      ranges.push({ rect, parent, text });
    }
    const target = ranges
      .filter((item) => allowDeviceRemoval || !/Remove this device|Reset all|Sign out/i.test(item.text))
      .sort((a, b) => a.text.length - b.text.length)[0];
    if (!target) return false;
    const x = target.rect.left + target.rect.width / 2;
    const y = target.rect.top + target.rect.height / 2;
    const clickable = document.elementFromPoint(x, y) || target.parent;
    clickable.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, clientX: x, clientY: y }));
    clickable.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: x, clientY: y }));
    clickable.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: x, clientY: y }));
    return true;
  }, { patternSource, allowDeviceRemoval }).catch(() => false);
}

async function clickDialogUntitledClose(page) {
  for (const selector of [
    "#mx_Dialog_Container button[aria-label*='Close']",
    "#mx_Dialog_Container [role='button'][aria-label*='Close']",
    "button[aria-label*='Close']",
    "[role='button'][aria-label*='Close']",
    ".mx_Dialog_cancelButton",
    ".mx_AccessibleButton[aria-label*='Close']",
  ]) {
    const button = page.locator(selector).first();
    if (await button.isVisible().catch(() => false)) {
      await button.click({ force: true }).catch(() => {});
      return true;
    }
  }
  return false;
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
    if (!clicked && await clickTextRange(page, "Can.?t confirm\\??")) {
      clicked = true;
      acted = true;
      await page.waitForTimeout(2000);
    }
    if (!clicked && await clickTextRange(page, "I.?ll verify later|Verify later|Skip verification|Not now|Cancel|Close")) {
      clicked = true;
      acted = true;
      await page.waitForTimeout(2000);
    }
    if (!clicked && i >= 4 && await clickTextRange(page, "Remove this device", true)) {
      clicked = true;
      acted = true;
      await page.waitForTimeout(3000);
    }
    if (clicked) continue;
    await page.keyboard.press("Escape").catch(() => {});
    await page.waitForTimeout(1000);
  }
  return acted;
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
      await page.getByRole("button", { name: /^(Cancel|Skip|Dismiss)$/i }).last().click({ force: true }).catch(async () => {
        await page.keyboard.press("Escape").catch(() => {});
      });
      await page.waitForTimeout(1500);
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
  for (let i = 0; i < 18; i += 1) {
    const body = await page.locator("body").innerText().catch(() => "");
    if (/Device verified/i.test(body)) {
      await clickText(page, /^Done$/i, "last");
      await page.waitForTimeout(2000);
      continue;
    }
    if (/Back up your chats|Key storage|Get recovery key/i.test(body)) {
      const dismiss = page.locator("button, [role='button']").filter({ hasText: /^Dismiss$/i }).first();
      if (await dismiss.isVisible().catch(() => false)) await dismiss.click({ force: true }).catch(() => {});
      else await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(1500);
      continue;
    }
    if (/Are you sure\? Without verifying|I'll verify later/i.test(body)) {
      await page.getByText(/I'll verify later/i).first().click({ force: true }).catch(async () => {
        await clickText(page, /verify later/i, "first");
      });
      await page.waitForTimeout(2500);
      continue;
    }
    if (/Notifications Enable desktop notifications/i.test(body)) {
      await page.getByRole("button", { name: /^Dismiss$/i }).first().click({ force: true }).catch(async () => {
        await clickText(page, /^Dismiss$/i, "first");
      });
      await page.waitForTimeout(1000);
      continue;
    }
    if (/Are you sure you want to reset your digital identity/i.test(body)) {
      const cancel = page.locator("#mx_Dialog_Container button, #mx_Dialog_Container [role='button']").filter({ hasText: /^Cancel$/i }).last();
      if (await cancel.isVisible().catch(() => false)) await cancel.click({ force: true }).catch(() => {});
      else await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(2000);
      continue;
    }
    if (/Confirm your digital identity|reset your digital identity/i.test(body)) {
      const skip = page.locator(".mx_CompleteSecurity_skip").first();
      if (await skip.isVisible().catch(() => false)) {
        await skip.click({ force: true }).catch(() => {});
        await page.waitForTimeout(2500);
        continue;
      }
      await page.keyboard.press("Escape").catch(() => {});
      if (/Can't confirm\?|Can.t confirm\?/i.test(body)) {
        await page.getByText(/Can't confirm\?|Can.t confirm\?/i).first().click({ force: true }).catch(async () => {
          await clickText(page, /Can't confirm\?|Can.t confirm\?/i, "first");
        });
        await page.waitForTimeout(1500);
      }
      if (/Are you sure you want to reset your digital identity/i.test(await page.locator("body").innerText().catch(() => ""))) {
        const cancel = page.locator("#mx_Dialog_Container button, #mx_Dialog_Container [role='button']").filter({ hasText: /^Cancel$/i }).last();
        if (await cancel.isVisible().catch(() => false)) await cancel.click({ force: true }).catch(() => {});
        else await page.keyboard.press("Escape").catch(() => {});
        await page.waitForTimeout(2000);
        continue;
      }
      if (/Remove this device/i.test(await page.locator("body").innerText().catch(() => ""))) {
        await clickText(page, /Remove this device/i, "first");
        await page.waitForTimeout(2500);
        continue;
      }
      await clickText(page, /^(Cancel|Skip|Later|Continue|Done)$/i, "last");
      await page.waitForTimeout(2000);
      continue;
    }
    if (/Save your Security Key|Recovery Key|Download|Copy/i.test(body)) {
      await clickText(page, /^(Continue|Done|Skip)$/i, "last");
      await page.waitForTimeout(2500);
      continue;
    }
    if (/Use Single Sign On to continue|Single Sign On/i.test(body)) {
      await clickText(page, /^Single Sign On$/i, "first");
      await page.waitForTimeout(3000);
      if (await page.locator('input[name="username"]').isVisible().catch(() => false)) {
        await page.locator('input[name="username"]').fill(opsChatUser);
        await page.locator('input[name="password"]').fill(opsChatPassword);
        await page.locator('button[type="submit"], input[type="submit"]').first().click();
        await page.waitForTimeout(8000);
      }
      continue;
    }
    await dismissNoise(page);
    return;
  }
}

async function login(page) {
  requireSecret("OPS_CHAT_USER", opsChatUser);
  requireSecret("OPS_CHAT_PASSWORD", opsChatPassword);
  await page.goto(`${opsChatUrl.replace(/\/$/, "")}/#/login`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});
  const initialBody = await page.locator("body").innerText().catch(() => "");
  if (/Welcome to Agentic Ops Chat/i.test(initialBody) && /Sign in/i.test(initialBody)) {
    const signInLink = page.getByRole("link", { name: /^Sign in$/i }).first();
    if (await signInLink.isVisible().catch(() => false)) {
      await signInLink.click({ force: true });
    } else {
      await clickText(page, /Sign in/i, "first");
    }
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(1500);
  }
  const keycloak = page.getByText(/Sign in with Keycloak|Keycloak/i).first();
  await keycloak.waitFor({ state: "visible", timeout: 60000 });
  await keycloak.click();
  await page.locator('input[name="username"]').waitFor({ state: "visible", timeout: 30000 }).catch(() => {});
  if (await page.locator('input[name="username"]').isVisible().catch(() => false)) {
    await page.locator('input[name="username"]').fill(opsChatUser);
    await page.locator('input[name="password"]').fill(opsChatPassword);
    await page.locator('button[type="submit"], input[type="submit"]').first().click();
    await page.waitForTimeout(10000);
    const consentBody = await page.locator("body").innerText().catch(() => "");
    if (/Continue to your account|grant .* access to your account/i.test(consentBody)) {
      await page.getByRole("button", { name: /^Continue$/i }).last().click({ force: true }).catch(async () => {
        await clickText(page, /^Continue$/i, "last");
      });
      await page.waitForTimeout(10000);
    }
  } else {
    await page.waitForFunction(() => {
      const text = document.body.innerText || "";
      return /Confirm your digital identity|Agentic Ops Agent|Rooms|People|Home/i.test(text);
    }, null, { timeout: 60000 }).catch(() => {});
  }
  const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
  if (/Cannot reach homeserver|login provider is unavailable|missing_session|No session cookie/i.test(body)) {
    throw new Error(`Ops Chat login error: ${body.slice(0, 500)}`);
  }
  if (/No chats yet|Home|People|Rooms/i.test(body) && !/Back up your chats|Welcome to Agentic Ops Chat/i.test(body)) {
    return;
  }
  await settleElement(page);
  const after = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
  if (/Welcome to Agentic Ops Chat/i.test(after) && /Sign in/i.test(after)) {
    throw new Error(`Element login returned to welcome page: ${after.slice(0, 300)}`);
  }
}

async function openAgentDm(page) {
  await page.goto(`${opsChatUrl.replace(/\/$/, "")}/#/user/@agentic-ops:agentic-ops.local`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(5000);
  await settleElement(page);
  await clearDialogs(page);
  let body = await page.locator("body").innerText().catch(() => "");
  if (/Welcome to Agentic Ops Chat|Sign in/i.test(body) && !/Agentic Ops Agent|Send message/i.test(body)) {
    await login(page);
    await page.goto(`${opsChatUrl.replace(/\/$/, "")}/#/user/@agentic-ops:agentic-ops.local`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(5000);
    await settleElement(page);
    await clearDialogs(page);
  }
  const sendButton = page.getByRole("button", { name: /^Send message$/i }).last();
  if (await sendButton.isVisible().catch(() => false)) {
    await sendButton.click({ force: true });
    await page.waitForTimeout(5000);
  }
  if (await page.getByText(/Start a conversation with someone/i).first().isVisible().catch(() => false)) {
    await page.getByRole("button", { name: /^Close$/i }).last().click({ force: true }).catch(async () => {
      await page.keyboard.press("Escape").catch(() => {});
    });
    await page.waitForTimeout(1000);
    await page.getByRole("button", { name: /^Send message$/i }).last().click({ force: true }).catch(async () => {
      await clickText(page, /^Send message$/i, "last");
    });
    await page.waitForTimeout(5000);
  }
  if (await page.getByText(/Start a chat with this new contact/i).first().isVisible().catch(() => false)) {
    const cont = page.getByRole("button", { name: /^Continue$/i }).last();
    if (await cont.isVisible().catch(() => false)) await cont.click({ force: true });
    else await clickText(page, /^Continue$/i, "last");
    await page.waitForTimeout(5000);
  }
  await settleElement(page);
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
