"""Paired client (v1 username == v2 `hue-application-key`).

Adapted from diyHue's HueObjects/ApiUser.py (Apache-2.0) — see /NOTICE.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


class ApiUser:
    def __init__(
        self,
        username: str,
        name: str,
        client_key: str,
        create_date: str | None = None,
        last_use_date: str | None = None,
    ) -> None:
        self.username = username
        self.name = name
        self.client_key = client_key
        self.create_date = create_date or _now()
        self.last_use_date = last_use_date or _now()

    def touch(self) -> None:
        self.last_use_date = _now()

    def get_v1_api(self) -> dict:
        return {"name": self.name, "create date": self.create_date, "last use date": self.last_use_date}

    def save(self) -> dict:
        return {
            "name": self.name,
            "client_key": self.client_key,
            "create_date": self.create_date,
            "last_use_date": self.last_use_date,
        }
