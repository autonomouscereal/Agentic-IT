#!/usr/bin/env python3
"""Small iTop REST CLI for the AI Server deployment.

Credentials come from environment variables or the dashboard/iTop .env files.
The client uses iTop REST v1.4 with dual auth: Basic Auth plus user/password
inside json_data.
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_ENV_FILES = [
    "/opt/agentic-it/SOC_TESTING/soc-dashboard/.env",
    "/opt/agentic-it/SOC_TESTING/itop-deployment/.env",
]


def parse_env_file(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    except FileNotFoundError:
        return


def load_env():
    for path in DEFAULT_ENV_FILES:
        parse_env_file(path)


class iTopClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password

    def _auth_header(self):
        token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        return f"Basic {token}"

    def post(self, operation, data=None):
        payload = {"operation": operation, "user": self.username, "password": self.password}
        if data:
            payload.update(data)
        body = urllib.parse.urlencode({
            "version": "1.4",
            "json_output": "1",
            "json_data": json.dumps(payload),
        }).encode()
        request = urllib.request.Request(
            f"{self.base_url}/webservices/rest.php",
            data=body,
            method="POST",
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            return {"code": exc.code, "error": exc.read().decode("utf-8", errors="replace")[:500]}
        except Exception as exc:
            return {"code": -1, "error": str(exc)}

    def check(self):
        return self.post("core/check_credentials")

    def get(self, class_name, key, output_fields=None):
        payload = {"class": class_name, "key": str(key)}
        if output_fields:
            payload["output_fields"] = output_fields
        return self.post("core/get", payload)

    def create(self, class_name, fields, comment):
        return self.post("core/create", {"class": class_name, "comment": comment, "fields": fields})

    def update(self, class_name, key, fields, comment):
        return self.post("core/update", {"class": class_name, "key": str(key), "comment": comment, "fields": fields})

    def delete(self, class_name, key, comment):
        return self.post("core/delete", {"class": class_name, "key": str(key), "comment": comment})

    def stimulus(self, class_name, key, stimulus, fields, comment):
        return self.post("core/apply_stimulus", {
            "class": class_name,
            "key": str(key),
            "stimulus": stimulus,
            "comment": comment,
            "fields": fields,
        })


def json_arg(value):
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser():
    parser = argparse.ArgumentParser(description="iTop REST v1.4 CLI")
    parser.add_argument("--base-url", default=None, help="iTop base URL, without /webservices/rest.php")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check")

    get_p = sub.add_parser("get")
    get_p.add_argument("class_name")
    get_p.add_argument("key")
    get_p.add_argument("--fields", default=None)

    create_p = sub.add_parser("create")
    create_p.add_argument("class_name")
    create_p.add_argument("fields", type=json_arg)
    create_p.add_argument("--comment", default="Created by iTop CLI")

    update_p = sub.add_parser("update")
    update_p.add_argument("class_name")
    update_p.add_argument("key")
    update_p.add_argument("fields", type=json_arg)
    update_p.add_argument("--comment", default="Updated by iTop CLI")

    delete_p = sub.add_parser("delete")
    delete_p.add_argument("class_name")
    delete_p.add_argument("key")
    delete_p.add_argument("--comment", default="Deleted by iTop CLI")

    stimulus_p = sub.add_parser("stimulus")
    stimulus_p.add_argument("class_name")
    stimulus_p.add_argument("key")
    stimulus_p.add_argument("stimulus")
    stimulus_p.add_argument("--fields", type=json_arg, default={})
    stimulus_p.add_argument("--comment", default="Stimulus applied by iTop CLI")
    return parser


def main():
    load_env()
    args = build_parser().parse_args()
    host = os.environ.get("ITOP_HOST", "localhost").strip() or "localhost"
    port = os.environ.get("ITOP_PORT", "25432").strip() or "25432"
    base_url = (args.base_url or os.environ.get("ITOP_URL") or f"http://{host}:{port}").rstrip("/")
    username = os.environ.get("ITOP_USER") or os.environ.get("ITOP_USERNAME") or "admin"
    password = os.environ.get("ITOP_PASSWORD") or ""
    if not password:
        print(json.dumps({"code": -1, "error": "ITOP_PASSWORD is not configured."}, indent=2))
        return 2

    client = iTopClient(base_url, username, password)
    if args.command == "check":
        result = client.check()
    elif args.command == "get":
        result = client.get(args.class_name, args.key, args.fields)
    elif args.command == "create":
        result = client.create(args.class_name, args.fields, args.comment)
    elif args.command == "update":
        result = client.update(args.class_name, args.key, args.fields, args.comment)
    elif args.command == "delete":
        result = client.delete(args.class_name, args.key, args.comment)
    else:
        result = client.stimulus(args.class_name, args.key, args.stimulus, args.fields, args.comment)

    print(json.dumps(result, indent=2))
    return 0 if result.get("code") in (0, None) else 1


if __name__ == "__main__":
    sys.exit(main())
