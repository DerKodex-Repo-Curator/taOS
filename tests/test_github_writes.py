"""Tests for the taOS Agent GitHub write helper (tsk-nc7o4o).

Spec sections 2 and 3: the agent acts as the user (fork, branch
``taos-agent/<slug>``, PR into dev); a secret scan refuses the write before
any network call; at most one open taOS Agent PR per repo per user; the PR
body ends with the attribution line; nothing ever deletes, force-pushes or
merges.

The fake GitHub server is an ``httpx.MockTransport`` handler that answers the
REST calls the helper makes and records every request it sees.
"""
from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio

from tinyagentos import __version__

try:
    from tinyagentos import github_writes as gw
except ImportError:  # red-first run on a base without the helper: each test FAILS
    gw = None

UPSTREAM = "jaylfc/taOS"
LOGIN = "alice"


class FakeGitHub:
    def __init__(self, *, fork_exists: bool = False, open_pulls: list | None = None):
        self.log: list[httpx.Request] = []
        self.fork_exists = fork_exists
        self.open_pulls = open_pulls or []
        self.refs: dict[str, str] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.log.append(request)
        path = request.url.path
        method = request.method
        if method == "GET" and path == f"/repos/{LOGIN}/taOS":
            if not self.fork_exists:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(
                200, json={"full_name": f"{LOGIN}/taOS", "fork": True,
                           "parent": {"full_name": UPSTREAM}},
            )
        if method == "POST" and path == f"/repos/{UPSTREAM}/forks":
            self.fork_exists = True
            return httpx.Response(202, json={"full_name": f"{LOGIN}/taOS"})
        if method == "GET" and path == f"/repos/{UPSTREAM}/git/ref/heads/dev":
            return httpx.Response(200, json={"object": {"sha": "basesha"}})
        if method == "GET" and path.startswith(f"/repos/{LOGIN}/taOS/git/ref/heads/"):
            ref = path.split("/git/ref/", 1)[1]
            if ref in self.refs:
                return httpx.Response(200, json={"object": {"sha": self.refs[ref]}})
            return httpx.Response(404, json={"message": "Not Found"})
        if method == "GET" and path.startswith(f"/repos/{LOGIN}/taOS/git/commits/"):
            return httpx.Response(200, json={"tree": {"sha": "basetree"}})
        if method == "POST" and path == f"/repos/{LOGIN}/taOS/git/trees":
            return httpx.Response(201, json={"sha": "newtree"})
        if method == "POST" and path == f"/repos/{LOGIN}/taOS/git/commits":
            return httpx.Response(201, json={"sha": "newcommit"})
        if method == "POST" and path == f"/repos/{LOGIN}/taOS/git/refs":
            body = json.loads(request.content)
            self.refs[body["ref"].removeprefix("refs/")] = body["sha"]
            return httpx.Response(201, json={"ref": body["ref"]})
        if method == "PATCH" and path.startswith(f"/repos/{LOGIN}/taOS/git/refs/"):
            return httpx.Response(200, json={})
        if method == "GET" and path == f"/repos/{UPSTREAM}/pulls":
            return httpx.Response(200, json=self.open_pulls)
        if method == "POST" and path == f"/repos/{UPSTREAM}/pulls":
            return httpx.Response(
                201, json={"html_url": f"https://github.com/{UPSTREAM}/pull/9", "number": 9}
            )
        if method == "POST" and path == f"/repos/{UPSTREAM}/issues":
            return httpx.Response(
                201, json={"html_url": f"https://github.com/{UPSTREAM}/issues/8", "number": 8}
            )
        return httpx.Response(418, json={"message": f"unexpected {method} {path}"})

    def bodies(self, method: str, suffix: str) -> list[dict]:
        return [
            json.loads(r.content) for r in self.log
            if r.method == method and r.url.path.endswith(suffix)
        ]


@pytest.fixture
def fake():
    return FakeGitHub()


@pytest_asyncio.fixture
async def http(fake):
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as client:
        yield client


def _session(http: httpx.AsyncClient, data_dir: str | None = "/var/lib/taos-data"):
    return gw.GitHubSession(token="gho_test", login=LOGIN, http=http, data_dir=data_dir)


ATTRIBUTION = f"Filed by the taOS Agent on behalf of {LOGIN} (taOS {__version__})"


# -- secret scan: refused before any network call ---------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content, kind",
    [
        ("peer = 100.101.12.7\n", "tailscale_address"),
        ('API_KEY = "sk-abcdefghijklmnopqrstuvwx"\n', "api_key"),
        ("host = 192.168.1.20\n", "ipv4_address"),
        ("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n", "private_key"),
        ("box.tail1234.ts.net\n", "tailscale_hostname"),
        ("path = /var/lib/taos-data/secrets.db\n", "data_dir_path"),
    ],
)
async def test_push_refuses_secret_before_network(http, fake, content, kind):
    gh = _session(http)
    with pytest.raises(gw.SecretScanRefused) as exc:
        await gw.push_branch(gh, UPSTREAM, "fix-weather", {"app/x.py": content}, "fix")
    assert kind in exc.value.kinds
    assert fake.log == []
    # The refusal names the kind, never the matched value.
    assert content.strip().split()[-1].strip('"') not in str(exc.value)


@pytest.mark.asyncio
async def test_pr_and_issue_bodies_are_scanned(http, fake):
    gh = _session(http)
    with pytest.raises(gw.SecretScanRefused):
        await gw.open_pr(gh, UPSTREAM, "fix-weather", "Fix", "token sk-abcdefghijklmnopqrstuvwx")
    with pytest.raises(gw.SecretScanRefused):
        await gw.create_issue(gh, UPSTREAM, "Crash", "my box is 100.64.0.3")
    assert fake.log == []


