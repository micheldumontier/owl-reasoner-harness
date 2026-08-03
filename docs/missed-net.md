# The MISSED net — corpus-scale completeness accounting for rustdl

**What it answers:** *how many entailments did this change lose, and on which ontologies?*

Every other gate in this project answers a different question. `run-soundness-diff.sh` proves
**FP=0** on 11 curated fixtures. A harness sweep counts **outcome** transitions (`dnf → ok`).
`normalise.py gate` proves the *normaliser* reproduces known closure counts. None of them can see
a lost subsumption on an ontology that still classifies, which is precisely the shape of every
completeness/performance trade on the table: a lower depth cap that recovers 3 DNFs and costs 4
pairs on `ore_ont_10019`; a Horn-only wide-body admission; any future budget change. Without a
MISSED net those levers cannot be *evaluated*, only guessed at.

```sh
# 1. arm sweep (rustdl, output captured).  env: LIST, CAP, JOBS, RUSTDL_*
scripts/missed-net.sh sweep v0413 /mnt/.../bin/rustdl-v0413-main-72a1103
python3 scripts/missed-net.py manifest --arm v0413

# 2. population: seeded, stratified, reproducible
python3 scripts/missed-net.py select --manifest .../manifest-v0413.jsonl \
        --n 400 --n-tableau 200 --seed 20260803 -o baselines/<date>-missed-net-population.txt

# 3. peers (adopt retained closures first, then run only the remainder)
python3 scripts/missed-net.py reuse --peer konclude \
        --triage baselines/2026-08-01-triage-konclude-c120.jsonl \
        --src /mnt/um-share-drive/dumontier/rustdl-triage-scratch/konclude \
        --population POP.txt --out-remaining KON-TODO.txt
scripts/missed-net.sh peer konclude KON-TODO.txt          # same for hermit

# 4. the net
scripts/missed-net.sh net v0413 --population POP.txt -o baselines/<date>-missed-net-v0413.jsonl

# 5. any later arm: ΔMISSED against the committed baseline
scripts/missed-net.sh sweep TIGHT $BIN --pair-timeout-ms 1
scripts/missed-net.sh net TIGHT --population POP.txt \
        --baseline baselines/<date>-missed-net-v0413.jsonl
```

## Why a shell driver plus a Python analyser

The **sweep** legs go through the Rust harness (`run`), because that is what enforces one
invocation per ontology, a wall + peak-RSS record, a thread pin, a binary fingerprint and a
resumable JSONL. The **analysis** is Python because it must call `normalise.py` directly:
closure diffing is *not* reimplemented anywhere — the union oracle is assembled from
`normalise.read_normalised` and **every FP/MISSED number is returned by `normalise.compare`**.

## The four things that make the numbers mean anything

**1. The oracle is the UNION of Konclude and HermiT.** Konclude is documented to *under-report*
(`ore_ont_9540`: Konclude 66 pairs, HermiT 71; `ore_ont_10407`, where rustdl matched HermiT and
Konclude was the outlier). A "MISSED" measured against Konclude alone can therefore be **Konclude's**
error. Where the two peers **disagree**, the ontology is recorded `peer_disagreement` and **excluded
from the total** — a contested oracle is not an oracle, and adjudicating would launder a guess into
a headline. Disagreement is *either* a pair-set difference *or* an unsatisfiability difference.

**2. Peer outcome comes from output CONTENT, never an exit code.** Konclude exits 0 on a
nonexistent file, on junk, and on a real ontology alike, writing an 896-byte Thing/Nothing-only
hierarchy in the failure cases. The predicate is `triage.py::declared_real_class`, imported rather
than re-written — it is per-format because a "format-agnostic" version once misread 110 of 192
HermiT runs as front-end failures. `EMPTY` peer output is **not** an oracle.

**3. An arm with no closure is not `MISSED=0`.** If the arm timed out, crashed or was rejected,
the row is `arm_no_closure` and excluded from the total, and `ΔMISSED` reports it separately as
`newly_unscored`. Booking it 0 would make "trade answers for timeouts" read as free — the single
most dangerous way this net could lie.

