#!/usr/bin/env bash
# Konclude v0.7.0-1138, native static binary. Reads .ofn directly (no ROBOT step).
# No container/JVM overhead to subtract.
exec /data/dumontier/reasoners/konclude classification -i "$1" -o "${2:-/dev/null}"
