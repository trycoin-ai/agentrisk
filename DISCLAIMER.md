# Disclaimer

AgentRisk is open-source software that **mechanically evaluates user-defined rules
against user-supplied data.** Please read this before relying on it.

## Not advice, not a fiduciary

AgentRisk is **not investment advice**, not a fiduciary, not a broker, and not a
registered investment adviser. Nothing it outputs is a recommendation to buy, sell,
or hold any security or asset.

- A **PASS** verdict means a proposed trade did not violate the rules *you* wrote.
  It is **not** a statement that a trade is safe, suitable, prudent, or likely to be
  profitable.
- A **BLOCK** verdict is **not** a prediction of loss. It only means the trade
  violated one of your own rules.
- AgentRisk never generates, ranks, scores, or suggests trade ideas, and never
  executes trades.

## It cannot prevent trades

AgentRisk produces advisory data. **It cannot physically stop an order.** Whether a
trade is actually placed depends entirely on the integrating system honoring the
verdict. If your code does not gate execution on the result, no protection exists.

## It is only as good as its inputs

- Analyses and verdicts depend entirely on the accuracy and completeness of the
  portfolio data supplied to it. AgentRisk fetches no market data and verifies no
  prices.
- Classification data (sectors, themes, asset classes) is provided best-effort and
  may be incomplete, subjective, or out of date.

## Trading is risky

Trading, and especially automated or agent-driven trading, involves substantial risk,
including the risk of losing more than you invest (e.g. with margin or options).
**You are solely responsible** for your trades, your risk policy, your integration,
and your use of this software.

## No warranty

This software is provided **"as is"**, without warranty of any kind, express or
implied, under the [MIT License](LICENSE). In no event shall the authors or copyright
holders be liable for any claim, damages, or other liability arising from its use.
