# Provisioned reasoners (2026-07-31)

Uniform wrappers in `/data/dumontier/reasoners/` so the harness can drive every reasoner
through the same `--reasoner <path> --args '{}'` interface. Each wrapper's header records
the overhead that must be stated when its walls are compared.

| reasoner | version | invocation | overhead floor | bibtex smoke |
|---|---|---|---|---|
| **Konclude** | v0.7.0-1138 (Jun 2021, latest release) | native static binary, reads `.ofn` | **none** | 0.09 s / 21 MB |
| **HermiT** | 1.4.3 via `obolibrary/robot:v1.9.6` | docker + OpenJDK 11 | **0.56 s** (measured, docker+JVM boot) | 2.46 s / 32 MB |
| **KM** (Kobayashi-MaRust) | `c6ced84` (161 commits pulled) | `ofn F \| kobayashi-marust` | negligible; **20 GB cap mandatory** | 0.02 s / 9 MB |

`/data/dumontier/reasoners/run-{konclude,hermit,km}.sh` — all take one ontology path.

## Notes that change how results must be read

**Konclude is the version already used as the FP=0 oracle** (the 2026-07-11 curated MATRIX
cites `konclude-0.7.0-1138`), so historical comparisons remain meaningful. It is a *native
static* binary — no container startup to subtract. This matters: a docker-based Konclude's
~1.5 s container startup previously inflated walls and produced retracted "beats Konclude"
claims.

**Konclude and HermiT both read `.ofn` directly.** The 2026-06-08 ORE harness converted
everything to OWL/XML with ROBOT first; that dependency is gone, removing a conversion step
that could itself distort timings.

**HermiT's 0.56 s floor was measured before use** (`java -version` inside the container, zero
reasoning). Its 2.03 s on pizza is therefore ~1.5 s of work against Konclude's 48 ms *total*.
An unadjusted wall comparison is meaningless at small scale.

**KM's 20 GB cap is a safety requirement, not tuning.** Run uncapped on `pizza.ofn` — a
~100-class ontology — KM reached **237 GB RSS** and was **OOM-killed after 898 s**, degrading
every other measurement running on the host at the time. Under the upstream `AGENTS.md`
config (240 s / 20 GB) it aborts cleanly at 52 s with `memory allocation of 584 bytes failed`.
So on this host KM **cannot classify pizza**, while it handles small EL fine (bibtex, 0.02 s).
Never run KM in a sweep without the cap.

**KM's output needs filtering before closure comparison.** It emits Tseitin definers in
`subsumptions`, e.g. `{"subsumptions":{"Article":["Entry","Q_1","Q_10",…]}}`. The `Q_*` entries
are internal and must be dropped, the way rustdl filters synthetic `DKey` classes via
`reportable_class_iris`. Comparing raw output would report spurious KM subsumptions.

**Output formats differ and are not directly diffable.** Konclude writes an OWL/XML class
hierarchy; HermiT writes `SubClassOf( <iri> <iri> )` lines; KM writes JSON keyed by class;
rustdl writes `direct<TAB>sub<TAB>sup`. A cross-reasoner closure comparison needs a
normaliser per format — the 2026-06-08 harness had one (`work/diff.py`), which is worth
reusing rather than rewriting.

## Not yet done

- No cross-reasoner run has been made with these wrappers. The harness records a binary
  fingerprint per run, so each reasoner's run will carry its own provenance header and
  `compare` will warn if pins or caps differ.
- The output normaliser (above) is the remaining piece before FP/MISSED can be computed
  across reasoners rather than just wall/RSS.
- ELK and whelk-rs are not provisioned; the 2026-07-11 curated MATRIX covered them.
