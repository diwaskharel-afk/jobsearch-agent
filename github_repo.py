import os
import re
from typing import NamedTuple, Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.github.com"
TIMEOUT_SECONDS = 10
MAX_README_CHARS = 12_000  # ~3k tokens; enough for the parts of a README that describe the project

_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")

# README noise that only costs tokens: comments, badges, images and HTML layout tags.
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_BADGE = re.compile(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)")  # [![alt](image)](link)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_HTML_TAG = re.compile(
    r"</?(?:a|p|div|span|img|br|hr|h[1-6]|picture|source|details|summary|table|thead|tbody|tr|td|th"
    r"|b|i|em|strong|sub|sup|center|kbd|code|pre|ul|ol|li)\b[^>]*>",
    re.I,
)
_BLANK_LINES = re.compile(r"\n{3,}")


class RepoRef(NamedTuple):
    owner: str
    repo: str
    ref: Optional[str] = None   # branch or tag from a /tree/<ref>/... link
    path: str = ""              # folder from a /tree/<ref>/<path> link; its README is read instead of the root one

    def __str__(self) -> str:
        return f"{self.owner}/{self.repo}" + (f"/{self.path}" if self.path else "")


class RepoFetchError(Exception):
    """Raised with a message that can be shown to the user as is."""


def parse_github_url(url: str) -> Optional[RepoRef]:
    """RepoRef for a github.com repo URL in any common form; None for other hosts or malformed URLs."""
    text = url.strip()
    if not text:
        return None
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    if (parsed.hostname or "").lower() not in ("github.com", "www.github.com"):
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if not (_NAME.match(owner) and _NAME.match(repo)):
        return None
    if len(parts) >= 4 and parts[2] == "tree":
        return RepoRef(owner, repo, parts[3], "/".join(parts[4:]))
    return RepoRef(owner, repo)


def clean_readme(text: str) -> str:
    text = _HTML_COMMENT.sub("", text)
    text = _BADGE.sub("", text)
    text = _IMAGE.sub("", text)
    text = _HTML_TAG.sub("", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = _BLANK_LINES.sub("\n\n", text).strip()
    if len(text) > MAX_README_CHARS:
        cut = text.rfind("\n", 0, MAX_README_CHARS)
        text = text[: cut if cut > 0 else MAX_README_CHARS] + "\n\n[README truncated]"
    return text


def fetch_readme(repo: RepoRef) -> str:
    """The repo's cleaned README text. Raises RepoFetchError on any failure."""
    headers = {"Accept": "application/vnd.github.raw+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{API_URL}/repos/{repo.owner}/{repo.repo}/readme" + (f"/{repo.path}" if repo.path else "")
    params = {"ref": repo.ref} if repo.ref else None
    try:
        response = httpx.get(url, headers=headers, params=params, timeout=TIMEOUT_SECONDS, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise RepoFetchError(f"couldn't reach GitHub to read {repo}.") from exc

    if response.status_code == 200:
        return clean_readme(response.text)
    if response.status_code == 404:
        hint = "" if token else " Private repos need a GITHUB_TOKEN in .env."
        raise RepoFetchError(f"no README found for {repo}: the repo doesn't exist, is private or has no README.{hint}")
    if response.status_code == 401:
        raise RepoFetchError("GitHub rejected the GITHUB_TOKEN in .env; check that it is valid.")
    if response.status_code in (403, 429) and response.headers.get("x-ratelimit-remaining") == "0":
        raise RepoFetchError("GitHub's hourly request limit is reached. Try again later or add a GITHUB_TOKEN to .env.")
    raise RepoFetchError(f"GitHub returned status {response.status_code} for {repo}.")
