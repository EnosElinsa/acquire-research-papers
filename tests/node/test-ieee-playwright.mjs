import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

let subject = {};
try {
  subject = await import("../../scripts/ieee-playwright.mjs");
} catch {
  // RED: tests below define the generalized bridge contract.
}

class FakeResponse {
  constructor(body, { status = 200, contentType = "application/pdf" } = {}) {
    this.bytes = Buffer.from(body);
    this.statusCode = status;
    this.contentType = contentType;
  }

  ok() { return this.statusCode >= 200 && this.statusCode < 300; }
  status() { return this.statusCode; }
  headers() { return { "content-type": this.contentType }; }
  async body() { return this.bytes; }
  async text() { return this.bytes.toString("utf8"); }
}

class FakeRequestContext {
  constructor({ pdfResponses = [], bibtex = "@article{k,title={A Synthetic IEEE Paper}}" } = {}) {
    this.pdfResponses = [...pdfResponses];
    this.bibtex = bibtex;
    this.calls = [];
  }

  async get(url, options) {
    this.calls.push({ method: "GET", url, options });
    const response = this.pdfResponses.shift();
    if (!response) throw new Error("Unexpected PDF request");
    return response;
  }

  async post(url, options) {
    this.calls.push({ method: "POST", url, options });
    return new FakeResponse(JSON.stringify({ data: this.bibtex }), {
      contentType: "application/json",
    });
  }
}

class FakeLocator {
  constructor(page, key) {
    this.page = page;
    this.key = key;
  }

  async count() {
    if (this.key === "pdf") return 2;
    if (this.key === "pdf-primary") return 1;
    if (this.key === "iframe") return this.page.currentUrl.includes("/stamp/stamp.jsp") ? 1 : 0;
    if (this.key === "institution") return this.page.institutionReady ? 1 : 0;
    if (this.key === "document-title") return 1;
    return 1;
  }

  async waitFor() {
    if (this.key === "institution") this.page.institutionReady = true;
  }

  async getAttribute(name) {
    if (this.key === "pdf-primary" && name === "href") {
      return "/stamp/stamp.jsp?tp=&arnumber=11014597";
    }
    if (this.key === "iframe" && name === "src") {
      return "/stampPDF/getPDF.jsp?tp=&arnumber=11014597&ref=synthetic";
    }
    if (this.key === "title-result" && name === "href") return "/document/11014597";
    return null;
  }

  async fill(value) {
    this.page.actions.push(["fill", this.key]);
    if (this.key === "school") this.page.school = value;
    if (this.key === "username") this.page.username = value;
    if (this.key === "password") this.page.password = value;
  }

  async click() {
    this.page.actions.push(["click", this.key]);
    if (this.key === "carsi-login") {
      this.page.carsiAttempts += 1;
      if (this.page.carsiNavigationFailures > 0) {
        this.page.carsiNavigationFailures -= 1;
        this.page.currentUrl = "chrome-error://chromewebdata/";
      } else {
        this.page.currentUrl = `https://${this.page.redirectHost}/login`;
      }
    } else if (this.key === "gxu-login") {
      this.page.authenticated = true;
      if (this.page.requiresConsent) {
        this.page.consentReady = true;
        this.page.currentUrl = `https://${this.page.redirectHost}/consent`;
      } else {
        this.page.currentUrl = "https://ds.carsi.edu.cn/ds/index.html";
      }
    } else if (this.key === "gxu-consent") {
      this.page.consentReady = false;
      this.page.consentAccepted = true;
      this.page.currentUrl = "https://ds.carsi.edu.cn/ds/index.html";
    }
  }
}

class FakePage {
  constructor({
    redirectHost = "idp.gxu.edu.cn",
    denyFirstStamp = false,
    evaluateFailures = 0,
    carsiNavigationFailures = 0,
    requiresConsent = false,
    xplMetadata = {},
  } = {}) {
    this.currentUrl = "about:blank";
    this.redirectHost = redirectHost;
    this.denyFirstStamp = denyFirstStamp;
    this.evaluateFailures = evaluateFailures;
    this.carsiNavigationFailures = carsiNavigationFailures;
    this.carsiAttempts = 0;
    this.requiresConsent = requiresConsent;
    this.consentReady = false;
    this.consentAccepted = false;
    this.xplMetadata = xplMetadata;
    this.actions = [];
    this.authenticated = false;
    this.institutionReady = true;
  }

