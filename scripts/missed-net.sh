#!/usr/bin/env bash
# missed-net.sh — the corpus-scale MISSED net: per-ontology completeness loss for a
# rustdl build, against a Konclude ∪ HermiT oracle.
#
# WHY A SHELL DRIVER PLUS A PYTHON ANALYSER (and not one or the other):
#   * the SWEEP legs must go through the Rust harness (`run`), because that is what
#     enforces one invocation per ontology, a wall+RSS record, a thread pin, a
#     fingerprint gate and a resumable JSONL. Re-implementing any of that in Python
#     would be re-implementing the thing this repo exists to stop getting wrong.
#   * the ANALYSIS must be Python, because it has to call `normalise.py`'s parsers and
#     `compare` DIRECTLY. Closure diffing is not re-implemented anywhere: the union
#     oracle is built from `normalise.read_normalised` and every FP/MISSED number comes
#     out of `normalise.compare`. See scripts/missed-net.py.
#
# SUBCOMMANDS
#   sweep  TAG BIN [EXTRA_CLASSIFY_ARGS]   rustdl leg, output captured  (env LIST, CAP)
#   peer   konclude|hermit LISTFILE        one peer leg over a population
#   net    TAG                             normalise + union oracle + per-ont MISSED
#
# Everything bulky (raw hierarchies, normalised TSVs, pinned binaries) lives under
# $SCRATCH on the shared volume. The root filesystem was at 97% / 15 GB free when this
# was written and one rustdl corpus pass alone emits ~15 GB of closures.
set -u
H=/data/dumontier/owl-reasoner-harness
SCRATCH=${MISSED_NET_SCRATCH:-/mnt/um-share-drive/dumontier/missed-net}
CORPUS=${MISSED_NET_CORPUS:-/data/dumontier/ore-run/pool_sample/files}
CAP=${CAP:-60}
JOBS=${JOBS:-4}
HARNESS=$H/target/release/owl-reasoner-harness

die() { echo "missed-net: $*" >&2; exit 2; }
[ -x "$HARNESS" ] || die "build the harness first: cargo build --release"

# Refuse to fill either volume. A leg that fills a shared drive takes down every other
# measurement on the host, which is strictly worse than not running.
guard_disk() {
  for vol in / "$SCRATCH"; do
    avail=$(df --output=avail -k "$vol" | tail -1)
    [ "$avail" -lt 5242880 ] && die "free space on $vol below 5 GB ($avail kB) — aborting"
  done
}

# One JSONL PER CHUNK. Pointing concurrent chunks at a single --out produced 40
# unparseable interleaved records and 73 silently missing ontologies once already.
sweep_chunks() {
  local tag=$1 wrapper=$2 outdir=$3 list=$4 cap=$5 d
  d=$SCRATCH/runs/$tag; mkdir -p "$d" "$outdir"
  # DELETE THE CONCATENATED RESULT FIRST. It is written only at the very end, so a
  # leftover file from an earlier (smaller) run of the same tag is indistinguishable from
  # a finished leg -- measured: a 4-ontology smoke left runs/hermit/hermit.jsonl in place,
  # a later 377-ontology leg was still running, and a "both legs done" check on file
  # EXISTENCE passed while the analyser would have read the 4-case file as the oracle.
  rm -f "$d/$tag.jsonl" "$d"/c[0-9][0-9]
  split -n "l/$JOBS" -d "$list" "$d/c"
  local pids=()
  for c in "$d"/c[0-9][0-9]; do
    [ -s "$c" ] || continue
    HARNESS_OUT_DIR="$outdir" "$HARNESS" run \
      --corpus "$CORPUS" --only "$c" --reasoner "$wrapper" --args '{}' \
      --cap-secs "$cap" --threads 1 --ext owl \
      --out "$d/$tag-$(basename "$c").jsonl" > "$d/$tag-$(basename "$c").log" 2>&1 &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  # Adopted rows (missed-net.py reuse) are kept in their OWN file and merged by the
  # analyser, so a re-swept ontology overrides an adopted one and nothing is duplicated.
  cat "$d"/"$tag"-c[0-9][0-9].jsonl > "$d/$tag.jsonl"
  # The harness probes `--reasoner --version` for the run header. The three provisioned
  # peer wrappers have no --version arm, so the probe reaches their capture branch with
  # `--version` in place of an ontology path and drops a garbage-named entry (e.g.
  # "basename (GNU coreutils) 8.32", a FILE for Konclude and a DIRECTORY for HermiT)
  # into the output dir. Sweep anything whose name is not a plausible ontology stem, so
  # a later `for f in raw/*` never picks one up as an answer.
  find "$outdir" -maxdepth 1 -mindepth 1 -regextype posix-extended \
       ! -regex '.*/[A-Za-z0-9][A-Za-z0-9_.-]*' -exec rm -rf {} + 2>/dev/null || true
  guard_disk
  echo "LEG $tag: $(grep -c '"kind":"case"' "$d/$tag.jsonl") cases -> $d/$tag.jsonl"
}

