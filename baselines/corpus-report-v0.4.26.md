### Corpus report — v0.4.26

Population **424** ontologies · cap **60s** · 1 thread · binary `73ac02e8ab0d`

| | classified | DNF | empty output |
|---|---|---|---|
| count | **418** | 6 | 0 |

| | mean | median | p90 | max |
|---|---|---|---|---|
| wall (s) | 3.5814 | 0.25 | 12.18 | 59.5 |
| peak RSS (MiB) | 183.7 | 28.76 | 489.9 | 6711.6 |

Reported inconsistent: **15** · flagged incomplete: **67**

**Gate vs `v0.4.25`: PASS**

- consistency-verdict flips: **0** (must be 0)
- ontologies lost (classified → not): **0** (must be 0)
- closure shrank on: 1 (informational; a smaller per-pair budget legitimately under-approximates)
  - `ore_ont_12698`: 126736 → 126734