**4. Validate the pipeline before trusting a number.** `python3 scripts/normalise.py gate`
reproduces rustdl's 11 committed FP=0 closure counts exactly (galen 27997, notgalen 32739, sio
8904, ore-10908 6001, wine 653, pizza 499, alehif 247, ro 158, ore-15672 142, sulo 51, bibtex 16).
If it fails, the net is measuring nothing. `normalise.py selftest` pins the identity invariants the
count gate is blind to.

## Population

`select` draws a **seeded, reproducible, stratified** sample from the arm's own manifest, whose
frame is *the ontologies that arm completed with a non-empty closure* — a DNF has no closure to
diff. Strata are `# fragment:` (**pure-EL / Horn / out-of-EL**) × **search-exercised**.

**`tableau>0` is the wrong predicate, and using it would have made the net vacuous.** Measured on
the first 546 completers of this sweep, `# subsumption: … tableau=N` has N>0 on **2** of them, and
the tableau satisfiability-probe counter on 6 — because the Phase-7 label heuristic prunes 96–100%
of oracle calls and `trust_sat` lets the wedge answer the rest. A stratum of two rows cannot detect
a per-pair-budget trade. The binding predicate is therefore `search_exercised` = any of
`# subsumption: … tableau>0`, `# satisfiability probes: … tableau>0`, or
**`# label heuristic: … pass_through>0`** — a pair that survived the label prune and was sent to
the wedge/tableau oracle. That holds on ~10% of completers, an order of magnitude more, and it is
the counter a per-pair budget actually cuts.

Those rows are **deliberately over-sampled**: `select` takes **all** of them, up to `--n-tableau`.
A per-pair-budget or depth-cap trade **cannot** lose a pair on an ontology the saturation fast path
answered outright, so a population without them would be **vacuous for the net's primary purpose**
however large it was. Among the no-search rows the quota is **equal per fragment, not
proportional** — proportional sampling would drown Horn and out-of-EL in pure-EL. Consequence,
stated so nobody mis-reads it: **the sample is not a corpus share.** `select` writes a
`.meta.json` recording the seed, the frame composition and the realised per-stratum quota, so the
sample can be reconstructed exactly.

The full corpus of ~1,730 completers is deliberately **not** used: HermiT carries a measured 0.56 s
docker+JVM floor *per invocation* on top of its reasoning, so a full peer leg is many hours for
little extra signal.

## Reuse, not recomputation

`reuse` adopts the peer hierarchies retained by the 2026-08-01 DNF-257 triage
(`/mnt/um-share-drive/dumontier/rustdl-triage-scratch/{konclude,hermit}/`, 243 / 150 non-empty).
Most of those ontologies are *not* in this population — rustdl did not complete them then — but
v0.4.7…v0.4.13 recovered ~100 of them, so the overlap is exactly the **hard tail**, which is also
the most expensive part of a peer leg. Only `CLASSIFIED` rows with a non-empty file are adopted
(hardlinked, so they cost no space); a retained `DNF` is **re-run**, because its outcome was
recorded on a different day at a different cap and is not comparable otherwise. Adopted rows carry
`reused_from` and `reused_cap_secs` and live in their own `reused.jsonl`, which a freshly swept row
overrides.

## What this does NOT prove

- **A MISSED count is not automatically a bug.** rustdl is a documented **sound
  under-approximation** in several places — `trust_sat` concludes "not subsumed" from the wedge's
  own `Sat` verdict, the fragment gates route some inputs to an incomplete engine, and
  `--pair-timeout-ms` defaults to **1000 ms**, so *the baseline arm itself is budgeted*. The
  baseline's job is to make **changes** visible as a **Δ**, not to indict the current state.
- **It is not a soundness gate.** FP is reported (and must stay 0) but the curated
  `run-soundness-diff.sh` net plus the area canaries remain the soundness authority. A green FP=0
  net over the curated fixtures is *not* evidence of soundness in an area the fixtures are inert
  for — a real `xsd:float`/`xsd:double` DKey false positive shipped for months underneath it.
- **It is not a corpus share.** The population is stratified and over-samples the tableau rows on
  purpose; percentages of *this* sample are not percentages of ORE.