def test_env_file_is_refused():
    assert "env_file" in gw.secret_scan("DB_PASSWORD=hunter2\n", path=".env")
    assert gw.secret_scan("version = 1.0.0\nhost = 127.0.0.1\n") == []


# -- branch name, PR shape, attribution -------------------------------------

@pytest.mark.asyncio
async def test_full_flow_branch_pr_and_attribution(http, fake):
    gh = _session(http)
    fork = await gw.ensure_fork(gh, UPSTREAM)
    assert fork == f"{LOGIN}/taOS"
    branch = await gw.push_branch(
        gh, UPSTREAM, "fix-weather", {"app/weather.py": "x = 1\n"}, "Fix weather crash"
    )
    assert branch == "taos-agent/fix-weather"
    assert fake.bodies("POST", "/git/refs") == [
        {"ref": "refs/heads/taos-agent/fix-weather", "sha": "newcommit"}
    ]

    pr = await gw.open_pr(gh, UPSTREAM, "fix-weather", "Fix weather crash", "It crashed.")
    assert pr == {"url": f"https://github.com/{UPSTREAM}/pull/9", "number": 9}
    (sent,) = fake.bodies("POST", f"/repos/{UPSTREAM}/pulls")
    assert sent["head"] == f"{LOGIN}:taos-agent/fix-weather"
    assert sent["base"] == "dev"
    assert sent["body"].rstrip().splitlines()[-1] == ATTRIBUTION

    issue = await gw.create_issue(gh, UPSTREAM, "Weather crash", "Steps: open it.")
    assert issue["number"] == 8
    (sent,) = fake.bodies("POST", f"/repos/{UPSTREAM}/issues")
    assert sent["body"].rstrip().splitlines()[-1] == ATTRIBUTION

    # Every call carries the user's token; nothing destructive was issued.
    assert all(r.headers["authorization"] == "Bearer gho_test" for r in fake.log)
    _assert_no_destructive_calls(fake.log)


@pytest.mark.asyncio
async def test_existing_branch_is_fast_forwarded_never_forced(http, fake):
    gh = _session(http)
    fake.fork_exists = True
    fake.refs["heads/taos-agent/fix-weather"] = "oldhead"
    await gw.push_branch(gh, UPSTREAM, "fix-weather", {"a.py": "y = 2\n"}, "more")
    (commit,) = fake.bodies("POST", "/git/commits")
    assert commit["parents"] == ["oldhead"]
    (patch,) = fake.bodies("PATCH", "/git/refs/heads/taos-agent/fix-weather")
    assert patch == {"sha": "newcommit", "force": False}
    _assert_no_destructive_calls(fake.log)


def _assert_no_destructive_calls(log: list[httpx.Request]) -> None:
    for r in log:
        assert r.method != "DELETE", r.url
        assert "/merge" not in r.url.path, r.url
        if r.content:
            assert json.loads(r.content).get("force") in (None, False), r.url


@pytest.mark.parametrize("bad", ["", "Fix", "a/b", "../x", "-x", "x" * 61])
@pytest.mark.asyncio
async def test_bad_slug_is_refused(http, fake, bad):
    gh = _session(http)
    with pytest.raises(ValueError):
        await gw.push_branch(gh, UPSTREAM, bad, {"a.py": "x\n"}, "m")
    assert fake.log == []


# -- one open taOS Agent PR per repo per user -------------------------------

@pytest.mark.asyncio
async def test_second_open_pr_is_refused(fake):
    fake.open_pulls = [{
        "html_url": f"https://github.com/{UPSTREAM}/pull/5", "number": 5,
        "head": {"label": f"{LOGIN}:taos-agent/older-fix", "ref": "taos-agent/older-fix"},
    }]
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as http:
        gh = _session(http, data_dir=None)
        with pytest.raises(gw.OpenPullRequestExists) as exc:
            await gw.open_pr(gh, UPSTREAM, "fix-weather", "Fix", "body")
    assert exc.value.url == f"https://github.com/{UPSTREAM}/pull/5"
    assert fake.bodies("POST", f"/repos/{UPSTREAM}/pulls") == []


@pytest.mark.asyncio
async def test_same_branch_open_pr_is_returned_not_duplicated(fake):
    fake.open_pulls = [{
        "html_url": f"https://github.com/{UPSTREAM}/pull/5", "number": 5,
        "head": {"label": f"{LOGIN}:taos-agent/fix-weather", "ref": "taos-agent/fix-weather"},
    }]
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as http:
        gh = _session(http, data_dir=None)
        pr = await gw.open_pr(gh, UPSTREAM, "fix-weather", "Fix", "body")
    assert pr == {"url": f"https://github.com/{UPSTREAM}/pull/5", "number": 5}
    assert fake.bodies("POST", f"/repos/{UPSTREAM}/pulls") == []


@pytest.mark.asyncio
async def test_other_users_taos_agent_prs_do_not_count(fake):
    fake.open_pulls = [{
        "html_url": f"https://github.com/{UPSTREAM}/pull/5", "number": 5,
        "head": {"label": "bob:taos-agent/older-fix", "ref": "taos-agent/older-fix"},
    }]
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as http:
        gh = _session(http, data_dir=None)
        pr = await gw.open_pr(gh, UPSTREAM, "fix-weather", "Fix", "body")
    assert pr["number"] == 9
