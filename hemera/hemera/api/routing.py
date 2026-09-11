"""Route registration helper: also registers a trailing-slash alias for
every route, so e.g. `POST /api/` and `POST /api` both reach the same
handler.

Found from a real pairing failure (add-on logs showed the actual client's
requests, not a guess): Hue Sync for PC always sends `POST /api/` — with a
trailing slash — to register, while every other client tested against this
project (the Hue app, curl, our own tests) uses the slash-less `POST /api`.
aiohttp's router treats those as two distinct paths, so the slash-less-only
route left Sync's request 404ing on every single attempt — indistinguishable
from its side from the bridge simply never responding at all, matching
exactly the "stuck on the push-link screen" symptom reported.

Deliberately NOT implemented as an aiohttp middleware that redirects (which
is what aiohttp's own built-in ``normalize_path_middleware`` does for this
exact mismatch): a redirect requires the client to correctly re-send the
same method and body to the new location, which isn't something to rely on
for a client we don't control or get to test against directly. It also
turns out a middleware can't do this in a redirect-free way either, for an
unrelated reason confirmed by testing: aiohttp binds the "next handler" in
the middleware chain to the route resolved *before* any middleware runs, so
a middleware that resolves a trailing-slash-stripped path to a real route
and then calls ``handler(alt_request)`` still gets a 404 back — ``handler``
stays bound to the originally-resolved (unmatched) route regardless of what
``alt_request.match_info`` says. Registering both paths up front avoids
both problems at once.
"""

from __future__ import annotations

from aiohttp import web


def add_route(app: web.Application, method: str, path: str, handler) -> None:
    """Register `path` for `method`, plus a `path + "/"` alias whenever
    `path` doesn't already end in a slash (and isn't the bare root `/`,
    which has no meaningful "with trailing slash" variant)."""
    app.router.add_route(method, path, handler)
    if path != "/" and not path.endswith("/"):
        app.router.add_route(method, path + "/", handler)
