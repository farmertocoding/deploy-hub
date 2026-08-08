"""SEC-B10-SSRF-GUARD — the git URL is the Hub's first untrusted input.

Table-driven so adding a bypass someone thinks of later is one line, not a new test.
Resolution is stubbed in the DNS cases: the point under test is the decision made about
an address, not whether the network is up in CI.
"""
import socket

import pytest
from django.core.exceptions import ValidationError

from core import validators
from core.validators import validate_git_url

REJECTED = [
    # (url, expected error code, why this case exists)
    ("http://github.com/o/r.git", "bad_scheme", "plaintext http is tamperable"),
    ("git://github.com/o/r.git", "bad_scheme", "git:// is unauthenticated"),
    ("file:///etc/passwd", "bad_scheme", "local file read"),
    ("ftp://github.com/o/r.git", "bad_scheme", "not a git transport"),
    ("https://user:token@github.com/o/r.git", "embedded_credentials",
     "a token in a URL leaks into audit rows and logs"),
    ("https://token@github.com/o/r.git", "embedded_credentials",
     "bare userinfo over https is a token holder, not a login"),
    ("ssh://git:secret@github.com/o/r.git", "embedded_credentials",
     "a password is never acceptable, even over ssh"),
    ("https://127.0.0.1/o/r.git", "blocked_address", "loopback"),
    ("https://[::1]/o/r.git", "blocked_address", "IPv6 loopback"),
    ("https://10.0.0.5/o/r.git", "blocked_address", "RFC1918"),
    ("https://192.168.1.1/o/r.git", "blocked_address", "RFC1918"),
    ("https://172.16.0.1/o/r.git", "blocked_address", "RFC1918"),
    ("https://169.254.169.254/latest/meta-data/", "blocked_address",
     "cloud metadata endpoint — the highest-value SSRF target"),
    ("https://100.64.0.1/o/r.git", "blocked_address", "carrier-grade NAT"),
    ("https://[fc00::1]/o/r.git", "blocked_address", "IPv6 unique-local"),
    ("https://0.0.0.0/o/r.git", "blocked_address", "unspecified"),
    ("https://localhost/o/r.git", "blocked_host", "loopback by name"),
    ("https://buildbox.local/o/r.git", "blocked_host", "mDNS name"),
    ("https://gitlab.internal/o/r.git", "blocked_host", "private suffix"),
    ("https://github.com:8080/o/r.git", "bad_port", "non-standard port"),
    ("git@github.com:o/r.git", "scp_syntax", "ambiguous scp syntax"),
    ("github.com/o/r.git", "no_scheme", "scheme-less"),
    ("https://github.com", "no_path", "no repository path"),
    ("https://github.com/o/r.git\nrm -rf /", "control_chars",
     "newline turns one argument into two"),
    ("", "required", "empty"),
    ("   ", "required", "whitespace only"),
    ("https://github.com/" + "a" * 3000, "too_long", "unbounded input"),
]

ACCEPTED = [
    "https://github.com/org/repo.git",
    "https://github.com/org/repo",
    "https://gitlab.com:443/org/sub/repo.git",
    "ssh://git@github.com/org/repo.git",
    "ssh://git@github.com:22/org/repo.git",
    "git+ssh://git@github.com/org/repo.git",
]


@pytest.mark.req("SEC-B10-SSRF-GUARD")
@pytest.mark.parametrize("url,code,why", REJECTED, ids=[r[0][:40] for r in REJECTED])
def test_rejected(url, code, why):
    with pytest.raises(ValidationError) as exc:
        validate_git_url(url, resolve=False)
    assert exc.value.code == code, f"{why}: got {exc.value.code!r}, want {code!r}"


@pytest.mark.req("SEC-B10-SSRF-GUARD")
@pytest.mark.parametrize("url", ACCEPTED)
def test_accepted(url):
    assert validate_git_url(url, resolve=False) == url


@pytest.mark.req("SEC-B10-SSRF-GUARD")
def test_ssh_login_user_is_not_a_credential():
    """Regression (build finding, 2026-08-09): the first version rejected all
    userinfo, which banned ssh://git@host — the standard form for every SSH remote
    on GitHub, GitLab and Bitbucket. Scheme-aware since."""
    for url in ("ssh://git@github.com/o/r.git", "ssh://deploy@example.com/o/r.git"):
        assert validate_git_url(url, resolve=False) == url


@pytest.mark.req("SEC-B10-SSRF-GUARD")
def test_public_name_resolving_to_private_ip_is_rejected(monkeypatch):
    """The DNS attack: a public name whose A record points inside the network."""
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **kw: [(2, 1, 6, "", ("10.1.2.3", 0))],
    )
    with pytest.raises(ValidationError) as exc:
        validate_git_url("https://evil.example.com/o/r.git")
    assert exc.value.code == "blocked_address"


@pytest.mark.req("SEC-B10-SSRF-GUARD")
def test_any_private_address_rejects_not_all(monkeypatch):
    """One public + one private address is a deliberate attack shape. Checking 'all
    addresses are private' instead of 'any address is private' would pass this."""
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **kw: [
            (2, 1, 6, "", ("140.82.121.4", 0)),
            (2, 1, 6, "", ("169.254.169.254", 0)),
        ],
    )
    with pytest.raises(ValidationError) as exc:
        validate_git_url("https://mixed.example.com/o/r.git")
    assert exc.value.code == "blocked_address"


@pytest.mark.req("SEC-B10-SSRF-GUARD")
def test_public_name_resolving_to_public_ip_is_accepted(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **kw: [(2, 1, 6, "", ("140.82.121.4", 0))],
    )
    url = "https://github.com/org/repo.git"
    assert validate_git_url(url) == url


@pytest.mark.req("SEC-B10-SSRF-GUARD")
def test_unresolvable_host_is_rejected(monkeypatch):
    def boom(*a, **kw):
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(ValidationError) as exc:
        validate_git_url("https://nx.example.com/o/r.git")
    assert exc.value.code == "unresolvable"


@pytest.mark.req("SEC-B10-SSRF-GUARD")
def test_known_limit_is_documented_not_silent():
    """D-007: submit-time validation cannot survive DNS rebinding. The mitigation is
    structural (the Hub never clones). If someone deletes that note, this fails —
    a silent known-limit is how a second layer quietly stops being built."""
    doc = validators.validate_git_url.__doc__
    assert "rebinding" in doc.lower()
    assert "D-007" in doc
