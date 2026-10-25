# tradera-cli

Read-only terminal search for [tradera.se](https://www.tradera.com) via the official Tradera API.
Small hobby tool: search listings and ended-auction prices from the terminal.

## Setup

1. Register a free developer account at https://api.tradera.com/register and create an application.
2. Put the credentials in `~/.config/tradera-cli/env` (or export them):

```sh
TRADERA_APP_ID=1234
TRADERA_APP_KEY=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
```

3. `uv sync && uv run tradera --help` (or `uv tool install --editable .`)

## Usage

```sh
tradera search "thinkpad t14s" --max-price 6000 --sort PriceAscending --pages 2
tradera search "x1 carbon" --condition OnlySecondHand --seller Company --json
tradera search "x1 carbon gen 9" --ended --sort EndDateDescending   # what they actually went for
tradera counties                 # county ids for --county
tradera categories dator         # category ids for --category
tradera item 123456789           # full item data
```

Notes:

- Search uses SOAP v3 `SearchAdvanced` (stable, typed WSDL). REST v4 search is beta with empty schemas; item and reference data use REST v4.
- Price shown is Buy Now if set, else the next bid. `köp nu` = fixed price, `butik` = shop listing, `N bud` = auction.
- The `--sort/--type/--condition/--seller` values are undocumented in the WSDL; the ones offered were probed live (2026-09-28). An unknown value comes back as an API error.
- Rate limit: 10,000 calls/24h per method. Read-only by design: Tradera's terms forbid automated or timed bidding.

## Tests

`uv run pytest` (mocked), `uv run pytest -m live` once credentials exist.
