import { execFile } from "node:child_process";
import { createRequire } from "node:module";
import { mkdir, open, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
const CARSI_DISCOVERY_URL = "https://ds.carsi.edu.cn/login/index.html";
const IEEE_HOST = "ieeexplore.ieee.org";
const CITATION_URL = `https://${IEEE_HOST}/rest/search/citation/format`;
const DNS_HOST = /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i;

export const SELECTORS = Object.freeze({
  documentTitle: "h1.document-title",
  pdfHref: 'a[href*="/stamp/stamp.jsp"]',
  pdfPrimaryHref: 'a.xpl-btn-pdf[href*="/stamp/stamp.jsp"]',
  pdfFrame: 'iframe[src*="/stampPDF/getPDF.jsp"]',
});

export class IeeeFlowError extends Error {
  constructor(phase, message, details = {}) {
    super(message);
    this.name = "IeeeFlowError";
    this.phase = phase;
    this.details = details;
  }
}

export function classifyPaperReference(reference) {
  const value = String(reference ?? "").trim();
  if (!value) throw new TypeError("paper reference is required");
  if (/^https:\/\/ieeexplore\.ieee\.org\//i.test(value)) return { kind: "url", value };
  if (/^10\.\d{4,9}\/[\w.()/:;-]+$/i.test(value)) return { kind: "doi", value };
  return { kind: "title", value };
}

export function normalizeInstitutionProfile(payload = {}) {
  const required = [
    "organization",
    "carsiSchoolPlaceholder",
    "carsiSearchText",
    "carsiInstitution",
    "carsiLoginButtonName",
    "credentialHost",
    "usernameLabel",
    "passwordLabel",
    "loginButtonName",
  ];
  const profile = {};
  for (const name of required) {
    const value = String(payload[name] ?? "").trim();
    if (!value) throw new IeeeFlowError("credential-read", `Institution profile field is missing: ${name}.`);
    profile[name] = value;
  }
  profile.credentialHost = profile.credentialHost.toLowerCase();
  if (profile.credentialHost.endsWith(".") || !DNS_HOST.test(profile.credentialHost)) {
    throw new IeeeFlowError("credential-read", "Institution credential host must be one exact DNS hostname.");
  }
  profile.consentTitle = String(payload.consentTitle ?? "").trim();
  profile.consentButtonName = String(payload.consentButtonName ?? "").trim();
  if (Boolean(profile.consentTitle) !== Boolean(profile.consentButtonName)) {
    throw new IeeeFlowError(
      "credential-read",
      "Institution consent title and button name must both be configured or both be empty.",
    );
  }
  return profile;
}

export function isApprovedCredentialHost(hostname, institutionProfile) {
  const value = String(hostname ?? "").trim().toLowerCase();
  if (!value || value.endsWith(".")) return false;
  return value === normalizeInstitutionProfile(institutionProfile).credentialHost;
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
      throw new IeeeFlowError("path-boundary", `${name} is required for production automation.`);
    }
  }
  const localRoot = path.resolve(localAppData);
  const expectedWorkRoot = path.join(localRoot, "Codex", "paper-acquisition", "runs");
  const expectedProfile = path.join(
    localRoot,
    "Codex",
    "browser-profiles",
    "acquire-research-papers",
    "ieee",
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
    throw new IeeeFlowError("path-boundary", "The browser work directory must remain under the global run root.");
  }
  if (!samePath(profileDir, expectedProfile)) {
    throw new IeeeFlowError("path-boundary", "A dedicated acquire-research-papers IEEE profile is required.");
  }
  if (!samePath(dependencyRoot, expectedDependencies)) {
    throw new IeeeFlowError("path-boundary", "Playwright dependencies must use the dedicated global root.");
  }
  if (secretPath && !samePath(secretPath, expectedSecret)) {
    throw new IeeeFlowError("path-boundary", "The DPAPI payload must use the dedicated global secret path.");
  }
}

