"""Tests for finmint.config module."""

import os
import stat
import warnings

import pytest
import yaml

from finmint.config import (
    check_permissions,
    get_token,
    init_config,
    load_config,
    resolve_api_key,
    save_token,
    validate_config,
)


VALID_CONFIG = {
    "claude": {
        "api_key_env": "ANTHROPIC_API_KEY",
    },
}


def _write_config(home: "Path", config: dict) -> "Path":
    """Helper to write a config.yaml inside a fake home directory."""
    from pathlib import Path

    finmint_dir = home / ".finmint"
    finmint_dir.mkdir(mode=0o700, exist_ok=True)
    config_file = finmint_dir / "config.yaml"
    config_file.write_text(yaml.dump(config, default_flow_style=False))
    return config_file


# --- load_config ---


class TestLoadConfig:
    def test_loads_valid_yaml(self, tmp_path):
        _write_config(tmp_path, VALID_CONFIG)
        result = load_config(home=tmp_path)
        assert result == VALID_CONFIG
        assert result["claude"]["api_key_env"] == "ANTHROPIC_API_KEY"

    def test_missing_file_raises_with_instructions(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(home=tmp_path)

    def test_missing_file_error_mentions_init(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="finmint init"):
            load_config(home=tmp_path)

    def test_invalid_yaml_raises_value_error(self, tmp_path):
        finmint_dir = tmp_path / ".finmint"
        finmint_dir.mkdir(mode=0o700)
        config_file = finmint_dir / "config.yaml"
        config_file.write_text(":\n  bad:\n    - [unmatched")
        with pytest.raises(ValueError, match="Invalid YAML"):
            load_config(home=tmp_path)

    def test_empty_file_raises_value_error(self, tmp_path):
        finmint_dir = tmp_path / ".finmint"
        finmint_dir.mkdir(mode=0o700)
        config_file = finmint_dir / "config.yaml"
        config_file.write_text("")
        with pytest.raises(ValueError, match="empty"):
            load_config(home=tmp_path)


# --- validate_config ---


class TestValidateConfig:
    def test_valid_config_passes(self):
        # Should not raise
        validate_config(VALID_CONFIG)

    def test_missing_claude_section_raises(self):
        config = {}
        with pytest.raises(ValueError, match="Missing required section: 'claude'"):
            validate_config(config)

    def test_raw_api_key_warns(self):
        config = {
            "claude": {"api_key_env": "sk-ant-api03-secret"},
        }
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_config(config)
            assert len(w) == 1
            assert "raw API key" in str(w[0].message)
            assert "environment variable" in str(w[0].message)

    def test_section_not_a_dict_raises(self):
        config = {"claude": "not_a_dict"}
        with pytest.raises(ValueError, match="must be a mapping"):
            validate_config(config)


# --- resolve_api_key ---


class TestResolveApiKey:
    def test_resolves_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        result = resolve_api_key(VALID_CONFIG)
        assert result == "sk-ant-test-key"

    def test_missing_env_var_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="not set or empty"):
            resolve_api_key(VALID_CONFIG)

    def test_empty_env_var_raises(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        with pytest.raises(RuntimeError, match="not set or empty"):
            resolve_api_key(VALID_CONFIG)

    def test_custom_env_var_name(self, monkeypatch):
        config = {"claude": {"api_key_env": "MY_CUSTOM_KEY"}}
        monkeypatch.setenv("MY_CUSTOM_KEY", "sk-custom-key")
        result = resolve_api_key(config)
        assert result == "sk-custom-key"


# --- init_config ---


class TestInitConfig:
    def test_creates_directory_and_config(self, tmp_path):
        config_file = init_config(home=tmp_path)
        assert config_file.exists()
        config = yaml.safe_load(config_file.read_text())
        assert config["claude"]["api_key_env"] == "ANTHROPIC_API_KEY"

    def test_directory_has_mode_0700(self, tmp_path):
        init_config(home=tmp_path)
        finmint_dir = tmp_path / ".finmint"
        dir_mode = finmint_dir.stat().st_mode & 0o777
        assert dir_mode == 0o700

    def test_config_file_has_mode_0600(self, tmp_path):
        config_file = init_config(home=tmp_path)
        file_mode = config_file.stat().st_mode & 0o777
        assert file_mode == 0o600

    def test_idempotent_on_existing_directory(self, tmp_path):
        init_config(home=tmp_path)
        # Run again -- should not error
        config_file = init_config(home=tmp_path)
        assert config_file.exists()


# --- save_token ---


class TestSaveToken:
    def test_writes_token_to_file(self, tmp_path):
        token_file = save_token("my-jwt-token", home=tmp_path)
        assert token_file.exists()
        assert token_file.read_text().strip() == "my-jwt-token"

    def test_creates_directory_if_not_exists(self, tmp_path):
        token_file = save_token("new-jwt-token", home=tmp_path)
        assert token_file.parent.exists()
        assert token_file.read_text().strip() == "new-jwt-token"

    def test_file_has_mode_0600(self, tmp_path):
        token_file = save_token("my-jwt-token", home=tmp_path)
        file_mode = token_file.stat().st_mode & 0o777
        assert file_mode == 0o600

    def test_overwrites_existing_token(self, tmp_path):
        save_token("old-token", home=tmp_path)
        save_token("updated-token", home=tmp_path)
        token_file = tmp_path / ".finmint" / "token"
        assert token_file.read_text().strip() == "updated-token"


# --- get_token ---


class TestGetToken:
    def test_reads_token_from_file(self, tmp_path):
        save_token("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test", home=tmp_path)
        result = get_token(home=tmp_path)
        assert result == "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"

    def test_strips_bearer_prefix(self, tmp_path):
        save_token("Bearer my-jwt-token", home=tmp_path)
        result = get_token(home=tmp_path)
        assert result == "my-jwt-token"

    def test_raises_when_file_missing(self, tmp_path):
        with pytest.raises(RuntimeError, match="token file not found"):
            get_token(home=tmp_path)

    def test_raises_when_file_empty(self, tmp_path):
        save_token("", home=tmp_path)
        with pytest.raises(RuntimeError, match="token file is empty"):
            get_token(home=tmp_path)


# --- check_permissions ---


class TestCheckPermissions:
    def test_no_warning_when_dir_not_exists(self, tmp_path):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            check_permissions(home=tmp_path)
            assert len(w) == 0

    def test_no_warning_when_permissions_correct(self, tmp_path):
        finmint_dir = tmp_path / ".finmint"
        finmint_dir.mkdir(mode=0o700)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            check_permissions(home=tmp_path)
            assert len(w) == 0

    def test_warns_when_world_readable(self, tmp_path):
        finmint_dir = tmp_path / ".finmint"
        finmint_dir.mkdir(mode=0o755)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            check_permissions(home=tmp_path)
            assert len(w) == 1
            assert "world-readable" in str(w[0].message)
            assert "chmod 700" in str(w[0].message)
