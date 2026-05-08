from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import Settings, parse_csv


def test_parse_csv_strips_and_omits_empty_values() -> None:
    assert parse_csv("auto-triage-ready, bug, , docs ") == [
        "auto-triage-ready",
        "bug",
        "docs",
    ]


def test_settings_parses_comma_separated_env_values() -> None:
    settings = Settings(
        GITHUB_REPOSITORIES="owner/repo, other/project",
        GITHUB_ISSUE_TAGS_TO_WORK_ON="auto-triage-ready,bug",
    )

    assert settings.github_repositories == ["owner/repo", "other/project"]
    assert settings.github_issue_tags_to_work_on == ["auto-triage-ready", "bug"]
    assert settings.github_issue_fixed_tag == "auto-triage-fixed"


def test_settings_rejects_invalid_repository_names() -> None:
    with pytest.raises(ValidationError):
        Settings(GITHUB_REPOSITORIES="not-a-repo")

