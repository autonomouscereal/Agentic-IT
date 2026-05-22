#!/usr/bin/env node
/*
 * Real-user Ops Chat proof for developer one-off artifacts.
 *
 * The test uses Element/Keycloak, asks the chat agent for code/HTML/Markdown
 * artifacts, and verifies that the agent validates each artifact before
 * sending it back as rendered code blocks instead of mangled plain chat.
 */

const { chromium } = require("playwright");

const opsChatUrl = process.env.OPS_CHAT_URL || "https://127.0.0.1:3303";
const opsChatUser = process.env.OPS_CHAT_USER || "";
const opsChatPassword = process.env.OPS_CHAT_PASSWORD || "";
const ignoreHttpsErrors = /^(1|true|yes|on)$/i.test(process.env.PLAYWRIGHT_IGNORE_HTTPS_ERRORS || "");
const marker = process.env.OPS_CHAT_DEV_ARTIFACT_MARKER || `ops-chat-dev-artifact-${Date.now()}`;
const screenshotDir = process.env.PLAYWRIGHT_SCREENSHOT_DIR || "";
const includeAnimation = /^(1|true|yes|on)$/i.test(process.env.OPS_CHAT_TEST_ANIMATION || "");
const includeUpload = /^(1|true|yes|on)$/i.test(process.env.OPS_CHAT_TEST_UPLOAD || "");
const includeCombinedAnimationPython = /^(1|true|yes|on)$/i.test(process.env.OPS_CHAT_TEST_COMBINED_ANIMATION_PYTHON || "");

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
    return;
  }
}

async function login(page) {
  requireSecret("OPS_CHAT_USER", opsChatUser);
  requireSecret("OPS_CHAT_PASSWORD", opsChatPassword);
  await page.goto(`${opsChatUrl.replace(/\/$/, "")}/#/login`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});
  let initialBody = await page.locator("body").innerText().catch(() => "");
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
  await maybeScreenshot(page, "ops-chat-dev-artifacts-open");
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
    const input = page.locator(selector).last();
    if (await input.isVisible().catch(() => false)) return input;
  }
  const body = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 1200);
  throw new Error(`Element composer not found. url=${page.url()} body=${body}`);
}

function ticketCount(text) {
  return Array.from(String(text || "").matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi)).length;
}

async function codeBlockCount(page) {
  return await page.locator("pre code, pre").count().catch(() => 0);
}

async function sendArtifactRequest(page, label, message, expected) {
  await settleElement(page);
  await clearDialogs(page);
  const beforeText = await page.locator("body").innerText().catch(() => "");
  const beforeTickets = ticketCount(beforeText);
  const beforeBlocks = await codeBlockCount(page);
  const input = await composer(page);
  await input.click({ force: true });
  await input.fill(message).catch(async () => input.type(message));
  await page.keyboard.press("Enter");
  await page.getByText(/working on that now|agent finishes/i).first().isVisible({ timeout: 10000 }).catch(() => false);
  await page.waitForFunction(
    ({ expectedMarker, expectedText, expectedMarkers, expectedRequireCodeBlock, beforeTicketCount, beforeBlockCount }) => {
      const text = document.body.innerText || "";
      const blocks = document.querySelectorAll("pre code, pre").length;
      const tickets = Array.from(text.matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi)).length;
      const codeOk = expectedRequireCodeBlock ? blocks > beforeBlockCount : true;
      const markersOk = (expectedMarkers || []).every((marker) => text.includes(marker));
      return text.includes("Validation: passed")
        && text.includes(expectedMarker)
        && markersOk
        && text.includes(expectedText)
        && codeOk
        && tickets === beforeTicketCount;
    },
    {
      expectedMarker: expected.marker,
      expectedText: expected.text || "",
      expectedMarkers: expected.extraMarkers || [],
      expectedRequireCodeBlock: expected.requireCodeBlock !== false,
      beforeTicketCount: beforeTickets,
      beforeBlockCount: beforeBlocks,
    },
    { timeout: Number(process.env.OPS_CHAT_UI_CASE_TIMEOUT_MS || 3600000) },
  );
  await page.waitForTimeout(1000);
  const body = (await page.locator("body").innerText()).replace(/\s+/g, " ");
  if (/Dashboard intake failed|chat_agent_tool_not_used|did not return a clean response/i.test(body.slice(Math.max(0, body.length - 2500)))) {
    throw new Error(`${label}: chat failure visible in UI`);
  }
  return {
    label,
    code_blocks_added: (await codeBlockCount(page)) - beforeBlocks,
    ticket_count_delta: ticketCount(body) - beforeTickets,
  };
}

