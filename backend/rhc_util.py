"""Small, dependency-free helpers for RHC: rate limiting, TTL caching, time."""
import threading
import time


def now_ts():
    """Current UTC epoch seconds (int)."""
    return int(time.time())


def floor_to(ts, step):
    return (int(ts) // step) * step


def ceil_to(ts, step):
    ts = int(ts)
    return ts if ts % step == 0 else (ts // step + 1) * step


class TokenBucket:
    """Thread-safe token bucket. rate = tokens per second, capacity = burst size."""

    def __init__(self, rate_per_sec, capacity=None, clock=time.monotonic, sleep=time.sleep):
        self.rate = max(float(rate_per_sec), 1e-9)
        self.capacity = float(capacity if capacity is not None else max(1.0, rate_per_sec))
        self._tokens = self.capacity
        self._clock = clock
        self._sleep = sleep
        self._last = clock()
        self._lock = threading.Lock()

    @classmethod
    def per_minute(cls, n, **kw):
        return cls(n / 60.0, capacity=max(1.0, min(n, 5.0)), **kw)

    def _refill(self):
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now

    def try_acquire(self, n=1.0):
        with self._lock:
            self._refill()
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False

    def wait_time(self, n=1.0):
        with self._lock:
            self._refill()
            deficit = n - self._tokens
            return 0.0 if deficit <= 0 else deficit / self.rate

    def acquire(self, n=1.0, timeout=None):
        """Block until n tokens are available. Returns False on timeout."""
        start = self._clock()
        while True:
            if self.try_acquire(n):
                return True
            wait = self.wait_time(n)
            if timeout is not None and (self._clock() - start + wait) > timeout:
                return False
            self._sleep(min(max(wait, 0.01), 5.0))


class TTLCache:
    """Tiny thread-safe TTL cache with a max size (oldest-inserted eviction)."""

    def __init__(self, ttl_s, max_items=5_000, clock=time.monotonic):
        self.ttl = ttl_s
        self.max_items = max_items
        self._clock = clock
        self._data = {}
        self._lock = threading.Lock()

    def get(self, key, default=None):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return default
            exp, val = item
            if exp < self._clock():
                self._data.pop(key, None)
                return default
            return val

    def set(self, key, value, ttl_s=None):
        with self._lock:
            if len(self._data) >= self.max_items and key not in self._data:
                self._data.pop(next(iter(self._data)))
            self._data[key] = (self._clock() + (self.ttl if ttl_s is None else ttl_s), value)

    def __len__(self):
        return len(self._data)
