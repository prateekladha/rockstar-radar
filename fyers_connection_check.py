#!/usr/bin/env python3
"""Read-only FYERS V3 quote connectivity diagnostic.

Run from the existing Rockstar Radar pilot directory:
    python fyers_connection_check.py

Only requests one known-valid quote; never submits orders. It does not display
or save app secrets, access tokens, redirect URLs, or profile information.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

HOST = "api-t1.fyers.in"
SYMBOL = "NSE:SBIN-EQ"
ENV_PATH = Path(__file__).resolve().parent / ".env"


def read_file_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def redact(value: object, app_id: str, token: str) -> str:
    text = str(value if value is not None else "")
    for secret in (token, app_id):
        if secret:
            text = text.replace(secret, "[redacted]")
    # Do not output long JWT-like words even if the server echoed a token.
    import re
    text = re.sub(r"eyJ[A-Za-z0-9._=-]{16,}", "[redacted]", text)
    return text[:140]


def interpret(http_status: int, payload: object, app_id: str = "", token: str = "") -> str:
    if not isinstance(payload, dict):
        return "NON_JSON: HTTP %s returned a non-object body. Check proxy/service response." % http_status
    code = payload.get("code")
    message = redact(payload.get("message", ""), app_id, token)
    s = payload.get("s")
    if http_status == 200 and (s == "ok" or code == 200):
        rows = payload.get("d")
        if isinstance(rows, list) and any(
            isinstance(x, dict) and x.get("n") == SYMBOL and x.get("s") == "ok"
            for x in rows
        ):
            return "PASS: Direct HTTPS GET returned a valid SBIN quote (HTTP 200)."
        return "UNEXPECTED: HTTP 200 but no valid SBIN quote row; API status=%s code=%s." % (s, code)
    if http_status == 401 or code in (-8, -15, -16, -17, -352):
        kind = "AUTH"
    elif http_status == 403:
        kind = "PERMISSION"
    elif http_status == 429 or code in (-360, -429):
        kind = "RATE_LIMIT"
    elif http_status in (400, 422) or code in (-50, -300):
        kind = "BAD_REQUEST"
    elif http_status >= 500:
        kind = "SERVICE"
    else:
        kind = "API_FAILURE"
    return "%s: HTTP %s, FYERS code=%s, message=%s" % (kind, http_status, code, message)


def direct_get_quotes(app_id: str, token: str, opener=None) -> tuple[str, str]:
    """Returns (machine-status, safe diagnosis). Never prints or returns credentials."""
    url = "https://" + HOST + "/data/quotes?" + urllib.parse.urlencode({"symbols": SYMBOL})
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": app_id + ":" + token,
            "Content-Type": "application/json",
            "version": "3",
            "Accept": "application/json",
        },
        method="GET",
    )
    open_request = opener or urllib.request.urlopen
    try:
        if opener is None:
            response = open_request(req, timeout=12, context=ssl.create_default_context())
        else:
            response = open_request(req, timeout=12)
        with response as res:
            http_status = res.getcode()
            raw = res.read(16384)
    except urllib.error.HTTPError as exc:
        http_status = exc.code
        raw = exc.read(16384)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        cause = type(reason).__name__
        if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(reason):
            return "TLS", "TLS_ERROR: certificate verification failed. Check Python certificates, VPN/proxy, and system clock."
        if isinstance(reason, (socket.gaierror,)):
            return "DNS", "DNS_ERROR: cannot resolve FYERS API host. Check internet, DNS, or VPN."
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "TIMEOUT", "TIMEOUT: could not complete FYERS HTTPS request within 12 seconds."
        return "TRANSPORT", "TRANSPORT_ERROR: HTTPS failed before receiving an HTTP response (%s)." % cause
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return "NON_JSON", "NON_JSON: HTTP %s returned non-JSON. Check proxy/VPN, blocked API host, or service response." % http_status
    result = interpret(http_status, payload, app_id, token)
    return ("PASS" if result.startswith("PASS:") else "HTTP"), result


def main() -> int:
    print("Rockstar Radar | FYERS read-only connectivity check")
    print("This check does not place orders or display credentials.")
    file_values = read_file_env(ENV_PATH)
    if not ENV_PATH.is_file():
        print("WARNING: .env not found beside this script. Copy it into the project folder first.")
    for key in ("FYERS_APP_ID", "FYERS_ACCESS_TOKEN"):
        shell = os.environ.get(key)
        saved = file_values.get(key)
        if shell and saved and shell != saved:
            print("WARNING: %s differs between shell and .env; the existing pilot uses the SHELL value." % key)
    app_id = os.environ.get("FYERS_APP_ID", file_values.get("FYERS_APP_ID", "")).strip()
    token = os.environ.get("FYERS_ACCESS_TOKEN", file_values.get("FYERS_ACCESS_TOKEN", "")).strip()
    print("App ID set: %s | Access token set: %s" % (bool(app_id), bool(token)))
    if not app_id or not token or "YOUR_" in app_id:
        print("ACTION: Set FYERS_APP_ID and FYERS_ACCESS_TOKEN; run python launch.py login locally.")
        return 2
    if not app_id.endswith("-100"):
        print("WARNING: FYERS App ID normally ends in -100. Check the app dashboard.")
    if token.startswith(app_id + ":"):
        print("TOKEN_FORMAT_ERROR: FYERS_ACCESS_TOKEN must contain only the access token, without an App ID prefix.")
        return 2
    if any(k in os.environ for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")):
        print("NOTE: An HTTP(S) proxy environment variable is set (value hidden).")
    try:
        sdk_version = importlib.metadata.version("fyers-apiv3")
    except importlib.metadata.PackageNotFoundError:
        sdk_version = "not installed"
    print("FYERS Python SDK: %s" % sdk_version)
    try:
        socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)
        print("DNS lookup: OK")
    except socket.gaierror:
        print("DNS lookup: FAILED - check DNS / VPN / network")
    print("Checking direct read-only Quotes GET for NSE:SBIN-EQ...")
    status, message = direct_get_quotes(app_id, token)
    print(message)
    if status == "PASS":
        print("NEXT: Authorization and direct Quotes API work. The -99 is likely SDK/requests-specific; update the SDK or use direct-HTTPS fallback.")
        return 0
    if "AUTH:" in message or "PERMISSION:" in message:
        print("NEXT: Verify the active FYERS app, Market Data permission and daily token. Then run python launch.py login.")
    elif "RATE_LIMIT:" in message:
        print("NEXT: Stop polling and retry only after the FYERS rate-limit window resets.")
    elif status in ("DNS", "TLS", "TIMEOUT", "TRANSPORT", "NON_JSON"):
        print("NEXT: Fix local HTTPS/DNS/certificates or VPN/proxy before retrying the scanner.")
    else:
        print("NEXT: Use the HTTP status and FYERS code above to identify the underlying API failure.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
