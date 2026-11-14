#!/usr/bin/env python3
"""Fill the __PLACEHOLDER__ tokens in iam/, eventbridge/ and statemachine/ from config.env.

Every *.json file in those folders is copied to build/ (including
iam/policy-step-functions-logging.json, which has no placeholders).

Usage:  python3 scripts/render.py config.env
Output: build/<same relative paths>   (git-ignored; paste these into the console)
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main(config_path):
    cfg = {}
    for line in pathlib.Path(config_path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    tokens = {
        "__ACCOUNT_ID__": cfg["ACCOUNT_ID"],
        "__REGION__": cfg["REGION"],
        "__BUCKET__": cfg["BUCKET"],
        "__APPSYNC_API_ID__": cfg.get("APPSYNC_API_ID", "__APPSYNC_API_ID__"),
        "__SUBNET_1__": cfg.get("SUBNET_1", "__SUBNET_1__"),
        "__SUBNET_2__": cfg.get("SUBNET_2", "__SUBNET_2__"),
        "__SECURITY_GROUP__": cfg.get("SECURITY_GROUP", "__SECURITY_GROUP__"),
        "__LAMBDA_PREFIX__": f"arn:aws:lambda:{cfg['REGION']}:{cfg['ACCOUNT_ID']}:function:",
    }
    out_root = ROOT / "build"
    for folder in ("iam", "eventbridge", "statemachine"):
        for path in (ROOT / folder).glob("*.json"):
            text = path.read_text()
            for token, value in tokens.items():
                text = text.replace(token, value)
            target = out_root / folder / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
            print("wrote", target.relative_to(ROOT))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
