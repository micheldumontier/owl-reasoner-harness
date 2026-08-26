//! `run`: one invocation per ontology, fingerprint-checked, streamed to JSONL.

use crate::model::{Case, Header, Outcome};
use clap::Args;
use sha2::{Digest, Sha256};
use std::fs;
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Instant;

/// `timeout(1)`'s exit code when it kills the child.
const CAP_EXIT_CODE: i32 = 124;

#[derive(Args)]
pub struct RunArgs {
    /// Directory of ontology files.
    #[arg(long)]
    pub corpus: PathBuf,
    /// Reasoner executable.
    #[arg(long)]
    pub reasoner: PathBuf,
    /// Argument template; `{}` is replaced by the ontology path.
    #[arg(long, default_value = "classify {}")]
    pub args: String,
    /// Per-ontology wall cap in seconds.
    #[arg(long, default_value_t = 30)]
    pub cap_secs: u64,
    /// Pin `RAYON_NUM_THREADS`. Recorded in the header; peak RSS is uninterpretable
    /// without it (one ontology: 42 MB at 1 thread vs 1.47 GB across cores).
    #[arg(long)]
    pub threads: Option<usize>,
    /// Skip inputs larger than this, recorded as `Skipped` with a reason — never
    /// silently dropped, because a silent exclusion once inflated a corpus share 3×.
    #[arg(long)]
    pub max_bytes: Option<u64>,
    /// File extensions to include.
    #[arg(long, default_value = "owl,ofn,owx,omn,ttl,rdf")]
    pub ext: String,
    /// Abort unless this string is present in the reasoner binary. Use it to prove a
    /// build carries (or does not carry) an instrumentation marker before trusting a
    /// sweep — the check that would have caught a sabotaged build.
    #[arg(long)]
    pub require_marker: Option<String>,
    /// Abort if this string IS present (the inverse guard: prove a build is clean).
    #[arg(long)]
    pub forbid_marker: Option<String>,
    /// File containing one ontology stem per line (blank lines and `#` comments ignored).
    /// When given, only those stems are measured; missing stems are emitted as `Skipped`
    /// records — never silently dropped.
    #[arg(long)]
    pub only: Option<PathBuf>,
    /// Digest stdout per ontology, enabling `compare` to check answer identity.
    #[arg(long, default_value_t = true)]
    pub digest_output: bool,
    /// Exclude `#`-prefixed banner lines from the stdout digest.
    ///
    /// **Load-bearing for any answer-identity claim.** rustdl's banners carry
    /// wall-clock timings and a millisecond-bucketed `# wedge-cost-histogram`,
    /// so a RAW stdout digest is nondeterministic run to run: on a 1920-ontology
    /// two-arm sweep a raw OFF-vs-ON comparison reported 1133 of 1745 completers
    /// as DIFFERENT, which is essentially all timing noise. Digesting only the
    /// non-`#` lines makes `compare`'s answer-identity check mean what it says.
    /// `out_lines` still counts the FULL stdout, so the record keeps reflecting
    /// what the reasoner actually printed.
    #[arg(long, default_value_t = false)]
    pub digest_strip_comments: bool,
    #[arg(long)]
    pub out: PathBuf,
}

fn sha256_file(p: &Path) -> std::io::Result<String> {
    let bytes = fs::read(p)?;
    let mut h = Sha256::new();
    h.update(&bytes);
    Ok(format!("{:x}", h.finalize()))
}

fn binary_contains(p: &Path, needle: &str) -> std::io::Result<bool> {
    let bytes = fs::read(p)?;
    Ok(bytes.windows(needle.len()).any(|w| w == needle.as_bytes()))
}

