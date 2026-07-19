import { execFile } from "node:child_process";
import { createRequire } from "node:module";
import { mkdir, open, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
const CANONICAL_HOST = "www.sciencedirect.com";
const SCAU_AUTH_HOST = "vpn.scau.edu.cn";
const SCAU_PROXY_HOST = "www-sciencedirect-com-s.vpn.scau.edu.cn";
const PII_PATH = /^\/science\/article\/(?:abs\/)?pii\/([A-Z0-9]+)\/?$/i;

export const SELECTORS = Object.freeze({
  username:
    'input[name="username"], input[name="userName"], input[name="account"], input[type="text"]',
  password: 'input[type="password"]',
  submit:
    'button[type="submit"], input[type="submit"], button.login-btn, button#login, button.login',
});

export class ScienceDirectFlowError extends Error {
  constructor(phase, message, details = {}) {
    super(message);
    this.name = "ScienceDirectFlowError";
    this.phase = phase;
    this.details = details;
  }
}

export function isApprovedCredentialHost(hostname) {
  return String(hostname ?? "").toLowerCase() === SCAU_AUTH_HOST;
}

export function isApprovedProxyHost(hostname) {
  return String(hostname ?? "").toLowerCase() === SCAU_PROXY_HOST;
}

function hostnameOf(value, phase) {
  try {
    return new URL(value).hostname.toLowerCase();
  } catch {
    throw new ScienceDirectFlowError(phase, "The browser returned an invalid URL.");
  }
}

function canonicalReference(reference) {
  let parsed;
  try {
    parsed = new URL(String(reference ?? "").trim());
  } catch {
    throw new ScienceDirectFlowError("reference", "A canonical ScienceDirect URL is required.");
  }
  if (parsed.protocol !== "https:" || parsed.hostname.toLowerCase() !== CANONICAL_HOST) {
    throw new ScienceDirectFlowError("reference", "ScienceDirect input must use the exact publisher host.");
  }
  const match = PII_PATH.exec(parsed.pathname);
  if (!match) {
    throw new ScienceDirectFlowError("reference", "ScienceDirect input has no canonical article PII.");
  }
  const pii = match[1].toUpperCase();
  const landingUrl = `https://${CANONICAL_HOST}/science/article/pii/${pii}`;
  return { pii, landingUrl };
}

export function canonicalToProxyUrl(reference) {
  const { pii } = canonicalReference(reference);
  return `https://${SCAU_PROXY_HOST}/science/article/pii/${pii}`;
}

export function assertNoInteractiveChallenge(text) {
  const value = String(text ?? "");
  if (/(?:captcha|验证码|人机验证|are you a robot)/i.test(value)) {
    throw new ScienceDirectFlowError("captcha", "SCAU access requires an interactive CAPTCHA.");
  }
  if (/(?:\botp\b|one[- ]time|verification code|动态口令|一次性口令|短信验证)/i.test(value)) {
    throw new ScienceDirectFlowError("otp", "SCAU access requires an interactive one-time code.");
  }
}

function samePath(left, right) {
  const normalize = (value) => path.resolve(String(value)).replace(/[\\/]+$/, "").toLowerCase();
  return normalize(left) === normalize(right);
}

function isPathInside(child, parent) {
  const relative = path.relative(path.resolve(parent), path.resolve(child));
  return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);
}

