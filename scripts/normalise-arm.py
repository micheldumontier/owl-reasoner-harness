#!/usr/bin/env python3
"""Normalise one arm's captured output into compact per-ontology pair files.

Run this right after an arm finishes, beside the compression step. Adjudication then
reads these instead of re-parsing raw output.

WHY: raw taxonomies run to 100+ MB of XML or JSON, and re-scoring re-parses every one.
Three times today the SCORING RULES changed -- excluding TOP-implied rows, empty-vs-
missing, a bad interning map -- and each re-score paid the full parse again. The parse
is deterministic; the rules are what move. Cache the parse, keep the rules cheap to
change, and keep the raw output so a rule change can still regenerate from source.

    normalise-arm.py <arm> <sweep_dir> <corpus> [workers]

Writes <sweep_dir>/norm/<arm>/<ont>.tsv.gz -- two columns, sub and sup, of DIRECT
pairs (not closed; closure is cheap from these and stays a scoring-time decision).
"""
import glob, gzip, os, sys, importlib.util
from concurrent.futures import ProcessPoolExecutor

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("norm", os.path.join(_here, "normalise.py"))
norm = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(norm)

FMT = {"rustdl": "rustdl", "km130": "km", "km140": "km", "km": "km",
       "konclude": "konclude", "hermit": "hermit", "elk": "hermit", "jfact": "hermit"}
EXT = {"rustdl": ".out", "km130": ".json", "km140": ".json", "km": ".json",
       "konclude": ".owx", "hermit": ".ofn", "elk": ".ofn", "jfact": ".ofn"}

ARM, SW, POOL = sys.argv[1], sys.argv[2], sys.argv[3]
W = int(sys.argv[4]) if len(sys.argv) > 4 else 8
OUT = os.path.join(SW, "norm", ARM)
os.makedirs(OUT, exist_ok=True)


def one(src):
    base = os.path.basename(src)
    for suf in (EXT[ARM] + ".gz", EXT[ARM]):
        if base.endswith(suf):
            ont = base[: -len(suf)]
            break
    else:
        return 0
    dst = os.path.join(OUT, ont + ".tsv.gz")
    if os.path.exists(dst):
        return 0
    onto = os.path.join(POOL, ont + ".owl")
    if not os.path.exists(onto):
        return 0
    try:
        # An EMPTY output is an ANSWER (no named subsumptions), not a parse failure;
        # it must produce an empty pair file rather than none, or scoring cannot tell
        # "answered nothing" from "never answered".
        pairs = [] if os.path.getsize(src) == 0 else sorted(norm.normalise_file(FMT[ARM], src, onto).pairs())
    except Exception:
        return 0
    tmp = dst + ".part"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for a, b in pairs:
            fh.write("%s\t%s\n" % (a, b))
    os.replace(tmp, dst)          # atomic: a killed run leaves no half-written cache
    return 1


if __name__ == "__main__":
    srcs = sorted(glob.glob("%s/out/%s/*" % (SW, ARM)))
    srcs = [s for s in srcs if not s.endswith(".stderr") and not s.endswith(".stderr.gz")]
    n = 0
    with ProcessPoolExecutor(max_workers=W) as ex:
        for r in ex.map(one, srcs, chunksize=8):
            n += r
    print("normalised %s: %d new pair files in %s" % (ARM, n, OUT))
