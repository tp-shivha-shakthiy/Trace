"""Tests for GitHub normalizer / event type mapping."""

from app.normalizers import (
    normalize_event,
    normalize_event_type,
    normalize_repo,
    normalize_user,
    parse_iso,
)

FAKE_USER = {
    "id": 123,
    "login": "test",
    "name": "Test User",
    "avatar_url": "https://example.com/a",
    "html_url": "https://example.com/u",
    "company": "TestCo",
    "location": "Earth",
    "bio": "Tester",
    "followers": 10,
    "following": 5,
    "public_repos": 8,
}

FAKE_REPO = {
    "id": 501,
    "name": "demo",
    "full_name": "test/demo",
    "description": "A demo",
    "html_url": "https://example.com/test/demo",
    "homepage": "https://example.com",
    "default_branch": "main",
    "language": "Go",
    "topics": ["api", "backend"],
    "fork": False,
    "stargazers_count": 3,
    "forks_count": 1,
    "open_issues_count": 2,
    "watchers_count": 3,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2026-06-01T00:00:00Z",
    "pushed_at": "2026-08-01T00:00:00Z",
}

def _event(eid, etype, day, payload, repo="test/demo"):
    return {
        "id": eid,
        "type": etype,
        "created_at": f"2026-08-0{day}T12:00:00Z",
        "repo": {"name": repo},
        "payload": payload,
    }


FAKE_EVENTS = [
    _event("1", "PushEvent", 1, {"ref": "refs/heads/main"}),
    _event("2", "PullRequestEvent", 2, {"pull_request": {"number": 10}}),
    _event("3", "IssuesEvent", 3, {"issue": {"number": 5}}),
    _event("4", "ReleaseEvent", 4, {"release": {"tag_name": "v1.0.0"}}),
    _event("5", "CreateEvent", 5, {"ref_type": "repository", "ref": "demo"}),
    _event("6", "WatchEvent", 6, {}),
    _event("7", "ForkEvent", 7, {}),
]


def test_normalize_event_types():
    assert normalize_event_type("PushEvent") == "commit"
    assert normalize_event_type("CreateEvent") == "repository_created"
    assert normalize_event_type("PullRequestEvent") == "pull_request"
    assert normalize_event_type("IssuesEvent") == "issue"
    assert normalize_event_type("ReleaseEvent") == "release_created"
    assert normalize_event_type("WatchEvent") == "repo_watched"
    assert normalize_event_type("ForkEvent") == "repo_forked"


def test_parse_iso():
    dt = parse_iso("2024-01-15T10:30:00Z")
    assert dt is not None
    assert dt.year == 2024
    assert dt.tzinfo is not None
    assert parse_iso("") is None
    assert parse_iso(None) is None


def test_normalize_user_fields():
    user = normalize_user(FAKE_USER)
    assert user.github_id == 123
    assert user.username == "test"
    assert user.public_repos == 8


def test_normalize_repo_fields():
    repo = normalize_repo(FAKE_REPO)
    assert repo.github_id == 501
    assert repo.language == "Go"
    assert repo.topics == ["api", "backend"]
    assert repo.is_fork is False
    assert repo.stargazers_count == 3


def test_normalize_event_push():
    event = normalize_event(FAKE_EVENTS[0])
    assert event.event_type == "commit"
    assert event.github_event_id == "1"
    assert event.resource_id == "refs/heads/main"


def test_normalize_event_pull_request():
    event = normalize_event(FAKE_EVENTS[1])
    assert event.event_type == "pull_request"
    assert event.resource_id == "pr/10"


def test_normalize_event_issue():
    event = normalize_event(FAKE_EVENTS[2])
    assert event.event_type == "issue"
    assert event.resource_id == "issue/5"


def test_normalize_event_release():
    event = normalize_event(FAKE_EVENTS[3])
    assert event.event_type == "release_created"
    assert event.resource_id == "v1.0.0"


def test_normalize_event_create():
    event = normalize_event(FAKE_EVENTS[4])
    assert event.event_type == "repository_created"
    assert event.resource_id == "repository/demo"


def test_unknown_event_type_slugged():
    event = normalize_event(FAKE_EVENTS[5])
    assert event.event_type == "repo_watched"


def test_normalize_repo_topics_list():
    repo = normalize_repo({**FAKE_REPO, "topics": "not a list"})
    assert repo.topics == []