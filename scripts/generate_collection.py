#!/usr/bin/env python3
"""Generate a Postman collection from Fleet's REST API documentation.

Fleet does not publish an OpenAPI spec; the source of truth is
``docs/REST API/rest-api.md`` in the fleetdm/fleet repo, versioned by
release tag (e.g. ``fleet-v4.88.0``).

This script parses that markdown and emits a Postman v2.1 collection:

- ``## Section``  -> folder
- ``### Endpoint`` -> request (first `METHOD /path` code line is the definition)
- ``#### Parameters`` table -> path variables, query params (disabled by
  default), body skeleton, or multipart form-data, based on the "In" column
- ``#### Example`` -> documented request body and first default response are
  attached as the request body / a saved example response

Conventions preserved from the original hand-built collection:

- ``{{baseUrl}}`` prefix on every URL
- ``Authorization: Bearer {{token}}`` header on authenticated endpoints
- ``POST /login`` carries a test script that stores ``response.token`` in the
  ``token`` environment variable
- query params are included but disabled, with ``{{name}}`` placeholder values

Usage:
    # from an already-checked-out fleet repo / local file
    python3 scripts/generate_collection.py --input path/to/rest-api.md --version 4.88.0

    # fetch the docs for a release tag automatically (shallow sparse clone)
    python3 scripts/generate_collection.py --tag fleet-v4.88.0

    # output path (default: fleet.postman_collection.json)
    python3 scripts/generate_collection.py --tag fleet-v4.88.0 -o fleet.postman_collection.json
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

FLEET_REPO = "https://github.com/fleetdm/fleet.git"
DOC_PATH = "docs/REST API/rest-api.md"
SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"

METHOD_RE = re.compile(r"^`(GET|POST|PUT|PATCH|DELETE|HEAD)\s+(/\S+?)`\s*$")
HEADING_RE = re.compile(r"^(#{2,5})\s+(.*?)\s*$")
STATUS_RE = re.compile(r"^`Status:\s*(\d+)")
TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")

# Endpoints that must not send the Authorization header.
NO_AUTH_PHRASES = (
    "authentication is not required",
    "no authentication required",
    "does not require authentication",
)

# Corrections for known bugs in the upstream docs. Keyed by (method, path as
# written in the docs) -> corrected path. Review on each release; remove
# entries once fixed upstream.
PATH_FIXUPS = {
    # Missing /api/v1/fleet prefix + literal example ID in the definition line.
    ("POST", "/scripts/batch/abc-def/cancel"):
        "/api/v1/fleet/scripts/batch/:batch_execution_id/cancel",
}

# Public endpoints (no API token needed) — the docs don't flag these with a
# consistent phrase, so they're listed explicitly.
NO_AUTH_PATHS = {
    "/api/v1/fleet/login",
    "/api/v1/fleet/forgot_password",
    "/api/v1/fleet/reset_password",
    "/api/v1/fleet/sso",
    "/api/v1/fleet/sso/callback",
}

PLACEHOLDERS = {
    "integer": "0",
    "number": "0",
    "boolean": "false",
    "string": "\"\"",
    "array": "[]",
    "list": "[]",
    "object": "{}",
    "json": "{}",
}


def fetch_docs(tag: str, workdir: Path) -> Path:
    """Shallow sparse-clone the fleet repo at *tag*, return path to rest-api.md."""
    dest = workdir / "fleet"
    subprocess.run(
        [
            "git", "clone", "--quiet", "--depth", "1", "--branch", tag,
            "--filter=blob:none", "--sparse", FLEET_REPO, str(dest),
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(dest), "sparse-checkout", "set", "docs/REST API"],
        check=True,
    )
    return dest / DOC_PATH


def split_sections(lines, level):
    """Yield (title, body_lines) for each heading of *level* ('##' etc.)."""
    marker = "#" * level + " "
    title, body = None, []
    for line in lines:
        if line.startswith(marker):
            if title is not None:
                yield title, body
            title, body = line[len(marker):].strip(), []
        elif title is not None:
            body.append(line)
    if title is not None:
        yield title, body


def parse_param_table(lines, start):
    """Parse a markdown table starting at *start*; return (params, next_index)."""
    params = []
    i = start
    header_seen = False
    while i < len(lines):
        m = TABLE_ROW_RE.match(lines[i])
        if not m:
            if header_seen:
                break
            if lines[i].strip():
                break
            i += 1
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        i += 1
        if not header_seen:
            header_seen = True  # header row
            continue
        if cells and set(cells[0]) <= {"-", " ", ":"}:
            continue  # separator row
        if len(cells) < 3:
            continue
        name = re.sub(r"[`*]", "", cells[0]).strip()
        ptype = cells[1].lower()
        where = cells[2].lower()
        desc = clean_md(cells[3]) if len(cells) > 3 else ""
        if not name or where not in ("query", "body", "path", "form", "url"):
            continue
        params.append({"name": name, "type": ptype, "in": where, "description": desc})
    return params, i


def clean_md(text: str) -> str:
    """Light markdown cleanup for Postman descriptions."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links -> text
    return text.replace("<br>", " ").replace("<br/>", " ").strip()


