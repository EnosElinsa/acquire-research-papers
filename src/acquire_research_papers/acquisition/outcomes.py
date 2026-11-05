"""One mapping from acquisition failures to item error codes, shared by every caller."""
from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from acquire_research_papers.acquisition.adapters.ieee import IeeeBridgeError
from acquire_research_papers.acquisition.base import (
    AccessRequired,
    NotOfficial,
    PageContractChanged,
)
from acquire_research_papers.artifacts import InvalidPdfError
from acquire_research_papers.bibliography import BibMissing, MetadataMismatch
from acquire_research_papers.http import HttpStatusError, NetworkTransient, RateLimited
from acquire_research_papers.resolver import AmbiguousInput, UnsupportedPublisher


IEEE_ACCESS_PHASES = frozenset(
    {
        "authentication-not-complete",
        "authentication-result",
        "credential-read",
        "unexpected-auth-host",
        "carsi-school",
        "carsi-institution",
        "carsi-login",
        "institution-username",
        "institution-password",
        "institution-login",
        "attribute-release-controls",
        "attribute-release-required",
        "institutional-return",
        "download-after-auth",
        "access-required",
        "manual-login-timeout",
        "assisted-login-timeout",
    }
)
# Failures of the institution login itself, not of one paper's entitlement. Repeating them for
# every remaining paper would resubmit credentials and re-wait for the user, so a batch pauses
# the publisher host after the first one.
IEEE_LOGIN_PHASES = (IEEE_ACCESS_PHASES - {"download-after-auth", "access-required"}) | {
    "form-contract"
}
# Unexpected browser failures (crash, closed context, busy profile) are worth one more run.
IEEE_AUTOMATION_PHASES = frozenset({"automation", "profile-in-use"})
IEEE_CONFIGURATION_PHASES = frozenset({"dependency-install"})
# Outside Windows the browser adapter is unavailable, so the paper joins the manual queue.
IEEE_UNSUPPORTED_PHASES = frozenset({"unsupported-platform"})

# error_code -> CLI exit status (sysexits: 69 unavailable, 75 temporary, 78 configuration).
EXIT_CODES = {
    "access_required": 69,
    "unsupported_adapter": 69,
    "rate_limited": 75,
    "network_transient": 75,
    "automation_error": 75,
    "configuration_required": 78,
    "contract_error": 78,
}
# Internal outcome hint read by batch acquisition; never written to ledgers or CLI output.
PAUSE_HOST = "pause_host"


def public_outcome(outcome: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in outcome.items() if key != PAUSE_HOST}


def is_ieee_access_phase(phase: str) -> bool:
    return phase in IEEE_ACCESS_PHASES


def _host(url: str) -> str:
    try:
        return urlsplit(url).hostname or "unknown host"
    except ValueError:
        return "unknown host"


def failure_outcome(error: BaseException) -> dict[str, str]:
    """Classify one acquisition failure without exposing URLs, queries, or credentials."""
    if isinstance(error, UnsupportedPublisher):
        return {"error_code": "unsupported_adapter", "message": str(error)}
    if isinstance(error, AccessRequired):
        return {"error_code": "access_required", "message": str(error)}
    if isinstance(error, IeeeBridgeError):
        if error.phase in IEEE_ACCESS_PHASES:
            code = "access_required"
        elif error.phase in IEEE_AUTOMATION_PHASES:
            code = "automation_error"
        elif error.phase in IEEE_CONFIGURATION_PHASES:
            code = "configuration_required"
        elif error.phase in IEEE_UNSUPPORTED_PHASES:
            code = "unsupported_adapter"
        else:
            code = "contract_error"
        outcome = {"error_code": code, "message": f"{error} (IEEE phase: {error.phase})"}
        if error.phase in IEEE_LOGIN_PHASES:
            outcome[PAUSE_HOST] = True
        return outcome
    if isinstance(error, RateLimited):
        return {"error_code": "rate_limited", "message": f"HTTP 429 from {_host(error.url)}"}
    if isinstance(error, NetworkTransient):
        return {"error_code": "network_transient", "message": str(error)}
    if isinstance(error, httpx.TransportError):
        return {
            "error_code": "network_transient",
            "message": f"network error ({type(error).__name__})",
        }
    if isinstance(error, HttpStatusError):
        status = error.status_code
        if status >= 500:
            code = "network_transient"
        elif status in {401, 403}:
            code = "access_required"
        else:
            code = "contract_error"
        message = f"HTTP {status} from {_host(error.url)}"
        if code == "network_transient":
            # E.g. AAAI's citation export answered 520 for every client in Nov 2026 while its
            # pages and PDFs worked: a server fault on the publisher's side, not a refusal.
            message += "; the publisher's server failed, so rerun later"
        if code == "access_required":
            message += (" (a bot check that only a normal browser passes)"
                        if getattr(error, "bot_challenge", False) else "")
            message += "; download it in a browser and import it with manual-fetch"
        return {"error_code": code, "message": message}
    if isinstance(
        error,
        (AmbiguousInput, PageContractChanged, NotOfficial, MetadataMismatch, BibMissing,
         InvalidPdfError),
    ):
        return {"error_code": "contract_error", "message": str(error)}
    return {
        "error_code": "contract_error",
        "message": f"unexpected {type(error).__name__} during acquisition",
    }
