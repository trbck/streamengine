import numpy as np
import asyncio
import unittest
import logging
from redisobjstore import RedisObjectStorage

class Stock:
    def __init__(self, ticker, company_name, quotes):
        self.ticker = ticker
        self.company_name = company_name
        self.quotes = quotes

    def __repr__(self):
        return f"Stock(ticker={self.ticker}, company_name={self.company_name}, quotes=Array of shape {self.quotes.shape})"

class TestRedisObjectStorage(unittest.TestCase):
    def setUp(self):
        # Allow nested use of asyncio.run() in Jupyter Notebook
        import nest_asyncio
        nest_asyncio.apply()
        self.storage = RedisObjectStorage(log_level=logging.INFO)

    def tearDown(self):
        asyncio.run(self.storage.close())

    async def asyncSetUp(self):
        # Example Stock object
        self.quotes = np.random.rand(1000, 10)
        self.stock = Stock(ticker="AAPL", company_name="Apple Inc.", quotes=self.quotes)

    async def test_store_and_retrieve_stock(self):
        # Store the Stock object
        await self.storage.store_with_pickle('test:stock:AAPL', self.stock)

        # Retrieve the Stock object
        retrieved_stock = await self.storage.retrieve_with_pickle('test:stock:AAPL')

        # Assertions
        self.assertIsNotNone(retrieved_stock)
        self.assertEqual(retrieved_stock.ticker, self.stock.ticker)
        self.assertEqual(retrieved_stock.company_name, self.stock.company_name)
        np.testing.assert_array_equal(retrieved_stock.quotes, self.stock.quotes)

    async def test_list_and_delete_keys(self):
        # Store the Stock object
        await self.storage.store_with_pickle('test:stock:AAPL', self.stock)

        # List keys
        keys = await self.storage.list_keys('test:stock:*')
        self.assertIn('test:stock:AAPL', keys)

        # Delete keys
        await self.storage.delete_keys('test:stock:*')

        # Verify deletion
        keys_after_deletion = await self.storage.list_keys('test:stock:*')
        self.assertNotIn('test:stock:AAPL', keys_after_deletion)

    def test_store_and_retrieve_stock_sync(self):
        asyncio.run(self.asyncSetUp())
        asyncio.run(self.test_store_and_retrieve_stock())

    def test_list_and_delete_keys_sync(self):
        asyncio.run(self.asyncSetUp())
        asyncio.run(self.test_list_and_delete_keys())

if __name__ == '__main__':
    unittest.main(argv=[''], exit=False)