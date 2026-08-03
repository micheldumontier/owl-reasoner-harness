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

## Sensitivity — the part that proves the net works

**A net that reports 0 for everything is indistinguishable from a broken net.** So the net is
validated against a build known to lose entailments, with the direction predicted *first*. The
in-tree lever is `--pair-timeout-ms 1` (the documented sound under-approximation: pairs over budget
default to "not subsumed"). Calibrated out-of-band on `pizza.ofn`: **309 direct pairs at the 1000 ms
default, 289 at 1 ms.** Prediction, recorded before running: **ΔMISSED > 0, concentrated in rows
with `tableau>0` or `mode: hybrid`, FP unchanged at 0** — a pure-EL fast-path ontology issues no
per-pair probe and so cannot lose anything. See the results table in
`baselines/<date>-missed-net-*.summary.json` and the commit message.

The net's own arithmetic is pinned by `tests/test_missed_net.py`, and those tests were **sabotaged
to prove they guard**: degrading the union oracle to Konclude-only, folding `peer_disagreement`
rows into the total, and scoring a no-closure arm as `MISSED=0` each fail exactly one intended
test. A guard test that survives its own sabotage is not a guard.
