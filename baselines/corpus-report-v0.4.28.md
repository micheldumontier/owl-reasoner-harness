### Corpus report — v0.4.28

Population **424** ontologies · cap **60s** · 1 thread · binary `1929157b34e0`

| | classified | DNF | empty output |
|---|---|---|---|
| count | **416** | 8 | 0 |

| | mean | median | p90 | max |
|---|---|---|---|---|
| wall (s) | 3.3564 | 0.24 | 11.73 | 55.33 |
| peak RSS (MiB) | 164.9 | 29.0 | 474.8 | 3291.3 |

Reported inconsistent: **15** · flagged incomplete: **69**

**Gate vs `v0.4.27`: **FAIL****

> ⚠️ Baseline records NO host. If it was measured on different hardware, `ontologies lost` is not a valid comparison — re-baseline on this host (`fsesrv-g1`, 32 cores).

- consistency-verdict flips: **0** (must be 0)
- ontologies lost (classified → not): **2** (must be 0)
  - `ore_ont_2574`
  - `ore_ont_7192`
- closure shrank on: 1 (informational; a smaller per-pair budget legitimately under-approximates)
  - `ore_ont_12698`: 126737 → 126735
