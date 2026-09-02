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

        # BUG: accessing a key should mark it as recently used.
        return self.cache[key]

    def put(self, key, value):
        if key in self.cache:
            # BUG: updating a key should also mark it as recently used.
            self.cache[key] = value
            return

        self.cache[key] = value

        if len(self.cache) > self.capacity:
            # BUG: this removes the most recently used item.
            self.cache.popitem(last=True)