  async goto(url) {
    if (url.includes("/stamp/stamp.jsp") && this.denyFirstStamp && !this.authenticated) {
      this.currentUrl = "https://ieeexplore.ieee.org/document/11014597?denied=";
    } else {
      this.currentUrl = url;
    }
  }

  url() { return this.currentUrl; }
  async waitForLoadState() {}
  async waitForURL() {}
  async waitForTimeout() {}
  async title() {
    return this.consentReady ? "信息发布" : "A Synthetic IEEE Paper | IEEE Xplore";
  }

  async evaluate() {
    if (this.evaluateFailures > 0) {
      this.evaluateFailures -= 1;
      throw new Error("Execution context was destroyed");
    }
    return {
      citation: {
        title: "A Synthetic IEEE Paper",
        authors: ["Ada Lovelace", "Alan Turing"],
        date: "2026",
        venue: "IEEE Transactions on Testing",
        doi: "10.1109/TEST.2026.1",
        articleNumber: "11014597",
      },
      xpl: this.xplMetadata,
      h1Title: "A Synthetic IEEE Paper",
      canonicalUrl: "https://ieeexplore.ieee.org/document/11014597",
      locationUrl: "https://ieeexplore.ieee.org/document/11014597",
      userAgent: "Synthetic Chrome",
    };
  }

  locator(selector) {
    if (selector === "h1.document-title") return new FakeLocator(this, "document-title");
    if (selector === 'a[href*="/stamp/stamp.jsp"]') return new FakeLocator(this, "pdf");
    if (selector === 'a.xpl-btn-pdf[href*="/stamp/stamp.jsp"]') return new FakeLocator(this, "pdf-primary");
    if (selector === 'iframe[src*="/stampPDF/getPDF.jsp"]') return new FakeLocator(this, "iframe");
    throw new Error(`Unexpected selector: ${selector}`);
  }

  getByPlaceholder() { return new FakeLocator(this, "school"); }
  getByLabel(name) { return new FakeLocator(this, name === "用户名" ? "username" : "password"); }
  getByRole(role) {
    if (role === "option") return new FakeLocator(this, "institution");
    if (role === "link") return new FakeLocator(this, "title-result");
    if (role === "button") {
      if (this.consentReady) return new FakeLocator(this, "gxu-consent");
      return new FakeLocator(this, this.currentUrl.includes(this.redirectHost) ? "gxu-login" : "carsi-login");
    }
    throw new Error(`Unexpected role: ${role}`);
  }
}

function fakeContext(options) {
  return { request: new FakeRequestContext(options) };
}

test("pins reference classification, selectors, and exact credential host", () => {
  assert.equal(subject.classifyPaperReference("https://ieeexplore.ieee.org/document/11014597").kind, "url");
  assert.equal(subject.classifyPaperReference("10.1109/TAP.2025.3571069").kind, "doi");
  assert.equal(subject.isApprovedCredentialHost("IDP.GXU.EDU.CN"), true);
  assert.equal(subject.isApprovedCredentialHost("idp.gxu.edu.cn.evil.example"), false);
  assert.equal(subject.SELECTORS.carsiInstitution, "广西大学（GuangXi University）");
  assert.equal(subject.SELECTORS.pdfPrimaryHref, 'a.xpl-btn-pdf[href*="/stamp/stamp.jsp"]');
});

