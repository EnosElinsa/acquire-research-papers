import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

let subject = {};
try {
  subject = await import("../../scripts/ieee-playwright.mjs");
} catch {
  // RED: tests below define the generalized bridge contract.
}

const INSTITUTION_PROFILE = Object.freeze({
  organization: "Example University",
  carsiSchoolPlaceholder: "Institution name",
  carsiSearchText: "Example University",
  carsiInstitution: "Example University (Example)",
  carsiLoginButtonName: "Continue",
  carsiEntityId: "https://login.example.edu/idp/shibboleth",
  credentialHost: "login.example.edu",
  usernameLabel: "Account",
  passwordLabel: "Passcode",
  loginButtonName: "Sign in",
  resourceAccessUrl: "https://ds.carsi.edu.cn/resource/gotoResource.php?id=resource:example-ieee",
  attributeReleaseTitle: "Release information",
  attributeReleaseAcceptControlName: "_eventId_proceed",
  attributeReleaseRejectControlName: "_eventId_AttributeReleaseRejected",
});

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
    if (this.key === "iframe") {
      if (this.page.stampVisits <= this.page.missingPdfFrameVisits) return 0;
      return this.page.currentUrl.includes("/stamp/stamp.jsp") ? 1 : 0;
    }
    if (this.key === "institution") return this.page.institutionReady ? 1 : 0;
    if (this.key === "username" && this.page.idpSessionActive) return 0;
    if (this.key === "username" && this.page.attributeReleaseReady) return 0;
    if (this.key === "username" && this.page.delayedIdpForm && !this.page.idpFormReady) return 0;
    if (this.key === "attribute-accept" || this.key === "attribute-reject") {
      if (this.key === "attribute-reject" && this.page.attributeRejectMissing) return 0;
      return this.page.attributeReleaseReady && this.page.attributeControlsReady ? 1 : 0;
    }
    if (this.key === "school" && this.page.requireCurrentCarsiLoginUrl) {
      return this.page.currentUrl === "https://ds.carsi.edu.cn/login/index.html" ? 1 : 0;
    }
    if (this.key === "document-title") return 1;
    return 1;
  }

  async waitFor() {
    if (this.key === "institution") this.page.institutionReady = true;
    if (this.key === "username" && this.page.delayedIdpForm) this.page.idpFormReady = true;
    if (this.key === "attribute-accept" || this.key === "attribute-reject") {
      this.page.attributeControlsReady = true;
    }
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

  async evaluate(_callback, value) {
    if (this.key !== "carsi-entity-id") throw new Error(`Unexpected evaluate target: ${this.key}`);
    this.page.carsiEntityId = value;
  }

  async inputValue() {
    if (this.key !== "carsi-entity-id") throw new Error(`Unexpected inputValue target: ${this.key}`);
    return this.page.carsiEntityId;
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
        if (this.page.attributeReleaseForExistingSession) {
          this.page.attributeReleaseOrigin = "login";
          this.page.attributeReleaseReady = true;
          this.page.currentUrl = `https://${this.page.redirectHost}/idp/profile/SAML2/Redirect/SSO?execution=e1s2`;
        } else {
          this.page.currentUrl = `https://${this.page.redirectHost}/login`;
        }
      }
    } else if (this.key === "institution-login") {
      this.page.authenticated = true;
      if (this.page.attributeReleaseAfterLogin) {
        this.page.attributeReleaseOrigin = "login";
        this.page.attributeReleaseReady = true;
        this.page.currentUrl = `https://${this.page.redirectHost}/idp/profile/SAML2/Redirect/SSO?execution=e1s2`;
      } else {
        this.page.currentUrl = "https://ds.carsi.edu.cn/ds/index.html";
      }
    } else if (this.key === "attribute-accept") {
      this.page.attributeReleaseReady = false;
      this.page.attributeReleaseAccepted = true;
      this.page.authenticated = true;
      this.page.currentUrl = this.page.attributeReleaseOrigin === "login"
        ? "https://ds.carsi.edu.cn/ds/index.html"
        : (
          this.page.attributeReleaseReturnsCarsiOnce
            ? "https://ds.carsi.edu.cn/ds/index.html"
            : this.page.resourceGatewayReturnsIeee
            ? "https://ieeexplore.ieee.org/document/11014597"
            : "https://ds.carsi.edu.cn/ds/index.html"
        );
    } else if (this.key === "attribute-reject") {
      this.page.attributeReleaseRejected = true;
    }
  }
}

