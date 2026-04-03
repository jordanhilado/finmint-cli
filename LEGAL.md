# Legal

## Not Financial Advice

Finmint is a personal productivity tool. **It is not financial advice, and should not be used as a substitute for professional financial guidance.** The AI-generated categorizations and spending summaries are automated best guesses and may be inaccurate. Do not make financial decisions based solely on Finmint's output. The authors and contributors are not financial advisors and accept no responsibility for decisions made using this tool.

## Unofficial API Usage

Finmint accesses Copilot Money's **internal, undocumented GraphQL API**. This API is not publicly documented, versioned, or supported by Copilot Money. By using Finmint, you acknowledge that:

- **You are responsible for complying with Copilot Money's Terms of Service.** Using this tool may violate those terms. Review Copilot Money's ToS before use.
- **This API can change or break at any time** without notice. The maintainers of Finmint have no control over the Copilot Money API and cannot guarantee continued functionality.
- **Finmint reads and writes your own data.** When you accept, re-categorize, or annotate a transaction in the review TUI, those changes are synced back to your Copilot Money account. Finmint never deletes data or accesses any account other than your own.
- **You provide your own authentication token.** Finmint does not automate login, bypass authentication, or access any account other than your own.

## Third-Party API Usage

Finmint sends transaction data (merchant names, amounts, and dates) to the Anthropic API for AI categorization. By using Finmint, you consent to this data being transmitted to Anthropic and processed according to [Anthropic's usage policies](https://www.anthropic.com/policies). You are responsible for any API usage charges incurred.

## Reverse Engineering and Interoperability

The API interactions in this project were developed through observation of network traffic from the author's own authenticated sessions, solely for the purpose of personal interoperability with the author's own data. This project is provided as-is for educational and personal-use purposes. The author makes no claim that this use is authorized by Copilot Money and assumes no liability for others' use of this code.

## No Warranty

This software is provided "as is", without warranty of any kind, express or implied. The authors and contributors are not responsible for any consequences of using this tool, including but not limited to:

- Account suspension or termination by Copilot Money
- Incorrect transaction categorizations or financial summaries
- Data loss or corruption
- Unintended modifications to your Copilot Money data via write-back sync
- Terms of service violations with any third-party service
- Financial losses of any kind

**You use this software entirely at your own risk.**

See the [MIT License](LICENSE) for the full legal text.

## Trademarks

"Copilot Money" is a trademark of Copilot IQ, Inc. "Claude" and "Anthropic" are trademarks of Anthropic, PBC. This project is not affiliated with either company. All trademarks are the property of their respective owners. Use of these names is for identification purposes only and does not imply endorsement.
