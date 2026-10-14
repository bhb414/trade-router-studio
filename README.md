# Trade Router Studio

Trade Router Studio is a separate local web application built on top of
[Trade Router](https://github.com/bhb414/trade-router). Trade Router remains the broker gateway daemon;
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

The authenticated browser session remains valid for 30 days and survives Studio
restarts. Run `trade-studio open` again after that period or after rotating the local
installation token.

Commands:

```text
trade-studio start [--no-browser]
trade-studio open
trade-studio status
trade-studio stop
```

The VBS and CMD launchers are development helpers. End users should run the packaged
`TradeRouterStudio.exe`. It keeps one console window open; closing that window or
pressing Ctrl+C stops Studio and the central Router. Router, Studio, and strategy child
processes do not open additional consoles. The dashboard's **종료** button performs the
same ordered shutdown.

## Windows distribution and updates

Build a release ZIP from the Studio checkout and the sibling Router checkout:

```powershell
.\scripts\build-release.ps1
```

The command creates the following files under `release`:

- `TradeRouterStudio-windows-x64.zip`
- `TradeRouterStudio-windows-x64.zip.sha256`

GitHub Actions runs the same build for a `v*` tag and publishes both files to
[Studio Releases](https://github.com/bhb414/trade-router-studio/releases). A recipient
extracts the ZIP once and runs `TradeRouterStudio.exe`. The dashboard checks that
release feed, downloads both assets, verifies SHA-256, stops the two local services,
replaces the program directory, and starts the new version.

Runtime data is outside the install directory under the current Windows user's local
application data directory. Updating or replacing the program folder therefore keeps
encrypted credentials, account aliases, strategy source, logs, and SQLite state. Never
put App Keys, App Secrets, tokens, account data, `.db`, or `.dpapi` files in a GitHub
release.

After committing normal code changes, publish the next version with one command:

```powershell
.\scripts\publish-release.ps1 -Version 0.1.1
```

The script updates both package version files, runs Ruff and pytest, commits the
version, and pushes the matching tag. The tag starts the Windows release workflow.

## Web setup

The dashboard can complete the initial setup without using the Router CLI:

1. Use **연결 등록** to save KIS, NAMUH, or simulated credentials. Choose whether
   the credentials are for live, paper, or both environments. Accounts and strategy
   market data select their actual environment separately.
2. Use **계좌 등록** to bind an account alias and set central risk limits.
3. Open **스크립트**, register a strategy, and save its Python source.
4. Enable the account and strategy separately before starting an order-capable script.

Broker credentials and full account numbers are sent directly to Trade Router and
stored in its Windows DPAPI vault. Studio only displays public metadata and masked
account numbers. New accounts and strategies start with order permission disabled.

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