export function assertAutomationPathBoundaries({
  workDir,
  profileDir,
  dependencyRoot,
  secretPath = "",
  localAppData = process.env.LOCALAPPDATA,
  testMode = false,
}) {
  if (testMode === true) return;
  for (const [name, value] of Object.entries({ workDir, profileDir, dependencyRoot, localAppData })) {
    if (!String(value ?? "").trim()) {
      throw new ScienceDirectFlowError("path-boundary", `${name} is required for production automation.`);
    }
  }
  const localRoot = path.resolve(localAppData);
  const expectedWorkRoot = path.join(localRoot, "Codex", "paper-acquisition", "runs");
  const expectedProfile = path.join(
    localRoot,
    "Codex",
    "browser-profiles",
    "acquire-research-papers",
    "sciencedirect-scau",
  );
  const expectedDependencies = path.join(localRoot, "Codex", "deps", "acquire-research-papers");
  const expectedSecret = path.join(
    localRoot,
    "Codex",
    "secrets",
    "acquire-research-papers",
    "secrets.clixml",
  );
  if (!isPathInside(workDir, expectedWorkRoot)) {
    throw new ScienceDirectFlowError(
      "path-boundary",
      "The browser work directory must remain under the global run root.",
    );
  }
  if (!samePath(profileDir, expectedProfile)) {
    throw new ScienceDirectFlowError(
      "path-boundary",
      "A dedicated acquire-research-papers ScienceDirect profile is required.",
    );
  }
  if (!samePath(dependencyRoot, expectedDependencies)) {
    throw new ScienceDirectFlowError(
      "path-boundary",
      "Playwright dependencies must use the dedicated global root.",
    );
  }
  if (secretPath && !samePath(secretPath, expectedSecret)) {
    throw new ScienceDirectFlowError(
      "path-boundary",
      "The DPAPI payload must use the dedicated global secret path.",
    );
  }
}

async function uniqueLocator(locator, phase, description) {
  const count = await locator.count();
  if (count !== 1) {
    throw new ScienceDirectFlowError(
      phase,
      `${description} must resolve to exactly one element; found ${count}.`,
      { count },
    );
  }
  return locator;
}

async function resolveLoginAction(page) {
  const stable = page.locator(SELECTORS.submit);
  const stableCount = await stable.count();
  if (stableCount === 1) return stable;
  if (stableCount > 1) {
    throw new ScienceDirectFlowError(
      "authentication-form",
      `SCAU login action must resolve to exactly one element; found ${stableCount}.`,
      { count: stableCount },
    );
  }
  const semantic = page.getByRole("button", { name: "登录", exact: true });
  return uniqueLocator(semantic, "authentication-form", "SCAU semantic login action");
}

export async function readCredentialForHost(hostname, { secretPath = "" } = {}) {
  if (!isApprovedCredentialHost(hostname)) {
    throw new ScienceDirectFlowError(
      "authentication-host",
      "Credential release denied for an unapproved hostname.",
    );
  }
  const bridge = path.join(MODULE_DIR, "read-sciencedirect-credential.ps1");
  const args = [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    bridge,
    "-ExpectedHost",
    hostname,
  ];
  if (secretPath) args.push("-SecretPath", secretPath);
  let stdout;
  try {
    ({ stdout } = await execFileAsync("powershell", args, {
      encoding: "utf8",
      windowsHide: true,
      maxBuffer: 64 * 1024,
    }));
  } catch {
    throw new ScienceDirectFlowError("credential-read", "The encrypted SCAU credential could not be loaded.");
  }
  try {
    const credential = JSON.parse(stdout);
    if (!String(credential.username ?? "") || !String(credential.password ?? "")) {
      throw new Error("missing credential fields");
    }
    return { username: String(credential.username), password: String(credential.password) };
  } catch {
    throw new ScienceDirectFlowError(
      "credential-read",
      "The SCAU credential bridge returned an invalid response.",
    );
  }
}

