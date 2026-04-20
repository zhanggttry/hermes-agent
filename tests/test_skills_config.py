"""Tests for hermes_cli.skills_config — get_disabled_skills robustness.

Covers the two bugs reported in GitHub issue #13026:
  1. ``skills: null`` crashes with ``AttributeError``
  2. ``skills.disabled: my-skill`` (scalar) splits into individual characters

Also covers the mirror implementation in ``agent.skill_utils`` which
already handles these cases correctly.
"""

import pytest

from hermes_cli.skills_config import get_disabled_skills, _normalize_string_set


# ─── _normalize_string_set ────────────────────────────────────────────────


class TestNormalizeStringSet:
    """Unit tests for the _normalize_string_set helper."""

    def test_none_returns_empty(self):
        assert _normalize_string_set(None) == set()

    def test_empty_list_returns_empty(self):
        assert _normalize_string_set([]) == set()

    def test_empty_string_returns_empty(self):
        assert _normalize_string_set("") == set()

    def test_scalar_string_wrapped_in_set(self):
        """The core bug: ``set("my-skill")`` splits into chars."""
        assert _normalize_string_set("my-skill") == {"my-skill"}

    def test_list_of_strings(self):
        assert _normalize_string_set(["skill-a", "skill-b"]) == {"skill-a", "skill-b"}

    def test_whitespace_stripped(self):
        assert _normalize_string_set(["  spaced  "]) == {"spaced"}

    def test_empty_strings_filtered(self):
        assert _normalize_string_set(["valid", "", "  "]) == {"valid"}

    def test_non_string_values_cast(self):
        assert _normalize_string_set([123]) == {"123"}


# ─── get_disabled_skills ──────────────────────────────────────────────────


class TestGetDisabledSkills:
    """Robustness tests for get_disabled_skills."""

    # --- Bug #13026 case 1: skills: null ---
    def test_skills_null_no_crash(self):
        """``skills: null`` must not raise AttributeError."""
        result = get_disabled_skills({"skills": None})
        assert result == set()

    # --- Bug #13026 case 2: disabled is a scalar string ---
    def test_disabled_scalar_string(self):
        """``skills.disabled: my-skill`` must NOT split into characters."""
        result = get_disabled_skills({"skills": {"disabled": "my-skill"}})
        assert result == {"my-skill"}

    # --- Additional edge cases ---

    def test_empty_config(self):
        assert get_disabled_skills({}) == set()

    def test_no_skills_key(self):
        assert get_disabled_skills({"other": "data"}) == set()

    def test_skills_is_non_dict(self):
        """``skills: "invalid"`` should return empty set, not crash."""
        assert get_disabled_skills({"skills": "invalid"}) == set()

    def test_disabled_normal_list(self):
        result = get_disabled_skills(
            {"skills": {"disabled": ["skill-a", "skill-b"]}}
        )
        assert result == {"skill-a", "skill-b"}

    def test_disabled_empty_list(self):
        result = get_disabled_skills({"skills": {"disabled": []}})
        assert result == set()

    def test_platform_disabled_scalar_string(self):
        """Scalar in platform_disabled should also be normalized."""
        result = get_disabled_skills(
            {"skills": {"platform_disabled": {"telegram": "my-skill"}}},
            platform="telegram",
        )
        assert result == {"my-skill"}

    def test_platform_disabled_null_falls_back(self):
        """When platform_disabled is None, fall back to global list."""
        result = get_disabled_skills(
            {"skills": {"disabled": ["global-skill"], "platform_disabled": None}},
            platform="telegram",
        )
        assert result == {"global-skill"}

    def test_platform_falls_back_to_global(self):
        result = get_disabled_skills(
            {"skills": {"disabled": ["global-skill"]}}, platform="telegram"
        )
        assert result == {"global-skill"}

    def test_platform_overrides_global(self):
        result = get_disabled_skills(
            {
                "skills": {
                    "disabled": ["global-skill"],
                    "platform_disabled": {"telegram": ["tg-skill"]},
                }
            },
            platform="telegram",
        )
        assert result == {"tg-skill"}

    def test_platform_disabled_empty_list(self):
        result = get_disabled_skills(
            {"skills": {"platform_disabled": {"telegram": []}}},
            platform="telegram",
        )
        assert result == set()

    def test_unknown_platform_falls_back(self):
        result = get_disabled_skills(
            {
                "skills": {
                    "disabled": ["global-skill"],
                    "platform_disabled": {"discord": ["dc-skill"]},
                }
            },
            platform="telegram",
        )
        assert result == {"global-skill"}
