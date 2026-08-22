import threading

import backend.app.services.store as store_mod
from backend.app.config import settings
from backend.app.services.store import TaskStore, get_store


def test_get_store_returns_same_instance_across_threads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(store_mod, "_store", None)

    barrier = threading.Barrier(10)
    results: list[TaskStore] = []
    results_lock = threading.Lock()

    def worker():
        barrier.wait()
        instance = get_store()
        with results_lock:
            results.append(instance)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    assert all(r is results[0] for r in results)
    assert isinstance(results[0], TaskStore)