export async function authenticateThroughScau({
  page,
  credentialReader = readCredentialForHost,
  secretPath = "",
  timeoutMs = 45_000,
}) {
  const initialHost = hostnameOf(page.url(), "authentication-host");
  if (isApprovedProxyHost(initialHost)) return { submitted: false };
  if (!isApprovedCredentialHost(initialHost)) {
    throw new ScienceDirectFlowError(
      "authentication-host",
      "SCAU authentication left the exact approved host.",
    );
  }

  let bodyText = "";
  try {
    bodyText = await page.locator("body").innerText();
  } catch {
    throw new ScienceDirectFlowError("authentication-page", "SCAU authentication page is unreadable.");
  }
  assertNoInteractiveChallenge(bodyText);

  const username = await uniqueLocator(
    page.locator(SELECTORS.username),
    "authentication-form",
    "SCAU username field",
  );
  const password = await uniqueLocator(
    page.locator(SELECTORS.password),
    "authentication-form",
    "SCAU password field",
  );
  const submit = await resolveLoginAction(page);

  const credential = await credentialReader(initialHost, { secretPath });
  if (!String(credential?.username ?? "") || !String(credential?.password ?? "")) {
    throw new ScienceDirectFlowError("credential-read", "The SCAU credential is incomplete.");
  }
  try {
    await username.fill(credential.username);
    await password.fill(credential.password);
    await submit.click();
  } finally {
    credential.username = null;
    credential.password = null;
  }

  try {
    await page.waitForURL((url) => isApprovedProxyHost(url.hostname), { timeout: timeoutMs });
  } catch {
    throw new ScienceDirectFlowError(
      "authentication-not-complete",
      "SCAU authentication did not complete; CAPTCHA, OTP, or corrected credentials may be required.",
    );
  }
  if (!isApprovedProxyHost(hostnameOf(page.url(), "authentication-not-complete"))) {
    throw new ScienceDirectFlowError(
      "authentication-not-complete",
      "SCAU authentication did not return to the approved ScienceDirect proxy.",
    );
  }
  return { submitted: true };
}

async function waitForDocument(page, timeoutMs) {
  try {
    await page.waitForLoadState("domcontentloaded", { timeout: timeoutMs });
  } catch {
    // Host, challenge, and metadata checks below remain authoritative.
  }
}

async function readMetadata(page, canonical) {
  let payload;
  try {
    payload = await page.evaluate(() => {
      const values = (name) => Array.from(
        document.querySelectorAll(`meta[name="${name}" i]`),
        (node) => String(node.getAttribute("content") ?? "").trim(),
      ).filter(Boolean);
      return {
        title: values("citation_title"),
        authors: values("citation_author"),
        date: values("citation_publication_date"),
        venue: values("citation_journal_title"),
        doi: values("citation_doi"),
        publisher: values("citation_publisher"),
      };
    });
  } catch {
    throw new ScienceDirectFlowError("metadata", "ScienceDirect proxy metadata could not be read.");
  }
  const one = (values, label) => {
    if (!Array.isArray(values) || values.length !== 1 || !String(values[0]).trim()) {
      throw new ScienceDirectFlowError("metadata", `ScienceDirect proxy has missing or ambiguous ${label}.`);
    }
    return String(values[0]).trim();
  };
  if (!Array.isArray(payload.authors) || payload.authors.length === 0) {
    throw new ScienceDirectFlowError("metadata", "ScienceDirect proxy has no article authors.");
  }
  const date = one(payload.date, "publication date");
  const yearMatch = /(?:19|20)\d{2}/.exec(date);
  if (!yearMatch) {
    throw new ScienceDirectFlowError("metadata", "ScienceDirect publication date has no year.");
  }
  return {
    pii: canonical.pii,
    title: one(payload.title, "title"),
    authors: payload.authors.map((value) => String(value).trim()).filter(Boolean),
    year: Number(yearMatch[0]),
    venue: one(payload.venue, "journal title"),
    doi: one(payload.doi, "DOI"),
    publisher: one(payload.publisher, "publisher"),
    landingUrl: canonical.landingUrl,
  };
}

async function safeProxyGet(request, initialUrl, options, timeoutMs) {
  let current = new URL(initialUrl);
  for (let redirects = 0; redirects <= 3; redirects += 1) {
    if (current.protocol !== "https:" || !isApprovedProxyHost(current.hostname)) {
      throw new ScienceDirectFlowError("redirect-host", "ScienceDirect proxy request left the approved host.");
    }
    const response = await request.get(current.href, {
      ...options,
      failOnStatusCode: false,
      maxRedirects: 0,
      timeout: timeoutMs,
    });
    if (![301, 302, 303, 307, 308].includes(response.status())) return { response, url: current.href };
    const location = response.headers().location;
    if (!location || redirects === 3) {
      throw new ScienceDirectFlowError("redirect", "ScienceDirect proxy returned an invalid redirect chain.");
    }
    current = new URL(location, current);
  }
  throw new ScienceDirectFlowError("redirect", "ScienceDirect proxy redirect limit was exceeded.");
}

