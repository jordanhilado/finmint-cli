"""Finmint configuration — load, validate, and initialize ~/.finmint/config.yaml."""

import os
import stat
import warnings
from pathlib import Path

import yaml


FINMINT_DIR_NAME = ".finmint"
CONFIG_FILE_NAME = "config.yaml"

REQUIRED_KEYS = {
    "copilot": ["token"],
    "claude": ["api_key_env"],
}

DEFAULT_CONFIG = {
    "copilot": {
        "token": "",
    },
    "claude": {
        "api_key_env": "ANTHROPIC_API_KEY",
    },
}


def _finmint_dir(home: Path | None = None) -> Path:
    """Return the path to the ~/.finmint/ directory."""
    base = home or Path.home()
    return base / FINMINT_DIR_NAME


def _config_path(home: Path | None = None) -> Path:
    """Return the path to ~/.finmint/config.yaml."""
    return _finmint_dir(home) / CONFIG_FILE_NAME


def check_permissions(home: Path | None = None) -> None:
    """Warn if ~/.finmint/ directory is world-readable."""
    finmint_dir = _finmint_dir(home)
    if not finmint_dir.exists():
        return
    mode = finmint_dir.stat().st_mode
    if mode & stat.S_IROTH:
        warnings.warn(
            f"{finmint_dir} is world-readable (mode {oct(mode)}). "
            f"Run: chmod 700 {finmint_dir}",
            stacklevel=2,
        )


def load_config(home: Path | None = None) -> dict:
    """Read ~/.finmint/config.yaml and return it as a dict.

    Raises FileNotFoundError with setup instructions if the file is missing.
    Raises ValueError if the YAML is invalid.
    """
    config_file = _config_path(home)
    if not config_file.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_file}\n"
            f"Run 'finmint init' or create it manually.\n"
            f"See config.example.yaml for the expected format."
        )
    text = config_file.read_text()
    try:
        config = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {config_file}: {exc}") from exc
    if config is None:
        raise ValueError(f"Config file is empty: {config_file}")
    return config


def validate_config(config: dict) -> list[str]:
    """Check required keys exist. Returns a list of error messages (empty if valid).

    Also warns if a raw API key (starts with 'sk-') was placed directly in config
    instead of an environment variable name.
    """
    errors = []
    for section, keys in REQUIRED_KEYS.items():
        if section not in config:
            errors.append(f"Missing required section: '{section}'")
            continue
        if not isinstance(config[section], dict):
            errors.append(f"Section '{section}' must be a mapping, got {type(config[section]).__name__}")
            continue
        for key in keys:
            if key not in config[section]:
                errors.append(f"Missing required key: '{section}.{key}'")

    # Warn if copilot token is empty or a placeholder
    copilot_section = config.get("copilot", {})
    if isinstance(copilot_section, dict):
        token = copilot_section.get("token", "")
        if not token or not token.strip():
            errors.append(
                "copilot.token is empty. Run 'finmint token' to set your Copilot Money JWT."
            )

    # Warn if someone put a raw API key instead of an env var name
    claude_section = config.get("claude", {})
    if isinstance(claude_section, dict):
        api_key_env = claude_section.get("api_key_env", "")
        if isinstance(api_key_env, str) and api_key_env.startswith("sk-"):
            warnings.warn(
                "It looks like you put a raw API key in 'claude.api_key_env'. "
                "This field should contain the NAME of an environment variable "
                "(e.g., 'ANTHROPIC_API_KEY'), not the key itself. "
                "Store the key in an env var for security.",
                stacklevel=2,
            )

    if errors:
        raise ValueError(
            "Config validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return errors


def resolve_api_key(config: dict) -> str:
    """Read the Claude API key from the environment variable named in config.

    Raises RuntimeError if the environment variable is not set or empty.
    """
    env_var_name = config["claude"]["api_key_env"]
    api_key = os.environ.get(env_var_name)
    if not api_key:
        raise RuntimeError(
            f"Environment variable '{env_var_name}' is not set or empty.\n"
            f"Set it before running finmint:\n"
            f"  export {env_var_name}=sk-ant-..."
        )
    return api_key


def init_config(home: Path | None = None) -> Path:
    """Create ~/.finmint/ directory and config.yaml with default values.
    Returns the path to the created config file.
    """
    finmint_dir = _finmint_dir(home)
    config_file = _config_path(home)
    finmint_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    finmint_dir.chmod(0o700)
    config_file.write_text(yaml.dump(DEFAULT_CONFIG, default_flow_style=False))
    config_file.chmod(0o600)
    return config_file


def save_token(token: str, home: Path | None = None) -> Path:
    """Save a Copilot Money JWT to config.yaml (read-modify-write).
    Creates config file with defaults if it doesn't exist.
    Returns the path to the config file.
    """
    config_file = _config_path(home)
    if config_file.exists():
        config = yaml.safe_load(config_file.read_text()) or {}
    else:
        finmint_dir = _finmint_dir(home)
        finmint_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        finmint_dir.chmod(0o700)
        config = dict(DEFAULT_CONFIG)

    if "copilot" not in config:
        config["copilot"] = {}
    config["copilot"]["token"] = token

    config_file.write_text(yaml.dump(config, default_flow_style=False))
    config_file.chmod(0o600)
    return config_file


def get_token(config: dict) -> str:
    """Read the Copilot Money JWT from config.
    Raises RuntimeError if the token is not set or empty.
    """
    token = config.get("copilot", {}).get("token", "")
    if not token or not token.strip():
        raise RuntimeError(
            "Copilot Money token is not set.\n"
            "Run 'finmint token' to paste your JWT from the Copilot Money web app."
        )
    return token
