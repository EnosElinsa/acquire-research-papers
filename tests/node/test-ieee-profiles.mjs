import assert from "node:assert/strict";
import test from "node:test";
import {mkdtemp, readFile, rm, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import * as subject from "../../scripts/ieee-playwright.mjs";

const institutionProfile = Object.freeze({
  organization: 'Example University', carsiSchoolPlaceholder: 'Institution name',
  carsiSearchText: 'Example', carsiInstitution: 'Example University',
  carsiLoginButtonName: 'Continue', carsiEntityId: 'https://login.example.edu/idp/shibboleth',
  credentialHost: 'login.example.edu', usernameLabel: 'Account', passwordLabel: 'Passcode',
  loginButtonName: 'Sign in',
  resourceAccessUrl: 'https://ds.carsi.edu.cn/resource/gotoResource.php?id=example-ieee',
});

test('local credential payload releases only for the exact payload and institution hostname', async () => {
  const reader = subject.credentialReaderFromPayload({host: 'LOGIN.EXAMPLE.EDU',
    username: 'synthetic-user', password: 'synthetic-password'});
  assert.deepEqual(await reader('login.example.edu', {institutionProfile}),
    {username: 'synthetic-user', password: 'synthetic-password'});
  for (const hostname of ['login.example.edu.evil.test', 'other.example.edu',
    'login.example.edu.', 'https://login.example.edu/', 'login.example.edu:443', '']) {
    await assert.rejects(reader(hostname, {institutionProfile}), error => {
      assert.equal(error.phase, 'unexpected-auth-host');
      assert.equal(error.message.includes('synthetic-password'), false);
      return true;
    });
  }
  const otherProfile = {...institutionProfile, credentialHost: 'other.example.edu'};
  await assert.rejects(reader('login.example.edu', {institutionProfile: otherProfile}),
    {phase: 'unexpected-auth-host'});
  await assert.rejects(reader('other.example.edu', {institutionProfile: otherProfile}),
    {phase: 'unexpected-auth-host'});
});

test('invalid local credential payloads are rejected before any release', () => {
  for (const payload of [null, {},
    {host: 'https://login.example.edu', username: 'synthetic', password: 'synthetic-password'},
    {host: 'login.example.edu.', username: 'synthetic', password: 'synthetic-password'},
    {host: 'login.example.edu', username: '', password: 'synthetic-password'},
    {host: 'login.example.edu', username: 'synthetic', password: ''}]) {
    assert.throws(() => subject.credentialReaderFromPayload(payload), error => {
      assert.equal(error.phase, 'credential-read');
      assert.equal(error.message.includes('synthetic-password'), false);
      return true;
    });
  }
});

test('missing local credentials are required only when an exact-host login reads them', async () => {
  const reader = subject.credentialReaderFromPayload({host: 'login.example.edu',
    username: null, password: null});
  await assert.rejects(reader('login.example.edu.evil.test', {institutionProfile}),
    {phase: 'unexpected-auth-host'});
  await assert.rejects(reader('login.example.edu', {institutionProfile}), error => {
    assert.equal(error.phase, 'credential-read');
    assert.equal(error.message.includes('null'), false);
    return true;
  });
});

test('CARSI inspection proceeds with an explicit missing-credential payload', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'arp-inspect-no-credential-'));
  const form = {inputs: [], controls: []};
  const page = {goto: async () => {}, url: () => 'https://login.example.edu/login',
    evaluate: async () => form};
  try {
    const result = await subject.runAutomatedRetrieval({
      chromium: {launchPersistentContext: async () => ({pages: () => [page], close: async () => {}})},
      profileDir: path.join(root, 'profile'), workDir: path.join(root, 'run'),
      testMode: true, operation: 'inspect',
      credentialReader: subject.credentialReaderFromPayload({host: 'login.example.edu',
        username: null, password: null}),
      accessProfile: {schema_version: 2, id: 'campus', organization: 'Example',
        mode: 'carsi', entry_url: institutionProfile.resourceAccessUrl,
        credential_host: institutionProfile.credentialHost, contract: institutionProfile},
    });
    assert.deepEqual(result, {status: 'inspected', hostname: 'login.example.edu', form});
  } finally {await rm(root, {recursive: true, force: true});}
});

test('explicit dataRoot accepts dedicated paths independently of legacy localAppData', () => {
  const dataRoot = path.join(os.tmpdir(), 'arp-portable-boundaries');
  const options = {dataRoot, localAppData: undefined,
    workDir: path.join(dataRoot, 'paper-acquisition', 'runs', 'run-one'),
    profileDir: path.join(dataRoot, 'browser-profiles', 'acquire-research-papers', 'ieee-profiles', 'campus'),
    dependencyRoot: path.join(dataRoot, 'deps', 'acquire-research-papers')};
  assert.doesNotThrow(() => subject.assertAutomationPathBoundaries(options));
  assert.doesNotThrow(() => subject.assertAutomationPathBoundaries({...options,
    localAppData: path.join(os.tmpdir(), 'unrelated-local'),
    profileDir: path.join(dataRoot, 'browser-profiles', 'acquire-research-papers', 'ieee'),
    secretPath: path.join(dataRoot, 'secrets', 'acquire-research-papers', 'secrets.clixml')}));
  const invalid = [
    {workDir: path.join(dataRoot, 'paper-acquisition', 'runs')},
    {workDir: path.join(dataRoot, 'paper-acquisition', 'runs-other', 'run-one')},
    {workDir: path.join(dataRoot, 'paper-acquisition', 'runs', '..', 'outside')},
    {profileDir: path.join(dataRoot, 'browser-profiles', 'acquire-research-papers', 'ieee-profiles', 'campus', 'nested')},
    {profileDir: path.join(dataRoot, 'browser-profiles', 'acquire-research-papers', 'personal')},
    {dependencyRoot: path.join(dataRoot, 'deps', 'other')},
    {secretPath: path.join(dataRoot, 'secrets', 'other.clixml')},
    {dependencyRoot: path.join(dataRoot, 'Codex', 'deps', 'acquire-research-papers')},
  ];
  for (const changes of invalid) {
    assert.throws(() => subject.assertAutomationPathBoundaries({...options, ...changes}),
      {phase: 'path-boundary'});
  }
});

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
