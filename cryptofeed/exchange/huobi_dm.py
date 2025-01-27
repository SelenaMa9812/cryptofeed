'''
Copyright (C) 2017-2021  Bryant Moscon - bmoscon@gmail.com

Please see the LICENSE file for the terms and conditions
associated with this software.
'''
from collections import defaultdict
from cryptofeed.symbols import Symbol
import logging
from typing import Dict, Tuple
import zlib
from decimal import Decimal

from sortedcontainers import SortedDict as sd
from yapic import json

from cryptofeed.connection import AsyncConnection
from cryptofeed.defines import BID, ASK, BUY, FUNDING, FUTURES, HUOBI_DM, L2_BOOK, SELL, TRADES
from cryptofeed.feed import Feed
from cryptofeed.standards import timestamp_normalize


LOG = logging.getLogger('feedhandler')


class HuobiDM(Feed):
    id = HUOBI_DM
    symbol_endpoint = 'https://www.hbdm.com/api/v1/contract_contract_info'

    @classmethod
    def _parse_symbol_data(cls, data: dict) -> Tuple[Dict, Dict]:
        ret = {}
        info = defaultdict(dict)

        for e in data['data']:
            # Pricing is all in USD, see https://huobiglobal.zendesk.com/hc/en-us/articles/360000113102-Introduction-of-Huobi-Futures
            s = Symbol(e['symbol'], 'USD', type=FUTURES, expiry_date=e['contract_code'].replace(e['symbol'], ''))

            ret[s.normalized] = e['contract_code']
            info['tick_size'][s.normalized] = e['price_tick']
            info['instrument_type'][s.normalized] = FUTURES
        return ret, info

    def __init__(self, **kwargs):
        super().__init__('wss://www.hbdm.com/ws', **kwargs)

    def __reset(self):
        self.l2_book = {}

    async def _book(self, msg: dict, timestamp: float):
        """
        {
            'ch':'market.BTC_CW.depth.step0',
            'ts':1565857755564,
            'tick':{
                'mrid':14848858327,
                'id':1565857755,
                'bids':[
                    [  Decimal('9829.99'), 1], ...
                ]
                'asks':[
                    [ 9830, 625], ...
                ]
            },
            'ts':1565857755552,
            'version':1565857755,
            'ch':'market.BTC_CW.depth.step0'
        }
        """
        pair = self.exchange_symbol_to_std_symbol(msg['ch'].split('.')[1])
        data = msg['tick']
        forced = pair not in self.l2_book

        # When Huobi Delists pairs, empty updates still sent:
        # {'ch': 'market.AKRO-USD.depth.step0', 'ts': 1606951241196, 'tick': {'mrid': 50651100044, 'id': 1606951241, 'ts': 1606951241195, 'version': 1606951241, 'ch': 'market.AKRO-USD.depth.step0'}}
        # {'ch': 'market.AKRO-USD.depth.step0', 'ts': 1606951242297, 'tick': {'mrid': 50651100044, 'id': 1606951242, 'ts': 1606951242295, 'version': 1606951242, 'ch': 'market.AKRO-USD.depth.step0'}}
        if 'bids' in data and 'asks' in data:
            update = {
                BID: sd({
                    Decimal(price): Decimal(amount)
                    for price, amount in data['bids']
                }),
                ASK: sd({
                    Decimal(price): Decimal(amount)
                    for price, amount in data['asks']
                })
            }

            if not forced:
                self.previous_book[pair] = self.l2_book[pair]
            self.l2_book[pair] = update

            await self.book_callback(self.l2_book[pair], L2_BOOK, pair, forced, False, timestamp_normalize(self.id, msg['ts']), timestamp)

    async def _trade(self, msg: dict, timestamp: float):
        """
        {
            'ch': 'market.btcusd.trade.detail',
            'ts': 1549773923965,
            'tick': {
                'id': 100065340982,
                'ts': 1549757127140,
                'data': [{'id': '10006534098224147003732', 'amount': Decimal('0.0777'), 'price': Decimal('3669.69'), 'direction': 'buy', 'ts': 1549757127140}]}
        }
        """
        for trade in msg['tick']['data']:
            await self.callback(TRADES,
                                feed=self.id,
                                symbol=self.exchange_symbol_to_std_symbol(msg['ch'].split('.')[1]),
                                order_id=trade['id'],
                                side=BUY if trade['direction'] == 'buy' else SELL,
                                amount=Decimal(trade['amount']),
                                price=Decimal(trade['price']),
                                timestamp=timestamp_normalize(self.id, trade['ts']),
                                receipt_timestamp=timestamp
                                )

    async def message_handler(self, msg: str, conn, timestamp: float):

        # unzip message
        msg = zlib.decompress(msg, 16 + zlib.MAX_WBITS)
        msg = json.loads(msg, parse_float=Decimal)

        # Huobi sends a ping evert 5 seconds and will disconnect us if we do not respond to it
        if 'ping' in msg:
            await conn.write(json.dumps({'pong': msg['ping']}))
        elif 'status' in msg and msg['status'] == 'ok':
            return
        elif 'ch' in msg:
            if 'trade' in msg['ch']:
                await self._trade(msg, timestamp)
            elif 'depth' in msg['ch']:
                await self._book(msg, timestamp)
            else:
                LOG.warning("%s: Invalid message type %s", self.id, msg)
        else:
            LOG.warning("%s: Invalid message type %s", self.id, msg)

    async def subscribe(self, conn: AsyncConnection):
        self.__reset()
        client_id = 0
        for chan in self.subscription:
            if chan == FUNDING:
                continue
            for pair in self.subscription[chan]:
                client_id += 1
                await conn.write(json.dumps(
                    {
                        "sub": f"market.{pair}.{chan}",
                        "id": str(client_id)
                    }
                ))
