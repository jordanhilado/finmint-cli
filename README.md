# Finmint

Terminal-based personal finance tool. Pull bank transactions from [Copilot Money](https://copilot.money), auto-categorize with AI, review interactively, and visualize spending -- all from your terminal.

## Features

- Fetch transactions from all connected bank accounts via Copilot Money
- AI-powered auto-categorization via Claude API, with local merchant rules that learn from your corrections
- Interactive TUI for reviewing and categorizing transactions
- Pie charts (monthly) and bar charts (yearly) for spending visualization
- AI-generated narrative summaries of your spending patterns
- Manage labels, accounts, and merchant rules from the terminal

## Install

```bash
pip install -e .
```

## Setup

1. **Copilot Money account**: Sign up at [copilot.money](https://copilot.money) and connect your bank accounts.

2. **Claude API key**: Get an API key from [Anthropic](https://console.anthropic.com/).

3. **Set your API key**:
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   ```

4. **Set your Copilot Money token**:
   ```bash
   finmint token
   ```
   This prompts you to paste a JWT from the Copilot Money web app (browser dev tools → Network tab → Authorization header). Tokens last ~1 hour.

5. **Sync and review**:
   ```bash
   finmint 3-2026
   ```

## Usage

```bash
# Review and categorize this month's transactions
finmint 3-2026

# View spending breakdown with pie chart and AI summary
finmint view 3-2026

# View yearly overview with bar chart
finmint view 2026

# Set or refresh your Copilot Money token
finmint token

# View connected bank accounts
finmint accounts

# Manage category labels
finmint labels

# Manage merchant categorization rules
finmint rules
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