async function uploadFileForAgent(page) {
  const fs = require("fs");
  const os = require("os");
  const path = require("path");
  const uploadPath = path.join(os.tmpdir(), `${marker}_upload_request.md`);
  fs.writeFileSync(
    uploadPath,
    [
      `# Uploaded Codex Harness File Test`,
      ``,
      `Marker: ${marker}-upload-source`,
      ``,
      `Please create a validated Markdown summary artifact named ${marker}_upload_summary.md.`,
      `The returned artifact must include marker ${marker}-upload-summary.`,
    ].join("\n"),
    "utf8",
  );
  await settleElement(page);
  await clearDialogs(page);
  const beforeText = await page.locator("body").innerText().catch(() => "");
  const beforeTickets = ticketCount(beforeText);
  const beforeBlocks = await codeBlockCount(page);
  let uploaded = false;
  const chooserPromise = page.waitForEvent("filechooser", { timeout: 5000 }).catch(() => null);
  for (const pattern of [/Attach/i, /Upload/i, /Send file/i, /^\+$/i]) {
    if (await clickText(page, pattern, "last")) {
      const chooser = await chooserPromise;
      if (chooser) {
        await chooser.setFiles(uploadPath);
        uploaded = true;
        break;
      }
    }
  }
  if (!uploaded) {
    const fileInput = page.locator('input[type="file"]').last();
    await fileInput.setInputFiles(uploadPath, { timeout: 10000 });
    uploaded = true;
  }
  await page.waitForTimeout(1500);
  const dialogBox = page.locator("#mx_Dialog_Container textarea, #mx_Dialog_Container [contenteditable='true'], #mx_Dialog_Container [role='textbox']").last();
  if (await dialogBox.isVisible().catch(() => false)) {
    await dialogBox.fill(`Please read this uploaded file and return the requested validated Markdown artifact with marker ${marker}-upload-summary.`).catch(async () => {
      await dialogBox.type(`Please read this uploaded file and return the requested validated Markdown artifact with marker ${marker}-upload-summary.`);
    });
  }
  let sent = false;
  for (const pattern of [/^Send$/i, /^Upload$/i, /Send file/i]) {
    const button = page.locator("#mx_Dialog_Container button, #mx_Dialog_Container [role='button'], button, [role='button']").filter({ hasText: pattern }).last();
    if (await button.isVisible().catch(() => false)) {
      await button.click({ force: true }).catch(() => {});
      sent = true;
      break;
    }
  }
  if (!sent) {
    await page.keyboard.press("Enter").catch(() => {});
  }
  await page.waitForFunction(
    ({ markerValue, beforeTicketCount, beforeBlockCount }) => {
      const text = document.body.innerText || "";
      const blocks = document.querySelectorAll("pre code, pre").length;
      const tickets = Array.from(text.matchAll(/(?:Dashboard ticket: #|I created ticket #)(\d+)/gi)).length;
      return text.includes("Validation: passed")
        && text.includes(`${markerValue}-upload-summary`)
        && blocks > beforeBlockCount
        && tickets === beforeTicketCount;
    },
    { markerValue: marker, beforeTicketCount: beforeTickets, beforeBlockCount: beforeBlocks },
    { timeout: Number(process.env.OPS_CHAT_UI_CASE_TIMEOUT_MS || 3600000) },
  );
  const body = await page.locator("body").innerText();
  return {
    label: "upload-markdown",
    code_blocks_added: (await codeBlockCount(page)) - beforeBlocks,
    ticket_count_delta: ticketCount(body) - beforeTickets,
  };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ ignoreHTTPSErrors: ignoreHttpsErrors, viewport: { width: 1500, height: 1050 } });
  const page = await context.newPage();
  const proof = { status: "running", marker, user: opsChatUser, cases: [] };
  try {
    await login(page);
    await openAgentDm(page);
    proof.cases.push(await sendArtifactRequest(
      page,
      "python",
      `Create a self-contained Python script named ${marker}_slugify.py that slugifies a list of labels. Include marker ${marker}-python in a comment, include a __main__ self-test using assert, run/validate it, and return the full script.`,
      { marker: `${marker}-python`, text: "def slugify" },
    ));
    proof.cases.push(await sendArtifactRequest(
      page,
      "html",
      `Create a single-file HTML page named ${marker}_status_card.html for a small operations status card. Include marker ${marker}-html in a data attribute. Validate it and return the full HTML.`,
      { marker: `${marker}-html`, text: "<html" },
    ));
    proof.cases.push(await sendArtifactRequest(
      page,
      "markdown",
      `Create a Markdown mini-runbook named ${marker}_runbook.md with a checklist and a fenced bash example. Include marker ${marker}-markdown. Validate it and return the full markdown.`,
      { marker: `${marker}-markdown`, text: "Checklist" },
    ));
    proof.cases.push(await sendArtifactRequest(
      page,
      "bash",
      `Create a bash script named ${marker}_check_port.sh that checks whether a host and port are reachable using nc if available. Include marker ${marker}-bash in a comment. Validate syntax and return the full script.`,
      { marker: `${marker}-bash`, text: "#!/usr/bin/env bash" },
    ));
    if (includeAnimation) {
      proof.cases.push(await sendArtifactRequest(
        page,
        "animation",
        `Create a short Remotion MP4 animation artifact named ${marker}_ops_motion.mp4 using the animation-video and remotion-best-practices skills. Include marker ${marker}-animation in the title, subtitle, or validation notes. Validate it as video and return it as a downloadable artifact. Do not create a ticket.`,
        { marker: `${marker}-animation`, text: "binary video artifact", requireCodeBlock: false },
      ));
    }
    if (includeCombinedAnimationPython) {
      proof.cases.push(await sendArtifactRequest(
        page,
        "combined-animation-python",
        `In one no-ticket response, create two validated artifacts: (1) a Python script named ${marker}_ascii_cost.py that prints an ASCII bar chart for demo tea prices over time and includes marker ${marker}-python-ascii in a comment; (2) a short Remotion MP4 animation named ${marker}_cost_motion.mp4 using the animation-video and remotion-best-practices skills and include marker ${marker}-animation-combined in the title, subtitle, or validation notes. Validate the Python script and the video, return the script as a code block, and return the video as a downloadable artifact. Do not create a ticket.`,
        {
          marker: `${marker}-python-ascii`,
          extraMarkers: [`${marker}-animation-combined`],
          text: "binary video artifact",
        },
      ));
    }
    if (includeUpload) {
      proof.cases.push(await uploadFileForAgent(page));
    }
    await maybeScreenshot(page, "ops-chat-dev-artifacts-complete");
    await browser.close();
    proof.status = "passed";
    console.log(JSON.stringify(proof, null, 2));
  } catch (error) {
    await maybeScreenshot(page, "ops-chat-dev-artifacts-failed").catch(() => {});
    await browser.close();
    proof.status = "failed";
    proof.error = String(error && error.message || error);
    console.error(JSON.stringify(proof, null, 2));
    process.exit(2);
  }
})();