def extract_code_block(lines, start):
    """Return (block_text, next_index) for a fenced block at/after *start*."""
    i = start
    while i < len(lines) and not lines[i].strip().startswith("```"):
        if lines[i].strip() and not lines[i].startswith(("#", "`Status", ">")):
            return None, start
        i += 1
    if i >= len(lines):
        return None, start
    i += 1
    block = []
    while i < len(lines) and not lines[i].strip().startswith("```"):
        block.append(lines[i])
        i += 1
    return "\n".join(block), i + 1


def parse_endpoint(title, lines):
    """Parse one ### subsection. Returns a dict or None if not an endpoint."""
    method = path = None
    description_lines = []
    params = []
    example_url = None
    request_body = None
    response = None
    no_auth = False

    text_lower = "\n".join(lines).lower()
    if any(p in text_lower for p in NO_AUTH_PHRASES):
        no_auth = True

    i = 0
    in_example = False
    current_h5 = None
    while i < len(lines):
        line = lines[i]
        h = HEADING_RE.match(line)
        if h:
            hlevel, htitle = len(h.group(1)), h.group(2).lower()
            if hlevel == 4:
                in_example = htitle.startswith("example")
                current_h5 = None
                if htitle.startswith("parameters"):
                    params, i = parse_param_table(lines, i + 1)
                    continue
            elif hlevel == 5:
                current_h5 = htitle
                if in_example and htitle.startswith("request body") and request_body is None:
                    block, i = extract_code_block(lines, i + 1)
                    if block is not None:
                        request_body = block
                        continue
            i += 1
            continue

        m = METHOD_RE.match(line.strip())
        if m:
            if not in_example and method is None:
                method, path = m.group(1), m.group(2).split("?")[0]
            elif in_example and example_url is None:
                example_url = m.group(2)
            i += 1
            continue

        s = STATUS_RE.match(line.strip())
        if s and in_example and response is None and (current_h5 or "").startswith("default response"):
            code = int(s.group(1))
            block, i = extract_code_block(lines, i + 1)
            response = {"code": code, "body": block or ""}
            continue

        if not in_example and method is None or (method is not None and not in_example and not line.startswith("#")):
            if not METHOD_RE.match(line.strip()):
                description_lines.append(line)
        i += 1

    if method is None:
        return None

    path = PATH_FIXUPS.get((method, path), path)

    if path in NO_AUTH_PATHS:
        no_auth = True

    # Normalize body vs form-data. The docs' "In" column is unreliable here
    # (some JSON params are marked "form", and file uploads are marked "body").
    # The reliable signal is the param type: a `file` param means multipart.
    has_file = any("file" in p["type"] for p in params)
    for p in params:
        if p["in"] in ("body", "form"):
            p["in"] = "form" if has_file else "body"

    return {
        "name": title,
        "method": method,
        "path": path,
        "description": "\n".join(description_lines).strip(),
        "params": params,
        "request_body": request_body,
        "response": response,
        "no_auth": no_auth,
    }


def synthesize_body(params):
    """Build a JSON body skeleton from body params when no example exists."""
    body_params = [p for p in params if p["in"] == "body"]
    if not body_params:
        return None
    entries = []
    for p in body_params:
        placeholder = PLACEHOLDERS.get(p["type"].split()[0] if p["type"] else "", "\"\"")
        entries.append(f'  "{p["name"]}": {placeholder}')
    return "{\n" + ",\n".join(entries) + "\n}"


