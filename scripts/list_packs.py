from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_config


def resolve(config: dict, selection: str) -> list[str]:
    enabled = [pack for pack in config["packs"] if pack.get("enabled", True)]
    exact = [pack["id"] for pack in enabled if pack["id"] == selection]
    if exact:
        return exact
    if selection == "all":
        return [pack["id"] for pack in enabled]
    result = [
        pack["id"]
        for pack in enabled
        if selection in pack.get("groups", [])
    ]
    if not result:
        groups = sorted({group for pack in enabled for group in pack.get("groups", [])})
        raise ValueError(f"Unknown pack/group '{selection}'. Available groups: {', '.join(groups)}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve a dictionary build matrix")
    parser.add_argument("--group", default="core")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    packs = resolve(config, args.group)
    matrix = {"pack": packs}
    encoded = json.dumps(matrix, ensure_ascii=False, indent=2 if args.pretty else None, separators=None if args.pretty else (",", ":"))
    print(encoded)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"matrix={json.dumps(matrix, separators=(',', ':'))}\n")


if __name__ == "__main__":
    main()
