"""Private stdlib-only HTTP helper. Invoked by network.py with isolated Python."""

from __future__ import annotations

from http.client import IncompleteRead
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, build_opener


def _transfer():
    # -I ignores PYTHONPATH and the working directory. Only the installed source
    # next to this helper is added for the shared URL and redirect policies.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    specification = json.loads(sys.stdin.buffer.read(65537))
    policy = specification["policy"]
    if policy == "opds":
        from malferma_libro.opds import _SafeRedirects, _validate_url
        validate, redirects = _validate_url, _SafeRedirects
    elif policy == "voice":
        from malferma_libro.voices import _VoiceRedirects, _trusted_url
        validate, redirects = _trusted_url, _VoiceRedirects
    else:
        raise ValueError("Invalid HTTP policy")
    limit, timeout = specification["limit"], specification["timeout"]
    if type(limit) is not int or not 0 < limit <= 512 * 1024 * 1024 or not 0 < timeout <= 60:
        raise ValueError("Invalid HTTP transfer budget")
    url = specification["url"]
    validate(url)
    request = Request(url, headers=specification["headers"])
    with build_opener(redirects()).open(request, timeout=timeout) as response:
        final_url = response.geturl()
        validate(final_url)
        if len(final_url) > 8192:
            raise ValueError("HTTP response URL exceeded its bounds")
        headers = {}
        for name in ("Content-Type", "Content-Length", "Content-Encoding"):
            value = response.headers.get(name)
            if value is not None:
                if len(value) > 1024:
                    raise ValueError("HTTP header exceeded its bounds")
                headers[name] = value
        length = headers.get("Content-Length")
        try:
            expected = int(length) if length is not None else None
        except ValueError:
            expected = None
        if expected is not None and expected > limit:
            raise ValueError("HTTP response exceeded its byte limit")
        metadata = json.dumps({"url": final_url, "headers": headers, "status": response.status})
        sys.stdout.buffer.write(metadata.encode("utf-8") + b"\n")
        sys.stdout.buffer.flush()
        total = 0
        while True:
            chunk = response.read(min(65536, limit - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError("HTTP response exceeded its byte limit")
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        if expected is not None and expected >= 0 and total != expected:
            raise IncompleteRead(b"")


def main():
    try:
        _transfer()
    except HTTPError as error:
        error.close()
        result = {"kind": "http", "code": error.code}
    except IncompleteRead:
        result = {"kind": "incomplete"}
    except TimeoutError:
        result = {"kind": "timeout"}
    except Exception as error:
        result = {"kind": "network", "message": str(error)[:1024]}
    else:
        return 0
    sys.stderr.write(json.dumps(result))
    return 1


if __name__ == "__main__":
    sys.exit(main())