function hostnameOf(value, phase) {
  try {
    return new URL(value).hostname.toLowerCase();
  } catch {
    throw new IeeeFlowError(phase, "The browser returned an invalid URL.");
  }
}

async function uniqueLocator(locator, phase, description) {
  const count = await locator.count();
  if (count !== 1) {
    throw new IeeeFlowError(
      phase,
      `${description} must resolve to exactly one element; found ${count}.`,
      { count },
    );
  }
  return locator;
}

async function waitForDocument(page, timeoutMs) {
  try {
    await page.waitForLoadState("domcontentloaded", { timeout: timeoutMs });
  } catch {
    // URL, hostname, and selector checks below remain authoritative.
  }
}

function firstText(...values) {
  return values.map((value) => String(value ?? "").trim()).find(Boolean) ?? "";
}

export function normalizePageMetadata(payload = {}) {
  const citation = payload.citation ?? {};
  const xpl = payload.xpl ?? {};
  const xplAuthors = Array.isArray(xpl.authors)
    ? xpl.authors
      .map((author) => firstText(typeof author === "string" ? author : author?.name))
      .filter(Boolean)
    : [];
  const namedAuthors = String(xpl.authorNames ?? "")
    .split(";")
    .map((author) => author.trim())
    .filter(Boolean);
  const citationAuthors = Array.isArray(citation.authors)
    ? citation.authors.map((author) => String(author).trim()).filter(Boolean)
    : [];
  const date = firstText(citation.date, xpl.publicationDate, xpl.publicationYear);
  const yearMatch = date.match(/(?:19|20)\d{2}/);
  const doiLink = firstText(xpl.doiLink).replace(/^https:\/\/doi\.org\//i, "");
  return {
    title: firstText(citation.title, xpl.title, xpl.displayDocTitle, payload.h1Title),
    authors: citationAuthors.length ? citationAuthors : (xplAuthors.length ? xplAuthors : namedAuthors),
    year: yearMatch ? Number(yearMatch[0]) : 0,
    venue: firstText(
      citation.venue,
      xpl.publicationTitle,
      xpl.displayPublicationTitle,
    ),
    doi: firstText(citation.doi, xpl.doi, doiLink),
    canonicalUrl: firstText(payload.canonicalUrl, xpl.persistentLink, payload.locationUrl),
    articleNumber: firstText(citation.articleNumber, xpl.articleNumber),
    userAgent: firstText(payload.userAgent),
    pdfStampUrl: firstText(xpl.pdfUrl),
    pdfDirectUrl: firstText(xpl.pdfPath),
    isFreeDocument: xpl.isFreeDocument === true || String(xpl.isFreeDocument) === "true",
    isOpenAccess: xpl.isOpenAccess === true || String(xpl.isOpenAccess) === "true",
  };
}

async function readPaperMetadata(page, timeoutMs) {
  const extract = () => {
    const values = (name) => Array.from(document.querySelectorAll(`meta[name="${name}"]`))
      .map((element) => element.getAttribute("content")?.trim() || "")
      .filter(Boolean);
    const content = (name) => values(name)[0] || "";
    const xpl = globalThis.xplGlobal?.document?.metadata ?? {};
    const doiLabel = Array.from(document.querySelectorAll("main strong"))
      .slice(0, 64)
      .find((element) => element.textContent?.trim() === "DOI:");
    const doiHref = doiLabel?.nextElementSibling?.getAttribute?.("href") || "";
    const canonicalUrl = document.querySelector('link[rel="canonical"]')?.getAttribute("href")
      || location.href;
    return {
      citation: {
        title: content("citation_title"),
        authors: values("citation_author"),
        date: content("citation_publication_date") || content("citation_date"),
        venue: content("citation_journal_title")
          || content("citation_conference_title")
          || content("citation_publication_title"),
        doi: content("citation_doi")
          || content("DC.Identifier")
          || doiHref.replace(/^https:\/\/doi\.org\//i, ""),
        articleNumber: content("citation_arnumber")
          || canonicalUrl.match(/\/document\/(\d+)/)?.[1]
          || location.pathname.match(/\/document\/(\d+)/)?.[1]
          || "",
      },
      xpl: {
        title: xpl.title,
        displayDocTitle: xpl.displayDocTitle,
        authors: Array.isArray(xpl.authors)
          ? xpl.authors.map((author) => ({ name: author?.name }))
          : [],
        authorNames: xpl.authorNames,
        publicationDate: xpl.publicationDate,
        publicationYear: xpl.publicationYear,
        publicationTitle: xpl.publicationTitle,
        displayPublicationTitle: xpl.displayPublicationTitle,
        doi: xpl.doi,
        doiLink: xpl.doiLink,
        articleNumber: xpl.articleNumber,
        pdfUrl: xpl.pdfUrl,
        pdfPath: xpl.pdfPath,
        isFreeDocument: xpl.isFreeDocument,
        isOpenAccess: xpl.isOpenAccess,
        persistentLink: xpl.persistentLink,
      },
      h1Title: document.querySelector("h1.document-title")?.textContent?.trim()
        || document.querySelector("h1")?.textContent?.trim()
        || "",
      canonicalUrl,
      locationUrl: location.href,
      userAgent: navigator.userAgent,
    };
  };

  try {
    await page.locator(SELECTORS.documentTitle).waitFor({
      state: "visible",
      timeout: Math.min(timeoutMs, 20_000),
    });
  } catch {
    // The bounded metadata checks below distinguish a persistent WAF page from normal loading.
  }
  let metadata = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      metadata = normalizePageMetadata(await page.evaluate(extract));
      if (String(metadata?.title ?? "").trim()) break;
    } catch {
      metadata = null;
    }
    if (attempt === 2) break;
    if (hostnameOf(page.url(), "paper-metadata") !== IEEE_HOST) {
      throw new IeeeFlowError("paper-metadata", "IEEE metadata navigation left the expected host.");
    }
    await waitForDocument(page, timeoutMs);
    if (typeof page.waitForTimeout === "function") await page.waitForTimeout(Math.min(500, timeoutMs));
  }
  if (!String(metadata?.title ?? "").trim()) {
    throw new IeeeFlowError("paper-metadata", "IEEE paper title metadata is missing.");
  }
  if (!Array.isArray(metadata.authors) || metadata.authors.length === 0) {
    throw new IeeeFlowError("paper-metadata", "IEEE author metadata is missing.");
  }
  if (!Number.isInteger(metadata.year) || !String(metadata.venue ?? "").trim()) {
    throw new IeeeFlowError("paper-metadata", "IEEE year or venue metadata is missing.");
  }
  if (!/^\d+$/.test(String(metadata.articleNumber ?? ""))) {
    throw new IeeeFlowError("paper-metadata", "IEEE article number metadata is missing.");
  }

  const currentUrl = page.url();
  const canonicalCandidate = String(metadata.canonicalUrl ?? "").trim();
  const canonicalUrl = canonicalCandidate
    && hostnameOf(canonicalCandidate, "paper-metadata") === IEEE_HOST
    ? canonicalCandidate
    : currentUrl;
  return {
    title: String(metadata.title).trim(),
    authors: metadata.authors.map((author) => String(author).trim()).filter(Boolean),
    year: Number(metadata.year),
    venue: String(metadata.venue).trim(),
    doi: String(metadata.doi ?? "").trim(),
    url: canonicalUrl,
    articleNumber: String(metadata.articleNumber),
    userAgent: String(metadata.userAgent ?? "").trim(),
    pdfStampUrl: String(metadata.pdfStampUrl ?? "").trim(),
    pdfDirectUrl: String(metadata.pdfDirectUrl ?? "").trim(),
    isFreeDocument: metadata.isFreeDocument === true,
    isOpenAccess: metadata.isOpenAccess === true,
  };
}

