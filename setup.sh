#!/usr/bin/env bash
# Provision the pinned reasoners for THIS platform into ./vendor.
#
# Every artifact is named in reasoners.lock with a sha256 and is VERIFIED after
# download. A checksum mismatch aborts rather than proceeding, because the whole point
# of pinning is knowing which binary produced a number.
#
# Nothing is installed system-wide, nothing needs root, and nothing upstream is
# redistributed by this repository.
#
#   ./setup.sh            fetch what is missing
#   ./setup.sh --check    report only, fetch nothing
#   ./setup.sh --force    re-fetch even if present
set -u
cd "$(dirname "$0")"
V="$PWD/vendor"; LOCK="$PWD/reasoners.lock"; mkdir -p "$V"
MODE="${1:-}"

case "$(uname -s)" in
  Linux)  OS=linux ;;
  Darwin) OS=mac ;;
  *) echo "unsupported OS: $(uname -s)" >&2; exit 2 ;;
esac
case "$(uname -m)" in
  x86_64|amd64)  ARCH=x64 ;;
  arm64|aarch64) ARCH=aarch64 ;;
  *) echo "unsupported arch: $(uname -m)" >&2; exit 2 ;;
esac
PLAT="$OS-$ARCH"
echo "== platform: $PLAT   vendor: $V =="

sha_of() { # portable: shasum on macOS, sha256sum on Linux
  if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}
say() { printf "  %-10s %-14s %s\n" "$1" "$2" "$3"; }

get() { # name version sha url
  local name=$1 ver=$2 want=$3 url=$4 dest="$V/$1.download"
  case "$name" in
    robot)    final="$V/robot.jar" ;;
    rustdl)   final="$V/rustdl" ;;
    konclude) final="$V/konclude" ;;
    *)        final="$V/$name" ;;
  esac
  if [ -e "$final" ] && [ "$MODE" != "--force" ]; then say "$name" "$ver" "present"; return 0; fi
  if [ "$MODE" = "--check" ]; then say "$name" "$ver" "MISSING"; return 0; fi

  curl -fsSL --max-time 1800 -o "$dest" "$url" || { say "$name" "$ver" "FETCH FAILED"; return 1; }
  local got; got=$(sha_of "$dest")
  if [ "$got" != "$want" ]; then
    rm -f "$dest"
    say "$name" "$ver" "CHECKSUM MISMATCH -- refusing"
    echo "      expected $want" >&2
    echo "      got      $got" >&2
    return 1
  fi
  case "$url" in
    *.zip) (cd "$V" && unzip -qo "$dest" && rm -f "$dest") &&
           ln -sfn "$(cd "$V" && ls -d Konclude-* 2>/dev/null | head -1)" "$final" ;;
    *)     mv "$dest" "$final"; [ "$name" = rustdl ] && chmod +x "$final" ;;
  esac
  say "$name" "$ver" "installed, sha verified"
}

# ---- pinned artifacts for this platform
while IFS=$'\t' read -r name plat ver sha url; do
  case "$name" in ''|\#*) continue ;; esac
  [ "$plat" = any ] || [ "$plat" = "$PLAT" ] || continue
  get "$name" "$ver" "$sha" "$url"
done < "$LOCK"

# ---- JDK: needed by HermiT, ELK and FaCT++/JFact via java/ReasonerCli. Fetched from
# the Adoptium API rather than pinned by sha, because the API serves a moving "latest
# 17" -- the JVM is a host for the reasoners, not one of the things under test.
if [ -x "$V/jdk/bin/java" ] || [ -x "$V/jdk/Contents/Home/bin/java" ]; then say jdk 17 "present"
elif [ "$MODE" = "--check" ]; then say jdk 17 "MISSING"
else
  curl -fsSL --max-time 1800 -o "$V/jdk.tgz" \
    "https://api.adoptium.net/v3/binary/latest/17/ga/${OS/mac/mac}/${ARCH}/jdk/hotspot/normal/eclipse" \
    && tar xzf "$V/jdk.tgz" -C "$V" && rm -f "$V/jdk.tgz" \
    && ln -sfn "$(cd "$V" && ls -d jdk-17* | head -1)" "$V/jdk" \
    && { [ -d "$V/jdk/Contents/Home" ] && ln -sfn "$V/jdk/Contents/Home" "$V/jdkhome"; true; } \
    && say jdk 17 "installed" || say jdk 17 "FETCH FAILED"
fi

# ---- supplied by you
echo "== supplied by you =="
KMB="$(ls "$V"/km-* 2>/dev/null | head -1)"
say KM "-" "${KMB:-not present -- publishes no binaries; put yours at vendor/km-<version>}"
say corpus "-" "any directory of .owl/.ofn files; pass with --corpus"

cat <<'NOTE'

== notes ==
* Konclude's LINUX build needs libpcre.so.3 (PCRE1), which modern distros dropped. If
  it exits 127 on "libpcre.so.3", install the real libpcre3 -- do NOT symlink PCRE2,
  an ABI mismatch could corrupt oracle output, which is worse than no oracle.
* Konclude ships no arm64 build. On Apple Silicon the x64 one runs under Rosetta 2.
* GNU `time` (Linux) or BSD `time -l` (macOS) supplies peak RSS. With neither, the
  harness still runs and records peak_rss_kb as null rather than inventing it.
* `--mem-mb` uses `ulimit -v` and is a no-op on macOS, which has no RLIMIT_AS.

Smoke-test before trusting anything:
  cargo build --release
  ./target/release/owl-reasoner-harness run --corpus <dir> \
    --reasoner wrappers/run-konclude.sh --args '{}' --cap-secs 60 --out /tmp/smoke.jsonl
NOTE
