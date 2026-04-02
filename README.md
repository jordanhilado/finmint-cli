# Finmint

Terminal-based personal finance tool. Pull bank transactions from [Copilot Money](https://copilot.money), auto-categorize with AI, review interactively, and visualize spending -- all from your terminal.

> **Disclaimer:** This project is **not affiliated with, endorsed by, or associated with Copilot Money (Copilot IQ, Inc.) or Anthropic, PBC** in any way. It uses a reverse-engineered, unofficial API that may break at any time. **This tool is not financial advice.** Use at your own risk. See [Legal](#legal) for full details.

## Features

- Fetch transactions from all connected bank accounts via Copilot Money
- AI-powered auto-categorization via Claude API, with local merchant rules that learn from your corrections
- Interactive TUI for reviewing and categorizing transactions
- Custom notes on individual transactions
- Color-coded category labels with customizable colors
- Sortable transaction tables (by any column, ascending or descending)
- Pie charts (monthly) and bar charts (yearly) for spending visualization
- AI-generated narrative summaries of your spending patterns
- Manage labels, accounts, and merchant rules from the terminal

## Install

```bash
pip install -e .
```

## Setup

1. **Copilot Money account**: Sign up at [copilot.money](https://copilot.money) and connect your bank accounts.

2. **Claude API key**: Get an API key from [Anthropic](https://console.anthropic.com/). This is a paid API -- you are responsible for any charges incurred.

3. **Set your API key**:
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   ```

4. **Set your Copilot Money token**:
   ```bash
   finmint token
   ```
   This prompts you to paste a JWT from the Copilot Money web app (browser dev tools -> Network tab -> Authorization header). Tokens expire periodically and will need to be refreshed.

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

### Review TUI Keybindings

| Key | Action |
|-----|--------|
| `a` | Accept transaction's current category |
| `c` | Change category |
| `e` | Exempt transaction from review |
| `n` | Add/edit a note on the transaction |
| `s` | Sort by column (opens picker) |
| `Space` | Toggle selection for bulk operations |
| `b` | Bulk accept all selected transactions |
| `t` | Toggle between table and one-by-one view |
| `q` | Quit |

Click any column header to sort by that column. Click again to reverse. Click a third time to clear the sort.

## Security

All credentials are stored locally on your machine. Finmint never transmits your data to any server other than the Copilot Money API (to fetch your transactions) and the Anthropic API (for AI categorization).

- **Copilot Money JWT** is stored in `~/.finmint/token` with `0600` permissions (owner-read-only)
- **Claude API key** is read from an environment variable (`ANTHROPIC_API_KEY` by default) -- never stored on disk
- **Transaction data** is stored in a local SQLite database at `~/.finmint/finmint.db`
- **No data leaves your machine** except API calls to Copilot Money (read and write-back) and Anthropic (categorization)
- **Data sent to Anthropic** includes merchant names, amounts, and dates for categorization -- no account numbers, tokens, or other PII

See [SECURITY.md](SECURITY.md) for the full security policy, including how to report vulnerabilities.

## Legal

### Not Financial Advice

Finmint is a personal productivity tool. **It is not financial advice, and should not be used as a substitute for professional financial guidance.** The AI-generated categorizations and spending summaries are automated best guesses and may be inaccurate. Do not make financial decisions based solely on Finmint's output. The authors and contributors are not financial advisors and accept no responsibility for decisions made using this tool.

### Unofficial API Usage

Finmint accesses Copilot Money's **internal, undocumented GraphQL API**. This API is not publicly documented, versioned, or supported by Copilot Money. By using Finmint, you acknowledge that:

- **You are responsible for complying with Copilot Money's Terms of Service.** Using this tool may violate those terms. Review Copilot Money's ToS before use.
- **This API can change or break at any time** without notice. The maintainers of Finmint have no control over the Copilot Money API and cannot guarantee continued functionality.
- **Finmint reads and writes your own data.** When you accept, re-categorize, or annotate a transaction in the review TUI, those changes are synced back to your Copilot Money account. Finmint never deletes data or accesses any account other than your own.
- **You provide your own authentication token.** Finmint does not automate login, bypass authentication, or access any account other than your own.

### Third-Party API Usage

Finmint sends transaction data (merchant names, amounts, and dates) to the Anthropic API for AI categorization. By using Finmint, you consent to this data being transmitted to Anthropic and processed according to [Anthropic's usage policies](https://www.anthropic.com/policies). You are responsible for any API usage charges incurred.

### Reverse Engineering and Interoperability

The API interactions in this project were developed through observation of network traffic from the author's own authenticated sessions, solely for the purpose of personal interoperability with the author's own data. This project is provided as-is for educational and personal-use purposes. The author makes no claim that this use is authorized by Copilot Money and assumes no liability for others' use of this code.

### No Warranty

This software is provided "as is", without warranty of any kind, express or implied. The authors and contributors are not responsible for any consequences of using this tool, including but not limited to:

- Account suspension or termination by Copilot Money
- Incorrect transaction categorizations or financial summaries
- Data loss or corruption
- Unintended modifications to your Copilot Money data via write-back sync
- Terms of service violations with any third-party service
- Financial losses of any kind

**You use this software entirely at your own risk.**

See the [MIT License](LICENSE) for the full legal text.

### Trademarks

"Copilot Money" is a trademark of Copilot IQ, Inc. "Claude" and "Anthropic" are trademarks of Anthropic, PBC. This project is not affiliated with either company. All trademarks are the property of their respective owners. Use of these names is for identification purposes only and does not imply endorsement.

## License

[MIT](LICENSE)
