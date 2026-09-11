from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

from picsyncra.services.translation_service import TranslationResult


KEY = ("google", "en", "cache-key", "Biala szafka")


def test_cache_shares_one_successful_loader_between_concurrent_callers() -> None:
    from picsyncra.services.translation_cache import TranslationCache

    cache = TranslationCache()
    started = threading.Event()
    release = threading.Event()
    calls = 0
    lock = threading.Lock()

    def loader() -> TranslationResult:
        nonlocal calls
        with lock:
            calls += 1
        started.set()
        assert release.wait(timeout=2)
        return TranslationResult("White cabinet")

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(cache.get_or_translate, KEY, loader) for _ in range(8)]
        assert started.wait(timeout=2)
        release.set()
        results = [future.result(timeout=2) for future in futures]

    assert calls == 1
    assert {result.text for result in results} == {"White cabinet"}


def test_cache_does_not_store_results_with_warning() -> None:
    from picsyncra.services.translation_cache import TranslationCache

    cache = TranslationCache()
    calls = 0

    def loader() -> TranslationResult:
        nonlocal calls
        calls += 1
        return TranslationResult("Biala szafka", {"code": "translation_failed"})

    cache.get_or_translate(KEY, loader, now=100.0)
    cache.get_or_translate(KEY, loader, now=100.0)

    assert calls == 2


def test_cache_expires_successful_result() -> None:
    from picsyncra.services.translation_cache import TranslationCache

    cache = TranslationCache(ttl_seconds=10)
    calls = 0

    def loader() -> TranslationResult:
        nonlocal calls
        calls += 1
        return TranslationResult(str(calls))

    assert cache.get_or_translate(KEY, loader, now=100.0).text == "1"
    assert cache.get_or_translate(KEY, loader, now=109.0).text == "1"
    assert cache.get_or_translate(KEY, loader, now=110.0).text == "2"
