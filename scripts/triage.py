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
    # EVERY REASONER WRITES A DIFFERENT FORMAT, so this dispatches per format.
    # A "cheap format-agnostic" version of this check was WRONG: it knew only
    # OWL/XML and tab-separated text, so HermiT's functional-syntax taxonomy --
    # a 4 MB file of SubClassOf( <iri> <iri> ) lines -- read as EMPTY, and 110
    # of 192 HermiT runs were misreported as front-end failures. Both that bug
    # and the earlier <Prefix IRI=...> bug were mine, not the reasoner's, so
    # each format arm below is validated against a known-answer case.
    import re

    def nontrivial(name: str) -> bool:
        return (
            name not in TRIVIAL
            and not name.endswith("#Thing")
            and not name.endswith("#Nothing")
        )

    if fmt == "konclude":
        # OWL/XML. SCOPED TO <Class> ELEMENTS: a bare /(?:IRI|abbreviatedIRI)="/
        # scan also matches the <Prefix name="" IRI="..."/> declarations that an
        # EMPTY hierarchy carries, so the 896-byte Thing/Nothing-only output read
        # as CLASSIFIED.
        return any(
            nontrivial(m.group(1))
            for m in re.finditer(r'<Class\s+(?:IRI|abbreviatedIRI)="([^"]+)"', text)
        )

    if fmt == "hermit":
        # OWL functional syntax, one axiom per line, IRIs in angle brackets.
        # EquivalentClasses counts: a group of >=2 named classes is a real result.
        for m in re.finditer(
            r"^\s*(?:SubClassOf|EquivalentClasses)\(\s*(.+?)\s*\)\s*$", text, re.M
        ):
            names = re.findall(r"<([^>]+)>", m.group(1))
            if sum(1 for n in names if nontrivial(n)) >= 1 and len(names) >= 2:
                return True
        return False

    if fmt == "rustdl":
        return any(
            "\t" in ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")
        )

    raise ValueError(f"no content predicate for format {fmt!r}")


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
