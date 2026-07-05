"""
M2 acceptance tests — Persian-aware chunker.

Contract:
  rpim_core_api.brain.chunking.chunk_text(
      text: str,
      max_chars: int = 700,
      overlap: int = 100,
  ) -> list[str]
  - splits on paragraph boundaries where possible
  - every chunk ≤ max_chars characters
  - consecutive chunks share overlapping content (≈ overlap chars)
  - empty / whitespace-only input → []

The import of chunk_text is lazy (inside each test body) following the same
pattern as conftest.py so that collection of other test files is not blocked
by a missing module.  Each test fails with ModuleNotFoundError until the
implementation provides rpim_core_api.brain.chunking.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Test fixtures — Persian multi-paragraph text ≥ 3000 chars
# These are plain string constants; no library imports required.
# ---------------------------------------------------------------------------

_PARA1 = (
    "در دنیای امروز، کسب‌وکارهای ایرانی با چالش‌های فراوانی در حوزه بازاریابی دیجیتال "
    "روبه‌رو هستند. بازار رقابتی امروز نیازمند استراتژی‌های نوآورانه و خلاقانه است که "
    "بتواند توجه مخاطبان هدف را جلب کند. تولید محتوای ارزشمند و متناسب با فرهنگ ایرانی "
    "یکی از مهم‌ترین عوامل موفقیت برندها در فضای مجازی به شمار می‌رود. برندهای ایرانی "
    "باید بتوانند با رویکردی صمیمانه و حرفه‌ای با مخاطبان خود ارتباط برقرار کنند و "
    "اعتماد آنها را جلب نمایند. در این مسیر، شناخت دقیق مخاطب هدف و درک نیازها و "
    "خواسته‌های او از اهمیت ویژه‌ای برخوردار است. این رویکرد جامع می‌تواند مزیت رقابتی "
    "پایداری برای برندهای ایرانی ایجاد کند و آنها را در مسیر رشد قرار دهد."
)

_PARA2 = (
    "کیفیت محصولات و خدمات یکی از اصلی‌ترین معیارهایی است که مشتریان ایرانی در هنگام "
    "خرید به آن توجه می‌کنند. برندهایی که می‌توانند استانداردهای بالایی از کیفیت را به "
    "مشتریان خود ارائه دهند، در بلندمدت موفق‌تر خواهند بود. ایجاد تجربه مثبت برای "
    "مشتری از لحظه آشنایی با برند تا پس از خرید، از مهم‌ترین اولویت‌های هر کسب‌وکاری "
    "باید باشد. خدمات پس از فروش مناسب و پاسخگویی سریع به نیازهای مشتریان، می‌تواند "
    "وفاداری آنها را به برند افزایش دهد. اعتمادسازی در میان مخاطبان ایرانی نیازمند "
    "صداقت، شفافیت و پایبندی به وعده‌ها است. این رویکرد جامع و یکپارچه می‌تواند "
    "مزیت رقابتی پایداری برای برندهای ایرانی ایجاد کند."
)

_PARA3 = (
    "استراتژی محتوایی قوی و منسجم می‌تواند تفاوت چشمگیری در موفقیت برندها ایجاد کند. "
    "تولید محتوای آموزشی، سرگرم‌کننده و مفید برای مخاطبان هدف، یکی از بهترین روش‌های "
    "جذب و نگهداری مخاطب است. استفاده از قالب‌های متنوع محتوایی از جمله ویدئو، پادکست، "
    "مقاله و اینفوگرافیک می‌تواند به گسترش دامنه دسترسی برند کمک کند. شبکه‌های اجتماعی "
    "داخلی مانند بله و ایتا، فرصت‌های مناسبی برای برندها فراهم می‌آورند. تقویم محتوایی "
    "منظم و برنامه‌ریزی دقیق برای انتشار محتوا، از عوامل کلیدی موفقیت در بازاریابی "
    "محتوایی است. این رویکرد جامع و یکپارچه مزیت رقابتی پایداری ایجاد خواهد کرد."
)

_PARA4 = (
    "تیم متخصص بازاریابی دیجیتال باید با درک عمیق از فرهنگ، ارزش‌ها و نیازهای جامعه "
    "ایرانی، محتوایی تولید کند که با مخاطبان هدف رزونانس داشته باشد. تحلیل داده‌ها و "
    "آمارهای مربوط به رفتار کاربران می‌تواند به بهبود مستمر استراتژی‌های بازاریابی کمک "
    "کند. استفاده از هوش مصنوعی و ابزارهای تحلیل پیشرفته، امکان شخصی‌سازی محتوا برای "
    "گروه‌های مختلف مخاطبان را فراهم می‌سازد. همکاری با اینفلوئنسرهای معتبر و "
    "چهره‌های شناخته‌شده می‌تواند اعتبار برند را در میان مخاطبان افزایش دهد. این "
    "رویکرد جامع و یکپارچه می‌تواند مزیت رقابتی پایداری برای برند ایجاد کند."
)

_PARA5 = (
    "اندازه‌گیری نتایج و بهینه‌سازی مستمر کمپین‌های بازاریابی از اهمیت بسزایی برخوردار "
    "است. شاخص‌های کلیدی عملکرد باید به دقت تعریف و پایش شوند تا بتوان میزان موفقیت "
    "استراتژی‌ها را ارزیابی کرد. بودجه‌بندی هوشمند و تخصیص منابع بر اساس بازده "
    "سرمایه‌گذاری، می‌تواند به بهینه‌سازی هزینه‌های بازاریابی کمک کند. در نهایت، "
    "موفقیت پایدار در بازاریابی دیجیتال نیازمند تعهد به بهبود مستمر، یادگیری از "
    "تجربیات و انطباق با تغییرات بازار است. هر برندی که می‌خواهد در دنیای دیجیتال "
    "موفق شود باید آمادگی تغییر و نوآوری مستمر را داشته باشد و از پیشرفت‌های فناوری "
    "در راستای اهداف خود بهره ببرد و این رویکرد جامع مزیت رقابتی پایداری ایجاد کند."
)

_PARA6 = (
    "هویت برند یکی از مهم‌ترین دارایی‌های غیرمادی هر کسب‌وکاری به شمار می‌رود. "
    "ایجاد هویت بصری منسجم شامل رنگ‌های برند، تایپوگرافی و لوگو، تأثیر مستقیمی بر "
    "ذهنیت مخاطبان دارد. برند قوی می‌تواند مزیت رقابتی پایداری در بازار ایجاد کند و "
    "موجب تمایز از رقبا شود. سرمایه‌گذاری در ساخت برند یک فرآیند بلندمدت است که نیاز "
    "به صبر، استراتژی و اجرای دقیق دارد. برندهای موفق ایرانی نشان داده‌اند که با "
    "تمرکز بر ارزش‌های اصیل و ارائه تجربه‌ای متمایز به مشتریان می‌توان جایگاه محکمی "
    "در بازار به دست آورد و وفاداری پایداری در میان مخاطبان هدف ایجاد کرد."
)

# Multi-paragraph Persian text; each paragraph separated by a blank line.
# Total length is ≥ 3000 chars (asserted in the relevant test).
_PERSIAN_TEXT = "\n\n".join([_PARA1, _PARA2, _PARA3, _PARA4, _PARA5, _PARA6])

# Continuous text with no paragraph boundaries, used for the overlap test.
# 70 repetitions of an 85-char sentence ≈ 5950 chars, forcing multiple splits.
_SENTENCE = "محصولات با کیفیت برتر برای مشتریان ایرانی عرضه می‌شود و رضایت مشتری اولویت اول ماست. "
_CONTINUOUS_TEXT = _SENTENCE * 70


# ---------------------------------------------------------------------------
# Tests — chunk_text imported lazily inside each body (mirrors conftest pattern)
# ---------------------------------------------------------------------------


def test_m2_chunking_empty_input_returns_empty_list():
    """Empty string → []."""
    from rpim_core_api.brain.chunking import chunk_text  # fails until implemented

    assert chunk_text("") == []


def test_m2_chunking_whitespace_only_returns_empty_list():
    """Whitespace-only string (spaces, newlines, tabs) → []."""
    from rpim_core_api.brain.chunking import chunk_text

    assert chunk_text("   \n\n\t   \n   ") == []


def test_m2_chunking_each_chunk_within_max_chars():
    """Every produced chunk must be ≤ max_chars characters."""
    from rpim_core_api.brain.chunking import chunk_text

    max_chars = 700
    chunks = chunk_text(_PERSIAN_TEXT, max_chars=max_chars, overlap=100)
    assert len(chunks) >= 1, "non-empty text must produce at least one chunk"
    for idx, chunk in enumerate(chunks):
        assert len(chunk) <= max_chars, (
            f"chunk[{idx}] has {len(chunk)} chars which exceeds max_chars={max_chars}"
        )


def test_m2_chunking_multi_paragraph_produces_multiple_chunks():
    """Multi-paragraph Persian text ≥ 3000 chars must produce ≥ 2 chunks."""
    from rpim_core_api.brain.chunking import chunk_text

    assert len(_PERSIAN_TEXT) >= 3000, (
        f"fixture text is {len(_PERSIAN_TEXT)} chars — must be ≥ 3000 for this test"
    )
    chunks = chunk_text(_PERSIAN_TEXT, max_chars=700, overlap=100)
    assert len(chunks) >= 2, (
        f"text with {len(_PERSIAN_TEXT)} chars must be split into ≥ 2 chunks; got {len(chunks)}"
    )


def test_m2_chunking_consecutive_overlap():
    """Consecutive chunks share overlapping content (overlap=100 chars).

    Uses a continuous text with no paragraph breaks so the chunker is forced
    to split mid-text and apply the overlap.  A 50-char snippet taken from
    inside the expected 100-char overlap zone must appear in the next chunk.
    """
    from rpim_core_api.brain.chunking import chunk_text

    chunks = chunk_text(_CONTINUOUS_TEXT, max_chars=700, overlap=100)
    assert len(chunks) >= 2, (
        f"continuous text of {len(_CONTINUOUS_TEXT)} chars must produce ≥ 2 chunks"
    )
    for i in range(len(chunks) - 1):
        # Take 50 chars from inside the expected 100-char overlap zone.
        # Even with word-boundary rounding the snippet must be in the next chunk.
        overlap_snippet = chunks[i][-50:]
        assert overlap_snippet in chunks[i + 1], (
            f"chunk[{i}] tail not found in chunk[{i + 1}]: "
            f"tail={overlap_snippet!r}, chunk[{i + 1}] head={chunks[i + 1][:150]!r}"
        )


def test_m2_chunking_short_text_returns_single_chunk():
    """Text shorter than max_chars → exactly one chunk preserving the content."""
    from rpim_core_api.brain.chunking import chunk_text

    short = "این یک متن کوتاه فارسی است برای آزمایش."
    assert len(short) < 700
    chunks = chunk_text(short, max_chars=700, overlap=100)
    assert len(chunks) == 1, f"short text must yield exactly 1 chunk; got {len(chunks)}"
    assert short.strip() in chunks[0], (
        f"short text content must be preserved in the single chunk: {chunks[0]!r}"
    )


def test_m2_chunking_custom_max_chars_respected():
    """A smaller max_chars produces at least as many chunks, each within the limit."""
    from rpim_core_api.brain.chunking import chunk_text

    chunks_700 = chunk_text(_PERSIAN_TEXT, max_chars=700, overlap=50)
    chunks_300 = chunk_text(_PERSIAN_TEXT, max_chars=300, overlap=50)
    assert len(chunks_300) >= len(chunks_700), (
        "smaller max_chars must produce at least as many chunks as a larger max_chars"
    )
    for idx, chunk in enumerate(chunks_300):
        assert len(chunk) <= 300, (
            f"chunk[{idx}] has {len(chunk)} chars — exceeds custom max_chars=300"
        )
