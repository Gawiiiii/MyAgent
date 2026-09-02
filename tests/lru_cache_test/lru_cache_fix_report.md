# LRUCache 修复报告

## 1. 问题定位分析

`lru_cache.py` 使用 `collections.OrderedDict` 保存缓存数据。`OrderedDict` 按插入顺序维护 key：

- 最久未使用的 key 位于最前面
- 最近使用的 key 位于最后面

因此，LRU 缓存需要满足两个关键行为：

1. 访问或更新 key 时，必须把该 key 移动到末尾，表示最近使用。
2. 缓存容量超限时，必须删除最前面的 key，表示淘汰最久未使用。

当前实现存在三处逻辑错误，导致 5 个测试中 4 个失败。

### 错误 1：`get` 访问后未更新使用顺序

原代码：

```python
def get(self, key):
    if key not in self.cache:
        return -1

    # BUG: accessing a key should mark it as recently used.
    return self.cache[key]
```

问题：

- `get` 成功读取 key 后，没有调用 `move_to_end(key)`。
- 在 `test_get_updates_usage_order` 中，访问 `a` 后，`a` 没有变成最近使用。
- 后续插入 `c` 触发淘汰时，`a` 被当作最久未使用误删。

### 错误 2：`put` 更新已有 key 后未更新使用顺序

原代码：

```python
def put(self, key, value):
    if key in self.cache:
        # BUG: updating a key should also mark it as recently used.
        self.cache[key] = value
        return
```

问题：

- 更新已有 key 时，只更新了 value，没有调用 `move_to_end(key)`。
- 在 `test_updating_key_updates_usage_order` 中，更新 `a` 后，`a` 仍保持原来靠前的位置。
- 后续插入 `c` 触发淘汰时，`a` 被误删。

### 错误 3：淘汰时删除了最近使用项

原代码：

```python
if len(self.cache) > self.capacity:
    # BUG: this removes the most recently used item.
    self.cache.popitem(last=True)
```

问题：

- `popitem(last=True)` 删除 `OrderedDict` 末尾元素，也就是最近最常用的 key。
- LRU 缓存应该淘汰最久未使用的 key，即 `OrderedDict` 开头的 key。
- 在 `test_evicts_least_recently_used_key` 和 `test_capacity_one` 中，被淘汰的 key 不正确。

## 2. 详细修改日志

### 修改文件

`lru_cache.py`

### 修改 1：`get` 访问后标记为最近使用

在 key 存在时，先将 key 移动到 `OrderedDict` 末尾，再返回值。

```python
def get(self, key):
    if key not in self.cache:
        return -1

    self.cache.move_to_end(key)
    return self.cache[key]
```

### 修改 2：`put` 更新已有 key 时同步刷新使用顺序

在更新已有 key 的值后，将 key 移动到 `OrderedDict` 末尾。

```python
def put(self, key, value):
    if key in self.cache:
        self.cache[key] = value
        self.cache.move_to_end(key)
        return
```

### 修改 3：淘汰时删除最久未使用项

将 `popitem(last=True)` 改为 `popitem(last=False)`，删除 `OrderedDict` 开头的 key。

```python
if len(self.cache) > self.capacity:
    self.cache.popitem(last=False)
```

## 3. 最终 diff

```diff
--- a/lru_cache.py
+++ b/lru_cache.py
@@ -14,17 +14,16 @@ class LRUCache:
         if key not in self.cache:
             return -1
 
-        # BUG: accessing a key should mark it as recently used.
+        self.cache.move_to_end(key)
         return self.cache[key]
 
     def put(self, key, value):
         if key in self.cache:
-            # BUG: updating a key should also mark it as recently used.
             self.cache[key] = value
+            self.cache.move_to_end(key)
             return
 
         self.cache[key] = value
 
         if len(self.cache) > self.capacity:
-            # BUG: this removes the most recently used item.
-            self.cache.popitem(last=True)
+            self.cache.popitem(last=False)
```

## 4. 测试验证

修改后重新运行当前目录测试，5 个测试全部通过：

```text
Ran 5 tests in 0.000s

OK
```

通过用例：

- `test_get_missing_key`
- `test_evicts_least_recently_used_key`
- `test_get_updates_usage_order`
- `test_updating_key_updates_usage_order`
- `test_capacity_one`
