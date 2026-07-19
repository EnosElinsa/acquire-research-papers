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
    return new FakeResponse(this.bibtex, { contentType: "application/x-bibtex" });
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
      this.page.currentUrl = `https://${this.page.redirectHost}/login`;
    } else if (this.key === "gxu-login") {
      this.page.authenticated = true;
      this.page.currentUrl = "https://ds.carsi.edu.cn/ds/index.html";
    }
  }
}

class FakePage {
  constructor({ redirectHost = "idp.gxu.edu.cn", denyFirstStamp = false, evaluateFailures = 0 } = {}) {
    this.currentUrl = "about:blank";
    this.redirectHost = redirectHost;
    this.denyFirstStamp = denyFirstStamp;
    this.evaluateFailures = evaluateFailures;
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
  async title() { return "A Synthetic IEEE Paper | IEEE Xplore"; }

  async evaluate() {
    if (this.evaluateFailures > 0) {
      this.evaluateFailures -= 1;
      throw new Error("Execution context was destroyed");
    }
    return {
      title: "A Synthetic IEEE Paper",
      authors: ["Ada Lovelace", "Alan Turing"],
      year: 2026,
      venue: "IEEE Transactions on Testing",
      doi: "10.1109/TEST.2026.1",
      canonicalUrl: "https://ieeexplore.ieee.org/document/11014597",
      articleNumber: "11014597",
      userAgent: "Synthetic Chrome",
    };
  }

  locator(selector) {
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
    assert.equal(bibCall.url, "https://ieeexplore.ieee.org/xpl/downloadCitations");
    assert.equal(bibCall.options.maxRedirects, 0);
    assert.equal(bibCall.options.form.recordIds, "11014597");
    assert.equal(bibCall.options.form["download-format"], "download-bibtex");
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
    assert.equal(chromium.calls[0].options.headless, true);
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
