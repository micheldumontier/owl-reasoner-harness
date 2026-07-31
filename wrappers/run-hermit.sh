#!/usr/bin/env bash
# HermiT 1.4.3 via obolibrary/robot:v1.9.6 (bundles the jar + OpenJDK 11).
# END-TO-END walls include ~0.56s docker+JVM boot floor (measured). Do not compare
# against a native reasoner's wall without subtracting or stating it.
#
# Usage: run-hermit.sh ONTOLOGY [OUT]
#   OUT omitted -> taxonomy to /dev/null (timing-only, the original behaviour).
#   OUT given   -> taxonomy written there, for the output normaliser.
# HermiT's -c writes to the -o PATH, never to stdout, so a run without OUT yields no
# classification at all; the ontology dir is mounted read-only so a reasoner run can
# never mutate the corpus, and OUT is mounted separately.
# HARNESS_OUT_DIR, if set, overrides $2 (see run-konclude.sh for why outcome must be
# decided from output content rather than an exit code).
if [ -n "${HARNESS_OUT_DIR:-}" ]; then
  mkdir -p "$HARNESS_OUT_DIR"
  set -- "$1" "$HARNESS_OUT_DIR/$(basename "${1%.*}").owx"
fi
f=$(readlink -f "$1"); d=$(dirname "$f"); b=$(basename "$f")
if [ -z "${2:-}" ]; then
  exec docker run --rm -v "$d":/w:ro --entrypoint java obolibrary/robot:v1.9.6 \
    -Dfile.encoding=UTF-8 -cp /tools/robot.jar org.semanticweb.HermiT.cli.CommandLine \
    -c -o /dev/null "/w/$b"
fi
mkdir -p "$(dirname "$2")"; o=$(readlink -f "$(dirname "$2")"); ob=$(basename "$2")
exec docker run --rm -v "$d":/w:ro -v "$o":/out --entrypoint java obolibrary/robot:v1.9.6 \
  -Dfile.encoding=UTF-8 -cp /tools/robot.jar org.semanticweb.HermiT.cli.CommandLine \
  -c -o "/out/$ob" "/w/$b"
