from siqe.updates.service import evaluate, parse_releases, parse_version

PAYLOAD = [
    {"tag_name": "v0.3.0-rc.1", "name": "0.3 RC", "body": "rc", "prerelease": True, "html_url": "u3"},
    {"tag_name": "v0.2.1", "name": "Hotfix", "body": "- Fixed tiling seams", "html_url": "u21"},
    {"tag_name": "v0.2.0", "name": "AI Lab", "body": "## New\n- Upscaling", "html_url": "u20"},
    {"tag_name": "v0.1.0", "name": "Foundation", "body": "First release", "html_url": "u10"},
    {"tag_name": "nightly", "name": "Not a version"},
    {"tag_name": "v9.9.9", "name": "Draft", "draft": True},
]


def test_parse_skips_drafts_and_non_versions_and_sorts_newest_first() -> None:
    releases = parse_releases(PAYLOAD)
    assert [r.version for r in releases] == ["0.3.0rc1", "0.2.1", "0.2.0", "0.1.0"]
    assert releases[0].prerelease is True


def test_newer_releases_exclude_prereleases_by_default() -> None:
    result = evaluate("0.1.0", parse_releases(PAYLOAD), include_prereleases=False)
    assert [r.version for r in result.newer] == ["0.2.1", "0.2.0"]
    assert result.latest is not None and result.latest.version == "0.2.1"
    assert result.current is not None and result.current.name == "Foundation"


def test_prereleases_included_when_enabled() -> None:
    result = evaluate("0.2.1", parse_releases(PAYLOAD), include_prereleases=True)
    assert [r.version for r in result.newer] == ["0.3.0rc1"]


def test_up_to_date() -> None:
    result = evaluate("v0.2.1", parse_releases(PAYLOAD), include_prereleases=False)
    assert result.newer == []


def test_unparsable_running_version_sees_every_release_as_newer() -> None:
    result = evaluate("dev", parse_releases(PAYLOAD), include_prereleases=False)
    assert len(result.newer) == 3


def test_parse_version_accepts_v_prefix() -> None:
    assert str(parse_version("v1.2.3")) == "1.2.3"
    assert parse_version("banana") is None
