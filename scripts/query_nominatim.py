#!/usr/bin/env python3
"""Test Nominatim search access and print a place name and coordinates.

Examples:
  python3 scripts/query_nominatim.py
  python3 scripts/query_nominatim.py "Guanacaste, Costa Rica"

The default query is the requested spelling, ``Gaunacaste``. Nominatim does not
correct that misspelling, so the default probe retries once with ``Guanacaste,
Costa Rica`` and clearly reports the fallback. Custom queries are not changed.
The script identifies itself with a custom User-Agent, as required by the public
Nominatim service's usage policy.
"""

from __future__ import annotations

import argparse
import json
import sys

import requests


ENDPOINT = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "PelagiaNominatimAccessTest/1.0"
DEFAULT_QUERY = "Gaunacaste"
DEFAULT_FALLBACK = "Guanacaste, Costa Rica"


def search(query: str, timeout: float = 30) -> tuple[str, dict]:
    """Return the request URL and first Nominatim result for *query*."""
    try:
        response = requests.get(
            ENDPOINT,
            params={"q": query, "format": "jsonv2", "limit": 1},
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        results = response.json()
    except requests.HTTPError as exc:
        detail = exc.response.text[:2000]
        raise RuntimeError(
            f"Nominatim returned HTTP {exc.response.status_code}: {detail}"
        ) from exc
    except requests.JSONDecodeError as exc:
        raise RuntimeError("Nominatim returned invalid JSON.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach Nominatim: {exc}") from exc

    url = response.url

    if not isinstance(results, list):
        raise RuntimeError("Nominatim returned an unexpected response shape.")
    if not results:
        raise LookupError(f"Nominatim found no results for {query!r}.")

    result = results[0]
    required = ("display_name", "lat", "lon")
    missing = [field for field in required if not result.get(field)]
    if missing:
        raise RuntimeError(
            "Nominatim result is missing required fields: " + ", ".join(missing)
        )
    return url, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default=DEFAULT_QUERY)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)

    resolved_query = args.query
    used_fallback = False
    try:
        url, result = search(resolved_query, timeout=args.timeout)
    except LookupError:
        if args.query != DEFAULT_QUERY:
            print(
                f"Error: Nominatim found no results for {args.query!r}.",
                file=sys.stderr,
            )
            return 1
        resolved_query = DEFAULT_FALLBACK
        used_fallback = True
        try:
            url, result = search(resolved_query, timeout=args.timeout)
        except (LookupError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output = {
        "requested_query": args.query,
        "resolved_query": resolved_query,
        "used_fallback": used_fallback,
        "display_name": result["display_name"],
        "latitude": float(result["lat"]),
        "longitude": float(result["lon"]),
        "request_url": url,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
