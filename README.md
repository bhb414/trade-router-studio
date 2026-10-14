# Trade Router Studio

Trade Router Studio is a separate local web application built on top of
[Trade Router](../trade-router). Trade Router remains the broker gateway daemon;
Studio manages Python strategy source, process lifecycle, and logs.

## Responsibilities

| Component | Responsibility |
|---|---|
| Trade Router | Broker authentication, rate limits, market data, accounts, risk checks, idempotency, orders |
| Trade Router Studio | Web editor, strategy registration, source storage, process start/stop/restart, logs |
| Strategy process | User-authored `async def main(router)` code using the normalized SDK |

Strategy processes never receive broker App Keys or App Secrets. They receive a
strategy-bound SDK client and every order still passes through Trade Router's central
account/strategy arming, reconciliation, buying-power, and risk checks.

## Development install

```powershell
cd H:\Hyunbin\snacks\trade-router-studio
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install "..\trade-router\dist\trade_router-0.1.0-py3-none-any.whl"
.\.venv\Scripts\python -m pip install -e ".[dev]"
trade-studio start
```

`trade-studio start` starts Trade Router when needed, starts Studio in the background,
and opens a one-time authenticated browser URL. The default addresses are:

- Trade Router daemon: `http://127.0.0.1:8877`
- Trade Router Studio: `http://127.0.0.1:8890`

Commands:

```text
trade-studio start [--no-browser]
trade-studio open
trade-studio status
trade-studio stop
```

## Script contract

```python
import asyncio


async def main(router):
    while True:
        quote = await router.market.quote(code="005930", venue="INTEGRATED")
        print(quote.instrument.code, quote.last)
        await asyncio.sleep(30)
```

Each running strategy has a separate Python process. A non-zero exit is restarted with
backoff up to five times. The desired running state is stored in Studio SQLite, so a
previously running strategy resumes after Studio restarts. Trade Router still blocks new
orders until its account and unresolved-order reconciliation completes.

The script is ordinary Python running with the current Windows user's permissions. Run
only code you wrote or trust. Broker secrets remain inside Trade Router's DPAPI vault.
