"""
M2 acceptance tests — rpim_shared.fake_embed.

Contract:
  fake_embed(text: str, dim: int = 1024) -> list[float]
  - deterministic: same text → identical vector
  - different texts → different vectors
  - returned vector is L2-normalized (sum of squares ≈ 1.0)

The import of fake_embed is lazy (inside each test body) following the same
pattern as conftest.py so that collection of other test files is not blocked
by a missing module.  Each test fails with ImportError until implemented.
"""

from __future__ import annotations

import math


def test_m2_fake_embed_deterministic():
    """Same text always produces an identical vector (pure function)."""
    from rpim_shared import fake_embed  # ImportError until implemented

    text = "کاتالوگ محصولات برند ایرانی"
    v1 = fake_embed(text)
    v2 = fake_embed(text)
    assert v1 == v2, "fake_embed must be deterministic: same input → same output"


def test_m2_fake_embed_different_texts_differ():
    """Different texts produce different vectors."""
    from rpim_shared import fake_embed

    v1 = fake_embed("متن اول برای آزمایش تعبیه‌سازی")
    v2 = fake_embed("متن کاملاً متفاوت دیگری برای بررسی")
    assert v1 != v2, "fake_embed must return different vectors for different inputs"


def test_m2_fake_embed_default_dim_is_1024():
    """Default dimension is 1024 floats."""
    from rpim_shared import fake_embed

    v = fake_embed("بررسی ابعاد پیش‌فرض")
    assert len(v) == 1024, f"expected 1024 dimensions, got {len(v)}"


def test_m2_fake_embed_custom_dim_honored():
    """Custom dim parameter controls the length of the returned vector."""
    from rpim_shared import fake_embed

    v = fake_embed("بررسی ابعاد سفارشی", dim=512)
    assert len(v) == 512, f"expected 512 dimensions, got {len(v)}"


def test_m2_fake_embed_l2_normalized():
    """Returned vector is L2-normalized: sum of squares must be ≈ 1.0."""
    from rpim_shared import fake_embed

    v = fake_embed("برند ایرانی با کیفیت و قیمت مناسب")
    sum_sq = sum(x * x for x in v)
    assert math.isclose(sum_sq, 1.0, abs_tol=1e-5), (
        f"vector is not L2-normalized: sum_of_squares={sum_sq:.8f}, expected ≈ 1.0"
    )


def test_m2_fake_embed_returns_list_of_floats():
    """Return type is list[float]; every element is a float."""
    from rpim_shared import fake_embed

    v = fake_embed("متن نمونه برای بررسی نوع داده")
    assert isinstance(v, list), f"expected list, got {type(v)}"
    assert len(v) > 0, "returned list must not be empty"
    assert all(isinstance(x, float) for x in v), (
        "all elements in the returned vector must be float"
    )


def test_m2_fake_embed_deterministic_across_calls():
    """Three independent calls with the same input all yield equal results."""
    from rpim_shared import fake_embed

    text = "آزمون تکرارپذیری تابع تعبیه‌سازی"
    results = [fake_embed(text) for _ in range(3)]
    assert results[0] == results[1] == results[2], (
        "fake_embed must return the identical vector on every call with the same input"
    )
