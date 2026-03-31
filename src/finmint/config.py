"""Finmint configuration — load, validate, and initialize ~/.finmint/config.yaml."""

import os
import stat
import warnings
from pathlib import Path

import yaml


FINMINT_DIR_NAME = ".finmint"
CONFIG_FILE_NAME = "config.yaml"

REQUIRED_KEYS = {
    "teller": ["cert_path", "key_path", "environment", "application_id"],
    "claude": ["api_key_env"],
}

DEFAULT_CONFIG = {
    "teller": {
        "cert_path": "/path/to/certificate.pem",
        "key_path": "/path/to/private_key.pem",
        "environment": "sandbox",
        "application_id": "your_application_id",
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


def init_config(home: Path | None = None, *, prompts: dict | None = None) -> Path:
    """Create ~/.finmint/ directory and config.yaml with first-run prompts.

    If prompts dict is provided, uses those values instead of interactive input.
    Returns the path to the created config file.
    """
    finmint_dir = _finmint_dir(home)
    config_file = _config_path(home)

    # Create directory with restricted permissions
    finmint_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Ensure permissions even if directory already existed
    finmint_dir.chmod(0o700)

    if prompts is None:
        cert_path = input("Teller certificate path (.pem): ").strip()
        key_path = input("Teller private key path (.pem): ").strip()
        environment = input("Teller environment (sandbox/production) [sandbox]: ").strip() or "sandbox"
        application_id = input("Teller application ID: ").strip()
        api_key_env = input("Claude API key env var name [ANTHROPIC_API_KEY]: ").strip() or "ANTHROPIC_API_KEY"
    else:
        cert_path = prompts.get("cert_path", DEFAULT_CONFIG["teller"]["cert_path"])
        key_path = prompts.get("key_path", DEFAULT_CONFIG["teller"]["key_path"])
        environment = prompts.get("environment", DEFAULT_CONFIG["teller"]["environment"])
        application_id = prompts.get("application_id", DEFAULT_CONFIG["teller"]["application_id"])
        api_key_env = prompts.get("api_key_env", DEFAULT_CONFIG["claude"]["api_key_env"])

    config = {
        "teller": {
            "cert_path": cert_path,
            "key_path": key_path,
            "environment": environment,
            "application_id": application_id,
        },
        "claude": {
            "api_key_env": api_key_env,
        },
    }

    config_file.write_text(yaml.dump(config, default_flow_style=False))
    config_file.chmod(0o600)

    return config_file
