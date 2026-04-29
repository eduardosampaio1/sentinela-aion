"""Testes de thread safety — Semana 2 (A-7, A-8).

A-7: SemanticCache._stats é thread-safe; incrementos concorrentes não perdem updates
A-8: get_cache() retorna o mesmo singleton em chamadas concorrentes de múltiplas threads
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

def _reset_cache_singleton():
    import aion.cache as c
    c._instance = None


# ── A-7: SemanticCache stats thread safety ───────────────────────────────────

class TestA7StatsConcurrency:
    """A-7: Múltiplas threads incrementando _stats não devem perder updates."""

    def setup_method(self):
        _reset_cache_singleton()

    def teardown_method(self):
        _reset_cache_singleton()

    def test_concurrent_hits_no_lost_updates(self):
        from aion.cache import SemanticCache
        cache = SemanticCache()
        n = 200

        def increment_hit():
            with cache._lock:
                cache._stats.hits += 1

        threads = [threading.Thread(target=increment_hit) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cache._stats.hits == n

    def test_concurrent_misses_no_lost_updates(self):
        from aion.cache import SemanticCache
        cache = SemanticCache()
        n = 150

        def increment_miss():
            with cache._lock:
                cache._stats.misses += 1

        threads = [threading.Thread(target=increment_miss) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cache._stats.misses == n

    def test_mixed_hits_and_misses_correct_total(self):
        from aion.cache import SemanticCache
        cache = SemanticCache()
        hit_count = 80
        miss_count = 60

        def do_hit():
            with cache._lock:
                cache._stats.hits += 1

        def do_miss():
            with cache._lock:
                cache._stats.misses += 1

        threads = (
            [threading.Thread(target=do_hit) for _ in range(hit_count)] +
            [threading.Thread(target=do_miss) for _ in range(miss_count)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cache._stats.hits == hit_count
        assert cache._stats.misses == miss_count

    def test_evictions_incremented_safely(self):
        from aion.cache import SemanticCache
        cache = SemanticCache()
        n = 100

        def do_evict():
            with cache._lock:
                cache._stats.evictions += 1

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(do_evict) for _ in range(n)]
            for f in as_completed(futures):
                f.result()

        assert cache._stats.evictions == n

    def test_invalidations_incremented_safely(self):
        from aion.cache import SemanticCache
        cache = SemanticCache()
        n = 75

        def do_invalidate():
            with cache._lock:
                cache._stats.invalidations += 1

        with ThreadPoolExecutor(max_workers=15) as executor:
            futures = [executor.submit(do_invalidate) for _ in range(n)]
            for f in as_completed(futures):
                f.result()

        assert cache._stats.invalidations == n

    def test_cache_has_lock_attribute(self):
        from aion.cache import SemanticCache
        cache = SemanticCache()
        assert hasattr(cache, "_lock")
        assert isinstance(cache._lock, type(threading.Lock()))

    def test_lock_is_instance_level_not_shared(self):
        from aion.cache import SemanticCache
        c1 = SemanticCache()
        c2 = SemanticCache()
        assert c1._lock is not c2._lock


# ── A-8: get_cache singleton thread safety ───────────────────────────────────

class TestA8SingletonThreadSafety:
    """A-8: get_cache() deve retornar sempre o mesmo singleton mesmo sob concorrência."""

    def setup_method(self):
        _reset_cache_singleton()

    def teardown_method(self):
        _reset_cache_singleton()

    def test_singleton_same_instance_single_thread(self):
        from aion.cache import get_cache
        a = get_cache()
        b = get_cache()
        assert a is b

    def test_singleton_same_instance_concurrent_threads(self):
        from aion.cache import get_cache
        instances = []
        lock = threading.Lock()

        def fetch():
            inst = get_cache()
            with lock:
                instances.append(inst)

        threads = [threading.Thread(target=fetch) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(instances) == 50
        first = instances[0]
        assert all(inst is first for inst in instances)

    def test_singleton_survives_reset_and_recreates(self):
        from aion.cache import get_cache
        import aion.cache as c

        a = get_cache()
        c._instance = None  # simulate reset
        b = get_cache()

        # After reset a new instance is created
        assert b is not a
        # But subsequent calls return the same new instance
        assert get_cache() is b

    def test_double_checked_locking_module_level(self):
        """_instance_lock deve ser um threading.Lock no nível do módulo."""
        import aion.cache as c
        assert hasattr(c, "_instance_lock")
        assert isinstance(c._instance_lock, type(threading.Lock()))

    def test_concurrent_first_init_no_duplicates(self):
        """Múltiplas threads tentando o primeiro get_cache() ao mesmo tempo."""
        _reset_cache_singleton()
        from aion.cache import get_cache
        instances = []
        lock = threading.Lock()

        barrier = threading.Barrier(20)

        def race_init():
            barrier.wait()  # all start at the same time
            inst = get_cache()
            with lock:
                instances.append(inst)

        threads = [threading.Thread(target=race_init) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(set(id(i) for i in instances)) == 1
