from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests
from dotenv import load_dotenv


load_dotenv()


class MFLAuthError(RuntimeError):
    """Raised when MFL authentication fails."""


@dataclass(frozen=True)
class MFLConfig:
    year: int = int(os.getenv("MFL_YEAR", "2026"))
    league_id: str = os.getenv("MFL_LEAGUE_ID", "33236")
    base_url: str = os.getenv("MFL_BASE_URL", "https://www43.myfantasyleague.com")
    api_base_url: str = os.getenv("MFL_API_BASE_URL", "https://api.myfantasyleague.com")
    api_key: str = os.getenv("MFL_API_KEY", "")
    username: str = os.getenv("MFL_USERNAME", "")
    password: str = os.getenv("MFL_PASSWORD", "")
    user_agent: str = os.getenv("MFL_USER_AGENT", "CodexDynastyAnalyzer/0.1")


class MFLClient:
    def __init__(self, config: MFLConfig | None = None) -> None:
        self.config = config or MFLConfig()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.config.user_agent})

    def login(self) -> None:
        if not self.config.username or not self.config.password:
            raise MFLAuthError("Set MFL_USERNAME and MFL_PASSWORD before using cookie login.")

        url = f"{self.config.api_base_url}/{self.config.year}/login"
        response = self.session.post(
            url,
            data={
                "USERNAME": self.config.username,
                "PASSWORD": self.config.password,
                "XML": "1",
            },
            timeout=30,
        )
        response.raise_for_status()

        root = ElementTree.fromstring(response.text)
        error = root if root.tag == "error" else root.find(".//error")
        if error is not None:
            message = error.attrib.get("message") or error.text or "MFL login failed."
            raise MFLAuthError(message)

        status = root if root.tag == "status" else root.find(".//status")
        if status is None:
            raise MFLAuthError("MFL login response did not include a status element.")

        cookie_name = status.attrib.get("cookie_name", "MFL_USER_ID")
        cookie_value = (
            status.attrib.get("cookie_value")
            or status.attrib.get(cookie_name)
            or status.attrib.get("MFL_USER_ID")
        )
        if not cookie_value:
            candidate_names = [name for name in status.attrib if name.lower() not in {"password"}]
            for name in candidate_names:
                value = status.attrib.get(name, "")
                if len(value) > 20 and name not in {"username", "franchise_id", "league_id"}:
                    cookie_name = name
                    cookie_value = value
                    break
        if not cookie_value:
            fields = ", ".join(sorted(status.attrib)) or "none"
            raise MFLAuthError(f"MFL login response did not include a cookie value. Status fields: {fields}")

        self.session.cookies.set(cookie_name, cookie_value, domain=".myfantasyleague.com")
        for cookie in response.cookies:
            self.session.cookies.set(cookie.name, cookie.value, domain=".myfantasyleague.com")

    def export(
        self,
        export_type: str,
        *,
        year: int | None = None,
        league_id: str | None = None,
        host: str | None = None,
        use_api_key: bool = True,
        login_first: bool = False,
        **params: Any,
    ) -> dict[str, Any]:
        if login_first:
            self.login()

        season = year or self.config.year
        base = host or self.config.base_url
        url = urljoin(base.rstrip("/") + "/", f"{season}/export")
        query: dict[str, Any] = {
            "TYPE": export_type,
            "JSON": "1",
        }

        target_league = league_id if league_id is not None else self.config.league_id
        if target_league:
            query["L"] = target_league

        if use_api_key and self.config.api_key:
            query["APIKEY"] = self.config.api_key

        query.update(params)
        response = self.session.get(url, params=query, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            error = data["error"]
            message = error.get("$t") if isinstance(error, dict) else str(error)
            raise MFLAuthError(message)

        return data
