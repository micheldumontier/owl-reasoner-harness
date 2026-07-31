#!/usr/bin/env bash
# HermiT 1.4.3 via obolibrary/robot:v1.9.6 (bundles the jar + OpenJDK 11).
# END-TO-END walls include ~0.56s docker+JVM boot floor (measured). Do not compare
# against a native reasoner's wall without subtracting or stating it.
f=$(readlink -f "$1"); d=$(dirname "$f"); b=$(basename "$f")
exec docker run --rm -v "$d":/w --entrypoint java obolibrary/robot:v1.9.6 \
  -Dfile.encoding=UTF-8 -cp /tools/robot.jar org.semanticweb.HermiT.cli.CommandLine \
  -c -o /dev/null "/w/$b"
