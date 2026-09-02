import unittest

from lru_cache import LRUCache


class LRUCacheTests(unittest.TestCase):
    def test_get_missing_key(self):
        cache = LRUCache(2)
        self.assertEqual(cache.get("missing"), -1)

    def test_evicts_least_recently_used_key(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)

        self.assertEqual(cache.get("a"), -1)
        self.assertEqual(cache.get("b"), 2)
        self.assertEqual(cache.get("c"), 3)

    def test_get_updates_usage_order(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(cache.get("a"), 1)

        cache.put("c", 3)

        self.assertEqual(cache.get("a"), 1)
        self.assertEqual(cache.get("b"), -1)
        self.assertEqual(cache.get("c"), 3)

    def test_updating_key_updates_usage_order(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("a", 10)
        cache.put("c", 3)

        self.assertEqual(cache.get("a"), 10)
        self.assertEqual(cache.get("b"), -1)

    def test_capacity_one(self):
        cache = LRUCache(1)
        cache.put("a", 1)
        cache.put("b", 2)

        self.assertEqual(cache.get("a"), -1)
        self.assertEqual(cache.get("b"), 2)


if __name__ == "__main__":
    unittest.main()
    
