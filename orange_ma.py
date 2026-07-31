#!/usr/bin/env python3
import argparse
import base64
import getpass
import json
import os
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
from pathlib import Path


BASE_URL = "https://maxit.orange.ma"
API_VERSION = "v10.9"
DEFAULT_CONFIG = Path(__file__).resolve().with_name("config.toml")


class CliError(Exception):
    pass


class ApiError(CliError):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail
        super().__init__(f"Orange API returned HTTP {status}: {detail}")


class InvalidCredentials(CliError):
    pass


class MaxItClient:
    def __init__(self, email, password, timeout=30):
        self.email = email
        self.password = password
        self.timeout = timeout
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Maxit/10.9.0",
            "X-OS": "android",
            "X-OS-Version": "Android 12",
            "X-OS-Model": "SM-A115F",
            "X-firebase-Id": "",
            "X-Line-Type": "PO",
        }

    def _request(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            BASE_URL + path,
            data=data,
            headers=self.headers | (headers or {}),
            method="POST" if body is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace").strip()
            try:
                payload = json.loads(detail)
                detail = payload.get("message") or payload.get("error") or detail
            except (json.JSONDecodeError, AttributeError):
                pass
            raise ApiError(error.code, detail) from error
        except urllib.error.URLError as error:
            raise CliError(f"Could not reach Orange API: {error.reason}") from error

        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise CliError("Orange API returned an invalid response") from error

    def login(self):
        try:
            user = self._request(
                f"/moncompte/{API_VERSION}/login",
                {
                    "login": self.email,
                    "password": base64.b64encode(self.password.encode()).decode(),
                    "culture": "fr",
                    "remember_me": True,
                    "channel": 2,
                    "checkByEmail": True,
                },
            )
        except ApiError as error:
            if error.status in (400, 401, 403):
                raise InvalidCredentials("Email or password is incorrect.") from error
            raise

        try:
            user["token"]
            user["msisdn"]
        except (KeyError, TypeError) as error:
            raise CliError("Login response did not contain a session token and line number") from error
        return user

    def balances(self, user):
        return self._request(
            f"/fiche-client/{API_VERSION}/balances/{user['msisdn']}",
            headers={
                "Accept-Language": user.get("language", "fr"),
                "X-SSO-TOKEN": user["token"],
            },
        )


def load_config(path):
    try:
        with path.open("rb") as config_file:
            config = tomllib.load(config_file)
    except FileNotFoundError:
        return {"email": "", "password": ""}
    except tomllib.TOMLDecodeError as error:
        raise CliError(f"Invalid TOML in {path}: {error}") from error
    return {
        "email": str(config.get("email") or ""),
        "password": str(config.get("password") or ""),
    }


def save_config(path, email, password):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as config_file:
            config_file.write(f"email = {json.dumps(email, ensure_ascii=False)}\n")
            config_file.write(f"password = {json.dumps(password, ensure_ascii=False)}\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def confirm(question):
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def interactive_login(config_path, current_email=""):
    while True:
        prompt = f"Email [{current_email}]: " if current_email else "Email: "
        email = input(prompt).strip() or current_email
        password = getpass.getpass("Password: ")
        if not email or not password:
            print("Email and password cannot be blank.", file=sys.stderr)
            continue

        client = MaxItClient(email, password)
        try:
            user = client.login()
        except InvalidCredentials as error:
            print(f"orange: {error}", file=sys.stderr)
            if confirm("Try again?"):
                current_email = email
                continue
            raise CliError("Login cancelled.") from error

        save_config(config_path, email, password)
        return client, user


def selected_balance(balance, command):
    metadata = {
        key: balance[key]
        for key in ("msisdn", "balanceAt", "billingCycle", "tariffPlan")
        if key in balance
    }
    if command in ("all", "plan"):
        metadata["items"] = balance.get("items", [])
    if command in ("all", "topups"):
        metadata["categories"] = balance.get("categories", [])
    return metadata


def balance_value_text(value):
    if not isinstance(value, dict):
        return ""
    amount = value.get("value")
    if amount is None:
        return ""
    return f"{amount} {value.get('unit', '')}".strip()


def item_text(item):
    if item.get("message"):
        text = item["message"]
    elif item.get("rawValue"):
        text = item["rawValue"]
    else:
        values = item.get("valueItems") or []
        text = " ".join(balance_value_text(value) for value in values).strip()

    gauge = item.get("gauge") or {}
    consumed = balance_value_text(gauge.get("consumed"))
    initial = balance_value_text(gauge.get("initial"))
    if consumed and initial:
        text = f"{text or 'Usage'} (used {consumed} of {initial})"
    elif gauge.get("consumedPercentage"):
        text = f"{text or 'Usage'} ({gauge['consumedPercentage']} used)"
    return text or "Unavailable"


def render_human(balance, command):
    lines = []
    tariff_plan = balance.get("tariffPlan")
    if tariff_plan:
        lines.append(str(tariff_plan))

    if command in ("all", "plan"):
        if lines:
            lines.append("")
        lines.append("Plan")
        items = balance.get("items", [])
        lines.extend(f"  {item_text(item)}" for item in items)
        if not items:
            lines.append("  No plan balances.")

    if command in ("all", "topups"):
        if lines:
            lines.append("")
        lines.append("Top-ups")
        categories = balance.get("categories", [])
        if not categories:
            lines.append("  No top-up balances.")
        for category in categories:
            lines.append(f"  {category.get('name') or 'Additional balance'}")
            items = category.get("items", [])
            lines.extend(f"    {item_text(item)}" for item in items)
            if not items:
                lines.append("    No balances.")

    if balance.get("balanceAt"):
        lines.extend(("", f"Updated: {balance['balanceAt']}"))
    return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(
        prog="orange",
        description="Show Orange Maroc plan and top-up balances.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("all", "plan", "topups", "login", "logout"),
        default="all",
        help="balance section to show (default: all)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"TOML credentials file (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument("--json", action="store_true", help="print JSON")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        config = load_config(args.config)
        email = config["email"]
        password = config["password"]

        if args.command == "logout":
            if not email or not password:
                print("Not logged in.")
                return 0
            if not confirm(f"Log out {email}?"):
                print("Logout cancelled.")
                return 0
            save_config(args.config, "", "")
            print("Logged out.")
            return 0

        if args.command == "login":
            if email and password and not confirm(f"Already logged in as {email}. Log in again?"):
                print("Login unchanged.")
                return 0
            client, _ = interactive_login(args.config, email)
            print(f"Logged in as {client.email}.")
            return 0

        if not email or not password:
            client, user = interactive_login(args.config, email)
        else:
            client = MaxItClient(email, password)
            try:
                user = client.login()
            except InvalidCredentials as error:
                print(f"orange: {error}", file=sys.stderr)
                if not confirm(f"Login failed for {email}. Log in again?"):
                    raise CliError("Login cancelled.") from error
                client, user = interactive_login(args.config, email)

        balance = client.balances(user)
        if args.json:
            print(json.dumps(selected_balance(balance, args.command), indent=2, ensure_ascii=False))
        else:
            print(render_human(balance, args.command))
    except (EOFError, KeyboardInterrupt):
        print("\norange: Cancelled.", file=sys.stderr)
        return 1
    except CliError as error:
        print(f"orange: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
