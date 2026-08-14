#!/usr/bin/env python3
"""Run one domestic QLD DipBuy cycle with a forced buy stage."""
import argparse

from src.core.engine.domestic_qld_dip_buy import DomesticQldDipBuyEngine
from src.main import TradingBot


def _reason(value: str) -> str:
    value = value.strip()
    if not value:
        raise argparse.ArgumentTypeError("reason is required")
    return value


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--stage", required=True, type=int, choices=(1, 2, 3))
    parser.add_argument("--reason", required=True, type=_reason)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        bot = TradingBot(account_id=args.account, save_accounts_meta=False)
    except ValueError as error:
        print(f"error: {error}")
        return 2

    runner = bot.runners[0]
    if runner.account.market_type != "domestic":
        print(f"error: {args.account} is not a domestic account")
        return 2

    if not isinstance(runner.engine, DomesticQldDipBuyEngine):
        print(f"error: {args.account} does not use DomesticQldDipBuyEngine")
        return 2

    runner.engine.force_buy_stage(args.stage, args.reason)
    bot.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
