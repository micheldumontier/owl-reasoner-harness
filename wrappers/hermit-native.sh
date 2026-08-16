#!/usr/bin/env bash
# HermiT WITHOUT a working docker runtime.
#
# WHY THIS EXISTS. `docker run` fails on this host with
#   failed to start shim: ... unsupported protocol: Yunix
# a broken containerd runtime -- but the obolibrary/robot image is PRESENT and
# `docker create` / `docker cp` / `docker export` do not start a container, so the
# image contents are extractable. The container JVM needs GLIBC_2.38 which the host
# lacks, so it is invoked through the CONTAINER'S OWN dynamic loader with the
# container's library path. This restores HermiT as a third oracle, which the FP
# adjudication rule (X - (Konclude u HermiT)) depends on.
#
# ONE-TIME SETUP (writes ~410 MB to /tmp/rootfs + 94 MB /tmp/robot.jar):
#   cid=$(docker create obolibrary/robot:v1.9.6)
#   docker cp "$cid:/tools/robot.jar" /tmp/robot.jar
#   mkdir -p /tmp/rootfs && docker export "$cid" | tar -xf - -C /tmp/rootfs
#   docker rm "$cid"
#
# OUTPUT FORMAT WARNING: HermiT via robot's CommandLine writes FUNCTIONAL syntax
# (`SubClassOf( <a> <b> )`), NOT the OWL/XML Konclude emits. Parsing it as XML yields
# an empty closure, which reads as "the reasoner found nothing" rather than "the
# parser matched nothing". Use a functional-syntax parser.
#
#   hermit-native.sh <ontology> <output>
set -u
R=${HERMIT_ROOTFS:-/tmp/rootfs}
JAR=${ROBOT_JAR:-/tmp/robot.jar}
JH=$R/usr/lib/jvm/java-11-openjdk-amd64
[ -x "$JH/bin/java" ] || { echo "hermit-native: rootfs not provisioned; see header" >&2; exit 2; }
exec "$R/lib64/ld-linux-x86-64.so.2" \
  --library-path "$R/lib/x86_64-linux-gnu:$R/usr/lib/x86_64-linux-gnu:$JH/lib:$JH/lib/server:$JH/lib/jli" \
  "$JH/bin/java" -Xmx${HERMIT_XMX:-12g} -Dfile.encoding=UTF-8 -cp "$JAR" \
  org.semanticweb.HermiT.cli.CommandLine -c -o "$2" "$1"
