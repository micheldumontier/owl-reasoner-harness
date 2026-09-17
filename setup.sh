#!/usr/bin/env bash
# Provision the reasoners this harness drives, into ./vendor.
#
# Fetches what is freely redistributable (a JDK, robot.jar, Konclude) and tells you
# what you must supply yourself. Re-running is safe: anything already present is left
# alone. Nothing is installed system-wide and nothing needs root.
#
#   ./setup.sh              # fetch everything obtainable
#   ./setup.sh --check      # report what is present, fetch nothing
set -u
cd "$(dirname "$0")"
V="$PWD/vendor"; mkdir -p "$V"
CHECK=0; [ "${1:-}" = "--check" ] && CHECK=1

case "$(uname -s)" in
  Linux)  OS=linux;  JDK_OS=linux; KON="Konclude-v0.7.0-1138-Linux-x64-GCC-Static-Qt5.12.10" ;;
  Darwin) OS=mac;    JDK_OS=mac;   KON="Konclude-v0.7.0-1138-OSX-x64-Clang-Static-Qt5.12.10" ;;
  *) echo "unsupported OS: $(uname -s)" >&2; exit 2 ;;
esac
case "$(uname -m)" in
  x86_64|amd64) ARCH=x64 ;;
  arm64|aarch64) ARCH=aarch64 ;;
  *) echo "unsupported arch: $(uname -m)" >&2; exit 2 ;;
esac

have() { [ -e "$1" ]; }
say()  { printf "  %-34s %s\n" "$1" "$2"; }

fetch() { # url dest
  [ $CHECK = 1 ] && return 0
  curl -fsSL --max-time 1800 -o "$2.part" "$1" && mv "$2.part" "$2"
}

echo "== vendor: $V =="

# ---- JDK (Temurin 17): needed by HermiT, ELK and FaCT++/JFact via java/ReasonerCli
if have "$V/jdk/bin/java"; then say "jdk" "present"
elif [ $CHECK = 1 ]; then say "jdk" "MISSING"
else
  fetch "https://api.adoptium.net/v3/binary/latest/17/ga/${JDK_OS}/${ARCH}/jdk/hotspot/normal/eclipse" "$V/jdk.tgz" \
    && tar xzf "$V/jdk.tgz" -C "$V" && rm -f "$V/jdk.tgz" \
    && ln -sfn "$(cd "$V" && ls -d jdk-17* | head -1)" "$V/jdk" \
    && say "jdk" "installed" || say "jdk" "FETCH FAILED"
  [ "$OS" = mac ] && [ -d "$V/jdk/Contents/Home" ] && ln -sfn "$V/jdk/Contents/Home" "$V/jdkhome"
fi

# ---- robot.jar: bundles HermiT, ELK and JFact. PIN THE VERSION -- different robot
# releases bundle different reasoner versions, and mixing them across hosts silently
# corrupts a comparison. Compare the sha256, never the filename.
if have "$V/robot.jar"; then say "robot.jar" "present ($(shasum -a 256 "$V/robot.jar" 2>/dev/null | cut -c1-16 || sha256sum "$V/robot.jar" | cut -c1-16))"
elif [ $CHECK = 1 ]; then say "robot.jar" "MISSING"
else
  fetch "https://github.com/ontodev/robot/releases/download/v1.9.10/robot.jar" "$V/robot.jar" \
    && say "robot.jar" "installed (expect sha 16a73c074f3df359)" || say "robot.jar" "FETCH FAILED"
fi

# ---- Konclude
if have "$V/konclude/Binaries/Konclude"; then say "konclude" "present"
elif [ $CHECK = 1 ]; then say "konclude" "MISSING"
else
  fetch "https://github.com/konclude/Konclude/releases/download/v0.7.0-1138/${KON}.zip" "$V/kon.zip" \
    && (cd "$V" && unzip -qo kon.zip && rm -f kon.zip && ln -sfn "$KON" konclude) \
    && say "konclude" "installed" || say "konclude" "FETCH FAILED -- see notes below"
fi

# ---- things you must supply
echo "== supplied by you =="
say "rustdl"  "$( [ -n "${MISSED_NET_RUSTDL:-}" ] && echo "MISSED_NET_RUSTDL=$MISSED_NET_RUSTDL" || echo 'build github.com/MaastrichtU-IDS/rustdl, then export MISSED_NET_RUSTDL' )"
KMB="$(ls "$V"/km-* 2>/dev/null | head -1)"
say "KM"      "${KMB:-optional; place the binary at vendor/km-<version> and set KM_BIN_DIR}"
say "corpus"  "$( [ -n "${CORPUS:-}" ] && echo "CORPUS=$CORPUS" || echo 'any directory of .owl/.ofn files; pass with --corpus' )"

cat <<'NOTE'

== notes ==
* Konclude's LINUX static build needs libpcre.so.3 (PCRE1), which modern distros no
  longer ship. If it exits 127 with "libpcre.so.3: cannot open shared object file",
  install the real libpcre3 and DO NOT symlink PCRE2 into place -- an ABI mismatch
  could corrupt oracle output, which is worse than having no oracle.
* GNU `time` is used for peak RSS. Without it the harness still runs and says so,
  recording peak_rss_kb as null rather than pretending. On macOS it uses BSD `time -l`.
* `ulimit -v` (--mem-mb) is a no-op on macOS, which has no RLIMIT_AS. A run there
  records memory as unenforced rather than implying the cap held.

Validate before trusting any result:
  ./target/release/owl-reasoner-harness run --corpus <dir> \
    --reasoner wrappers/run-konclude.sh --args '{}' --cap-secs 60 --out /tmp/smoke.jsonl
NOTE