async function resolvePaper(page, reference, timeoutMs) {
  if (reference.kind === "url") {
    await page.goto(reference.value, { waitUntil: "domcontentloaded", timeout: timeoutMs });
  } else if (reference.kind === "doi") {
    await page.goto(`https://doi.org/${reference.value}`, {
      waitUntil: "domcontentloaded",
      timeout: timeoutMs,
    });
  } else {
    const searchUrl = `https://${IEEE_HOST}/search/searchresult.jsp?queryText=${encodeURIComponent(reference.value)}`;
    await page.goto(searchUrl, { waitUntil: "domcontentloaded", timeout: timeoutMs });
    const result = await uniqueLocator(
      page.getByRole("link", { name: reference.value, exact: true }),
      "title-search-result",
      "Exact IEEE title result",
    );
    const href = await result.getAttribute("href");
    if (!href) throw new IeeeFlowError("title-search-result", "The exact title result has no target URL.");
    const target = new URL(href, searchUrl);
    if (target.hostname.toLowerCase() !== IEEE_HOST) {
      throw new IeeeFlowError("title-search-result", "The exact title result points outside IEEE Xplore.");
    }
    await page.goto(target.href, { waitUntil: "domcontentloaded", timeout: timeoutMs });
  }
  await waitForDocument(page, timeoutMs);
  const hostname = hostnameOf(page.url(), "resolve-paper");
  if (hostname !== IEEE_HOST) {
    throw new IeeeFlowError("resolve-paper", `Expected IEEE Xplore, received host ${hostname}.`);
  }
  return readPaperMetadata(page, timeoutMs);
}

