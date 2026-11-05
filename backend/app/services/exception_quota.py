from __future__ import annotations


def quota_is_unlimited(limit: int) -> bool:
    """A zero daily limit means unlimited; feature flags control enablement."""
    return limit == 0


def quota_remaining(limit: int, used: int) -> int | None:
    if quota_is_unlimited(limit):
        return None
    return max(0, limit - used)


def quota_exhausted(limit: int, used: int) -> bool:
    return not quota_is_unlimited(limit) and used >= max(0, limit)


def quota_batch_capacity(limit: int, used: int, batch_limit: int) -> int:
    safe_batch_limit = max(1, batch_limit)
    remaining = quota_remaining(limit, used)
    return safe_batch_limit if remaining is None else min(safe_batch_limit, remaining)
