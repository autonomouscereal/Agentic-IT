#!/usr/bin/env node
/*
 * Real-user Ops Chat marathon through Element.
 *
 * This intentionally keeps one Matrix room alive while mixing harmless chat,
 * current-info questions, several operational tickets, cancellations,
 * replacement work, scope changes, and a room-scoped ticket summary.
 */

const { chromium } = require("playwright");

const opsChatUrl = process.env.OPS_CHAT_URL || "https://127.0.0.1:3303";
const opsChatUser = process.env.OPS_CHAT_USER || "";
const opsChatPassword = process.env.OPS_CHAT_PASSWORD || "";
const ignoreHttpsErrors = /^(1|true|yes|on)$/i.test(process.env.PLAYWRIGHT_IGNORE_HTTPS_ERRORS || "");
const marker = process.env.OPS_CHAT_MARATHON_MARKER || `ops-chat-marathon-${Date.now()}`;
const screenshotDir = process.env.PLAYWRIGHT_SCREENSHOT_DIR || "";
const dashboardUrl = (process.env.DASHBOARD_URL || "").replace(/\/$/, "");
const dashboardToken = process.env.DASHBOARD_SERVICE_TOKEN || "";
const marathonMode = process.env.OPS_CHAT_MARATHON_MODE || "full";

function requireSecret(name, value) {
  if (!value) throw new Error(`${name} is required`);
}

async function dashboardGet(path) {
  if (!dashboardUrl || !dashboardToken) return null;
  const response = await fetch(`${dashboardUrl}${path}`, {
    headers: { "X-Dashboard-Service-Token": dashboardToken },
  });
  if (!response.ok) throw new Error(`dashboard GET ${path} failed: HTTP ${response.status} ${await response.text()}`);
  return await response.json();
}

