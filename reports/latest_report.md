# OmniAudit Report

- **Status:** PASS
- **Target:** `examples/buggy_pkg`
- **Workers:** `4`
- **Modules analyzed:** `2`
- **Findings:** `3`

## Architecture flow

```text
CLI -> AST planner -> ThreadPool agents -> disposable pytest sandbox
                                      -> triage -> unified diff -> verify
```

## Benchmark

| Mode | Workers | Wall-clock seconds |
| --- | ---: | ---: |
| Serial | 1 | 2.2568 |
| Parallel | 4 | 1.1834 |
| Speedup | - | 1.9071x |

## Module: `examples/buggy_pkg/__init__.py`

- Module complexity: `1`
- Generated tests: `1` collected result(s)
- Original run: `PASS`
- Patched verification: `PASS`

### Planned functions

| Function | Arguments | Defaults | Complexity | Line |
| --- | --- | --- | ---: | ---: |

## Module: `examples/buggy_pkg/math_ops.py`

- Module complexity: `1`
- Generated tests: `7` collected result(s)
- Original run: `FAIL`
- Patched verification: `PASS`

### Planned functions

| Function | Arguments | Defaults | Complexity | Line |
| --- | --- | --- | ---: | ---: |
| `average` | `nums` | `-` | 1 | 4 |
| `tail` | `items, n` | `-` | 1 | 9 |
| `append_item` | `val, bucket` | `[]` | 1 | 13 |

### Triage findings

- **REAL_BUG** `average`: empty input should raise ValueError instead of dividing by zero
  - Evidence: `4 failed, 3 passed in 0.03s`
- **REAL_BUG** `tail`: tail should return the last n items
  - Evidence: `4 failed, 3 passed in 0.03s`
- **REAL_BUG** `append_item`: default bucket must not be shared between calls
  - Evidence: `4 failed, 3 passed in 0.03s`

### Synthesized unified diff

```diff
--- examples/buggy_pkg/math_ops.py
+++ examples/buggy_pkg/math_ops.py
@@ -2,14 +2,18 @@


 def average(nums):
+    if not nums:
+        raise ValueError("nums must not be empty")
     total = sum(nums)
     return total / len(nums)


 def tail(items, n):
-    return items[:n]
+    return items[-n:] if n > 0 else []


-def append_item(val, bucket=[]):
+def append_item(val, bucket=None):
+    if bucket is None:
+        bucket = []
     bucket.append(val)
     return bucket
```

### Verification output

```text
.......                                                                  [100%]
7 passed in 0.03s
```
