"""Signed, retryable transactional event delivery to operator-configured destinations."""

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send(url, body, headers):
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code
    except (OSError, urllib.error.URLError):
        return None


def deliver_once(store, sender=send):
    row = store.claim_webhook()
    if row is None:
        return False
    destination = store.settings.webhook_destinations.get(row["tenant"])
    status = None
    if destination:
        body = json.dumps(row["payload"], separators=(",", ":"), sort_keys=True).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(
            destination["secret"].encode(), timestamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        try:
            status = sender(
                destination["url"],
                body,
                {
                    "Content-Type": "application/json",
                    "X-Verification-Timestamp": timestamp,
                    "X-Verification-Signature": "sha256=" + signature,
                    "X-Verification-Event-ID": str(row["event_cursor"]),
                },
            )
        except Exception:
            # Never retain credentials, request bodies or remote response content in logs.
            status = None
    store.finish_webhook(row, status)
    return True


def serve(store):
    while True:
        if not deliver_once(store):
            time.sleep(0.5)