async function verifyTicketContact(ticketId, expected) {
  if (!ticketId || !dashboardUrl || !dashboardToken) return { status: "skipped", reason: "dashboard_api_not_configured" };
  const ticket = await dashboardGet(`/api/tickets/${ticketId}`);
  for (const [key, pattern] of Object.entries(expected)) {
    const value = String(ticket[key] || "");
    if (!pattern.test(value)) {
      throw new Error(`ticket #${ticketId} ${key} expected ${pattern}, got ${JSON.stringify(value)}`);
    }
  }
  if (ticket.provider !== "local" && ticket.provider_sync_status !== "synced") {
    throw new Error(`ticket #${ticketId} provider sync not healthy: ${ticket.provider}/${ticket.provider_sync_status}`);
  }
  return {
    status: "verified",
    ticket_id: ticketId,
    requester: ticket.requester_name || ticket.requester_email,
    affected_user: ticket.affected_user_name || ticket.affected_user_email,
    provider: ticket.provider,
    provider_ref: ticket.provider_ref,
    provider_sync_status: ticket.provider_sync_status,
  };
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
    if (/Confirm encryption setup/i.test(dialogText)) {
      await clickText(page, /^Confirm$/i, "last");
      await page.waitForTimeout(2500);
      continue;
    }
    if (/Use Single Sign On to continue|Single Sign On/i.test(dialogText)) {
      await clickText(page, /Single Sign On/i, "last");
      await page.waitForTimeout(3000);
      if (await page.locator('input[name="username"]').isVisible().catch(() => false)) {
        await page.locator('input[name="username"]').fill(opsChatUser);
        await page.locator('input[name="password"]').fill(opsChatPassword);
        await page.locator('button[type="submit"], input[type="submit"]').first().click();
        await page.waitForTimeout(8000);
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
      await page.waitForTimeout(900);
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
    await clearDialogs(page);
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
  if (/Can't connect to homeserver|Cannot reach homeserver|login provider is unavailable|missing_session|No session cookie/i.test(body)) {
    throw new Error(`Element login failed: ${body.slice(0, 600)}`);
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

async function composer(page) {
  await settleElement(page);
  await clearDialogs(page);
  await dismissNoise(page);
  for (const selector of [
    'textarea[placeholder*="Message"]',
    '[contenteditable="true"]',
    '[role="textbox"]',
    'div[aria-label*="Send a message"]',
  ]) {
    const loc = page.locator(selector).last();
    if (await loc.isVisible().catch(() => false)) return loc;
  }
  const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 1200);
  throw new Error(`Element composer not found. url=${page.url()} body=${body}`);
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
  const sendMessage = page.getByRole("button", { name: /^Send message$/i }).last();
  if (await sendMessage.isVisible().catch(() => false)) {
    await sendMessage.click({ force: true });
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
  await composer(page);
}

function ticketIds(text) {
  return Array.from(text.matchAll(/(?:Dashboard ticket: #|I created ticket #|ticket #)(\d+)/gi)).map((match) => Number(match[1]));
}

async function sendMessage(page, label, message, expectPattern, timeout = 240000, options = {}) {
  await settleElement(page);
  await clearDialogs(page);
  const beforeRaw = await page.locator("body").innerText().catch(() => "");
  const beforeTickets = ticketIds(beforeRaw);
  const input = await composer(page);
  await input.click({ force: true });
  await input.fill(message).catch(async () => input.type(message));
  await page.keyboard.press("Enter");
  const workingAckSeen = await page.getByText(/working on that now|agent finishes/i).first().isVisible({ timeout: 10000 }).catch(() => false);
  await page.waitForFunction(
    ({ source, beforeText, requireNewTicket, beforeTicketCount }) => {
      const regex = new RegExp(source, "i");
      const text = document.body.innerText || "";
      if (text.length <= beforeText.length || !regex.test(text)) return false;
      if (requireNewTicket) {
        const count = Array.from(text.matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi)).length;
        return count > beforeTicketCount;
      }
      return true;
    },
    {
      source: expectPattern.source,
      beforeText: beforeRaw,
      requireNewTicket: !!options.requireNewTicket,
      beforeTicketCount: Array.from(beforeRaw.matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi)).length,
    },
    { timeout },
  );
  await page.waitForTimeout(1200);
  const bodyRaw = await page.locator("body").innerText();
  const afterTickets = ticketIds(bodyRaw);
  const newTickets = afterTickets.filter((id) => !beforeTickets.includes(id));
  const body = bodyRaw.replace(/\s+/g, " ");
  if (/US\/usr\/bin\/bash|usr\/bin\/bash/i.test(body)) {
    throw new Error(`${label}: shell expansion artifact appeared in answer`);
  }
  if (/Dashboard intake failed|chat_agent_tool_not_used|I received the message, but the dashboard did not return/i.test(body.slice(Math.max(0, body.length - 2000)))) {
    throw new Error(`${label}: dashboard/agent failure visible in chat`);
  }
  return { label, body, newTickets, workingAckSeen };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ ignoreHTTPSErrors: ignoreHttpsErrors, viewport: { width: 1500, height: 1050 } });
  const page = await context.newPage();
  const proof = { status: "running", marker, user: opsChatUser, turns: [], tickets: {} };
  try {
    await login(page);
    await openAgentDm(page);
    await maybeScreenshot(page, "ops-chat-marathon-open");

    if (marathonMode === "ticket-reuse-regression") {
      const first = await sendMessage(
        page,
        "first-software-ticket",
        `Please open a fresh separate ticket to install LibreOffice on laptop DEMO-LAPTOP-91 for Avery Example. Marker ${marker}.`,
        /Dashboard ticket: #|I created ticket #/,
        240000,
        { requireNewTicket: true },
      );
      proof.turns.push(first);
      proof.tickets.first = first.newTickets.at(-1);

      const second = await sendMessage(
        page,
        "second-software-ticket",
        `Jeff needs Figma installed on his laptop by tomorrow for a design review. This is a different person, software title, and device from the prior request. Marker ${marker}-figma.`,
        /Dashboard ticket: #|I created ticket #/,
        240000,
        { requireNewTicket: true },
      );
      proof.turns.push(second);
      proof.tickets.second = second.newTickets.at(-1);

      if (!proof.tickets.first || !proof.tickets.second) {
        throw new Error(`missing ticket ids in reuse regression: ${JSON.stringify(proof.tickets)}`);
      }
      if (proof.tickets.first === proof.tickets.second) {
        throw new Error(`second software request reused first ticket #${proof.tickets.first}`);
      }
      proof.contact_checks = {
        first: await verifyTicketContact(proof.tickets.first, {
          affected_user_name: /avery/i,
        }),
        second: await verifyTicketContact(proof.tickets.second, {
          affected_user_name: /jeff/i,
        }),
      };
      await maybeScreenshot(page, "ops-chat-ticket-reuse-regression-complete");
      await browser.close();
      proof.status = "passed";
      proof.mode = marathonMode;
      proof.turn_count = proof.turns.length;
      console.log(JSON.stringify(proof, null, 2));
      return;
    }

    proof.turns.push(await sendMessage(page, "sky-blue", `Before we start, why is the sky blue? Marker ${marker}.`, /blue|scatter|sunlight|wavelength|air molecules/));
    proof.turns.push(await sendMessage(page, "sky-eli5", "Explain it like I'm five, but keep it one paragraph.", /sunlight|bounces|tiny bits|blue light/));
    proof.turns.push(await sendMessage(page, "cat", "Send me a picture of a cat in text form.", /ASCII|o\.o|meow|whisker/));
    proof.turns.push(await sendMessage(page, "cat-followup", "Make it a different cat with a grumpy vibe.", /grumpy|unimpressed|different cat|judging/));
    proof.turns.push(await sendMessage(page, "watermelon-current", "What is the current general price of watermelon in China? Keep the numbers readable.", /CNY|RMB|\$[0-9]|per kg|wholesale/));

    const figma = await sendMessage(page, "figma-ticket", "Jeff needs Figma installed on his laptop by tomorrow for a design review. Please handle the request and ask only for what you actually need.", /Dashboard ticket: #|I created ticket #/, 240000, { requireNewTicket: true });
    proof.turns.push(figma);
    proof.tickets.figma = figma.newTickets.at(-1);

    const loginTicket = await sendMessage(page, "urgent-login-ticket", "Also I cannot log into GitLab before a customer call in 5 minutes. This is urgent.", /Dashboard ticket: #|I created ticket #/, 240000, { requireNewTicket: true });
    proof.turns.push(loginTicket);
    proof.tickets.login = loginTicket.newTickets.at(-1);

    proof.turns.push(await sendMessage(page, "meme-caption", "While those are running, give me a short clean meme caption about help desk life that I can send Rachel myself.", /help desk|caption|ticket|meme/));

    const mail = await sendMessage(page, "mailbox-ticket", "Can you check whether my mailbox has any emails from Alice about the birthday plan? If you need access, request it.", /Dashboard ticket: #|I created ticket #/, 240000, { requireNewTicket: true });
    proof.turns.push(mail);
    proof.tickets.mailbox = mail.newTickets.at(-1);

    const cancelFigma = await sendMessage(page, "cancel-figma", `Cancel the Figma install request${proof.tickets.figma ? ` ticket #${proof.tickets.figma}` : ""}; Jeff already has Figma.`, /cancelled ticket|canceled ticket|updated ticket|status update|recorded your update/);
    proof.turns.push(cancelFigma);

    const adobe = await sendMessage(page, "adobe-ticket", "Actually Jeff needs Adobe Acrobat Pro instead, but only if it is approved and licensed.", /Dashboard ticket: #|I created ticket #/, 240000, { requireNewTicket: true });
    proof.turns.push(adobe);
    proof.tickets.adobe = adobe.newTickets.at(-1);

    proof.turns.push(await sendMessage(page, "login-scope-change", `The GitLab issue ${proof.tickets.login ? `on ticket #${proof.tickets.login}` : ""} is actually Keycloak SSO MFA, not a GitLab local password.`, /updated ticket|recorded your latest message|reassign|Identity|Access|ticket #/));

    const vpn = await sendMessage(page, "vpn-ticket", "Open a low-priority ticket for VPN dropping every hour on the finance laptop.", /Dashboard ticket: #|I created ticket #/, 240000, { requireNewTicket: true });
    proof.turns.push(vpn);
    proof.tickets.vpn = vpn.newTickets.at(-1);

    proof.turns.push(await sendMessage(page, "cancel-vpn", `Cancel the VPN ticket${proof.tickets.vpn ? ` #${proof.tickets.vpn}` : ""}; I am on guest wifi and it is working now.`, /cancelled ticket|canceled ticket|updated ticket|status update|recorded your update/));

    proof.turns.push(await sendMessage(page, "room-summary", "What tickets are you tracking for me in this room right now? Include status if you can.", /ticket|tracking|cancel|status|open/));
    proof.turns.push(await sendMessage(page, "urgent-reminder", "Do not forget the account unlock before my call; keep the other requests moving too.", /updated ticket|recorded|account|call|ticket #/));

    if (!proof.tickets.figma || !proof.tickets.login || !proof.tickets.mailbox || !proof.tickets.adobe || !proof.tickets.vpn) {
      throw new Error(`missing expected ticket ids: ${JSON.stringify(proof.tickets)}`);
    }
    if (proof.tickets.adobe === proof.tickets.figma) {
      throw new Error("Adobe replacement reused the cancelled Figma ticket");
    }
    proof.contact_checks = {
      figma: await verifyTicketContact(proof.tickets.figma, {
        requester_name: /demo|marathon|account|chat/i,
        affected_user_name: /jeff/i,
      }),
      login: await verifyTicketContact(proof.tickets.login, {
        requester_name: /demo|marathon|account|chat/i,
        affected_user_name: /demo|marathon|account|chat/i,
      }),
      adobe: await verifyTicketContact(proof.tickets.adobe, {
        requester_name: /demo|marathon|account|chat/i,
        affected_user_name: /jeff/i,
      }),
    };
    const workingAcks = proof.turns.filter((turn) => turn.workingAckSeen).length;
    if (workingAcks < 3) {
      throw new Error(`working acknowledgement appeared too rarely: ${workingAcks}`);
    }

    await maybeScreenshot(page, "ops-chat-marathon-complete");
    await browser.close();
    proof.status = "passed";
    proof.working_ack_count = workingAcks;
    proof.turn_count = proof.turns.length;
    console.log(JSON.stringify(proof, null, 2));
  } catch (error) {
    await maybeScreenshot(page, "ops-chat-marathon-failed").catch(() => {});
    await browser.close();
    proof.status = "failed";
    proof.error = String(error && error.message || error);
    console.error(JSON.stringify(proof, null, 2));
    process.exit(2);
  }
})();