async function writeValidatedPdf(workDir, bytes) {
  if (bytes.length < 5 || bytes.subarray(0, 5).toString("ascii") !== "%PDF-") {
    throw new ScienceDirectFlowError(
      "atrust-required",
      "SCAU WebVPN did not expose the subscribed Elsevier PDF; aTrust may be required.",
    );
  }
  await mkdir(workDir, { recursive: true });
  const finalPath = path.join(workDir, "paper.pdf");
  const partialPath = `${finalPath}.partial`;
  let handle;
  try {
    await writeFile(partialPath, bytes, { flag: "wx" });
    handle = await open(partialPath, "r");
    const header = Buffer.alloc(5);
    const { bytesRead } = await handle.read(header, 0, header.length, 0);
    if (bytesRead !== 5 || header.toString("ascii") !== "%PDF-") {
      throw new ScienceDirectFlowError("download-validation", "The downloaded file is not a PDF.");
    }
    await handle.close();
    handle = null;
    await rename(partialPath, finalPath);
    return finalPath;
  } catch (error) {
    await handle?.close();
    await rm(partialPath, { force: true });
    throw error;
  }
}

async function retrieveArtifacts({ browserContext, paper, workDir, timeoutMs }) {
  const proxyOrigin = `https://${SCAU_PROXY_HOST}`;
  const proxyPdfUrl = `${proxyOrigin}/science/article/pii/${paper.pii}/pdfft?download=true`;
  const cite = new URL(`${proxyOrigin}/sdfe/arp/cite`);
  cite.searchParams.set("pii", paper.pii);
  cite.searchParams.set("format", "text/x-bibtex");
  cite.searchParams.set("withabstract", "true");

  const pdfResult = await safeProxyGet(
    browserContext.request,
    proxyPdfUrl,
    { headers: { accept: "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8" } },
    timeoutMs,
  );
  const pdfBytes = await pdfResult.response.body();
  const pdfPath = await writeValidatedPdf(workDir, pdfBytes);

  const bibResult = await safeProxyGet(
    browserContext.request,
    cite.href,
    { headers: { accept: "application/x-bibtex,text/plain;q=0.9,*/*;q=0.8" } },
    timeoutMs,
  );
  const bibtex = await bibResult.response.text();
  if (!bibResult.response.ok() || !/^\s*@\w+\s*\{/i.test(bibtex)) {
    throw new ScienceDirectFlowError(
      "citation-export",
      "ScienceDirect proxy did not return the official BibTeX export.",
    );
  }

  const canonicalPdfUrl =
    `https://${CANONICAL_HOST}/science/article/pii/${paper.pii}/pdfft?download=true`;
  const canonicalBibtexUrl = new URL(`https://${CANONICAL_HOST}/sdfe/arp/cite`);
  canonicalBibtexUrl.searchParams.set("pii", paper.pii);
  canonicalBibtexUrl.searchParams.set("format", "text/x-bibtex");
  canonicalBibtexUrl.searchParams.set("withabstract", "true");
  return {
    ...paper,
    status: "downloaded",
    pdfPath,
    pdfUrl: canonicalPdfUrl,
    bibtexUrl: canonicalBibtexUrl.href,
    accessPdfUrl: pdfResult.url,
    accessBibtexUrl: bibResult.url,
    bibtex,
  };
}

export async function retrieveScienceDirectPaper(options) {
  if (!options?.page || !options?.browserContext?.request) {
    throw new TypeError("page and browserContext are required");
  }
  if (!String(options.reference ?? "").trim()) throw new TypeError("reference is required");
  if (!String(options.workDir ?? "").trim()) throw new TypeError("workDir is required");
  const canonical = canonicalReference(options.reference);
  const timeoutMs = Number(options.timeoutMs ?? 45_000);
  const proxyUrl = canonicalToProxyUrl(canonical.landingUrl);

  try {
    await options.page.goto(proxyUrl, { waitUntil: "domcontentloaded", timeout: timeoutMs });
  } catch {
    throw new ScienceDirectFlowError("proxy-navigation", "The SCAU ScienceDirect proxy could not be opened.");
  }
  await waitForDocument(options.page, timeoutMs);
  await authenticateThroughScau({
    page: options.page,
    credentialReader: options.credentialReader ?? readCredentialForHost,
    secretPath: options.secretPath ? path.resolve(String(options.secretPath)) : "",
    timeoutMs,
  });
  await waitForDocument(options.page, timeoutMs);
  const currentHost = hostnameOf(options.page.url(), "proxy-host");
  if (!isApprovedProxyHost(currentHost)) {
    throw new ScienceDirectFlowError("proxy-host", "SCAU access did not return to the approved proxy.");
  }
  let bodyText = "";
  try {
    bodyText = await options.page.locator("body").innerText();
  } catch {
    throw new ScienceDirectFlowError("proxy-page", "ScienceDirect proxy page is unreadable.");
  }
  assertNoInteractiveChallenge(bodyText);
  const paper = await readMetadata(options.page, canonical);
  return retrieveArtifacts({
    browserContext: options.browserContext,
    paper,
    workDir: path.resolve(String(options.workDir)),
    timeoutMs,
  });
}

export async function runAutomatedRetrieval(options) {
  if (!options?.chromium || typeof options.chromium.launchPersistentContext !== "function") {
    throw new TypeError("a Playwright chromium implementation is required");
  }
  if (!String(options.profileDir ?? "").trim()) throw new TypeError("profileDir is required");
  if (!String(options.workDir ?? "").trim()) throw new TypeError("workDir is required");
  const profileDir = path.resolve(String(options.profileDir));
  const workDir = path.resolve(String(options.workDir));
  assertAutomationPathBoundaries({
    workDir,
    profileDir,
    dependencyRoot: options.dependencyRoot,
    secretPath: options.secretPath,
    localAppData: options.localAppData,
    testMode: options.testMode === true,
  });
  await mkdir(profileDir, { recursive: true });
  await mkdir(workDir, { recursive: true });
  const browserContext = await options.chromium.launchPersistentContext(profileDir, {
    channel: "chrome",
    headless: options.headless === true,
    args: ["--window-position=-32000,-32000", "--window-size=1280,900"],
    acceptDownloads: true,
    downloadsPath: workDir,
  });
  try {
    const page = browserContext.pages()[0] ?? await browserContext.newPage();
    return await retrieveScienceDirectPaper({ ...options, page, browserContext, workDir });
  } finally {
    await browserContext.close();
  }
}

export function loadPlaywrightChromium(dependencyRoot) {
  const require = createRequire(import.meta.url);
  const packagePath = path.join(path.resolve(dependencyRoot), "node_modules", "playwright-core");
  const playwright = require(packagePath);
  if (!playwright?.chromium) throw new Error("playwright-core does not expose chromium");
  return playwright.chromium;
}

function parseArgs(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (!arg.startsWith("--") || index + 1 >= argv.length) {
      throw new Error("Invalid command-line argument.");
    }
    options[arg.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = argv[index + 1];
    index += 1;
  }
  return options;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  for (const required of ["reference", "workDir", "profileDir", "dependencyRoot"]) {
    if (!String(options[required] ?? "").trim()) {
      throw new ScienceDirectFlowError("arguments", "A required automation argument is missing.");
    }
  }
  const chromium = loadPlaywrightChromium(options.dependencyRoot);
  const result = await runAutomatedRetrieval({
    ...options,
    chromium,
    timeoutMs: options.timeoutMs ? Number(options.timeoutMs) : undefined,
  });
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch((error) => {
    const payload = {
      status: "error",
      phase: error instanceof ScienceDirectFlowError ? error.phase : "automation",
      message: error instanceof ScienceDirectFlowError
        ? error.message
        : "ScienceDirect browser automation failed.",
    };
    process.stderr.write(`${JSON.stringify(payload)}\n`);
    process.exitCode = 1;
  });
}
