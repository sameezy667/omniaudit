"""Small module containing deterministic edge-case bugs for OmniAudit."""


def average(nums):
    total = sum(nums)
    return total / len(nums)


def tail(items, n):
    return items[:n]


def append_item(val, bucket=[]):
    bucket.append(val)
    return bucket
