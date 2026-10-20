"""Non-secret, versioned IEEE institution profiles and historical diagnostics."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from acquire_research_papers.artifacts import atomic_write_bytes

_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)),
             *(f"lpt{i}" for i in range(10)), "active"}
_SECRET_NAMES = {"password", "username", "token", "cookie", "cookies", "authorization",
                 "samlresponse", "samlrequest", "relaystate", "execution", "ticket"}
_PROFILE_FIELDS = {"schema_version", "id", "organization", "mode", "entry_url",
                   "credential_host", "credential_ref", "contract", "last_validation"}


def profile_id(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value) or value in _RESERVED:
        raise ValueError("profile ID must be a non-reserved lowercase name (letters/digits/hyphens)")
    return value


def _check_nonsecret(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in _SECRET_NAMES:
                raise ValueError("profiles cannot contain credentials or session state")
            _check_nonsecret(item)
    elif isinstance(value, list):
        for item in value:
            _check_nonsecret(item)
    elif isinstance(value, str) and value.startswith(("http:", "https:")):
        parsed = urlsplit(value)
        if parsed.username or parsed.password or any(
            key.casefold() in _SECRET_NAMES for key, _ in parse_qsl(parsed.query)
        ):
            raise ValueError("profile URLs cannot contain credentials or session state")


def validate_profile(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - _PROFILE_FIELDS:
        raise ValueError("unsupported institution profile fields")
    result = deepcopy(value)
    _check_nonsecret(result)
    if result.get("schema_version") != 2:
        raise ValueError("institution profile schema_version must be 2")
    profile_id(result.get("id", ""))
    if not isinstance(result.get("organization"), str) or not result["organization"].strip():
        raise ValueError("institution organization is required")
    if result.get("mode") not in {"direct", "assisted", "carsi"}:
        raise ValueError("mode must be direct, assisted, or carsi")
    parsed = urlsplit(result.get("entry_url", ""))
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError("entry_url must be an HTTPS URL without credentials or fragments")
    host = result.get("credential_host", "")
    if not isinstance(host, str):
        raise ValueError("credential_host must be one exact DNS hostname")
    if host:
        if not re.fullmatch(r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+"
                            r"[a-zA-Z0-9-]+", host):
            raise ValueError("credential_host must be one exact DNS hostname")
        result["credential_host"] = host.lower()
    contract = result.get("contract", {})
    if not isinstance(contract, dict):
        raise ValueError("contract must be an object")
    for name in ("usernameLocator", "passwordLocator", "loginLocator", "nextLocator"):
        if name not in contract:
            continue
        locator = contract[name]
        if (not isinstance(locator, dict) or locator.get("kind") not in
                {"label", "placeholder", "role", "id", "name"}
                or not isinstance(locator.get("value"), str) or not locator["value"].strip()):
            raise ValueError(f"{name} requires an exact typed locator")
        if locator["kind"] == "role" and locator.get("role") not in {"button", "link", "textbox"}:
            raise ValueError("unsupported form control role")
        if locator["kind"] in {"id", "name"} and not re.fullmatch(r"[A-Za-z0-9_-]+", locator["value"]):
            raise ValueError("exact control identifiers may contain letters, digits, hyphens and underscores")
    if result["mode"] == "carsi" and not host:
        raise ValueError("automatic CARSI login requires credential_host")
    if result["mode"] == "carsi":
        required = ("carsiSchoolPlaceholder", "carsiSearchText", "carsiInstitution",
                    "carsiLoginButtonName", "carsiEntityId", "resourceAccessUrl")
        for field in required:
            if not isinstance(contract.get(field), str) or not contract[field].strip():
                raise ValueError(f"automatic CARSI contract requires {field}")
        for field, locator in (("usernameLabel", "usernameLocator"),
                               ("passwordLabel", "passwordLocator"), ("loginButtonName", "loginLocator")):
            if not contract.get(field) and not contract.get(locator):
                raise ValueError(f"automatic CARSI contract requires {field} or {locator}")
        for field in ("carsiEntityId", "resourceAccessUrl", "ieeeWayfUrl"):
            if not contract.get(field):
                continue
            route = urlsplit(contract[field])
            if (route.scheme != "https" or not route.hostname or route.port not in (None, 443)
                    or route.username or route.password or route.fragment):
                raise ValueError(f"{field} must be an official HTTPS route")
            expected = {"resourceAccessUrl": "ds.carsi.edu.cn", "ieeeWayfUrl": "ieeexplore.ieee.org"}.get(field)
            if expected and route.hostname != expected:
                raise ValueError(f"{field} requires the exact {expected} host")
    if "credential_ref" in result:
        if result["credential_ref"] not in {f"ieee_profiles:{result['id']}",
                                           "legacy:ieee_institution"}:
            raise ValueError("credential_ref does not belong to this profile")
    return result


class InstitutionStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def path(self, identifier: str) -> Path:
        path = self.root / f"{profile_id(identifier)}.json"
        if path.resolve().parent != self.root:
            raise ValueError("institution profile path escapes the store")
        return path

    def save(self, value: dict[str, Any], *, replace: bool = False) -> dict[str, Any]:
        profile = validate_profile(value)
        path = self.path(profile["id"])
        if path.exists() and not replace:
            raise ValueError("institution profile already exists; use an explicit replacement")
        self._write(path, profile)
        if not (self.root / "active.json").exists():
            self.use(profile["id"])
        return profile

    @staticmethod
    def _write(path: Path, value: dict[str, Any]) -> None:
        atomic_write_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n")
                           .encode("utf-8"))

    def get(self, identifier: str) -> dict[str, Any]:
        path = self.path(identifier)
        try:
            profile = validate_profile(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            raise ValueError(f"institution profile does not exist: {identifier}") from None
        if profile["id"] != identifier:
            raise ValueError("institution profile ID does not match its filename")
        return profile

    def active(self) -> dict[str, Any] | None:
        path = self.root / "active.json"
        if not path.exists():
            return None
        if path.resolve().parent != self.root:
            raise ValueError("active profile path escapes the store")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {"id"}:
            raise ValueError("active institution profile index is invalid")
        return self.get(value["id"])

    def use(self, identifier: str) -> dict[str, Any]:
        profile = self.get(identifier)
        self._write(self.root / "active.json", {"id": identifier})
        return profile

    def list(self) -> list[dict[str, Any]]:
        return [self.get(p.stem) for p in sorted(self.root.glob("*.json"))
                if p.name != "active.json"]

    def browser_directory(self, root: Path, identifier: str) -> Path:
        destination = root.resolve() / profile_id(identifier)
        if destination.resolve().parent != root.resolve():
            raise ValueError("browser profile escapes its root")
        return destination

    def migrate_legacy(self, legacy: dict[str, Any]) -> dict[str, Any]:
        identifier = "legacy-default"
        if self.path(identifier).exists():
            return self.get(identifier)
        host = legacy.get("credentialHost", "")
        return self.save({
            "schema_version": 2, "id": identifier,
            "organization": legacy["organization"], "mode": "carsi",
            "entry_url": legacy.get("resourceAccessUrl") or "https://ieeexplore.ieee.org/",
            "credential_host": host, "credential_ref": "legacy:ieee_institution",
            "contract": legacy,
        })

    def record_validation(self, identifier: str, result: dict[str, Any]) -> dict[str, Any]:
        profile = self.get(identifier)
        allowed = {"download_verified", "returned_to_ieee", "institution_login_completed", "configuration_valid",
                   "access", "phase", "requires_user_action"}
        summary = {key: value for key, value in result.items() if key in allowed}
        summary["checked_at"] = datetime.now(UTC).isoformat()
        summary["institutional_entitlement_verified"] = bool(
            summary.get("download_verified") and summary.get("access") == "institutional"
        )
        profile["last_validation"] = summary
        return self.save(profile, replace=True)

    def details(self) -> dict[str, Any]:
        profile = self.active()
        return {"configured": profile is not None,
                "active_profile": profile["id"] if profile else None,
                "mode": profile["mode"] if profile else None,
                "session": "unknown", "live_check": False,
                "last_validation": profile.get("last_validation") if profile else None}


def browser_payload(profile: dict[str, Any]) -> dict[str, Any]:
    profile = validate_profile(profile)
    result = dict(profile.get("contract", {}))
    result.update(organization=profile["organization"], accessMode=profile["mode"],
                  entryUrl=profile["entry_url"], profileId=profile["id"],
                  credentialHost=profile.get("credential_host", ""),
                  credentialProfile=("" if profile.get("credential_ref", "").startswith("legacy:")
                                     else profile["id"]))
    return result
