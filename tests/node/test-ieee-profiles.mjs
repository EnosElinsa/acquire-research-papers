import assert from "node:assert/strict";
import test from "node:test";
import {mkdtemp, readFile, rm, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import * as subject from "../../scripts/ieee-playwright.mjs";

test("assisted profiles need no password fields and never resolve credential contracts", () => {
  assert.equal(typeof subject.normalizeAccessProfile, "function");
  const value = subject.normalizeAccessProfile({schema_version: 2, id: "qr-campus",
    organization: "Example", mode: "assisted", entry_url: "https://library.example.edu/ieee"});
  assert.equal(value.accessMode, "assisted");
  assert.equal(value.credentialHost, "");
  assert.throws(() => subject.normalizeAccessProfile({...value, entryUrl: "http://example.edu"}));
});

test("typed locators preserve exact label, placeholder, role and ID contracts", async () => {
  assert.equal(typeof subject.configuredLocator, "function");
  const calls = [];
  const locator = {count: async () => 1};
  const page = {getByLabel: (...x) => {calls.push(["label", ...x]); return locator;},
    getByPlaceholder: (...x) => {calls.push(["placeholder", ...x]); return locator;},
    getByRole: (...x) => {calls.push(["role", ...x]); return locator;},
    locator: (...x) => {calls.push(["id", ...x]); return locator;}};
  await subject.configuredLocator(page, {kind: "label", value: "Account"});
  await subject.configuredLocator(page, {kind: "placeholder", value: "Password"});
  await subject.configuredLocator(page, {kind: "role", role: "link", value: "Continue"});
  await subject.configuredLocator(page, {kind: "id", value: "username"});
  assert.equal(calls[0][2].exact, true);
  assert.equal(calls[2][1], "link");
  await assert.rejects(subject.configuredLocator(page, {kind: "script", value: "danger"}));
});

test("manual continuation waits for an exact IEEE HTTPS return and reads no credentials", async () => {
  assert.equal(typeof subject.waitForAssistedReturn, "function");
  const progress = [];
  const page = {goto: async () => {}, url: () => "https://ieeexplore.ieee.org/Xplore/home.jsp",
    waitForURL: async predicate => {
      assert.equal(predicate(new URL("https://ieeexplore.ieee.org.evil.test/")), false);
      assert.equal(predicate(new URL("https://ieeexplore.ieee.org/")), true);
    }, waitForLoadState: async () => {}};
  const result = await subject.waitForAssistedReturn({page, timeoutMs: 10,
    institutionProfile: {entryUrl: "https://library.example.edu/ieee"},
    progress: value => progress.push(value)});
  assert.equal(result.returned_to_ieee, true);
  assert.equal(progress[0].status, "requires_user_action");
});

test("manual login retains the visible dedicated window until return, then releases its lock", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "arp-manual-"));
  let release, waiting;
  const ready = new Promise(resolve => {waiting = resolve;});
  let closed = false;
  const page = {goto: async () => {}, url: () => "https://ieeexplore.ieee.org/",
    waitForURL: async () => {waiting(); await new Promise(resolve => {release = resolve;});}};
  const options = {chromium: {launchPersistentContext: async (directory, options) => {
      assert.equal(options.headless, false);
      return {pages: () => [page], close: async () => {closed = true;}};
    }}, profileDir: path.join(root, "profiles"), workDir: path.join(root, "runs"),
    testMode: true, operation: "login", timeoutMs: 1000, progress: () => {},
    accessProfile: {schema_version: 2, id: "campus", organization: "Example",
      mode: "assisted", entry_url: "https://library.example.edu/ieee"}};
  try {
    const pending = subject.runAutomatedRetrieval(options);
    await ready;
    assert.equal(closed, false);
    assert.equal(Number(await readFile(path.join(options.profileDir, ".arp-context.lock"), "utf8")), process.pid);
    release();
    const result = await pending;
    assert.equal(closed, true);
    assert.equal(result.download_verified, false);
    await assert.rejects(readFile(path.join(options.profileDir, ".arp-context.lock")));
    // A browser context left by a dead helper can be reopened.
    await writeFile(path.join(options.profileDir, ".arp-context.lock"), "2147483647");
    page.waitForURL = async () => {};
    await subject.runAutomatedRetrieval(options);
  } finally {await rm(root, {recursive: true, force: true});}
});