def build_request(ep):
    """Convert a parsed endpoint into a Postman item."""
    path_segments = [seg for seg in ep["path"].split("/") if seg]

    url = {
        "raw": "{{baseUrl}}" + ep["path"],
        "host": ["{{baseUrl}}"],
        "path": path_segments,
    }

    # Path variables (:id style)
    variables = []
    for p in ep["params"]:
        if p["in"] in ("path", "url"):
            variables.append({"key": p["name"], "value": "", "description": p["description"]})
    # Path params present in URL but missing from the table
    for seg in path_segments:
        if seg.startswith(":") and seg[1:] not in [v["key"] for v in variables]:
            variables.append({"key": seg[1:], "value": "", "description": ""})
    if variables:
        url["variable"] = variables

    query = [
        {
            "key": p["name"],
            "value": "{{%s}}" % p["name"],
            "description": p["description"],
            "disabled": True,
        }
        for p in ep["params"]
        if p["in"] == "query"
    ]
    if query:
        url["query"] = query

    headers = []

    body = None
    form_params = [p for p in ep["params"] if p["in"] == "form"]
    if form_params:
        body = {
            "mode": "formdata",
            "formdata": [
                {
                    "key": p["name"],
                    "value": "",
                    "type": "file" if "file" in p["type"] else "text",
                    "description": p["description"],
                }
                for p in form_params
            ],
        }
    else:
        raw = ep["request_body"] or synthesize_body(ep["params"])
        if raw and ep["method"] in ("POST", "PUT", "PATCH", "DELETE", "GET"):
            body = {"mode": "raw", "raw": raw, "options": {"raw": {"language": "json"}}}
            headers.append({"key": "Content-Type", "value": "application/json", "type": "text"})

    request = {
        "method": ep["method"],
        "header": headers,
        "url": url,
    }
    # Auth is inherited from the collection (Bearer {{token}}); public
    # endpoints explicitly opt out.
    if ep["no_auth"]:
        request["auth"] = {"type": "noauth"}
    if ep["description"]:
        request["description"] = clean_md(ep["description"])[:5000]
    if body:
        request["body"] = body

    item = {"name": ep["name"], "request": request, "response": []}

    if ep["response"] is not None:
        item["response"].append(
            {
                "name": f"Default response ({ep['response']['code']})",
                "originalRequest": {"method": ep["method"], "header": [], "url": {"raw": url["raw"]}},
                "status": "OK" if ep["response"]["code"] == 200 else "",
                "code": ep["response"]["code"],
                "_postman_previewlanguage": "json",
                "header": [],
                "cookie": [],
                "body": ep["response"]["body"],
            }
        )

    return item


def generate(md_text: str, version: str) -> dict:
    lines = md_text.splitlines()
    folders = []
    endpoint_count = 0

    for section_title, section_body in split_sections(lines, 2):
        items = []
        for sub_title, sub_body in split_sections(section_body, 3):
            ep = parse_endpoint(sub_title, sub_body)
            if ep:
                items.append(build_request(ep))
                endpoint_count += 1
        if items:
            folders.append({"name": section_title, "item": items})

    collection = {
        "info": {
            "_postman_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"fleet-api-{version}")),
            "name": f"Fleet API v{version}",
            "description": (
                f"Postman collection for the Fleet REST API, version {version}.\n\n"
                "**Note: this collection is a community resource and is not officially "
                "supported by Fleet.** For authoritative reference, use the official "
                "API documentation: https://fleetdm.com/docs/rest-api/rest-api\n\n"
                f"Generated from `{DOC_PATH}` at tag `fleet-v{version}` in the "
                "fleetdm/fleet repo by `scripts/generate_collection.py`.\n\n"
                "Setup: import the accompanying `fleet.postman_environment.json`, then "
                "set `baseUrl` to your Fleet server and `token` to your API token "
                "(Fleet UI > My account > Get API token). All requests inherit "
                "`Bearer {{token}}` auth from the collection.\n\n"
                "Query parameters are included on each request but disabled by default — "
                "enable the ones you need and replace the placeholder values."
            ),
            "schema": SCHEMA,
            "version": version,
        },
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}],
        },
        "item": folders,
    }
    print(f"Parsed {endpoint_count} endpoints across {len(folders)} folders.", file=sys.stderr)
    return collection


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="Path to a local rest-api.md")
    src.add_argument("--tag", help="Fleet release tag to fetch, e.g. fleet-v4.88.0")
    ap.add_argument("--version", help="Fleet version string (inferred from --tag if omitted)")
    ap.add_argument("-o", "--output", default="fleet.postman_collection.json")
    args = ap.parse_args()

    version = args.version
    if args.tag:
        version = version or args.tag.removeprefix("fleet-v")
        with tempfile.TemporaryDirectory() as td:
            md_path = fetch_docs(args.tag, Path(td))
            md_text = md_path.read_text(encoding="utf-8")
    else:
        if not version:
            ap.error("--version is required with --input")
        md_text = Path(args.input).read_text(encoding="utf-8")

    collection = generate(md_text, version)
    out = Path(args.output)
    out.write_text(json.dumps(collection, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    Path(out.parent, "VERSION").write_text(version + "\n", encoding="utf-8")

    env = {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "fleet-api-environment")),
        "name": "Fleet",
        "values": [
            {"key": "baseUrl", "value": "https://fleet.example.com", "type": "default", "enabled": True},
            {"key": "token", "value": "", "type": "secret", "enabled": True},
        ],
        "_postman_variable_scope": "environment",
    }
    env_path = Path(out.parent, "fleet.postman_environment.json")
    env_path.write_text(json.dumps(env, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {out} and {env_path} (Fleet v{version}).", file=sys.stderr)


if __name__ == "__main__":
    main()
