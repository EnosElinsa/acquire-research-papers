"""Built-in venue identifiers, each checked against its live source in November 2026.

A corpus spec can name a venue ("INFOCOM", "IEEE TMC") without looking up identifiers. A venue
whose name, alias, or short name matches a preset, and which declares no identifier of its own,
receives the preset's identifiers; ``preset: <id>`` selects one explicitly and ``preset: none``
turns matching off. The applied preset ID is recorded in the run's request-spec.json.

``checked`` records the evidence: the identifier's title at the source and its 2024 count.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VenuePreset:
    id: str
    name: str
    short_name: str
    kind: str
    publisher: str
    aliases: tuple[str, ...] = ()
    issn: tuple[str, ...] = ()
    openalex_source: tuple[str, ...] = ()
    checked: str = ""

    def to_dict(self) -> dict[str, Any]:
        identifiers: dict[str, Any] = {}
        if self.issn:
            identifiers["issn"] = list(self.issn)
        if self.openalex_source:
            identifiers["openalex_source"] = list(self.openalex_source)
        return {"id": self.id, "name": self.name, "short_name": self.short_name,
                "kind": self.kind, "publisher": self.publisher, "aliases": list(self.aliases),
                **identifiers, "checked": self.checked}


def _journal(preset_id: str, name: str, short: str, issn: str, count: int,
             *aliases: str) -> VenuePreset:
    return VenuePreset(preset_id, name, short, "journal", "IEEE", aliases, issn=(issn,),
                       checked=f"Crossref ISSN {issn} = '{name}'; 2024: {count} records")


def _series(preset_id: str, name: str, short: str, source: str, count: int,
            *aliases: str, publisher: str = "IEEE") -> VenuePreset:
    return VenuePreset(preset_id, name, short, "conference", publisher, aliases,
                       openalex_source=(source,),
                       checked=f"OpenAlex {source}; publication year = edition; 2024: {count} works")


PRESETS: tuple[VenuePreset, ...] = (
    _journal("ieee-tmc", "IEEE Transactions on Mobile Computing", "TMC", "1536-1233", 941,
             "IEEE TMC"),
    _journal("ieee-twc", "IEEE Transactions on Wireless Communications", "TWC", "1536-1276", 1376,
             "IEEE TWC"),
    _journal("ieee-jsac", "IEEE Journal on Selected Areas in Communications", "JSAC", "0733-8716",
             309, "IEEE JSAC"),
    _journal("ieee-iotj", "IEEE Internet of Things Journal", "IoT-J", "2327-4662", 3185,
             "IEEE IoT-J", "IEEE IoTJ", "IoTJ"),
    _journal("ieee-tvt", "IEEE Transactions on Vehicular Technology", "TVT", "0018-9545", 1713,
             "IEEE TVT"),
    _journal("ieee-tcom", "IEEE Transactions on Communications", "TCOM", "0090-6778", 600,
             "IEEE TCOM"),
    _journal("ieee-ton", "IEEE/ACM Transactions on Networking", "ToN", "1063-6692", 391,
             "IEEE/ACM ToN", "IEEE ToN"),
    _journal("ieee-tnse", "IEEE Transactions on Network Science and Engineering", "TNSE",
             "2327-4697", 522, "IEEE TNSE"),
    _journal("ieee-comst", "IEEE Communications Surveys & Tutorials", "COMST", "1553-877X", 82,
             "IEEE COMST", "IEEE Communications Surveys and Tutorials"),
    _journal("ieee-wcm", "IEEE Wireless Communications", "IEEE Wireless Commun.", "1536-1284", 305,
             "IEEE Wireless Communications Magazine"),
    _journal("ieee-network", "IEEE Network", "IEEE Network", "0890-8044", 299),
    _journal("ieee-tpds", "IEEE Transactions on Parallel and Distributed Systems", "TPDS",
             "1045-9219", 180, "IEEE TPDS"),
    _journal("ieee-tcc", "IEEE Transactions on Cloud Computing", "TCC", "2168-7161", 107,
             "IEEE TCC"),
    _journal("ieee-tsc", "IEEE Transactions on Services Computing", "TSC", "1939-1374", 326,
             "IEEE TSC"),
    _journal("ieee-tits", "IEEE Transactions on Intelligent Transportation Systems", "T-ITS",
             "1524-9050", 1634, "IEEE T-ITS", "IEEE TITS"),
    _journal("ieee-tnsm", "IEEE Transactions on Network and Service Management", "TNSM",
             "1932-4537", 479, "IEEE TNSM"),
    _journal("ieee-wcl", "IEEE Wireless Communications Letters", "WCL", "2162-2337", 778,
             "IEEE WCL"),
    _journal("ieee-comml", "IEEE Communications Letters", "COMML", "1089-7798", 624,
             "IEEE CL", "IEEE COMML"),
    _journal("ieee-taes", "IEEE Transactions on Aerospace and Electronic Systems", "TAES",
             "0018-9251", 682, "IEEE TAES"),
    VenuePreset("aaai", "Proceedings of the AAAI Conference on Artificial Intelligence", "AAAI",
                "conference", "AAAI", ("AAAI Conference on Artificial Intelligence",),
                issn=("2374-3468",),
                checked="Crossref ISSN 2374-3468 = 'Proceedings of the AAAI Conference on "
                        "Artificial Intelligence'; 2024: 2867 records"),
    _series("ieee-infocom", "IEEE Conference on Computer Communications (INFOCOM)", "INFOCOM",
            "S7407087743", 262, "IEEE INFOCOM"),
    _series("ieee-icc", "IEEE International Conference on Communications (ICC)", "ICC",
            "S4306419201", 940, "IEEE ICC"),
    _series("ieee-globecom", "IEEE Global Communications Conference (GLOBECOM)", "GLOBECOM",
            "S4210205019", 911, "IEEE GLOBECOM", "Globecom"),
    _series("ieee-wcnc", "IEEE Wireless Communications and Networking Conference (WCNC)", "WCNC",
            "S4210195247", 842, "IEEE WCNC"),
    _series("ieee-vtc", "IEEE Vehicular Technology Conference (VTC)", "VTC", "S4210185404", 1251,
            "IEEE VTC"),
    _series("ieee-icdcs", "IEEE International Conference on Distributed Computing Systems (ICDCS)",
            "ICDCS", "S4363608224", 160, "IEEE ICDCS"),
    _series("ieee-icnp", "IEEE International Conference on Network Protocols (ICNP)", "ICNP",
            "S4210215197", 90, "IEEE ICNP"),
    _series("ieee-iwqos", "IEEE/ACM International Symposium on Quality of Service (IWQoS)",
            "IWQoS", "S4210234387", 131, "IEEE IWQoS"),
    _series("ieee-secon", "IEEE International Conference on Sensing, Communication, and "
            "Networking (SECON)", "SECON", "S7407086276", 45, "IEEE SECON"),
    _series("acm-sigcomm", "ACM SIGCOMM Conference", "SIGCOMM", "S7407086014", 62,
            "ACM SIGCOMM", publisher="ACM"),
)

_IDENTIFIER_FIELDS = ("issn", "isbn", "collection_doi", "openalex_source")


def _key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _index() -> dict[str, VenuePreset]:
    index: dict[str, VenuePreset] = {}
    for preset in PRESETS:
        for value in (preset.id, preset.name, preset.short_name, *preset.aliases):
            key = _key(value)
            if key in index and index[key] is not preset:
                raise RuntimeError(f"venue preset key is ambiguous: {value}")
            index[key] = preset
    return index


_BY_KEY = _index()
_BY_ID = {preset.id: preset for preset in PRESETS}


def find_preset(name: str) -> VenuePreset | None:
    return _BY_KEY.get(_key(name))


def _matching(venue: dict[str, Any]) -> VenuePreset | None:
    chosen = venue.get("preset")
    if chosen == "none":
        return None
    if chosen:
        preset = _BY_ID.get(str(chosen))
        if preset is None:
            raise ValueError(f"unknown venue preset: {chosen}; see arp sources for the list")
        return preset
    if any(venue.get(field) for field in _IDENTIFIER_FIELDS):
        return None  # the venue's own identifiers win
    names = (venue.get("name", ""), venue.get("short_name", ""), *venue.get("aliases", ()))
    matches = {preset.id: preset for value in names if value and (preset := find_preset(value))}
    if len(matches) != 1:
        return None
    (preset,) = matches.values()
    publisher = str(venue.get("publisher", "")).strip()
    if publisher and _key(publisher) != _key(preset.publisher):
        return None  # a declared, different publisher is a different venue
    return preset


def _identifiers(values: Any) -> list[str]:
    return sorted(str(value).strip().casefold() for value in values or ())


def apply_presets(spec: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``spec`` whose matching venues carry their preset's identifiers.

    Idempotent: an already expanded spec (e.g. a copied request-spec.json) loads unchanged.
    """
    expanded = copy.deepcopy(spec)
    for venue in expanded.get("scope", {}).get("venues", ()):
        preset = _matching(venue)
        if preset is None:
            continue
        if venue.get("preset") and any(venue.get(field) for field in _IDENTIFIER_FIELDS):
            if any(_identifiers(venue.get(field)) != _identifiers(getattr(preset, field, ()))
                   for field in _IDENTIFIER_FIELDS):
                raise ValueError(
                    f"venue {venue['name']}: preset {preset.id} conflicts with the venue's own "
                    "identifiers; keep either the preset or the identifiers")
        venue["preset"] = preset.id
        for field in ("issn", "openalex_source"):
            values = getattr(preset, field)
            if values:
                venue[field] = list(values)
        venue.setdefault("kind", preset.kind)
        venue.setdefault("publisher", preset.publisher)
        venue.setdefault("short_name", preset.short_name)
        known = {_key(value) for value in (venue["name"], *venue.get("aliases", ()))}
        venue["aliases"] = [*venue.get("aliases", ()), *(
            value for value in (preset.name, *preset.aliases) if _key(value) not in known)]
    return expanded