test("normalizes current xplGlobal metadata when citation meta tags are absent", () => {
  const metadata = subject.normalizePageMetadata({
    citation: {},
    xpl: {
      title: "A Current IEEE Paper",
      authors: [{ name: "Ada Lovelace" }, { name: "Alan Turing" }],
      publicationYear: "2026",
      publicationTitle: "IEEE Transactions on Testing",
      doi: "10.1109/TEST.2026.2",
      articleNumber: "12000001",
      pdfUrl: "/stamp/stamp.jsp?tp=&arnumber=12000001",
      pdfPath: "/iel7/1/2/12000001.pdf",
      isFreeDocument: true,
    },
    h1Title: "A Current IEEE Paper",
    canonicalUrl: "https://ieeexplore.ieee.org/document/12000001",
    locationUrl: "https://ieeexplore.ieee.org/document/12000001",
    userAgent: "Synthetic Chrome",
  });
  assert.equal(metadata.title, "A Current IEEE Paper");
  assert.deepEqual(metadata.authors, ["Ada Lovelace", "Alan Turing"]);
  assert.equal(metadata.year, 2026);
  assert.equal(metadata.venue, "IEEE Transactions on Testing");
  assert.equal(metadata.articleNumber, "12000001");
  assert.equal(metadata.pdfStampUrl, "/stamp/stamp.jsp?tp=&arnumber=12000001");
  assert.equal(metadata.pdfDirectUrl, "/iel7/1/2/12000001.pdf");
  assert.equal(metadata.isFreeDocument, true);
});

