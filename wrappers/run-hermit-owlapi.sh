#!/usr/bin/env bash
# hermit via the shared OWLAPI driver (java/ReasonerCli.java), NOT via `robot reason`.
#
# WHY NOT robot: `robot reason` exits 1 and writes NO output file for any ontology
# containing an unsatisfiable class -- ROBOT's own ReasonerHelper check, so it is
# reasoner-independent (HermiT, ELK and JFact all refuse pizza.ofn identically, while
# ro.ofn passes). At least 130 of 1,783 ORE ontologies (7.3%) would be silently
# dropped. run-hermit.sh is unaffected because it calls HermiT's own CLI; elk has no
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
JAR=${ROBOT_JAR:-$HOME/eval-tools/robot.jar}
DIR=$(cd "$(dirname "$0")/../java" && pwd)
case "${1:-}" in --version|-V) echo "elk via ReasonerCli (robot.jar: $JAR)"; exit 0 ;; esac
[ -f "$JAR" ] || { echo "run-elk: robot.jar not found at $JAR; set ROBOT_JAR" >&2; exit 2; }
[ -f "$DIR/ReasonerCli.class" ] || javac -cp "$JAR" -d "$DIR" "$DIR/ReasonerCli.java" || exit 2
if [ -n "${HARNESS_OUT_DIR:-}" ]; then
  mkdir -p "$HARNESS_OUT_DIR"
  out="$HARNESS_OUT_DIR/$(basename "${1%.*}").ofn"
else
  out=/dev/null
fi
exec java -Xmx${OWLAPI_XMX:-12g} -Dfile.encoding=UTF-8 -cp "$JAR:$DIR" ReasonerCli hermit "$1" "$out"
