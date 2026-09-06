"""Personal ntfy notifications. No commands, arguments, transcript, or chat ID leave the PC."""
import re
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Notification server redirected the request; use its final HTTPS URL.")


def validate_url(url):
    url = url.strip()
    if not url:
        return ""
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not re.fullmatch(r"/[A-Za-z0-9_-]{1,200}", parsed.path)):
        raise ValueError("Use an HTTPS ntfy topic URL, for example https://ntfy.sh/your-private-topic.")
    return url


def send(url, token, title, count=1):
    url = validate_url(url)
    if not url:
        return
    body = (f"{title}: Codex needs your attention. "
            "Open the chat to review it. Acknowledge in ControlledYOLO to silence reminders.").encode("utf-8")
    headers = {"Content-Type": "text/plain; charset=utf-8", "Title": "Codex needs attention", "Priority": "4"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, body, headers, method="POST")
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=8) as response:
            if not 200 <= response.status < 300:
                raise ValueError("Notification server did not accept the message.")
    except urllib.error.HTTPError as error:
        raise ValueError(f"Phone notification failed (HTTP {error.code}).") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("Phone notification could not reach the server; will retry.") from None

