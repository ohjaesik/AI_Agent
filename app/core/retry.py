# app/core/retry.py

"""일반 함수 호출 retry helper.

외부 API나 일시적 실패가 가능한 작업을 지수 backoff로 재시도할 때 사용한다.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def retry_call(
    fn: Callable[[], T],
    *,
    retries: int = 2,
    backoff_seconds: float = 1.0,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """retry_call 함수. 일반 함수 호출 retry helper. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    last_error: BaseException | None = None

    for attempt in range(retries + 1):
        try:
            return fn()
        except retry_exceptions as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(backoff_seconds * (2**attempt))

    assert last_error is not None
    raise last_error
