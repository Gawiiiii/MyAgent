from collections import OrderedDict


class LRUCache:
    """A fixed-capacity least recently used cache."""

    def __init__(self, capacity):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.cache = OrderedDict()

    def get(self, key):
        if key not in self.cache:
            return -1

        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key, value):
        if key in self.cache:
            self.cache[key] = value
            self.cache.move_to_end(key)
            return

        self.cache[key] = value

        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)
