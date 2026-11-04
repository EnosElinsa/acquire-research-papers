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
    # Crossref proceedings DOIs, one per listed edition; other years need their own DOI.
    collection_doi: tuple[str, ...] = ()
    checked: str = ""

    def to_dict(self) -> dict[str, Any]:
        identifiers: dict[str, Any] = {}
        for name in _PRESET_IDENTIFIERS:
            if getattr(self, name):
                identifiers[name] = list(getattr(self, name))
        return {"id": self.id, "name": self.name, "short_name": self.short_name,
                "kind": self.kind, "publisher": self.publisher, "aliases": list(self.aliases),
                **identifiers, "checked": self.checked}


_PRESET_IDENTIFIERS = ("issn", "openalex_source", "collection_doi")


def _journal(preset_id: str, name: str, short: str, issn: str, count: int,
             *aliases: str) -> VenuePreset:
    return VenuePreset(preset_id, name, short, "journal", "IEEE", aliases, issn=(issn,),
                       checked=f"Crossref ISSN {issn} = '{name}'; 2024: {count} records")


def _proceedings(preset_id: str, name: str, short: str, editions: dict[int, tuple[str, int]],
                 *aliases: str, publisher: str = "ACM") -> VenuePreset:
    listed = ", ".join(f"{year} {doi} ({count})" for year, (doi, count) in sorted(editions.items()))
    return VenuePreset(preset_id, name, short, "conference", publisher, aliases,
                       collection_doi=tuple(doi for _, (doi, _) in sorted(editions.items())),
                       checked=f"Crossref proceedings DOIs, records in the edition year: {listed}")


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
    # Renamed in 2025: the IEEE/ACM ISSN has no records from 2025, the new one none before.
    VenuePreset("ieee-ton", "IEEE/ACM Transactions on Networking", "ToN", "journal", "IEEE",
                ("IEEE/ACM ToN", "IEEE ToN", "IEEE Transactions on Networking"),
                issn=("1063-6692", "2998-4157"),
                checked="Crossref ISSN 1063-6692 = 'IEEE/ACM Transactions on Networking' "
                        "(2024: 391, 2025: 0); ISSN 2998-4157 = 'IEEE Transactions on "
                        "Networking' (2024: 0, 2025: 257)"),
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
    _journal("ieee-tccn", "IEEE Transactions on Cognitive Communications and Networking",
             "TCCN", "2332-7731", 188, "IEEE TCCN"),
    _journal("ieee-tgcn", "IEEE Transactions on Green Communications and Networking", "TGCN",
             "2473-2400", 162, "IEEE TGCN"),
    _journal("ieee-tmlcn", "IEEE Transactions on Machine Learning in Communications and "
             "Networking", "TMLCN", "2831-316X", 102, "IEEE TMLCN"),
    _journal("ieee-tii", "IEEE Transactions on Industrial Informatics", "TII", "1551-3203", 1410,
             "IEEE TII"),
    _journal("ieee-tsp", "IEEE Transactions on Signal Processing", "TSP", "1053-587X", 382,
             "IEEE TSP"),
    _journal("ieee-tc", "IEEE Transactions on Computers", "TC", "0018-9340", 220, "IEEE TC"),
    _journal("ieee-tdsc", "IEEE Transactions on Dependable and Secure Computing", "TDSC",
             "1545-5971", 412, "IEEE TDSC"),
    _journal("ieee-tifs", "IEEE Transactions on Information Forensics and Security", "TIFS",
             "1556-6013", 735, "IEEE TIFS"),
    _journal("ieee-tevc", "IEEE Transactions on Evolutionary Computation", "TEVC", "1089-778X",
             161, "IEEE TEVC", "IEEE TEC"),
    _journal("ieee-tcyb", "IEEE Transactions on Cybernetics", "TCYB", "2168-2267", 713,
             "IEEE TCYB"),
    _journal("ieee-tnnls", "IEEE Transactions on Neural Networks and Learning Systems", "TNNLS",
             "2162-237X", 1501, "IEEE TNNLS"),
    _journal("ieee-tsmc", "IEEE Transactions on Systems, Man, and Cybernetics: Systems", "TSMC",
             "2168-2216", 790, "IEEE TSMC", "IEEE TSMC-S"),
    _journal("ieee-tiv", "IEEE Transactions on Intelligent Vehicles", "T-IV", "2379-8858", 822,
             "IEEE T-IV", "IEEE TIV"),
    _journal("ieee-tsusc", "IEEE Transactions on Sustainable Computing", "T-SUSC", "2377-3782",
             75, "IEEE T-SUSC", "IEEE TSUSC"),
    _journal("ieee-tetc", "IEEE Transactions on Emerging Topics in Computing", "TETC",
             "2168-6750", 106, "IEEE TETC"),
    _journal("ieee-tbdata", "IEEE Transactions on Big Data", "IEEE Trans. Big Data", "2332-7790",
             89),
    _journal("ieee-tase", "IEEE Transactions on Automation Science and Engineering", "T-ASE",
             "1545-5955", 627, "IEEE T-ASE", "IEEE TASE"),
    _journal("ieee-tit", "IEEE Transactions on Information Theory", "TIT", "0018-9448", 547,
             "IEEE TIT", "IEEE T-IT"),
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
    _proceedings("acm-mobicom",
                 "ACM International Conference on Mobile Computing and Networking (MobiCom)",
                 "MobiCom", {2022: ("10.1145/3495243", 111), 2023: ("10.1145/3570361", 152),
                             2024: ("10.1145/3636534", 286), 2025: ("10.1145/3680207", 158)},
                 "ACM MobiCom"),
    _proceedings("acm-mobihoc",
                 "ACM International Symposium on Theory, Algorithmic Foundations, and Protocol "
                 "Design for Mobile Networks and Mobile Computing (MobiHoc)",
                 "MobiHoc", {2021: ("10.1145/3466772", 29), 2022: ("10.1145/3492866", 40),
                             2023: ("10.1145/3565287", 94), 2024: ("10.1145/3641512", 57),
                             2025: ("10.1145/3704413", 72), 2026: ("10.1145/3842721", 115)},
                 "ACM MobiHoc"),
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
        for field in _PRESET_IDENTIFIERS:
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