class FakePage {
  constructor({
    redirectHost = "login.example.edu",
    denyFirstStamp = false,
    evaluateFailures = 0,
    paperNavigationFailures = 0,
    missingPdfFrameVisits = 0,
    carsiNavigationFailures = 0,
    requireCurrentCarsiLoginUrl = false,
    idpSessionActive = false,
    delayedIdpForm = false,
    attributeReleaseAfterLogin = false,
    attributeReleaseForExistingSession = false,
    attributeReleaseManualProceeds = false,
    attributeRejectMissing = false,
    attributeReleaseReturnsCarsiOnce = false,
    delayedAttributeReleaseControls = false,
    requiresAttributeRelease = false,
    resourceGatewayReturnsIeee = true,
    resourceGatewayRequiresLogin = true,
    resourceGatewayPortalVisits = 0,
    resourceGatewayNavigationFailures = 0,
    xplMetadata = {},
  } = {}) {
    this.currentUrl = "about:blank";
    this.redirectHost = redirectHost;
    this.denyFirstStamp = denyFirstStamp;
    this.evaluateFailures = evaluateFailures;
    this.paperNavigationFailures = paperNavigationFailures;
    this.missingPdfFrameVisits = missingPdfFrameVisits;
    this.stampVisits = 0;
    this.carsiNavigationFailures = carsiNavigationFailures;
    this.requireCurrentCarsiLoginUrl = requireCurrentCarsiLoginUrl;
    this.carsiAttempts = 0;
    this.idpSessionActive = idpSessionActive;
    this.delayedIdpForm = delayedIdpForm;
    this.idpFormReady = !delayedIdpForm;
    this.attributeReleaseAfterLogin = attributeReleaseAfterLogin;
    this.attributeReleaseForExistingSession = attributeReleaseForExistingSession;
    this.attributeReleaseManualProceeds = attributeReleaseManualProceeds;
    this.attributeRejectMissing = attributeRejectMissing;
    this.attributeReleaseReturnsCarsiOnce = attributeReleaseReturnsCarsiOnce;
    this.attributeControlsReady = !delayedAttributeReleaseControls;
    this.attributeReleaseOrigin = "";
    this.requiresAttributeRelease = requiresAttributeRelease;
    this.resourceGatewayReturnsIeee = resourceGatewayReturnsIeee;
    this.resourceGatewayRequiresLogin = resourceGatewayRequiresLogin;
    this.resourceGatewayPortalVisits = resourceGatewayPortalVisits;
    this.resourceGatewayNavigationFailures = resourceGatewayNavigationFailures;
    this.resourceGatewayVisits = 0;
    this.attributeReleaseReady = false;
    this.attributeReleaseAccepted = false;
    this.attributeReleaseRejected = false;
    this.xplMetadata = xplMetadata;
    this.actions = [];
    this.navigations = [];
    this.authenticated = false;
    this.institutionReady = true;
    this.carsiEntityId = "";
  }

  async goto(url) {
    this.navigations.push(url);
    if (url.includes("/document/11014597") && this.paperNavigationFailures > 0) {
      this.paperNavigationFailures -= 1;
      this.currentUrl = "chrome-error://chromewebdata/";
      throw new Error("page.goto: net::ERR_ABORTED at chrome-error://chromewebdata/");
    }
    if (url === INSTITUTION_PROFILE.resourceAccessUrl && this.resourceGatewayNavigationFailures > 0) {
      this.resourceGatewayNavigationFailures -= 1;
      throw new Error("page.goto: net::ERR_ABORTED while opening the resource gateway");
    }
    if (url.includes("/stamp/stamp.jsp")) this.stampVisits += 1;
    if (url.includes("/stamp/stamp.jsp") && this.denyFirstStamp && !this.authenticated) {
      this.currentUrl = "https://ieeexplore.ieee.org/document/11014597?denied=";
    } else if (url === INSTITUTION_PROFILE.resourceAccessUrl) {
      this.resourceGatewayVisits += 1;
      if (this.resourceGatewayRequiresLogin && !this.authenticated) {
        this.currentUrl = "https://ds.carsi.edu.cn/login/index.html";
      } else if (this.requiresAttributeRelease && !this.attributeReleaseAccepted) {
        this.attributeReleaseOrigin = "resource";
        this.attributeReleaseReady = true;
        this.currentUrl = `https://${this.redirectHost}/idp/profile/SAML2/Redirect/SSO?execution=e1s2`;
      } else {
        this.currentUrl = (
          this.resourceGatewayVisits > this.resourceGatewayPortalVisits
          && this.resourceGatewayReturnsIeee
        )
          ? "https://ieeexplore.ieee.org/document/11014597"
          : "https://ds.carsi.edu.cn/ds/index.html";
      }
    } else {
      this.currentUrl = url;
    }
  }

