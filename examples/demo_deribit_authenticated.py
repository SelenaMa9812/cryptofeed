#!/usr/bin/env python

from cryptofeed import FeedHandler
from cryptofeed.callback import OrderInfoCallback, AccBalancesCallback, UserFillsCallback
from cryptofeed.defines import DERIBIT, ORDER_INFO, ACC_BALANCES, USER_FILLS


async def order(feed, symbol, data: dict, receipt_timestamp):
    print(f"{feed}: {symbol}: Order update: {data}")


async def fill(feed, symbol, data: dict, receipt_timestamp):
    print(f"{feed}: {symbol}: Fill update: {data}")


async def balance(feed, currency, data: dict, receipt_timestamp):
    print(f"{feed}: Currency: {currency} Balance update: {data}")


def main():
    f = FeedHandler(config="config.yaml")

    f.add_feed(DERIBIT,
               channels=[USER_FILLS, ORDER_INFO],
               symbols=["ETH-USD-PERP", "BTC-USD-PERP", "ETH-USD-22M24", "BTC-50000-22M24-call"],
               callbacks={USER_FILLS: UserFillsCallback(fill), ORDER_INFO: OrderInfoCallback(order)},
               timeout=-1)
    f.add_feed(DERIBIT,
               channels=[ACC_BALANCES],
               symbols=["BTC", "ETH"],
               callbacks={ACC_BALANCES: AccBalancesCallback(balance)},
               timeout=-1)
    f.run()


if __name__ == '__main__':
    main()