test("retries one transient free-document PDF response without authentication", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-free-retry-"));
  try {
    const context = fakeContext({
      pdfResponses: [
        new FakeResponse("challenge", { status: 202, contentType: "text/html" }),
        new FakeResponse("%PDF-1.7\nfree\n%%EOF\n"),
      ],
    });
    const result = await subject.retrieveIeeePaper({
      page: new FakePage({ xplMetadata: { isFreeDocument: true } }),
      browserContext: context,
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      credentialReader: async () => { throw new Error("credentials must not be read"); },
    });
    assert.equal(result.status, "downloaded");
    assert.equal(context.request.calls.filter((call) => call.method === "GET").length, 2);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("downloads PDF and exports raw BibTeX through the shared-cookie request context", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-request-"));
  try {
    const browserContext = fakeContext({
      pdfResponses: [new FakeResponse("%PDF-1.7\nsynthetic\n%%EOF\n")],
      bibtex: "@article{k,title={A Synthetic IEEE Paper},doi={10.1109/TEST.2026.1}}",
    });
    const result = await subject.retrieveIeeePaper({
      page: new FakePage(),
      browserContext,
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      credentialReader: async () => { throw new Error("credentials must not be read"); },
    });
    assert.equal(result.status, "downloaded");
    assert.equal((await readFile(result.pdfPath)).subarray(0, 5).toString("ascii"), "%PDF-");
    assert.match(result.bibtex, /^@article/);
    assert.deepEqual(result.authors, ["Ada Lovelace", "Alan Turing"]);
    assert.equal(result.year, 2026);
    assert.equal(result.venue, "IEEE Transactions on Testing");
    const pdfCall = browserContext.request.calls.find((call) => call.method === "GET");
    assert.equal(pdfCall.options.maxRedirects, 0);
    const bibCall = browserContext.request.calls.find((call) => call.method === "POST");
    assert.equal(bibCall.url, "https://ieeexplore.ieee.org/rest/search/citation/format");
    assert.equal(bibCall.options.maxRedirects, 0);
    assert.deepEqual(bibCall.options.data.recordIds, ["11014597"]);
    assert.equal(bibCall.options.data["download-format"], "download-bibtex");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("authenticates once and retries PDF without releasing credentials to lookalike hosts", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-auth-"));
  let reads = 0;
  try {
    const context = fakeContext({
      pdfResponses: [
        new FakeResponse("denied", { status: 403, contentType: "text/html" }),
        new FakeResponse("%PDF-1.7\nauthorized\n%%EOF\n"),
      ],
    });
    const page = new FakePage();
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: context,
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      credentialReader: async (host) => {
        reads += 1;
        assert.equal(host, "idp.gxu.edu.cn");
        return { username: "synthetic-user", password: "synthetic-password" };
      },
    });
    assert.equal(result.status, "downloaded");
    assert.equal(reads, 1);
    assert.equal(page.username, "synthetic-user");
    assert.equal(page.password, "synthetic-password");

    await assert.rejects(
      subject.retrieveIeeePaper({
        page: new FakePage({ redirectHost: "idp.gxu.edu.cn.evil.example" }),
        browserContext: fakeContext({ pdfResponses: [new FakeResponse("denied", { status: 403 })] }),
        reference: "https://ieeexplore.ieee.org/document/11014597",
        workDir: path.join(root, "evil"),
        credentialReader: async () => { throw new Error("credential leak"); },
      }),
      (error) => error?.phase === "unexpected-auth-host",
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("retries one transient CARSI navigation before reading credentials", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-carsi-retry-"));
  let reads = 0;
  try {
    const context = fakeContext({
      pdfResponses: [
        new FakeResponse("denied", { status: 403, contentType: "text/html" }),
        new FakeResponse("%PDF-1.7\nauthorized\n%%EOF\n"),
      ],
    });
    const page = new FakePage({ carsiNavigationFailures: 1 });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: context,
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      credentialReader: async () => {
        reads += 1;
        return { username: "synthetic-user", password: "synthetic-password" };
      },
    });
    assert.equal(result.status, "downloaded");
    assert.equal(page.carsiAttempts, 2);
    assert.equal(reads, 1);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("accepts the exact Guangxi attribute-release page without a second credential read", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-consent-"));
  let reads = 0;
  try {
    const context = fakeContext({
      pdfResponses: [
        new FakeResponse("denied", { status: 403, contentType: "text/html" }),
        new FakeResponse("%PDF-1.7\nauthorized\n%%EOF\n"),
      ],
    });
    const page = new FakePage({ requiresConsent: true });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: context,
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      credentialReader: async () => {
        reads += 1;
        return { username: "synthetic-user", password: "synthetic-password" };
      },
    });
    assert.equal(result.status, "downloaded");
    assert.equal(reads, 1);
    assert.equal(page.consentAccepted, true);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("retries one transient metadata execution-context loss", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-metadata-"));
  try {
    const result = await subject.retrieveIeeePaper({
      page: new FakePage({ evaluateFailures: 1 }),
      browserContext: fakeContext({
        pdfResponses: [new FakeResponse("%PDF-1.7\nmetadata\n%%EOF\n")],
      }),
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      credentialReader: async () => { throw new Error("credentials must not be read"); },
    });
    assert.equal(result.status, "downloaded");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("launches and closes a dedicated persistent Chrome profile", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-profile-"));
  const page = new FakePage();
  const browserContext = {
    ...fakeContext({ pdfResponses: [new FakeResponse("%PDF-1.7\nprofile\n%%EOF\n")] }),
    pages: () => [page],
    closeCalls: 0,
    async close() { this.closeCalls += 1; },
  };
  const chromium = {
    calls: [],
    async launchPersistentContext(dir, options) {
      this.calls.push({ dir, options });
      return browserContext;
    },
  };
  try {
    const result = await subject.runAutomatedRetrieval({
      chromium,
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: path.join(root, "runs", "run-1"),
      profileDir: path.join(root, "profiles", "ieee"),
      testMode: true,
      credentialReader: async () => { throw new Error("credentials must not be read"); },
    });
    assert.equal(result.status, "downloaded");
    assert.equal(chromium.calls[0].options.channel, "chrome");
    assert.equal(chromium.calls[0].options.headless, false);
    assert.ok(chromium.calls[0].options.args.includes("--window-position=-32000,-32000"));
    assert.equal(browserContext.closeCalls, 1);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("enforces global acquisition runtime boundaries", () => {
  const localAppData = path.resolve("C:/Users/synthetic/AppData/Local");
  const allowed = {
    workDir: path.join(localAppData, "Codex", "paper-acquisition", "runs", "run-1"),
    profileDir: path.join(localAppData, "Codex", "browser-profiles", "acquire-research-papers", "ieee"),
    dependencyRoot: path.join(localAppData, "Codex", "deps", "acquire-research-papers"),
    localAppData,
  };
  assert.doesNotThrow(() => subject.assertAutomationPathBoundaries(allowed));
  assert.throws(() => subject.assertAutomationPathBoundaries({
    ...allowed,
    profileDir: path.join(localAppData, "Google", "Chrome", "User Data"),
  }));
  assert.throws(() => subject.assertAutomationPathBoundaries({
    ...allowed,
    workDir: path.resolve("C:/repo/raw/tmp"),
  }));
});