  url() { return this.currentUrl; }
  async waitForLoadState() {}
  async waitForURL() {
    if (this.attributeReleaseManualProceeds && this.attributeReleaseReady) {
      this.attributeReleaseReady = false;
      this.attributeReleaseAccepted = true;
      this.authenticated = true;
      this.currentUrl = "https://ds.carsi.edu.cn/resource/resource.php";
      return;
    }
    if (this.idpSessionActive && this.currentUrl.includes(this.redirectHost)) {
      this.currentUrl = "https://ds.carsi.edu.cn/ds/index.html";
      this.authenticated = true;
    }
  }
  async waitForTimeout() {}
  async title() {
    return this.attributeReleaseReady
      ? INSTITUTION_PROFILE.attributeReleaseTitle
      : "A Synthetic IEEE Paper | IEEE Xplore";
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
    if (selector === 'input[name="entityID"]') return new FakeLocator(this, "carsi-entity-id");
    if (selector === `button[name="${INSTITUTION_PROFILE.attributeReleaseAcceptControlName}"]`) {
      return new FakeLocator(this, "attribute-accept");
    }
    if (selector === `button[name="${INSTITUTION_PROFILE.attributeReleaseRejectControlName}"]`) {
      return new FakeLocator(this, "attribute-reject");
    }
    throw new Error(`Unexpected selector: ${selector}`);
  }

  getByPlaceholder(name) {
    assert.equal(name, INSTITUTION_PROFILE.carsiSchoolPlaceholder);
    return new FakeLocator(this, "school");
  }
  getByLabel(name) {
    if (name === INSTITUTION_PROFILE.usernameLabel) return new FakeLocator(this, "username");
    if (name === INSTITUTION_PROFILE.passwordLabel) return new FakeLocator(this, "password");
    throw new Error(`Unexpected label: ${name}`);
  }
  getByRole(role, options = {}) {
    if (role === "option") {
      assert.equal(options.name, INSTITUTION_PROFILE.carsiInstitution);
      return new FakeLocator(this, "institution");
    }
    if (role === "link") return new FakeLocator(this, "title-result");
    if (role === "button") {
      if (this.currentUrl.includes(this.redirectHost)) {
        assert.equal(options.name, INSTITUTION_PROFILE.loginButtonName);
      } else {
        assert.equal(options.name, INSTITUTION_PROFILE.carsiLoginButtonName);
      }
      return new FakeLocator(
        this,
        this.currentUrl.includes(this.redirectHost) ? "institution-login" : "carsi-login",
      );
    }
    throw new Error(`Unexpected role: ${role}`);
  }
}

function fakeContext(options) {
  return { request: new FakeRequestContext(options) };
}

