# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Credential Handling

Finmint handles two types of credentials:

| Credential | Storage | Permissions |
|---|---|---|
| Copilot Money JWT | `~/.finmint/token` | `0600` (owner-read-only) |
| Claude API key | Environment variable (`ANTHROPIC_API_KEY`) | Not stored on disk by Finmint |

**Design principles:**

- Credentials are never logged, printed, or included in error messages
- Credentials are never passed as CLI arguments (to avoid shell history exposure)
- The `~/.finmint/` directory is created with `0700` permissions
- The token file is created with `0600` permissions
- The `.gitignore` excludes all sensitive file patterns (`.env`, `*.pem`, `.finmint/`)

## Data Storage

- All transaction and account data is stored locally in `~/.finmint/finmint.db` (SQLite)
- No data is transmitted to any third party except:
  - **Copilot Money API** -- to fetch your account and transaction data, and to write back category changes, notes, and review status using your JWT
  - **Anthropic API** -- to categorize transactions using AI (merchant names, amounts, and dates are sent; no account numbers, tokens, or other PII)

## Reporting a Vulnerability

If you discover a security vulnerability in Finmint, please report it responsibly:

1. **Do not open a public issue.**
2. Use [GitHub's private security advisory feature](https://github.com/jordanhilado/finmint/security/advisories/new) to report the vulnerability, or email the maintainer at jordanalihilado@gmail.com.
3. Include a description of the vulnerability, steps to reproduce, and potential impact.

We will acknowledge receipt within 48 hours and aim to release a fix promptly.

## Scope

Finmint is a local-only CLI tool. Its attack surface is limited to:

- Token file permissions on disk
- Data sent to external APIs (Copilot Money, Anthropic)
- Dependencies (Python packages listed in `pyproject.toml`)

This project does not run a web server, accept network connections, or process untrusted input beyond API responses.
