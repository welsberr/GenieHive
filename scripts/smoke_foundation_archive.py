#!/usr/bin/env python3
"""Send one provider-neutral archive migration request through GenieHive."""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    base_url = os.environ.get("GENIEHIVE_BASE_URL")
    api_key = os.environ.get("GENIEHIVE_API_KEY")
    model = os.environ.get("GENIEHIVE_MODEL", "archive_migrator")
    missing = [
        name
        for name, value in (
            ("GENIEHIVE_BASE_URL", base_url),
            ("GENIEHIVE_API_KEY", api_key),
        )
        if not value
    ]
    if missing:
        print(f"missing required environment: {', '.join(missing)}", file=sys.stderr)
        return 2

    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Archive smoke test. Reply with OK and nothing else.",
            }
        ],
    }
    request = Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        print(f"GenieHive returned HTTP {exc.code}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"could not reach GenieHive: {exc.reason}", file=sys.stderr)
        return 1
    except (TimeoutError, OSError) as exc:
        print(f"could not reach GenieHive: {exc}", file=sys.stderr)
        return 1
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"GenieHive returned malformed JSON: {exc}", file=sys.stderr)
        return 1

    try:
        choices = payload["choices"]
        message = choices[0]["message"]
        content = message["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("assistant content is empty")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        print(f"GenieHive response is missing an assistant message: {exc}", file=sys.stderr)
        return 1

    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