async function resolvePdfUrls(page, paperUrl, timeoutMs, fallbackStampUrl = "") {
  let pdfLink = page.locator(SELECTORS.pdfHref);
  const count = await pdfLink.count();
  let href = "";
  if (count === 0) {
    href = fallbackStampUrl;
    if (!href) return null;
  } else if (count > 1) {
    const primary = page.locator(SELECTORS.pdfPrimaryHref);
    const primaryCount = await primary.count();
    if (primaryCount !== 1) {
      throw new IeeeFlowError("pdf-link", "IEEE PDF action is ambiguous.", { count, primaryCount });
    }
    pdfLink = primary;
  }
  if (!href) href = await pdfLink.getAttribute("href");
  if (!href) throw new IeeeFlowError("pdf-link", "The IEEE PDF action has no target URL.");
  const stampUrl = new URL(href, paperUrl);
  if (stampUrl.hostname.toLowerCase() !== IEEE_HOST) {
    throw new IeeeFlowError("pdf-link", "The IEEE PDF action points outside IEEE Xplore.");
  }
  await page.goto(stampUrl.href, { waitUntil: "domcontentloaded", timeout: timeoutMs });
  await waitForDocument(page, timeoutMs);
  const landed = new URL(page.url());
  if (landed.hostname.toLowerCase() !== IEEE_HOST) {
    throw new IeeeFlowError("pdf-frame", "IEEE PDF navigation left the expected host.");
  }
  if (!landed.pathname.startsWith("/stamp/") || landed.searchParams.has("denied")) return null;
  const frame = page.locator(SELECTORS.pdfFrame);
  if (typeof frame.waitFor === "function") {
    await frame.waitFor({ state: "attached", timeout: timeoutMs });
  }
  await uniqueLocator(frame, "pdf-frame", "IEEE PDF frame");
  const src = await frame.getAttribute("src");
  if (!src) throw new IeeeFlowError("pdf-frame", "The IEEE PDF frame has no source URL.");
  const pdfUrl = new URL(src, stampUrl.href);
  if (pdfUrl.hostname.toLowerCase() !== IEEE_HOST) {
    throw new IeeeFlowError("pdf-frame", "The IEEE PDF frame points outside IEEE Xplore.");
  }
  return { stampUrl: stampUrl.href, pdfUrl: pdfUrl.href };
}

async function assertPdfFile(pdfPath) {
  let handle;
  try {
    handle = await open(pdfPath, "r");
    const header = Buffer.alloc(5);
    const { bytesRead } = await handle.read(header, 0, header.length, 0);
    if (bytesRead !== 5 || header.toString("ascii") !== "%PDF-") {
      throw new IeeeFlowError("download-validation", "The downloaded file is not a PDF.");
    }
  } catch (error) {
    if (error instanceof IeeeFlowError) throw error;
    throw new IeeeFlowError("download-validation", "The downloaded PDF could not be read.");
  } finally {
    await handle?.close();
  }
}

