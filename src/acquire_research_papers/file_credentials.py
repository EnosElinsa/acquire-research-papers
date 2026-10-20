"""Editable credentials; values never belong in logs, profiles, or status output.

Construct one CredentialManager per command. Its API values and backend selection
are immutable snapshots; institution files are read once when first selected.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from io import StringIO
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib
from types import MappingProxyType
from typing import Any

from dotenv import dotenv_values
from dotenv.parser import parse_stream

from acquire_research_papers.credentials import API_PROVIDER_HOSTS, ApiKeyLoadError
from acquire_research_papers.institution_profiles import profile_id
from acquire_research_papers.paths import AppPaths

API_KEYS = MappingProxyType({
    'semantic_scholar': 'SEMANTIC_SCHOLAR_API_KEY', 'openalex': 'OPENALEX_API_KEY',
    'elsevier': 'ELSEVIER_API_KEY', 'mineru': 'MINERU_TOKEN',
})
TOKEN_HOSTS = MappingProxyType({**API_PROVIDER_HOSTS, 'mineru': 'mineru.net'})


def _private_file(path: Path) -> None:
    """Create an empty exclusive file, then restrict access before writing values."""
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    if os.name == 'nt':
        try:
            identity = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'],
                capture_output=True, text=True, check=True,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            match = re.search(r'S-1-\d+(?:-\d+)+', identity.stdout)
            if not match:
                raise ValueError('Current user identity is unavailable')
            subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
                            f'*{match.group()}:(F)'], capture_output=True, check=True,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.SubprocessError, ValueError):
            path.unlink(missing_ok=True)
            raise ValueError('Could not restrict configuration file permissions') from None


def _atomic_private_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # mktemp is avoided: reserve the name exclusively, apply ACLs, then write.
    descriptor, name = tempfile.mkstemp(prefix='.arp-', dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    temporary.unlink()
    try:
        _private_file(temporary)
        temporary.write_text(text, encoding='utf-8', newline='')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _bindings(path: Path, text: str):
    bindings = list(parse_stream(StringIO(text)))
    for binding in bindings:
        if binding.error or (binding.key is not None and
                (not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', binding.key)
                 or binding.value is None)):
            raise ValueError(f'Malformed dotenv file {path}, line {binding.original.line}')
    return bindings


def _comment(text: str) -> str:
    quote = None
    escaped = False
    for index, character in enumerate(text):
        if escaped:
            escaped = False
        elif character == '\\' and quote:
            escaped = True
        elif character in {'"', "'"}:
            if quote == character:
                quote = None
            elif quote is None:
                quote = character
        elif character == '#' and quote is None and index and text[index - 1].isspace():
            return text[index:].rstrip('\r\n')
    return ''


def _quoted(value: str) -> str:
    if not isinstance(value, str) or '\x00' in value:
        raise ValueError('Credential values must be strings without NUL characters')
    return "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'"


class FileCredentialStore:
    def __init__(self, path: Path):
        self.path = Path(path).expanduser().resolve()

    def _text(self) -> str:
        try:
            return self.path.read_text(encoding='utf-8-sig')
        except FileNotFoundError:
            return ''
        except UnicodeError:
            raise ValueError(f'Invalid UTF-8 dotenv file {self.path}') from None

    def snapshot(self) -> Mapping[str, str | None]:
        text = self._text()
        _bindings(self.path, text)
        return MappingProxyType(dict(dotenv_values(stream=StringIO(text), interpolate=False)))

    def update(self, values: Mapping[str, str]) -> None:
        for key, value in values.items():
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
                raise ValueError('Invalid dotenv field name')
            _quoted(value)
        text = self._text()
        bindings = _bindings(self.path, text)
        remaining = dict(values)
        output = []
        for binding in bindings:
            if binding.key in values:
                original = binding.original.string
                leading = original[:len(original) - len(original.lstrip('\r\n'))]
                comment = _comment(original)
                output.append(f'{leading}{binding.key}={_quoted(values[binding.key])}'
                              + (f' {comment}' if comment else '') + '\n')
                remaining.pop(binding.key, None)
            else:
                output.append(binding.original.string)
        result = ''.join(output)
        if remaining and result and not result.endswith('\n'):
            result += '\n'
        result += ''.join(f'{key}={_quoted(value)}\n' for key, value in remaining.items())
        _atomic_private_write(self.path, result)

    def initialize(self, keys: tuple[str, ...]) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _private_file(self.path)
        except FileExistsError:
            return
        self.path.write_text('# Editable local credentials. Do not commit this file.\n'
                             + ''.join(f'{key}=\n' for key in keys), encoding='utf-8')


class SnapshotTokenProvider:
    def __init__(self, read: Callable[[], str | None]):
        self._read = read

    def optional(self) -> str | None:
        value = self._read()
        return value if value and value.strip() else None

    def __call__(self) -> str:
        value = self.optional()
        if value is None:
            raise ApiKeyLoadError('Credential is not configured; use arp config setup')
        return value


class CredentialManager:
    def __init__(self, paths: AppPaths, *, env_file: Path | None = None,
                 environ: Mapping[str, str] | None = None,
                 legacy_reader: Callable[[str, str], str | None] | None = None,
                 legacy_status: Callable[[], Mapping[str, bool]] | None = None,
                 legacy_institution: Callable[[dict, str], dict | None] | None = None):
        self.paths = paths
        self.config = paths.config_paths
        self.environ = dict(os.environ if environ is None else environ)
        self.env_file = Path(env_file or self.environ.get('ARP_ENV_FILE') or
                             self.config.env_file).expanduser().resolve()
        self.legacy_reader = legacy_reader
        self.legacy_status = legacy_status
        self.legacy_institution = legacy_institution
        self._institutions: dict[str, Mapping] = {}
        self._legacy_tokens: dict[str, str | None] = {}
        self.backend = self._backend()
        file_values = FileCredentialStore(self.env_file).snapshot() if self.backend == 'file' else {}
        self._api = {provider: self.environ.get(key, file_values.get(key))
                     for provider, key in API_KEYS.items()}

    def _backend(self) -> str:
        try:
            settings = tomllib.loads(self.config.settings.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return 'dpapi' if (self.paths.secrets / 'secrets.clixml').is_file() else 'file'
        except (tomllib.TOMLDecodeError, UnicodeError):
            raise ValueError(f'Invalid configuration file {self.config.settings}') from None
        credentials = settings.get('credentials', {})
        backend = credentials.get('backend') if isinstance(credentials, dict) else None
        if not isinstance(backend, str) or backend not in {'file', 'dpapi'}:
            raise ValueError(f'Invalid credentials.backend in {self.config.settings}; use file or dpapi')
        return backend

    def initialize(self) -> dict[str, Any]:
        self.config.root.mkdir(parents=True, exist_ok=True)
        if not self.config.settings.exists():
            _atomic_private_write(self.config.settings, f'[credentials]\nbackend = "{self.backend}"\n')
        FileCredentialStore(self.env_file).initialize(tuple(API_KEYS.values()))
        return {'status': 'initialized', 'backend': self.backend,
                'config_root': str(self.config.root), 'env_file': str(self.env_file)}

    def api_provider(self, provider: str, expected_host: str) -> SnapshotTokenProvider:
        if provider not in TOKEN_HOSTS:
            raise ValueError('Unsupported API provider')
        if expected_host.casefold() != TOKEN_HOSTS[provider]:
            raise ValueError('API credential host does not match the provider')
        def read():
            if API_KEYS[provider] in self.environ:
                return self._api[provider] or None
            if self.backend == 'file':
                return self._api[provider] or None
            if provider not in self._legacy_tokens:
                self._legacy_tokens[provider] = (self.legacy_reader(provider, TOKEN_HOSTS[provider])
                                                if self.legacy_reader else None)
            return self._legacy_tokens[provider]
        return SnapshotTokenProvider(read)

    @staticmethod
    def _institution_identity(profile: dict, expected_host: str, *,
                              allow_legacy: bool = False) -> str:
        identifier = profile_id(profile.get('id', ''))
        references = {f'ieee_profiles:{identifier}'}
        if allow_legacy:
            references.add('legacy:ieee_institution')
        if profile.get('credential_ref') not in references:
            raise ValueError('Institution credential reference does not match the profile')
        if ((not allow_legacy or 'credential_file' in profile) and
                profile.get('credential_file') != f'credentials/{identifier}.env'):
            raise ValueError('Institution credential file does not belong to the profile')
        host = profile.get('credential_host', '')
        if (not re.fullmatch(r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+'
                             r'[a-zA-Z0-9-]+', host)
                or expected_host.casefold() != host.casefold()):
            raise ValueError('Institution credential host does not match the exact profile host')
        return identifier

    def _institution_store(self, identifier: str) -> FileCredentialStore:
        root = self.config.credentials.resolve()
        path = root / f'{identifier}.env'
        if path.resolve() != path:
            raise ValueError('Institution credential file does not belong to the profile')
        return FileCredentialStore(path)

    def institution(self, profile: dict, expected_host: str) -> dict[str, str] | None:
        identifier = self._institution_identity(profile, expected_host,
                                                allow_legacy=self.backend == 'dpapi')
        if self.backend == 'dpapi':
            return self.legacy_institution(profile, expected_host) if self.legacy_institution else None
        if identifier not in self._institutions:
            self._institutions[identifier] = self._institution_store(identifier).snapshot()
        values = self._institutions[identifier]
        username, password = values.get('INSTITUTION_USERNAME'), values.get('INSTITUTION_PASSWORD')
        return {'username': username, 'password': password} if username and password else None

    def save_api(self, provider: str, value: str) -> None:
        if self.backend != 'file':
            raise ValueError('Legacy backend requires explicit config migrate --from dpapi first')
        if provider not in API_KEYS:
            raise ValueError('Unsupported API provider')
        FileCredentialStore(self.env_file).update({API_KEYS[provider]: value})

    def save_institution(self, profile: dict, *, username: str, password: str) -> None:
        identifier = self._institution_identity(profile, profile.get('credential_host', ''))
        if self.backend != 'file':
            raise ValueError('Legacy backend requires explicit config migrate --from dpapi first')
        self._institution_store(identifier).update({
            'INSTITUTION_USERNAME': username, 'INSTITUTION_PASSWORD': password})

    def status(self, profile: dict | None = None) -> dict[str, bool]:
        if self.backend == 'dpapi':
            values = self.legacy_status() if self.legacy_status else {}
            result = {name: bool(values.get(name, False)) for name in ('ieee', *API_KEYS)}
            for provider, key in API_KEYS.items():
                if key in self.environ:
                    result[provider] = bool(self.environ[key].strip())
            return result
        result = {provider: bool((self._api[provider] or '').strip()) for provider in API_KEYS}
        result['ieee'] = bool(profile and profile.get('credential_ref') and
                              self.institution(profile, profile.get('credential_host', '')))
        return result

    def migrate_from_dpapi(self, exporter: Callable[[], Mapping], *,
                           before_switch: Callable[[], None] | None = None) -> dict[str, Any]:
        try:
            payload = exporter()
        except Exception:
            raise ValueError('DPAPI credential export failed; legacy store was preserved') from None
        if not isinstance(payload, Mapping) or set(payload) - {'api', 'institutions'}:
            raise ValueError('Invalid DPAPI migration payload')
        writes: list[tuple[FileCredentialStore, dict]] = []
        api = payload.get('api', {})
        if not isinstance(api, Mapping) or set(api) - set(API_KEYS):
            raise ValueError('Invalid DPAPI API provider fields')
        writes.append((FileCredentialStore(self.env_file),
                       {API_KEYS[key]: value for key, value in api.items() if value}))
        for entry in payload.get('institutions', []):
            identifier = self._institution_identity(entry['profile'], entry['expected_host'])
            writes.append((self._institution_store(identifier), {
                'INSTITUTION_USERNAME': entry['username'], 'INSTITUTION_PASSWORD': entry['password']}))
        conflicts = []
        for store, values in writes:
            existing = store.snapshot()
            for key, value in values.items():
                _quoted(value)
                if existing.get(key) and existing[key] != value:
                    conflicts.append(key)
        if conflicts:
            return {'status': 'conflict', 'conflicts': sorted(set(conflicts))}
        self._file_backend_text()
        # Backend switch is last. Any failed writes leave legacy credentials authoritative.
        for store, values in writes:
            if values:
                store.update(values)
        if before_switch is not None:
            before_switch()
        self._set_file_backend()
        self.backend = 'file'
        file_values = FileCredentialStore(self.env_file).snapshot()
        self._api = {provider: self.environ.get(key, file_values.get(key))
                     for provider, key in API_KEYS.items()}
        self._institutions.clear()
        return {'status': 'migrated', 'keys': sorted({key for _, values in writes for key in values})}

    def _file_backend_text(self) -> str:
        try:
            text = self.config.settings.read_text(encoding='utf-8')
        except FileNotFoundError:
            return '[credentials]\nbackend = "file"\n'
        try:
            original = tomllib.loads(text)
            if original['credentials']['backend'] not in {'dpapi', 'file'}:
                raise ValueError
        except (tomllib.TOMLDecodeError, UnicodeError, KeyError, TypeError, ValueError):
            raise ValueError(f'Invalid configuration file {self.config.settings}') from None
        expected = deepcopy(original)
        expected['credentials']['backend'] = 'file'
        if original == expected:
            return text
        # Locate string tokens, then let TOML parsing prove that a replacement
        # changes only credentials.backend. This preserves comments and all
        # other bytes for tables, inline tables, dotted keys and quoted keys.
        index = 0
        while index < len(text):
            if text[index] == '#':
                end = text.find('\n', index)
                index = len(text) if end == -1 else end + 1
                continue
            if text[index] not in {"'", '"'}:
                index += 1
                continue
            start = index
            quote = text[index]
            delimiter = quote * (3 if text.startswith(quote * 3, index) else 1)
            index += len(delimiter)
            while index < len(text):
                if quote == '"' and text[index] == '\\':
                    index += 2
                elif text.startswith(delimiter, index):
                    index += len(delimiter)
                    # TOML multiline strings may end with four or five quotes.
                    if len(delimiter) == 3:
                        while index < len(text) and text[index] == quote:
                            index += 1
                    break
                else:
                    index += 1
            candidate = text[:start] + '"file"' + text[index:]
            try:
                if tomllib.loads(candidate) == expected:
                    return candidate
            except tomllib.TOMLDecodeError:
                pass
        raise ValueError(f'Could not safely update configuration file {self.config.settings}')

    def _set_file_backend(self) -> None:
        _atomic_private_write(self.config.settings, self._file_backend_text())