- **It says nothing about ontologies the arm does not complete.** Those are `arm_no_closure` /
  outside the frame, and belong to the DNF-triage tooling instead.
- **Peer walls are not comparable** across reasoners here (HermiT's 0.56 s floor), and the arm
  wrapper caps address space at **24 GB**, which changes behaviour on a memory-tail ontology
  relative to an uncapped run.

## The committed baseline — v0.4.13 (`main` @ 72a1103, sha256 `44d7d80e…`)

`normalise.py gate`: **11/11 exact, 0 absent** (re-run immediately before the net).
`normalise.py selftest`: all pass. `tests/`: 21 pass.

Frame: **1,746 of 1,920** ORE ontologies completed at a 60 s single-thread cap (172 DNF,
2 front-end rejects). Population: **400**, seed **20260803**.

| stratum | frame | sample | baseline MISSED | onts w/ MISSED |
|---|---|---|---|---|
| pure-EL / no search | 559 | 70 | **0** | 0 |
| Horn / no search | 615 | 70 | **0** | 0 |
| Horn / search | 1 | 1 | 1 | 1 |
| out-of-EL / no search | 383 | 71 | 3,606 | — |
| out-of-EL / search | 188 | **188** | 1,591 | — |
| **total** | 1,746 | **400** | **5,198** | **60 of 393** |

**189 of 400 (47%) exercise a per-pair search** — the whole out-of-EL/search stratum plus the
single Horn one. There is no pure-EL/search stratum *at all* in the frame, which is the
saturation fast path working as designed.

Oracle coverage: `both` 337, Konclude-only 54, HermiT-only 3, none 6.
**`peer_disagreement`: 1** (`ore_ont_15682` — Konclude 513 pairs, HermiT 525; Konclude
under-reports, the same direction as `ore_ont_9540`. rustdl would have scored MISSED=14 there;
it is excluded instead). **`no_oracle`: 6** — five where Konclude wrote its 896-byte
Thing/Nothing-only output *and* HermiT produced nothing (both front ends failed), plus
`ore_ont_2574` (115 MB) where both peers DNF'd at 120 s.

**FP = 0 on all 393 scored ontologies against the UNION oracle**, over a 14.0M-pair oracle
closure. That is a soundness datum, and it is the strongest one in this repo: the curated
`run-soundness-diff.sh` net covers 11 fixtures.

**Read the 5,198 as a reference level, not an indictment.** It is concentrated — the top two
ontologies (`ore_ont_9654` 2,382 and `ore_ont_16457` 936) are 64% of it — and rustdl is a
documented sound under-approximation in exactly the places it lands: `trust_sat`, the fragment
gates, and the default 1000 ms per-pair budget. Its value is as the denominator of a Δ.

## Cost of a full run

Measured on this host (32 cores, `--threads 1`, 60 s arm cap / 120 s peer cap):

| leg | scope | jobs | wall |
|---|---|---|---|
| rustdl arm sweep (frame construction) | 1,920 ORE | 4 | **68 min** (dominated by 172 DNF rows at 60 s) |
| Konclude leg | 375 (25 adopted) | 4 | **7 min** — native binary, no container |
| HermiT leg | 377 (23 adopted) | 4 | **38 min** — the long pole (0.56 s docker+JVM floor *per invocation*) |
| `net` (normalise + union + 2 `compare`s per ontology) | 400 | 8 | **~5 min** warm, ~15 min cold |
| **baseline, end to end** | | | **~2 h** |
| a **later arm**: sweep the population + `net --baseline` | 400 | 2 / 8 | **~10 min** |

That asymmetry is the point. The expensive half is the frame and the peer legs, and both are
committed or cached; evaluating a new build costs ten minutes.

**Scratch footprint: ~45 GB, all of it under `$MISSED_NET_SCRATCH` on the shared volume, none on
the root filesystem** (which was at 97% / 15 GB free when this ran, and is unchanged by it).
Raw hierarchies dominate; the normalised TSVs are small. `raw/v0413/` is retained deliberately —
it is the frame, and re-drawing the population with a different `--seed` costs nothing while it
exists, versus 68 minutes to re-sweep. Delete `raw/<arm>/` for a superseded arm; keep
`tsv/<arm>/`.

The dominant per-ontology cost inside `net` is `normalise`'s transitive closure, which is
recomputed by `compare` on both sides — the largest oracle here is 1.31M pairs
(`ore_ont_4802`). Two guards exist because of it: `prune_inert_unsat_edges` (see below) and
`MISSED_NET_MAX_EDGES` (default 8M), which **records** an over-budget graph as
`arm_no_closure` rather than hanging on it.

### One ontology needed a provable shortcut

`ore_ont_11305` has 3,660 classes that are **all unsatisfiable and all mutually equivalent**,
with **zero** `direct` edges. rustdl reports that as one `equiv` line over 3,660 names plus
3,660 `unsat` lines, so `add_equiv_group` expands it to 3,660² = 13.4M edges and the closure
fixpoint then does ~3,660³ ≈ 4.9e10 set probes — hours — before `restricted()` discards every
pair, all 3,660 classes being excluded. Konclude does not hit this on the same ontology: it
writes `EquivalentClasses(owl:Nothing, …)`, which routes straight to `unsat` **without**
expanding. So it is an output-*shape* artefact of one reasoner.

`prune_inert_unsat_edges` drops an edge only when **(a)** both endpoints are in that file's own
unsat/Thing-equivalent set — so any pair it could contribute is removed anyway — **and (b)**
neither endpoint appears in any edge that is not itself fully inside that set, i.e. both are
isolated in the retained graph and lie on no path between other nodes. (a) alone would be
**wrong**: it would drop `U1 ⊑ U2` from `A ⊑ U1 ⊑ U2 ⊑ B` and silently lose the live `A ⊑ B`.
Deleting clause (b) left the whole suite green until
`test_prune_keeps_an_excluded_to_excluded_edge_that_is_on_a_live_path` was added — the obvious
fixture (`A ⊑ U ⊑ B`) has *no* edge fully inside the excluded set, so the sabotaged code also
dropped nothing. That is the second time in this file's history that a guard test survived its
own sabotage.

## Sensitivity — the part that proves the net works

**A net that reports 0 for everything is indistinguishable from a broken net.** So the net is
validated against a build known to lose entailments, with the direction predicted *first*. The
lever is `--pair-timeout-ms 1` (the documented sound under-approximation: pairs over budget
default to "not subsumed"). Calibrated out of band on `pizza.ofn`: **309 direct pairs at the
1000 ms default, 289 at 1 ms.**

**Prediction, committed in `f383c34` before the arm was run:** ΔMISSED > 0, concentrated in
search-exercised rows, FP unchanged at 0 — a fast-path ontology issues no per-pair probe and so
cannot lose anything.

**Result (`TIGHT1MS`, same pinned binary + sha, only `--pair-timeout-ms 1` added):**

| | |
|---|---|
| **ΔMISSED** | **+80** (5,198 → 5,278) |
| ontologies that lost pairs | **13** |
| ontologies that gained pairs | **0** |
| newly unscored (answers → DNF) | **1** (`ore_ont_15010`) |
| FP | **0**, unchanged |
| of the 13 losers, search-exercised | **13 / 13** |
| of the 1 newly unscored, search-exercised | **1 / 1** |
| losses in pure-EL or Horn/no-search rows | **0** |

Direction, magnitude and *location* all as predicted: every loss landed in the stratum the
population deliberately over-samples, and none landed in the 140 fast-path rows. Biggest single
losses `ore_ont_12191` 123→139, `ore_ont_11378` 123→138, `ore_ont_3077` 112→124. The
`newly_unscored` row is the other half of the trade the net must be able to see: a build can
"improve" MISSED by turning answers into timeouts, and that is reported separately rather than
being scored 0.

**The net sees a known loss. It is finished in the sense that mattered.**

The net's own arithmetic is pinned by `tests/test_missed_net.py`, and those tests were **sabotaged
to prove they guard**: degrading the union oracle to Konclude-only, folding `peer_disagreement`
rows into the total, and scoring a no-closure arm as `MISSED=0` each fail exactly one intended
test. A guard test that survives its own sabotage is not a guard.
