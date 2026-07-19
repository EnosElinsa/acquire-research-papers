import assert from "node:assert/strict";
import test from "node:test";

import {
  ScienceDirectFlowError,
  SELECTORS,
  assertNoInteractiveChallenge,
  authenticateThroughScau,
  canonicalToProxyUrl,
  isApprovedCredentialHost,
  isApprovedProxyHost,
} from "../../scripts/sciencedirect-playwright.mjs";


const AUTH_URL = "https://vpn.scau.edu.cn/portal/#!/login";
const PROXY_URL =
  "https://www-sciencedirect-com-s.vpn.scau.edu.cn/science/article/pii/S1049007824000411";


class FakeLocator {
  constructor({ count = 1, fill = null, click = null, text = "" } = {}) {
    this.matchCount = count;
    this.onFill = fill;
    this.onClick = click;
    this.text = text;
  }

  async count() {
    return this.matchCount;
  }

  async fill(value) {
    if (this.onFill) this.onFill(value);
  }

  async click() {
    if (this.onClick) this.onClick();
  }

  async innerText() {
    return this.text;
  }
}


class FakePage {
  constructor({ url = AUTH_URL, bodyText = "用户登录", afterSubmitUrl = PROXY_URL } = {}) {
    this.currentUrl = url;
    this.bodyText = bodyText;
    this.afterSubmitUrl = afterSubmitUrl;
    this.username = "";
    this.password = "";
    this.submissions = 0;
  }

  url() {
    return this.currentUrl;
  }

  locator(selector) {
    if (selector === "body") return new FakeLocator({ text: this.bodyText });
    if (selector === SELECTORS.username) {
      return new FakeLocator({ fill: (value) => { this.username = value; } });
    }
    if (selector === SELECTORS.password) {
      return new FakeLocator({ fill: (value) => { this.password = value; } });
    }
    if (selector === SELECTORS.submit) {
      return new FakeLocator({
        click: () => {
          this.submissions += 1;
          this.currentUrl = this.afterSubmitUrl;
        },
      });
    }
    return new FakeLocator({ count: 0 });
  }

  async waitForURL(predicate) {
    if (!predicate(new URL(this.currentUrl))) {
      throw new Error("URL predicate not satisfied");
    }
  }
}


test("maps only canonical ScienceDirect PII URLs to the exact SCAU proxy", () => {
  assert.equal(isApprovedCredentialHost("vpn.scau.edu.cn"), true);
  assert.equal(isApprovedCredentialHost("VPN.SCAU.EDU.CN"), true);
  assert.equal(isApprovedCredentialHost("vpn.scau.edu.cn.evil.example"), false);
  assert.equal(isApprovedProxyHost("www-sciencedirect-com-s.vpn.scau.edu.cn"), true);
  assert.equal(isApprovedProxyHost("www-sciencedirect-com-s.vpn.scau.edu.cn.evil.example"), false);
  assert.equal(canonicalToProxyUrl(
    "https://www.sciencedirect.com/science/article/pii/S1049007824000411",
  ), PROXY_URL);
  assert.throws(
    () => canonicalToProxyUrl("https://www.sciencedirect.com.evil.example/science/article/pii/X"),
    (error) => error instanceof ScienceDirectFlowError && error.phase === "reference",
  );
});


test("stops on CAPTCHA and one-time-code challenges", () => {
  assert.throws(
    () => assertNoInteractiveChallenge("请输入验证码"),
    (error) => error instanceof ScienceDirectFlowError && error.phase === "captcha",
  );
  assert.throws(
    () => assertNoInteractiveChallenge("Enter the one-time verification code"),
    (error) => error instanceof ScienceDirectFlowError && error.phase === "otp",
  );
  assert.doesNotThrow(() => assertNoInteractiveChallenge("用户登录"));
});


test("reuses an authenticated proxy session without reading credentials", async () => {
  const page = new FakePage({ url: PROXY_URL });
  const result = await authenticateThroughScau({
    page,
    credentialReader: async () => { throw new Error("credentials must not be read"); },
  });
  assert.deepEqual(result, { submitted: false });
  assert.equal(page.submissions, 0);
});


test("releases SCAU credentials once on the exact auth host and completes login", async () => {
  const page = new FakePage();
  let reads = 0;
  const result = await authenticateThroughScau({
    page,
    credentialReader: async (hostname) => {
      reads += 1;
      assert.equal(hostname, "vpn.scau.edu.cn");
      return { username: "synthetic-scau", password: "synthetic-password" };
    },
  });
  assert.deepEqual(result, { submitted: true });
  assert.equal(reads, 1);
  assert.equal(page.submissions, 1);
  assert.equal(page.username, "synthetic-scau");
  assert.equal(page.password, "synthetic-password");
  assert.equal(page.url(), PROXY_URL);
});


test("rejects unknown hosts before credential release", async () => {
  const page = new FakePage({ url: "https://vpn.scau.edu.cn.evil.example/login" });
  let reads = 0;
  await assert.rejects(
    authenticateThroughScau({
      page,
      credentialReader: async () => { reads += 1; return {}; },
    }),
    (error) => error instanceof ScienceDirectFlowError && error.phase === "authentication-host",
  );
  assert.equal(reads, 0);
});


test("never submits credentials twice when authentication remains incomplete", async () => {
  const page = new FakePage({ afterSubmitUrl: AUTH_URL });
  let reads = 0;
  await assert.rejects(
    authenticateThroughScau({
      page,
      credentialReader: async () => {
        reads += 1;
        return { username: "synthetic-scau", password: "synthetic-password" };
      },
    }),
    (error) => error instanceof ScienceDirectFlowError
      && error.phase === "authentication-not-complete",
  );
  assert.equal(reads, 1);
  assert.equal(page.submissions, 1);
});
