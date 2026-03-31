# Finmint

Terminal-based personal finance tool. Pull bank transactions via [Teller API](https://teller.io), auto-categorize with AI, review interactively, and visualize spending -- all from your terminal.

## Features

- Fetch transactions from all connected bank accounts via Teller API (mTLS)
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

1. **Teller certificates**: Sign up at [teller.io](https://teller.io), download your mTLS certificate and private key.

2. **Claude API key**: Get an API key from [Anthropic](https://console.anthropic.com/).

3. **Configure**: Copy the example config and fill in your values:
   ```bash
   mkdir -p ~/.finmint
   cp config.example.yaml ~/.finmint/config.yaml
   # Edit ~/.finmint/config.yaml with your cert paths and settings
   ```

4. **Set your API key**:
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   ```

5. **Connect a bank account**:
   ```bash
   finmint accounts
   ```

## Usage

```bash
# Review and categorize this month's transactions
finmint 3-2026

# View spending breakdown with pie chart and AI summary
finmint view 3-2026

# View yearly overview with bar chart
finmint view 2026

# Manage category labels
finmint labels

# Manage connected bank accounts
finmint accounts

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
