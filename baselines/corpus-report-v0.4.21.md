### Corpus report — v0.4.21

Population **424** ontologies · cap **60s** · 1 thread · binary `5f18ced6739c`

| | classified | DNF | empty output |
|---|---|---|---|
| count | **416** | 8 | 0 |

| | mean | median | p90 | max |
|---|---|---|---|---|
| wall (s) | 2.854 | 0.2 | 5.49 | 59.82 |
| peak RSS (MiB) | 148.3 | 22.55 | 356.6 | 6711.9 |

Reported inconsistent: **13** · flagged incomplete: **67**

**Gate vs `v0.4.18`: PASS**

- consistency-verdict flips: **0** (must be 0)
- ontologies lost (classified → not): **0** (must be 0)
- closure shrank on: 4 (informational; a smaller per-pair budget legitimately under-approximates)
  - `ore_ont_12698`: 126737 → 126736
  - `ore_ont_7532`: 10552 → 10550
  - `ore_ont_7893`: 973 → 971
  - `ore_ont_9662`: 9163 → 9161