async function tryFetchPdf({ page, browserContext, paper, workDir, timeoutMs }) {
  await page.goto(paper.url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
  await waitForDocument(page, timeoutMs);
  const urls = await resolvePdfUrls(page, paper.url, timeoutMs, paper.pdfStampUrl);
  if (!urls) return null;
  const response = await browserContext.request.get(urls.pdfUrl, {
    failOnStatusCode: false,
    maxRedirects: 0,
    timeout: timeoutMs,
    headers: {
      accept: "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
      referer: urls.stampUrl,
      ...(paper.userAgent ? { "user-agent": paper.userAgent } : {}),
    },
  });
  const bytes = await response.body();
  if (!response.ok() || bytes.length < 5 || bytes.subarray(0, 5).toString("ascii") !== "%PDF-") {
    return null;
  }
  await mkdir(workDir, { recursive: true });
  const finalPath = path.join(workDir, "paper.pdf");
  const partialPath = `${finalPath}.partial`;
  try {
    await writeFile(partialPath, bytes, { flag: "wx" });
    await assertPdfFile(partialPath);
    await rename(partialPath, finalPath);
  } catch (error) {
    await rm(partialPath, { force: true });
    throw error;
  }
  return { pdfPath: finalPath, pdfUrl: urls.pdfUrl };
}

async function exportOfficialBibtex({ browserContext, paper, timeoutMs }) {
  const response = await browserContext.request.post(CITATION_URL, {
    failOnStatusCode: false,
    maxRedirects: 0,
    timeout: timeoutMs,
    headers: {
      accept: "application/x-bibtex,text/plain;q=0.9,*/*;q=0.8",
      referer: paper.url,
      ...(paper.userAgent ? { "user-agent": paper.userAgent } : {}),
    },
    data: {
      recordIds: [paper.articleNumber],
      "download-format": "download-bibtex",
      lite: true,
    },
  });
  const raw = await response.text();
  let bibtex = "";
  try {
    bibtex = String(JSON.parse(raw)?.data ?? "");
  } catch {
    bibtex = "";
  }
  if (!response.ok() || !/^\s*@\w+\s*\{/i.test(bibtex)) {
    throw new IeeeFlowError("citation-export", "IEEE did not return an official BibTeX entry.");
  }
  return bibtex;
}

export async function readInstitutionProfile({ secretPath = "" } = {}) {
  const bridge = path.join(MODULE_DIR, "read-institution-profile.ps1");
  const args = [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    bridge,
  ];
  if (secretPath) args.push("-SecretPath", secretPath);
  let stdout;
  try {
    ({ stdout } = await execFileAsync("powershell", args, {
      encoding: "utf8",
      windowsHide: true,
      maxBuffer: 64 * 1024,
    }));
    return normalizeInstitutionProfile(JSON.parse(stdout));
  } catch {
    throw new IeeeFlowError("credential-read", "The IEEE institution profile could not be loaded.");
  }
}

export async function readCredentialForHost(
  hostname,
  { secretPath = "", institutionProfile } = {},
) {
  if (!isApprovedCredentialHost(hostname, institutionProfile)) {
    throw new IeeeFlowError(
      "unexpected-auth-host",
      "Credential release denied for an unapproved hostname.",
      { hostname },
    );
  }
  const bridge = path.join(MODULE_DIR, "read-browser-credential.ps1");
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
    throw new IeeeFlowError("credential-read", "The encrypted credential could not be loaded.");
  }
  try {
    const credential = JSON.parse(stdout);
    if (!String(credential.username ?? "") || !String(credential.password ?? "")) {
      throw new Error("missing credential fields");
    }
    return { username: String(credential.username), password: String(credential.password) };
  } catch {
    throw new IeeeFlowError("credential-read", "The credential bridge returned an invalid response.");
  }
}

async function openCarsiInstitutionLogin(page, timeoutMs, institutionProfile) {
  await page.goto(CARSI_DISCOVERY_URL, { waitUntil: "domcontentloaded", timeout: timeoutMs });
  const school = await uniqueLocator(
    page.getByPlaceholder(institutionProfile.carsiSchoolPlaceholder, { exact: true }),
    "carsi-school",
    "CARSI institution search",
  );
  await school.fill(institutionProfile.carsiSearchText);
  const candidate = page.getByRole("option", {
    name: institutionProfile.carsiInstitution,
    exact: true,
  });
  if (typeof candidate.waitFor === "function") {
    await candidate.waitFor({ state: "visible", timeout: timeoutMs });
  }
  const institution = await uniqueLocator(
    candidate,
    "carsi-institution",
    `${institutionProfile.organization} CARSI option`,
  );
  await institution.click();
  const carsiLogin = await uniqueLocator(
    page.getByRole("button", { name: institutionProfile.carsiLoginButtonName, exact: true }),
    "carsi-login",
    "CARSI login button",
  );
  await carsiLogin.click();
  if (typeof page.waitForURL === "function") {
    try {
      await page.waitForURL((url) => url.hostname.toLowerCase() !== "ds.carsi.edu.cn", {
        timeout: timeoutMs,
      });
    } catch {
      // Existing CARSI sessions may remain on discovery; recheck IEEE once below.
    }
  }
  await waitForDocument(page, timeoutMs);
  return hostnameOf(page.url(), "unexpected-auth-host");
}

async function authenticateThroughCarsi({
  page,
  credentialReader,
  institutionProfile,
  secretPath,
  timeoutMs,
}) {
  let authHost = "";
  for (let attempt = 0; attempt < 2; attempt += 1) {
    authHost = await openCarsiInstitutionLogin(page, timeoutMs, institutionProfile);
    if (authHost !== "chromewebdata") break;
  }
  if (authHost === "ds.carsi.edu.cn") return;
  if (!isApprovedCredentialHost(authHost, institutionProfile)) {
    throw new IeeeFlowError(
      "unexpected-auth-host",
      `CARSI redirected to unapproved authentication host ${authHost}.`,
      { hostname: authHost },
    );
  }

  const credential = await credentialReader(authHost, { secretPath, institutionProfile });
  try {
    const username = await uniqueLocator(
      page.getByLabel(institutionProfile.usernameLabel, { exact: true }),
      "institution-username",
      `${institutionProfile.organization} username field`,
    );
    const password = await uniqueLocator(
      page.getByLabel(institutionProfile.passwordLabel, { exact: true }),
      "institution-password",
      `${institutionProfile.organization} password field`,
    );
    const login = await uniqueLocator(
      page.getByRole("button", { name: institutionProfile.loginButtonName, exact: true }),
      "institution-login",
      `${institutionProfile.organization} login button`,
    );
    await username.fill(credential.username);
    await password.fill(credential.password);
    await login.click();
    if (typeof page.waitForURL === "function") {
      try {
        await page.waitForURL((url) => url.hostname.toLowerCase() !== institutionProfile.credentialHost, {
          timeout: Math.min(timeoutMs, 15_000),
        });
      } catch {
        // The bounded hostname check below reports an incomplete login.
      }
    }
    await waitForDocument(page, timeoutMs);
  } finally {
    credential.username = null;
    credential.password = null;
  }
  if (
    institutionProfile.consentTitle
    && isApprovedCredentialHost(
      hostnameOf(page.url(), "authentication-result"),
      institutionProfile,
    )
  ) {
    const title = await page.title();
    const consent = page.getByRole("button", {
      name: institutionProfile.consentButtonName,
      exact: true,
    });
    const consentCount = await consent.count();
    if (title === institutionProfile.consentTitle && consentCount === 1) {
      await consent.click();
      if (typeof page.waitForURL === "function") {
        try {
          await page.waitForURL((url) => url.hostname.toLowerCase() !== institutionProfile.credentialHost, {
            timeout: Math.min(timeoutMs, 30_000),
          });
        } catch {
          // The bounded hostname check below reports a rejected attribute release.
        }
      }
      await waitForDocument(page, timeoutMs);
    }
  }
  if (isApprovedCredentialHost(hostnameOf(page.url(), "authentication-result"), institutionProfile)) {
    throw new IeeeFlowError(
      "authentication-not-complete",
      "Institutional login did not complete; CAPTCHA, OTP, or corrected credentials may be required.",
      { requiresUserAction: true },
    );
  }
}

function resultPayload(paper, downloaded, bibtex) {
  return {
    status: "downloaded",
    title: paper.title,
    authors: paper.authors,
    year: paper.year,
    venue: paper.venue,
    doi: paper.doi,
    landingUrl: paper.url,
    pdfPath: downloaded.pdfPath,
    pdfUrl: downloaded.pdfUrl,
    bibtex,
    bibtexUrl: CITATION_URL,
  };
}

export async function retrieveIeeePaper(options) {
  if (!options?.page || !options?.browserContext?.request) {
    throw new TypeError("page and browserContext are required");
  }
  if (!String(options.workDir ?? "").trim()) throw new TypeError("workDir is required");
  const workDir = path.resolve(String(options.workDir));
  const timeoutMs = Number(options.timeoutMs ?? 45_000);
  const credentialReader = options.credentialReader ?? readCredentialForHost;
  const profileReader = options.profileReader ?? readInstitutionProfile;
  const secretPath = options.secretPath ? path.resolve(String(options.secretPath)) : "";
  await mkdir(workDir, { recursive: true });

  const paper = await resolvePaper(
    options.page,
    classifyPaperReference(options.reference),
    timeoutMs,
  );
  let downloaded = await tryFetchPdf({
    page: options.page,
    browserContext: options.browserContext,
    paper,
    workDir,
    timeoutMs,
  });
  if (!downloaded && (paper.isFreeDocument || paper.isOpenAccess)) {
    if (typeof options.page.waitForTimeout === "function") {
      await options.page.waitForTimeout(Math.min(750, timeoutMs));
    }
    downloaded = await tryFetchPdf({
      page: options.page,
      browserContext: options.browserContext,
      paper,
      workDir,
      timeoutMs,
    });
  }
  if (!downloaded) {
    const institutionProfile = options.institutionProfile
      ? normalizeInstitutionProfile(options.institutionProfile)
      : await profileReader({ secretPath });
    await authenticateThroughCarsi({
      page: options.page,
      credentialReader,
      institutionProfile,
      secretPath,
      timeoutMs,
    });
    downloaded = await tryFetchPdf({
      page: options.page,
      browserContext: options.browserContext,
      paper,
      workDir,
      timeoutMs,
    });
    if (!downloaded) {
      if (typeof options.page.waitForTimeout === "function") {
        await options.page.waitForTimeout(Math.min(750, timeoutMs));
      }
      downloaded = await tryFetchPdf({
        page: options.page,
        browserContext: options.browserContext,
        paper,
        workDir,
        timeoutMs,
      });
    }
  }
  if (!downloaded) {
    throw new IeeeFlowError(
      "download-after-auth",
      "IEEE did not return a PDF after CARSI authentication; entitlement may not cover the item.",
    );
  }
  const bibtex = await exportOfficialBibtex({
    browserContext: options.browserContext,
    paper,
    timeoutMs,
  });
  return resultPayload(paper, downloaded, bibtex);
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
    return await retrieveIeeePaper({ ...options, page, browserContext, workDir });
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
      throw new Error(`Invalid argument: ${arg}`);
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
      throw new Error(`Missing --${required.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}`);
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
      phase: error instanceof IeeeFlowError ? error.phase : "automation",
      message: String(error?.message ?? error),
    };
    process.stderr.write(`${JSON.stringify(payload)}\n`);
    process.exitCode = 1;
  });
}