pub fn main(a: RunArgs) -> Result<(), String> {
    if !a.reasoner.is_file() {
        return Err(format!("reasoner not found: {}", a.reasoner.display()));
    }
    let sha = sha256_file(&a.reasoner).map_err(|e| format!("hashing reasoner: {e}"))?;

    // Fingerprint gates run BEFORE any measurement. This is the whole point: a sweep
    // that measures the wrong binary is worse than no sweep, because it looks like data.
    if let Some(m) = &a.require_marker {
        if !binary_contains(&a.reasoner, m).map_err(|e| e.to_string())? {
            return Err(format!(
                "--require-marker {m:?} NOT found in {}. Refusing to run: the binary does \
                 not carry the instrumentation you asked for (rebuild, then re-check). \
                 Silence from an absent instrument is indistinguishable from silence from \
                 a slow program.",
                a.reasoner.display()
            ));
        }
    }
    if let Some(m) = &a.forbid_marker {
        if binary_contains(&a.reasoner, m).map_err(|e| e.to_string())? {
            return Err(format!(
                "--forbid-marker {m:?} IS present in {} — this looks like an instrumented \
                 or sabotaged build, not a clean one. Refusing to run.",
                a.reasoner.display()
            ));
        }
    }

    let version = Command::new(&a.reasoner)
        .arg("--version")
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());

    let exts: Vec<String> = a.ext.split(',').map(|s| s.trim().to_lowercase()).collect();

    // Build the candidate list. If `--only` was given, resolve each requested stem
    // against `--corpus`; missing stems become `Skipped` records (never silent drops).
    // Otherwise, enumerate the corpus directory as before.
    let (files, missing_stems, only_requested, only_resolved): (
        Vec<PathBuf>,
        Vec<String>,
        Option<usize>,
        Option<usize>,
    ) = if let Some(only_path) = &a.only {
        let list_text = fs::read_to_string(only_path)
            .map_err(|e| format!("reading --only file {}: {e}", only_path.display()))?;
        let stems: Vec<String> = list_text
            .lines()
            .map(|l| l.trim())
            .filter(|l| !l.is_empty() && !l.starts_with('#'))
            .map(|l| l.to_string())
            .collect();
        let n_requested = stems.len();
        let mut resolved = Vec::new();
        let mut missing = Vec::new();
        for stem in &stems {
            let found = exts.iter().find_map(|ext| {
                let p = a.corpus.join(format!("{stem}.{ext}"));
                if p.is_file() {
                    Some(p)
                } else {
                    None
                }
            });
            match found {
                Some(p) => resolved.push(p),
                None => missing.push(stem.clone()),
            }
        }
        let n_resolved = resolved.len();
        resolved.sort();
        (resolved, missing, Some(n_requested), Some(n_resolved))
    } else {
        let mut fs_files: Vec<PathBuf> = fs::read_dir(&a.corpus)
            .map_err(|e| format!("reading corpus: {e}"))?
            .filter_map(Result::ok)
            .map(|e| e.path())
            .filter(|p| {
                p.is_file()
                    && p.extension()
                        .and_then(|s| s.to_str())
                        .map(|s| exts.contains(&s.to_lowercase()))
                        .unwrap_or(false)
            })
            .collect();
        fs_files.sort();
        (fs_files, Vec::new(), None, None)
    };

    // Ensure the output directory exists before creating the file.
    if let Some(parent) = a.out.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent).ok();
        }
    }
    let f = fs::File::create(&a.out).map_err(|e| format!("creating {}: {e}", a.out.display()))?;
    let mut w = BufWriter::new(f);

    let header = Header {
        kind: "header".into(),
        reasoner: a.reasoner.display().to_string(),
        sha256: sha,
        version,
        marker_checked: a.require_marker.clone(),
        args_template: a.args.clone(),
        threads: a.threads,
        cap_secs: a.cap_secs,
        max_bytes: a.max_bytes,
        corpus: a.corpus.display().to_string(),
        n_candidates: files.len(),
        host_cores: std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(0),
        only_requested,
        only_resolved,
        digest_strip_comments: a.digest_strip_comments,
    };
    writeln!(w, "{}", serde_json::to_string(&header).unwrap()).ok();
    w.flush().ok();

    if let (Some(req), Some(res)) = (only_requested, only_resolved) {
        eprintln!(
            "harness: --only mode: {req} requested, {res} resolved, {} missing, cap {}s, threads {:?}, sha256 {}",
            req.saturating_sub(res),
            a.cap_secs,
            a.threads,
            &header.sha256[..12]
        );
    } else {
        eprintln!(
            "harness: {} candidates, cap {}s, threads {:?}, sha256 {}",
            files.len(),
            a.cap_secs,
            a.threads,
            &header.sha256[..12]
        );
    }

    // Emit Skipped records for stems that did not resolve to a file.
    for stem in &missing_stems {
        let exts_list = exts.join("|");
        emit(
            &mut w,
            Case {
                kind: "case".into(),
                ont: stem.clone(),
                outcome: crate::model::Outcome::Skipped.as_str().into(),
                wall_s: None,
                peak_rss_kb: None,
                bytes: None,
                skip_reason: Some(format!(
                    "requested via --only but no {stem}.{{{exts_list}}} found in corpus"
                )),
                out_sha256: None,
                out_lines: None,
            },
        );
    }

    let n_files = files.len();
    let mut n = 0usize;
    for path in &files {
        n += 1;
        let ont = path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("?")
            .to_string();
        let bytes = fs::metadata(path).map(|m| m.len()).ok();

        if let (Some(cap), Some(b)) = (a.max_bytes, bytes) {
            if b > cap {
                emit(
                    &mut w,
                    Case {
                        kind: "case".into(),
                        ont,
                        outcome: Outcome::Skipped.as_str().into(),
                        wall_s: None,
                        peak_rss_kb: None,
                        bytes,
                        skip_reason: Some(format!("bytes {b} > max_bytes {cap}")),
                        out_sha256: None,
                        out_lines: None,
                    },
                );
                continue;
            }
        }

        // ONE invocation. `/usr/bin/time -o` writes timing to a file so nothing is
        // piped and the child's real status survives; and note the timing line is the
        // LAST line, because `time` prepends "Command exited with non-zero status N"
        // when the child fails. Reading the first line yields "Command"/"exited".
        let tf = std::env::temp_dir().join(format!("och-{}-{}.time", std::process::id(), n));
        let argv: Vec<String> = a
            .args
            .split_whitespace()
            .map(|t| t.replace("{}", &path.display().to_string()))
            .collect();

        let mut cmd = Command::new("/usr/bin/time");
        cmd.arg("-f")
            .arg("%e %M")
            .arg("-o")
            .arg(&tf)
            .arg("timeout")
            .arg(a.cap_secs.to_string())
            .arg(&a.reasoner)
            .args(&argv)
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        if let Some(t) = a.threads {
            cmd.env("RAYON_NUM_THREADS", t.to_string());
        }

        let t0 = Instant::now();
        let out = cmd.output();
        let fallback_wall = t0.elapsed().as_secs_f64();

        let (outcome, stdout) = match out {
            Ok(o) => (
                Outcome::from_status(o.status.code(), CAP_EXIT_CODE),
                o.stdout,
            ),
            Err(e) => {
                eprintln!("  {ont}: spawn failed: {e}");
                (Outcome::ErrCrash, Vec::new())
            }
        };

        let (wall_s, peak_rss_kb) = read_timing(&tf).unwrap_or((Some(fallback_wall), None));
        fs::remove_file(&tf).ok();

        let (out_sha256, out_lines) = if a.digest_output && !stdout.is_empty() {
            let mut h = Sha256::new();
            if a.digest_strip_comments {
                // Hash only non-`#` lines. `split_inclusive` keeps each line's
                // terminator, so the digest still distinguishes outputs that
                // differ only in line breaks; a final unterminated line is
                // covered too.
                for line in stdout.split_inclusive(|&b| b == b'\n') {
                    if !line.starts_with(b"#") {
                        h.update(line);
                    }
                }
            } else {
                h.update(&stdout);
            }
            (
                Some(format!("{:x}", h.finalize())),
                Some(stdout.iter().filter(|&&b| b == b'\n').count()),
            )
        } else {
            (None, None)
        };

        emit(
            &mut w,
            Case {
                kind: "case".into(),
                ont,
                outcome: outcome.as_str().into(),
                wall_s,
                peak_rss_kb,
                bytes,
                skip_reason: None,
                out_sha256,
                out_lines,
            },
        );

        if n.is_multiple_of(200) {
            eprintln!("  ...{n}/{n_files}");
        }
    }
    w.flush().ok();
    eprintln!("harness: wrote {} records to {}", n, a.out.display());
    Ok(())
}

/// Parse `/usr/bin/time -f "%e %M"`. The timing is on the **last** line: when the
/// child exits non-zero, `time` prepends a "Command exited with non-zero status N"
/// line, and reading the first line silently yields garbage for exactly the rows
/// (timeouts, crashes) whose peak RSS matters most.
fn read_timing(p: &Path) -> Option<(Option<f64>, Option<u64>)> {
    let s = fs::read_to_string(p).ok()?;
    let last = s.lines().rfind(|l| !l.trim().is_empty())?;
    let mut it = last.split_whitespace();
    let w = it.next()?.parse::<f64>().ok();
    let r = it.next()?.parse::<u64>().ok();
    Some((w, r))
}

fn emit<W: Write>(w: &mut W, c: Case) {
    if let Ok(s) = serde_json::to_string(&c) {
        writeln!(w, "{s}").ok();
    }
    // Flush per record: a sweep killed mid-run must leave usable partial results.
    w.flush().ok();
}
