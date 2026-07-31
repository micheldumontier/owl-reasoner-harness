#!/usr/bin/env python3
"""Decide a triage outcome from OUTPUT CONTENT, not from an exit code.

WHY THIS EXISTS
---------------
Konclude exits 0 on a nonexistent file, on syntactic junk, and on a real ontology
alike -- and in the two failure cases still writes a well-formed hierarchy
containing only owl:Thing and owl:Nothing. A harness `ok` derived from its exit
status is therefore uninformative: a first triage leg reported 58 of 60 "ok"
before this was noticed, a number that would have inflated the algorithmic-gap
set with parse failures.

So for the peer-triage question -- "does another reasoner classify what rustdl
cannot?" -- the verdict must come from the output:

  DNF        the harness killed it at the cap. Exit-code-derived, and trustworthy:
             a SIGKILL is unambiguous.
  CLASSIFIED it parsed AND produced a class hierarchy over more than
             {owl:Thing, owl:Nothing}.
  EMPTY      it exited without being killed, but declared no real class. Almost
             always a parse or conversion failure. Counted SEPARATELY and never
             as a success -- conflating a front-end rejection with a reasoning
             limit is what makes a DNF roster unactionable.
  NO_OUTPUT  exited, wrote nothing at all (a crash, or an abort such as KM's
             allocation failure under its mandatory 20 GB cap).

`pairs` (the normalised transitive closure size) is recorded alongside, because a
CLASSIFIED verdict with a suspiciously small closure is worth a second look. It
is deliberately NOT the verdict predicate: an ontology may legitimately entail no
subsumption at all, and a reasoner that declares every class while entailing
nothing has still parsed and classified.
"""

import argparse
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
NORMALISE = HERE / "normalise.py"

# The two classes every OWL hierarchy carries whether or not anything was read.
TRIVIAL = {
    "http://www.w3.org/2002/07/owl#Thing",
    "http://www.w3.org/2002/07/owl#Nothing",
    "Thing",
    "Nothing",
    "owl:Thing",
    "owl:Nothing",
}


def declared_real_class(path: pathlib.Path, fmt: str) -> bool:
    """True if the output names at least one class that is not Thing/Nothing."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return False
    if fmt == "km":
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return False
        subs = obj.get("subsumptions") or {}
        return any(k not in TRIVIAL for k in subs)
    # Konclude/HermiT OWL-XML and rustdl text: look for any class name that is
    # not one of the two trivial ones. Cheap and format-agnostic on purpose --
    # the precise parse is the normaliser's job, and this must still answer for
    # an output the normaliser rejects.
    #
    # SCOPED TO <Class> ELEMENTS DELIBERATELY. A bare /(?:IRI|abbreviatedIRI)="/
    # scan matches the <Prefix name="" IRI="..."/> declarations that an EMPTY
    # hierarchy also carries, so the 896-byte Thing/Nothing-only output read as
    # CLASSIFIED. Caught by running the predicate against a junk file with a
    # known answer -- which is why the validation set includes one.
    import re

    for m in re.finditer(r'<Class\s+(?:IRI|abbreviatedIRI)="([^"]+)"', text):
        name = m.group(1)
        if name in TRIVIAL:
            continue
        if name.endswith("#Thing") or name.endswith("#Nothing"):
            continue
        return True
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if "\t" in line:
            return True
    return False


def closure_pairs(path: pathlib.Path, fmt: str, ontology: pathlib.Path | None):
    """Normalised closure size, or None if the normaliser could not read it."""
    cmd = [sys.executable, str(NORMALISE), "normalise", "--format", fmt, str(path)]
    if fmt == "km":
        if ontology is None:
            return None
        cmd += ["--ontology", str(ontology)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    return sum(
        1 for ln in proc.stdout.splitlines() if ln.strip() and not ln.startswith("#")
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jsonl", required=True, help="harness run output")
    ap.add_argument("--out-dir", required=True, help="HARNESS_OUT_DIR used for the run")
    ap.add_argument("--format", required=True, choices=["konclude", "hermit", "km", "rustdl"])
    ap.add_argument("--corpus", help="source ontology dir (required for km)")
    ap.add_argument("--ext", default="owl")
    ap.add_argument("--pairs", action="store_true", help="also normalise (slower)")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    out_dir = pathlib.Path(a.out_dir)
    suffix = ".json" if a.format == "km" else ".owx"
    rows = []
    for line in pathlib.Path(a.jsonl).read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("kind") != "case":
            continue
        ont = rec["ont"]
        outcome = rec["outcome"]
        cand = out_dir / f"{ont}{suffix}"

        if outcome == "dnf":
            verdict = "DNF"
        elif not cand.exists() or cand.stat().st_size == 0:
            verdict = "NO_OUTPUT"
        elif declared_real_class(cand, a.format):
            verdict = "CLASSIFIED"
        else:
            verdict = "EMPTY"

        row = {
            "ont": ont,
            "reasoner": a.format,
            "verdict": verdict,
            "harness_outcome": outcome,
            "wall_s": rec.get("wall_s"),
            "rss_kb": rec.get("peak_rss_kb"),
            "out_bytes": cand.stat().st_size if cand.exists() else 0,
        }
        if a.pairs and verdict == "CLASSIFIED":
            src = None
            if a.corpus:
                src = pathlib.Path(a.corpus) / f"{ont}.{a.ext}"
            row["pairs"] = closure_pairs(cand, a.format, src)
        rows.append(row)

    pathlib.Path(a.out).write_text(
        "".join(json.dumps(r) + "\n" for r in rows)
    )
    from collections import Counter

    tally = Counter(r["verdict"] for r in rows)
    print(f"{a.format}: {len(rows)} cases  {dict(tally)}")
    if tally.get("EMPTY"):
        print(
            f"  NOTE {tally['EMPTY']} EMPTY = exited without being killed but declared no "
            f"real class. These are front-end/parse failures, NOT successes."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
