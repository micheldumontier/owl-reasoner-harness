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
# `ulimit -v` caps ADDRESS SPACE, and the JVM RESERVES far more than it commits, so
# -Xmx must sit under the cap or the VM does not merely spill -- it fails to boot:
#   "Could not reserve enough space for NNNNNNKB object heap"
# In one test run that silently failed all 24 ontologies on all three JVM arms.
#
# THE OVERHEAD IS FIXED, NOT PROPORTIONAL -- measured, after an earlier cap/2 rule
# turned out to be over-conservative. At a 9216 MB cap the reservations are:
#   CompressedClassSpaceSize  1024 MiB (reserved by DEFAULT, and trimmed below)
#   ReservedCodeCacheSize      240 MiB
#   binary, libs, stacks, GC   ~1 GiB
# so `cap - 2048` holds across sizes: 4096->2048 (50% of cap), 10240->8192 (80%),
# 20480->18432 (90%). The penalty shrinks as the cap grows.
#
# cap/2 was wrong because it was measured while GC threads were unpinned, which is a
# DIFFERENT fault fixed just below. Two fixes were applied at once and only the pair
# was verified; re-measured with threads pinned, 6144m boots 5/5 at a 9216 cap where
# cap/2 would have allowed 4608m.
#
# Contract consequence, still worth stating: a native reasoner may use nearly the
# whole cap while a JVM reasoner gives up a fixed ~2 GiB, and a JVM `failed` can mean
# "could not reserve address space" rather than "ran out".
# CONSEQUENCE FOR THE CONTRACT, which must be stated rather than glossed: under one
# address-space cap a native reasoner may use nearly all of it as heap while a JVM
# reasoner gets roughly cap-2GiB. The memory contract is NOT uniform across the two.
if [ -n "${HARNESS_MEM_MB:-}" ]; then
  XMX="$(( HARNESS_MEM_MB > 3072 ? HARNESS_MEM_MB - 2048 : HARNESS_MEM_MB / 2 ))m"
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
# Trim the 1 GiB default class-space RESERVATION; 256m is ample for these
# reasoners and buys a full GiB of heap back under the same cap.
exec java -XX:ActiveProcessorCount=${JT} -XX:CompressedClassSpaceSize=256m -Xmx${XMX} -Dfile.encoding=UTF-8 -cp "$JAR:$DIR" ReasonerCli jfact "$1" "$out"
