#!/usr/bin/env bash
# jfact via the shared OWLAPI driver (java/ReasonerCli.java), NOT via `robot reason`.
#
# WHY NOT robot: `robot reason` exits 1 and writes NO output file for any ontology
# containing an unsatisfiable class -- ROBOT's own ReasonerHelper check, so it is
# reasoner-independent (HermiT, ELK and JFact all refuse pizza.ofn identically, while
# ro.ofn passes). At least 130 of 1,783 ORE ontologies (7.3%) would be silently
# dropped. run-hermit.sh is unaffected because it calls HermiT's own CLI; jfact has no
# CLI to call -- robot.jar carries org/semanticweb/elk/owlapi/ but no elk/cli, and
# JFact is an OWLAPI library (JFactFactory, 2016) that never had one.
#
# OUTPUT is HermiT-CLI-shaped, so normalise with `--format hermit`. Validated: the
# driver run with -hermit- reproduces HermiT's own CLI closure EXACTLY on
# pizza/ro/sulo (499/158/51, FP=0 MISSED=0, the committed reference values).
#
# WALL includes a JVM boot floor (~0.5s). Do not compare against a native reasoner's
# wall without subtracting or stating it.
#
# Exit: 0 answered, 3 DECLINED (unsupported construct -- an honest refusal, not a
# failure), 2 usage, 1 failed.
set -u
JAR=${ROBOT_JAR:-$(cd "$(dirname "$0")/../vendor" 2>/dev/null && pwd)/robot.jar}
DIR=$(cd "$(dirname "$0")/../java" && pwd)
case "${1:-}" in --version|-V) echo "jfact via ReasonerCli (robot.jar: $JAR)"; exit 0 ;; esac
[ -f "$JAR" ] || { echo "run-jfact: robot.jar not found at $JAR; set ROBOT_JAR" >&2; exit 2; }
[ -f "$DIR/ReasonerCli.class" ] || javac -cp "$JAR" -d "$DIR" "$DIR/ReasonerCli.java" || exit 2
if [ -n "${HARNESS_OUT_DIR:-}" ]; then
  mkdir -p "$HARNESS_OUT_DIR"
  out="$HARNESS_OUT_DIR/$(basename "${1%.*}").ofn"
else
  out=/dev/null
fi
# -Xmx MUST SIT UNDER THE HARNESS MEMORY CAP. `ulimit -v` limits ADDRESS SPACE, and
# the JVM reserves its whole max heap as address space at startup -- so `-Xmx12g`
# under a 9 GiB cap does not merely spill, it fails to boot:
#   "Error occurred during initialization of VM
#    Could not reserve enough space for 12582912KB object heap"
# In a test run that silently failed all 24 ontologies on all three JVM arms.
#
# MEASURED, and the boundary is NOT CRISP. Under `ulimit -v 9216MB`, HermiT boots at
# -Xmx6144m but not 7168m; ELK boots at 5632m, FAILS at 5120m, and boots again at
# 4608m. That non-monotonicity (address-space layout varies with ASLR) means any
# formula hugging the limit will flake intermittently across a 1,920-ontology run.
# So: half the cap, which passes all three with margin.
#
# CONTRACT CONSEQUENCE, which must be stated and not glossed: under one `ulimit -v`
# a native reasoner may use nearly the whole cap as working memory while a JVM
# reasoner gets HALF. The memory contract is not uniform across the two families,
# and a JVM `failed` may mean "could not reserve address space", not "ran out".
# CONSEQUENCE FOR THE CONTRACT, which must be stated rather than glossed: under one
# address-space cap a native reasoner may use nearly all of it as heap while a JVM
# reasoner gets roughly cap-2GiB. The memory contract is NOT uniform across the two.
if [ -n "${HARNESS_MEM_MB:-}" ]; then
  XMX="$(( HARNESS_MEM_MB / 2 ))m"
else
  XMX="${OWLAPI_XMX:-12g}"
fi
# PIN THE JVM'S THREADS TO THE SAME COUNT AS THE NATIVE REASONERS. The harness sets
# RAYON_NUM_THREADS from --threads, which pins rustdl; without this the JVM was free
# to size itself from all 16 CPUs -- ParallelGCThreads defaulted to 13 -- so the
# thread contract was NOT uniform across the two families even though the memory and
# wall contracts were.
#
# It is also what makes startup RELIABLE. Each GC thread reserves address space, and
# under `ulimit -v` that pushed ELK over the limit intermittently: 1 boot failure in
# 5 with NO error message at all, a silent rc=1 that in a 1,920-ontology sweep would
# read as the reasoner failing on those ontologies. Constrained, it is 5/5.
VJ="$(cd "$(dirname "$0")/../vendor" 2>/dev/null && pwd)"
[ -x "$VJ/jdk/bin/java" ] && PATH="$VJ/jdk/bin:$PATH"
[ -x "$VJ/jdkhome/bin/java" ] && PATH="$VJ/jdkhome/bin:$PATH"
JT="${RAYON_NUM_THREADS:-4}"
exec java -XX:ActiveProcessorCount=${JT} -Xmx${XMX} -Dfile.encoding=UTF-8 -cp "$JAR:$DIR" ReasonerCli jfact "$1" "$out"
