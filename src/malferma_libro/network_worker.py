"""Private stdlib-only HTTP helper. Invoked by network.py with isolated Python."""

from __future__ import annotations

from http.client import HTTPConnection, HTTPSConnection, IncompleteRead
from ipaddress import IPv6Address, ip_address, ip_network
import json
from pathlib import Path
import socket
import sys
from urllib.error import HTTPError
from urllib.request import HTTPHandler, HTTPSHandler, ProxyHandler, Request, build_opener


_NAT64_PREFIXES = (ip_network("64:ff9b::/96"), ip_network("64:ff9b:1::/48"))


def _public_address(address):
    ip = ip_address(address)
    if isinstance(ip, IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif (ip.is_site_local or ip.sixtofour is not None or ip.teredo is not None
              or any(ip in prefix for prefix in _NAT64_PREFIXES)):
            return False
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def _connect_public(destination, timeout, source_address=None):
    host, port = destination
    last_error = None
    for family, kind, protocol, _name, address in socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    ):
        if not _public_address(address[0]) or (family == socket.AF_INET6 and address[3]):
            continue
        connection = socket.socket(family, kind, protocol)
        try:
            connection.settimeout(timeout)
            if source_address is not None:
                connection.bind(source_address)
            # Connect to the exact resolver result that passed the policy.
            connection.connect(address)
            return connection
        except OSError as error:
            connection.close()
            last_error = error
    if last_error is not None:
        raise last_error
    raise OSError("OPDS cover destination is not a public IP address")


def _public_connection(connection_type):
    def create(*args, **kwargs):
        connection = connection_type(*args, **kwargs)
        # Preserve the original hostname for HTTP Host, TLS SNI and certificate
        # verification. Only the socket creation differs from the stdlib.
        connection._create_connection = _connect_public
        return connection
    return create


class _PublicHTTPHandler(HTTPHandler):
    def http_open(self, request):
        return self.do_open(_public_connection(HTTPConnection), request)


class _PublicHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        return self.do_open(_public_connection(HTTPSConnection), request, context=self._context)


def _transfer():
    # -I ignores PYTHONPATH and the working directory. Only the installed source
    # next to this helper is added for the shared URL and redirect policies.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    specification = json.loads(sys.stdin.buffer.read(65537))
    policy = specification["policy"]
    if policy in {"opds", "opds-cover"}:
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
    handlers = [redirects()]
    if policy == "opds-cover":
        # A proxy resolves the destination independently. Disable ambient
        # proxies for covers so the same socket policy applies to every hop.
        handlers.extend((ProxyHandler({}), _PublicHTTPHandler(), _PublicHTTPSHandler()))
    with build_opener(*handlers).open(request, timeout=timeout) as response:
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
