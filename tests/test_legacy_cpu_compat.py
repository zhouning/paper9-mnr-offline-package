from scripts.check_legacy_cpu_compat import baseline_is_legacy_safe, normalize_baseline


def test_normalize_baseline_accepts_numpy_list_string():
    assert normalize_baseline("['SSE', 'SSE2', 'SSE3']") == {"SSE", "SSE2", "SSE3"}


def test_normalize_baseline_accepts_sequence():
    assert normalize_baseline(["sse", "sse2", "ssse3"]) == {"SSE", "SSE2", "SSSE3"}


def test_baseline_rejects_x86_v2():
    assert baseline_is_legacy_safe({"SSE", "SSE2", "X86_V2"}) is False


def test_baseline_rejects_avx_dispatch_baseline():
    assert baseline_is_legacy_safe({"SSE", "SSE2", "AVX"}) is False


def test_baseline_accepts_pre_v2_features():
    assert baseline_is_legacy_safe({"SSE", "SSE2", "SSE3", "SSSE3"}) is True
