from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from acquire_research_papers import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arp")
    parser.add_argument("--version", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(json.dumps({"name": "acquire-research-papers", "version": __version__}))
        return 0
    parser.print_help()
    return 0