test("uses a configured institution profile and exact credential host", () => {
  assert.equal(subject.classifyPaperReference("https://ieeexplore.ieee.org/document/11014597").kind, "url");
  assert.equal(subject.classifyPaperReference("10.1109/TAP.2025.3571069").kind, "doi");
  assert.deepEqual(subject.normalizeInstitutionProfile(INSTITUTION_PROFILE), INSTITUTION_PROFILE);
  assert.equal(subject.isApprovedCredentialHost("LOGIN.EXAMPLE.EDU", INSTITUTION_PROFILE), true);
  assert.equal(subject.isApprovedCredentialHost("login.example.edu.evil.example", INSTITUTION_PROFILE), false);
  assert.equal(subject.isApprovedCredentialHost("login.example.edu.", INSTITUTION_PROFILE), false);
  assert.throws(
    () => subject.normalizeInstitutionProfile({
      ...INSTITUTION_PROFILE,
      attributeReleaseAcceptControlName: INSTITUTION_PROFILE.attributeReleaseRejectControlName,
    }),
    /accept and reject control names must be different/i,
  );
  assert.throws(
    () => subject.normalizeInstitutionProfile({ ...INSTITUTION_PROFILE, credentialHost: "https://login.example.edu/path" }),
    /exact DNS hostname/,
  );
  assert.throws(
    () => subject.normalizeInstitutionProfile({
      ...INSTITUTION_PROFILE,
      carsiEntityId: "https://login.example.edu:8443/idp/shibboleth",
    }),
    /CARSI entity ID/,
  );
  assert.equal(Object.hasOwn(subject.SELECTORS, "carsiInstitution"), false);
  assert.equal(subject.SELECTORS.pdfPrimaryHref, 'a.xpl-btn-pdf[href*="/stamp/stamp.jsp"]');
  assert.equal(
    subject.sanitizeTransitionUrl("https://idp.example.edu/SSO?execution=e1s2&token=secret#state"),
    "https://idp.example.edu/SSO?execution=[redacted]&token=[redacted]",
  );
});

test("sanitizes URL query values at the automation error boundary", () => {
  const payload = subject.toErrorPayload(new subject.IeeeFlowError(
    "paper-navigation",
    "page.goto failed for https://ieeexplore.ieee.org/document/11014597?RelayState=TOPSECRET&SAMLRequest=SECRET2",
    {
      targetUrl: "https://ieeexplore.ieee.org/document/11014597?Signature=SECRET3&OSSAccessKeyId=SECRET4&token=SECRET5",
    },
  ));
  const serialized = JSON.stringify(payload);
  for (const secret of ["TOPSECRET", "SECRET2", "SECRET3", "SECRET4", "SECRET5"]) {
    assert.equal(serialized.includes(secret), false);
  }
  for (const key of ["RelayState", "SAMLRequest", "Signature", "OSSAccessKeyId", "token"]) {
    assert.equal(serialized.includes(`${key}=[redacted]`), true);
  }
});