cmd=${1:-}; shift || true
case "$cmd" in

sweep)
  tag=${1:?tag}; bin=${2:?pinned rustdl binary}; shift 2
  extra="${*:-}"
  [ -x "$bin" ] || die "not executable: $bin"
  # SHA VERIFIED ONCE, HERE — not per invocation (46 MB x 1920 = ~90 GB of reads).
  # A ~2-hour sweep in this repo's history measured a sabotaged build whose source had
  # been reverted without rebuilding; the sha goes in the manifest so the arm can never
  # be re-read as some other binary.
  sha=$(sha256sum "$bin" | cut -d' ' -f1)
  ver=$("$bin" --version 2>/dev/null | tr -d '\n')
  list=${LIST:-}
  if [ -z "$list" ]; then
    list=$SCRATCH/work/all-$(basename "$CORPUS").txt
    mkdir -p "$(dirname "$list")"
    find "$CORPUS" -maxdepth 1 -name '*.owl' -printf '%f\n' | sed 's/\.owl$//' | sort > "$list"
  fi
  mkdir -p "$SCRATCH/runs/$tag"
  # RECORD THE RUSTDL_* ENVIRONMENT. A flag arm is defined as much by its env as by its
  # argv, and an arm whose env was not recorded cannot be re-run or trusted: an
  # unrecorded default flip is exactly how two "identical" runs disagree.
  envs=$(env | grep -E '^RUSTDL_' | sort | paste -sd, - || true)
  cat > "$SCRATCH/runs/$tag/manifest.json" <<EOF
{"arm":"$tag","binary":"$bin","sha256":"$sha","version":"$ver",
 "classify_args":"$extra","rustdl_env":"$envs","cap_secs":$CAP,"threads":1,"jobs":$JOBS,
 "corpus":"$CORPUS","list":"$list","n_requested":$(wc -l < "$list"),
 "wrapper":"$H/wrappers/run-rustdl.sh","when":"$(date -Is)"}
EOF
  echo "arm $tag: $ver sha ${sha:0:12} args '${extra}' cap ${CAP}s jobs $JOBS n=$(wc -l < "$list")"
  export MISSED_NET_RUSTDL="$bin" MISSED_NET_RUSTDL_ARGS="$extra"
  sweep_chunks "$tag" "$H/wrappers/run-rustdl.sh" "$SCRATCH/raw/$tag" "$list" "$CAP"
  ;;

peer)
  peer=${1:?konclude|hermit}; list=${2:?listfile}
  case "$peer" in
    konclude) wrapper=/data/dumontier/reasoners/run-konclude.sh ;;
    hermit)   wrapper=/data/dumontier/reasoners/run-hermit.sh ;;
    # KM is deliberately NOT an oracle leg: under its MANDATORY 20 GB cap it cannot even
    # classify pizza on this host, and it is measured-unsound on ~1795 ORE ontologies.
    *) die "peer must be konclude or hermit (KM is not an oracle: measured unsound)" ;;
  esac
  mkdir -p "$SCRATCH/runs/$peer"
  cat > "$SCRATCH/runs/$peer/manifest.json" <<EOF
{"arm":"$peer","wrapper":"$wrapper","cap_secs":${PEER_CAP:-120},"threads":1,
 "jobs":$JOBS,"corpus":"$CORPUS","list":"$list",
 "n_requested":$(grep -cve '^\s*$' "$list"),"when":"$(date -Is)"}
EOF
  sweep_chunks "$peer" "$wrapper" "$SCRATCH/raw/$peer" "$list" "${PEER_CAP:-120}"
  ;;

net)
  tag=${1:?tag}; shift
  exec python3 "$H/scripts/missed-net.py" net --arm "$tag" "$@"
  ;;

*) sed -n '2,30p' "$0"; exit 2 ;;
esac
