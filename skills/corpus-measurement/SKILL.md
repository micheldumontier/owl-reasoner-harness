---
name: corpus-measurement
description: Use when measuring a reasoner (or any binary) over an ontology corpus, or when about to report a population figure, a percentage, a DNF list, or a before/after comparison — enforces the pin-verify-smoke-attribute discipline that prevents retracted numbers
---

# Corpus measurement discipline

**Announce at start:** "I'm using the corpus-measurement skill; running its pre-flight before I
measure anything."

This exists because in one session, **five reported measurements had to be retracted. Every one was
a sampling or instrumentation error; none was a code error.** The code under test was right each
time. If you are about to run a sweep or quote a number, the failure mode is almost certainly here,
not in the reasoner.

The tooling half lives in `owl-reasoner-harness` (`run`/`report`/`compare`). This skill is the half
tooling cannot encode.

## Pre-flight — do these BEFORE the long run

Create a todo per item and complete them in order. Skipping one is how each retraction happened.

1. **Pin the binary, then fingerprint it.** Copy the build to a uniquely named path *immediately
   after the build that produced it*, and name the path after the configuration
   (`rustdl-gate-on`, not `rustdl2`). Record `sha256` + `--version`.
2. **Verify the pin against a DISCRIMINATING input.** Pick an input whose result *differs* between
   the configurations you are comparing, and check it before trusting anything. An input that reads
   the same under both cannot validate either.
3. **Prove the instrument is in the binary.** If you added a diagnostic, `strings <bin> | grep
   <marker>`. *Silence from an absent instrument is indistinguishable from silence from a slow
   program.*
4. **Smoke-test the harness on 3 known cases** — one expected pass, one expected fail/timeout, one
   edge case. Confirm each lands in the right bucket. This costs a minute and has caught a bug every
   time it was run.
5. **State the exclusions.** Any cap (`--max-bytes`, per-item timeout, extension filter) creates an
   excluded set. Write down what it is *before* the run, because you will be tempted to omit it
   after.

## Rules while measuring

- **One invocation per item.** If you need timing *and* an exit code, get both from one run
  (`/usr/bin/time -o file`, then read the status). Two runs cost double and can disagree.
- **Read the exit code, never a heuristic.** `rows > 0` is not "completed" — a killed process may
  have streamed partial output first.
- **Parse the LAST line of `/usr/bin/time -o`.** On a non-zero child it prepends
  `Command exited with non-zero status N`, so the first line yields garbage — for exactly the
  timeout/crash rows whose peak RSS matters most.
- **Never `cargo … | tail` then read `$?`.** That is `tail`'s status. Redirect to a file, then echo `$?`.
- **`tail`/`head` in a pipeline buffers to EOF.** An outer timeout kills the loop and you lose
  everything. Write per-item output to files.
- **Never `pkill -f <pattern>` where the pattern appears in your own command line** — it matches
  your own shell (this happened three times in one session, each time costing a command). Write the
  PID to a file at launch and kill by file.
- **Never rebuild while a measurement reads the binary.** Pin first; measure from the copy.
- **Record the thread pin.** Peak RSS swings ~35× with fan-out. RSS without a pin is uninterpretable.
- **Record actual wall; never bake in a threshold.** Then any smaller cap is derivable without a
  re-run.

## Before reporting a number

Check each. These are the exact shapes of the five retractions.

- **Is my population selected on the BINDING predicate, or on a proxy?** "≥50k assertions" was a
  proxy for "takes the fast path"; the real figure was 95× larger. Ask: *would this item still
  qualify if the feature I selected on were absent?* If yes, the selector is not binding.
- **Did a per-item timeout choose my sample?** A timeout is **not a neutral sampler** — it selects
  against the largest items. One 30 s cap excluded the 17 largest ontologies, and because the largest
  were the least interesting, a corpus share came out 3× too high. Any share must state its cap and
  its exclusions, or it is not a share.
- **Am I citing a bound as a result?** "Feature OFF" is an *upper bound* on what removing the
  feature's work can save, not the value of a partial optimisation. Report the fraction achieved.
- **Could the measured binary be the wrong one?** Stale, instrumented, sabotaged, or a different
  config. If a diagnostic printed nothing, suspect the binary before believing the program.
- **Am I attributing a change to the thing I changed?** Diff one variable at a time. A "verification"
  that also silently dropped an env var was uninterpretable, not negative.
- **Do the categories separate causes?** `DNF` (search blowup), `ERR` (front-end rejection), and
  `Skipped` (excluded) are three different problems. Merging them makes a roster unactionable.

## Verify a guard actually guards

A test written to protect against X often does not. **Break the thing it guards and confirm the test
fails.** A differential test added in that session passed under three separate sabotages of the very
property it was written for; it was documented as *not* closing the finding rather than overclaimed.

When you cannot make a guard fail, say so — "guard is not protecting this" is a finding, not a gap
to paper over.

## Rosters go stale

A DNF list or a fragment classification from weeks ago is a hypothesis. Re-measure before building
on it. In one session, a 13-ontology DNF roster was stale by 3, and a five-week-old two-bucket
taxonomy that had directed weeks of work turned out to be an artefact of *which budget each phase
honours* — not two mechanisms. Both were caught only by re-running.

## Report-only first

When a change's logic is subtle, implement the decision in **report-only** mode (count what it
*would* do, change nothing), validate it, then let it act. Verify report-only really is inert
(byte-identical output). In that session this predicted an exact figure — 9,515 axioms — that the
acting implementation then reproduced to the axiom, which is far stronger evidence than any test.
