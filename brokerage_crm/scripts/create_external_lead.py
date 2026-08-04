#!/usr/bin/env python3
"""Create a lead through the Brokerage CRM public ingestion endpoint."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("ODOO_URL", "http://localhost:8019"))
    parser.add_argument("--db", default=os.getenv("ODOO_DB"))
    parser.add_argument("--name", help="Optional lead title")
    parser.add_argument("--customer-name", required=True)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--campaign")
    parser.add_argument("--medium")
    parser.add_argument(
        "--assignment-type",
        choices=("manual", "round_robin"),
        required=True,
        help=(
            "Use round_robin to request automatic assignment or manual "
            "to create an unassigned lead."
        ),
    )
    parser.add_argument("--team-id", type=int)
    parser.add_argument("--notes")
    args = parser.parse_args()

    payload = {
        "name": args.name,
        "customer_name": args.customer_name,
        "phone": args.phone,
        "email": args.email,
        "source": args.source,
        "campaign": args.campaign,
        "medium": args.medium,
        "assignment_type": args.assignment_type,
        "team_id": args.team_id,
        "notes": args.notes,
    }
    body = json.dumps({key: value for key, value in payload.items() if value is not None})
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if args.db:
        headers["X-Odoo-Database"] = args.db

    request = urllib.request.Request(
        f"{args.url.rstrip('/')}/brokerage/api/v1/leads",
        data=body.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print(json.dumps(json.load(response), indent=2))
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        print(response_body, file=sys.stderr)
        raise SystemExit(1) from error
    except urllib.error.URLError as error:
        raise SystemExit(f"Could not connect to Odoo: {error.reason}") from error


if __name__ == "__main__":
    main()