test("preserves Unicode across the PowerShell profile and credential bridges", async () => {
  if (process.platform !== "win32") return;
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-utf8-"));
  const secretPath = path.join(root, "secrets.clixml");
  const setupPath = path.join(root, "setup.ps1");
  const secretStore = path.resolve("scripts", "secret-store.ps1").replaceAll("'", "''");
  const escapedSecretPath = secretPath.replaceAll("'", "''");
  try {
    const setup = `
$ErrorActionPreference = "Stop"
. '${secretStore}'
$password = ConvertTo-SecureString "测试密码" -AsPlainText -Force
$credential = [Management.Automation.PSCredential]::new("测试用户", $password)
$institution = [pscustomobject]@{
  Organization = "测试大学"
  CarsiSchoolPlaceholder = "请输入高校/机构名称"
  CarsiSearchText = "测试大学"
  CarsiInstitution = "测试大学（Test University）"
  CarsiLoginButtonName = "登录"
  CarsiEntityId = "https://login.example.edu/idp/shibboleth"
  CredentialHost = "login.example.edu"
  UsernameLabel = "用户名"
  PasswordLabel = "密码"
  LoginButtonName = "登录"
  ResourceAccessUrl = "https://ds.carsi.edu.cn/resource/gotoResource.php?id=resource:unicode-ieee"
  AttributeReleaseTitle = ""
  AttributeReleaseAcceptControlName = ""
  AttributeReleaseRejectControlName = ""
}
Set-IeeeInstitutionCredential -Institution $institution -Credential $credential -Path '${escapedSecretPath}'
`;
    await writeFile(setupPath, `\ufeff${setup}`, "utf8");
    await execFileAsync("powershell", [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      setupPath,
    ]);

    const profile = await subject.readInstitutionProfile({ secretPath });
    assert.equal(profile.organization, "测试大学");
    assert.equal(profile.carsiSchoolPlaceholder, "请输入高校/机构名称");
    assert.equal(profile.usernameLabel, "用户名");
    const credential = await subject.readCredentialForHost("login.example.edu", {
      secretPath,
      institutionProfile: profile,
    });
    assert.deepEqual(credential, { username: "测试用户", password: "测试密码" });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
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
      institutionProfile: INSTITUTION_PROFILE,
      credentialReader: async (host) => {
        reads += 1;
        assert.equal(host, "login.example.edu");
        return { username: "synthetic-user", password: "synthetic-password" };
      },
    });
    assert.equal(result.status, "downloaded");
    assert.equal(reads, 1);
    assert.ok(page.navigations.includes(INSTITUTION_PROFILE.resourceAccessUrl));
    assert.equal(page.username, "synthetic-user");
    assert.equal(page.password, "synthetic-password");

    await assert.rejects(
      subject.retrieveIeeePaper({
        page: new FakePage({ redirectHost: "login.example.edu.evil.example" }),
        browserContext: fakeContext({ pdfResponses: [new FakeResponse("denied", { status: 403 })] }),
        reference: "https://ieeexplore.ieee.org/document/11014597",
        workDir: path.join(root, "evil"),
        institutionProfile: INSTITUTION_PROFILE,
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
      institutionProfile: INSTITUTION_PROFILE,
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

test("opens the current CARSI login endpoint before resolving institution controls", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-carsi-entry-"));
  try {
    const context = fakeContext({
      pdfResponses: [
        new FakeResponse("denied", { status: 403, contentType: "text/html" }),
        new FakeResponse("%PDF-1.7\nauthorized\n%%EOF\n"),
      ],
    });
    const result = await subject.retrieveIeeePaper({
      page: new FakePage({ requireCurrentCarsiLoginUrl: true }),
      browserContext: context,
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      institutionProfile: INSTITUTION_PROFILE,
      credentialReader: async () => ({
        username: "synthetic-user",
        password: "synthetic-password",
      }),
    });
    assert.equal(result.status, "downloaded");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("an existing IdP session reaches the configured resource without reading credentials", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-idp-session-"));
  let reads = 0;
  try {
    const context = fakeContext({
      pdfResponses: [
        new FakeResponse("denied", { status: 403, contentType: "text/html" }),
        new FakeResponse("%PDF-1.7\nauthorized\n%%EOF\n"),
      ],
    });
    const page = new FakePage({ idpSessionActive: true });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: context,
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      institutionProfile: INSTITUTION_PROFILE,
      credentialReader: async () => {
        reads += 1;
        throw new Error("credentials must not be read for an existing IdP session");
      },
    });
    assert.equal(result.status, "downloaded");
    assert.equal(reads, 0);
    assert.ok(page.navigations.includes(INSTITUTION_PROFILE.resourceAccessUrl));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("waits for a delayed IdP form before the single credential read", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-delayed-idp-"));
  let reads = 0;
  try {
    const result = await subject.retrieveIeeePaper({
      page: new FakePage({ delayedIdpForm: true }),
      browserContext: fakeContext({
        pdfResponses: [
          new FakeResponse("denied", { status: 403, contentType: "text/html" }),
          new FakeResponse("%PDF-1.7\nauthorized\n%%EOF\n"),
        ],
      }),
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      institutionProfile: INSTITUTION_PROFILE,
      credentialReader: async () => {
        reads += 1;
        return { username: "synthetic-user", password: "synthetic-password" };
      },
    });
    assert.equal(result.status, "downloaded");
    assert.equal(reads, 1);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("handles attribute release from an existing IdP session without reading credentials", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-existing-release-"));
  let reads = 0;
  try {
    const page = new FakePage({ attributeReleaseForExistingSession: true });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: fakeContext({
        pdfResponses: [
          new FakeResponse("denied", { status: 403, contentType: "text/html" }),
          new FakeResponse("%PDF-1.7\nauthorized\n%%EOF\n"),
        ],
      }),
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      institutionProfile: INSTITUTION_PROFILE,
      acceptAttributeRelease: true,
      credentialReader: async () => {
        reads += 1;
        throw new Error("credentials must not be read for an existing IdP session");
      },
    });
    assert.equal(result.status, "downloaded");
    assert.equal(reads, 0);
    assert.equal(page.attributeReleaseAccepted, true);
    assert.ok(page.navigations.includes(INSTITUTION_PROFILE.resourceAccessUrl));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("an explicit opt-out does not click accept or reject", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-attribute-manual-"));
  try {
    const page = new FakePage({ requiresAttributeRelease: true });
    await assert.rejects(
      subject.retrieveIeeePaper({
        page,
        browserContext: fakeContext({
          pdfResponses: [new FakeResponse("denied", { status: 403, contentType: "text/html" })],
        }),
        reference: "https://ieeexplore.ieee.org/document/11014597",
        workDir: root,
        institutionProfile: INSTITUTION_PROFILE,
        acceptAttributeRelease: false,
        credentialReader: async () => ({
          username: "synthetic-user",
          password: "synthetic-password",
        }),
      }),
      (error) => error?.phase === "attribute-release-required",
    );
    assert.equal(page.attributeReleaseAccepted, false);
    assert.equal(page.attributeReleaseRejected, false);
    assert.equal(page.actions.some((action) => action[1] === "attribute-accept"), false);
    assert.equal(page.actions.some((action) => action[1] === "attribute-reject"), false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("continues when the user completes attribute release in the visible browser", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-attribute-manual-return-"));
  try {
    const page = new FakePage({
      requiresAttributeRelease: true,
      attributeReleaseManualProceeds: true,
    });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: fakeContext({
        pdfResponses: [
          new FakeResponse("denied", { status: 403, contentType: "text/html" }),
          new FakeResponse("%PDF-1.7\nmanual attribute release\n%%EOF\n"),
        ],
      }),
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      institutionProfile: INSTITUTION_PROFILE,
      acceptAttributeRelease: false,
      credentialReader: async () => ({ username: "user", password: "password" }),
    });
    assert.equal(result.status, "downloaded");
    assert.equal(page.actions.some((action) => action[1] === "attribute-accept"), false);
    assert.equal(page.actions.some((action) => action[1] === "attribute-reject"), false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("automatic attribute release clicks only accept", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-consent-"));
  let reads = 0;
  try {
    const context = fakeContext({
      pdfResponses: [
        new FakeResponse("denied", { status: 403, contentType: "text/html" }),
        new FakeResponse("%PDF-1.7\nauthorized\n%%EOF\n"),
      ],
    });
    const page = new FakePage({ requiresAttributeRelease: true });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: context,
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      institutionProfile: INSTITUTION_PROFILE,
      credentialReader: async () => {
        reads += 1;
        return { username: "synthetic-user", password: "synthetic-password" };
      },
    });
    assert.equal(result.status, "downloaded");
    assert.equal(reads, 1);
    assert.equal(page.attributeReleaseAccepted, true);
    assert.equal(page.attributeReleaseRejected, false);
    assert.deepEqual(
      page.actions.filter((action) => action[1].startsWith("attribute-")),
      [["click", "attribute-accept"]],
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("supports an IdP continuation page with one configured proceed control", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-single-proceed-"));
  try {
    const page = new FakePage({
      requiresAttributeRelease: true,
      attributeRejectMissing: true,
    });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: fakeContext({
        pdfResponses: [
          new FakeResponse("denied", { status: 403, contentType: "text/html" }),
          new FakeResponse("%PDF-1.7\nsingle proceed\n%%EOF\n"),
        ],
      }),
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      institutionProfile: {
        ...INSTITUTION_PROFILE,
        attributeReleaseRejectControlName: "",
      },
      acceptAttributeRelease: true,
      credentialReader: async () => ({ username: "user", password: "password" }),
    });
    assert.equal(result.status, "downloaded");
    assert.equal(page.actions.some((action) => action[1] === "attribute-accept"), true);
    assert.equal(page.actions.some((action) => action[1] === "attribute-reject"), false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("waits for delayed attribute-release controls", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-delayed-attribute-controls-"));
  try {
    const page = new FakePage({
      requiresAttributeRelease: true,
      delayedAttributeReleaseControls: true,
    });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: fakeContext({
        pdfResponses: [
          new FakeResponse("denied", { status: 403, contentType: "text/html" }),
          new FakeResponse("%PDF-1.7\ndelayed attribute controls\n%%EOF\n"),
        ],
      }),
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      institutionProfile: INSTITUTION_PROFILE,
      acceptAttributeRelease: true,
      credentialReader: async () => ({ username: "user", password: "password" }),
    });
    assert.equal(result.status, "downloaded");
    assert.equal(page.attributeReleaseAccepted, true);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("revisits the configured resource after attribute acceptance returns to CARSI", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-release-carsi-"));
  try {
    const page = new FakePage({
      requiresAttributeRelease: true,
      attributeReleaseReturnsCarsiOnce: true,
    });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: fakeContext({
        pdfResponses: [
          new FakeResponse("denied", { status: 403, contentType: "text/html" }),
          new FakeResponse("%PDF-1.7\nauthorized\n%%EOF\n"),
        ],
      }),
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      institutionProfile: INSTITUTION_PROFILE,
      acceptAttributeRelease: true,
      credentialReader: async () => ({
        username: "synthetic-user",
        password: "synthetic-password",
      }),
    });
    assert.equal(result.status, "downloaded");
    assert.equal(
      page.navigations.filter((url) => url === INSTITUTION_PROFILE.resourceAccessUrl).length,
      3,
    );
    assert.deepEqual(
      page.actions.filter((action) => action[1] === "attribute-accept"),
      [["click", "attribute-accept"]],
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("re-enters the configured resource when institutional login returns to the CARSI portal", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-login-portal-return-"));
  try {
    const page = new FakePage({ resourceGatewayRequiresLogin: false, resourceGatewayPortalVisits: 1 });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: fakeContext({
        pdfResponses: [
          new FakeResponse("denied", { status: 403, contentType: "text/html" }),
          new FakeResponse("%PDF-1.7\nauthorized after portal return\n%%EOF\n"),
        ],
      }),
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      institutionProfile: INSTITUTION_PROFILE,
      credentialReader: async () => ({
        username: "synthetic-user",
        password: "synthetic-password",
      }),
    });
    assert.equal(result.status, "downloaded");
    assert.equal(page.resourceGatewayVisits, 2);
    assert.equal(page.actions.some((action) => action[1] === "resource-card"), false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("counts transient CARSI recovery against the three-visit resource gateway budget", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-gateway-budget-"));
  try {
    const page = new FakePage({
      carsiNavigationFailures: 1,
      resourceGatewayPortalVisits: 3,
    });
    await assert.rejects(
      subject.retrieveIeeePaper({
        page,
        browserContext: fakeContext({
          pdfResponses: [new FakeResponse("denied", { status: 403, contentType: "text/html" })],
        }),
        reference: "https://ieeexplore.ieee.org/document/11014597",
        workDir: root,
        institutionProfile: INSTITUTION_PROFILE,
        credentialReader: async () => ({ username: "user", password: "password" }),
      }),
      (error) => error?.phase === "institutional-return",
    );
    assert.equal(page.resourceGatewayVisits, 3);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("retries a transient gateway failure without trusting a stale IEEE page URL", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-stale-gateway-url-"));
  let credentialReads = 0;
  try {
    const page = new FakePage({ resourceGatewayNavigationFailures: 1 });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: fakeContext({
        pdfResponses: [
          new FakeResponse("denied", { status: 403, contentType: "text/html" }),
          new FakeResponse("%PDF-1.7\nauthorized after gateway retry\n%%EOF\n"),
        ],
      }),
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      institutionProfile: INSTITUTION_PROFILE,
      credentialReader: async () => {
        credentialReads += 1;
        return { username: "user", password: "password" };
      },
    });
    assert.equal(result.status, "downloaded");
    assert.equal(credentialReads, 1);
    assert.equal(
      page.navigations.filter((url) => url === INSTITUTION_PROFILE.resourceAccessUrl).length,
      3,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("starts at the configured resource gateway before CARSI institution selection", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-gateway-first-"));
  let reads = 0;
  try {
    const page = new FakePage({ resourceGatewayRequiresLogin: true });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: fakeContext({
        pdfResponses: [
          new FakeResponse("denied", { status: 403, contentType: "text/html" }),
          new FakeResponse("%PDF-1.7\ngateway-first\n%%EOF\n"),
        ],
      }),
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      institutionProfile: INSTITUTION_PROFILE,
      credentialReader: async () => {
        reads += 1;
        return { username: "user", password: "password" };
      },
    });
    assert.equal(result.status, "downloaded");
    assert.equal(reads, 1);
    assert.equal(page.carsiEntityId, INSTITUTION_PROFILE.carsiEntityId);
    assert.equal(page.resourceGatewayVisits, 2);
    const gatewayIndex = page.navigations.indexOf(INSTITUTION_PROFILE.resourceAccessUrl);
    const discoveryIndex = page.navigations.indexOf("https://ds.carsi.edu.cn/login/index.html");
    assert.equal(gatewayIndex >= 0, true);
    assert.equal(discoveryIndex === -1 || gatewayIndex < discoveryIndex, true);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("handles a configured attribute-release page before CARSI return and still visits the resource", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-attribute-login-"));
  try {
    const page = new FakePage({ attributeReleaseAfterLogin: true });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: fakeContext({
        pdfResponses: [
          new FakeResponse("denied", { status: 403, contentType: "text/html" }),
          new FakeResponse("%PDF-1.7\nauthorized\n%%EOF\n"),
        ],
      }),
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      institutionProfile: INSTITUTION_PROFILE,
      acceptAttributeRelease: true,
      credentialReader: async () => ({
        username: "synthetic-user",
        password: "synthetic-password",
      }),
    });
    assert.equal(result.status, "downloaded");
    assert.equal(page.attributeReleaseAccepted, true);
    assert.equal(page.attributeReleaseRejected, false);
    assert.ok(page.navigations.includes(INSTITUTION_PROFILE.resourceAccessUrl));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("does not retry the PDF when the resource gateway fails to return to IEEE", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-return-"));
  try {
    const context = fakeContext({
      pdfResponses: [new FakeResponse("denied", { status: 403, contentType: "text/html" })],
    });
    await assert.rejects(
      subject.retrieveIeeePaper({
        page: new FakePage({ resourceGatewayReturnsIeee: false }),
        browserContext: context,
        reference: "https://ieeexplore.ieee.org/document/11014597",
        workDir: root,
        institutionProfile: INSTITUTION_PROFILE,
        credentialReader: async () => ({
          username: "synthetic-user",
          password: "synthetic-password",
        }),
      }),
      (error) => (
        error?.phase === "institutional-return"
        && error.message.includes("received ds.carsi.edu.cn")
      ),
    );
    assert.equal(context.request.calls.filter((call) => call.method === "GET").length, 1);
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

test("retries one transient chrome-error paper navigation", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-paper-navigation-"));
  try {
    const page = new FakePage({ paperNavigationFailures: 1 });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: fakeContext({
        pdfResponses: [new FakeResponse("%PDF-1.7\nnavigation retry\n%%EOF\n")],
      }),
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      credentialReader: async () => { throw new Error("credentials must not be read"); },
    });
    assert.equal(result.status, "downloaded");
    assert.equal(
      page.navigations.filter((url) => url.includes("/document/11014597")).length >= 2,
      true,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("redacts SAML query values from a real navigation failure payload", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-paper-navigation-error-"));
  try {
    const reference = "https://ieeexplore.ieee.org/document/11014597?RelayState=TOPSECRET&SAMLRequest=SECRET2";
    let caught;
    try {
      await subject.retrieveIeeePaper({
        page: new FakePage({ paperNavigationFailures: 2 }),
        browserContext: fakeContext(),
        reference,
        workDir: root,
        credentialReader: async () => { throw new Error("credentials must not be read"); },
      });
    } catch (error) {
      caught = error;
    }
    assert.ok(caught);
    const serialized = JSON.stringify(subject.toErrorPayload(caught));
    assert.equal(serialized.includes("TOPSECRET"), false);
    assert.equal(serialized.includes("SECRET2"), false);
    assert.equal(serialized.includes("RelayState=[redacted]"), true);
    assert.equal(serialized.includes("SAMLRequest=[redacted]"), true);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("treats a missing pre-auth PDF iframe as an entitlement signal", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-ieee-missing-frame-"));
  let reads = 0;
  try {
    const page = new FakePage({ missingPdfFrameVisits: 1 });
    const result = await subject.retrieveIeeePaper({
      page,
      browserContext: fakeContext({
        pdfResponses: [new FakeResponse("%PDF-1.7\nafter missing frame\n%%EOF\n")],
      }),
      reference: "https://ieeexplore.ieee.org/document/11014597",
      workDir: root,
      institutionProfile: INSTITUTION_PROFILE,
      credentialReader: async () => {
        reads += 1;
        return { username: "user", password: "password" };
      },
    });
    assert.equal(result.status, "downloaded");
    assert.equal(reads, 1);
    assert.equal(page.stampVisits, 2);
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
    assert.equal(
      chromium.calls[0].options.args.some((value) => value.startsWith("--window-position=")),
      false,
    );
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
