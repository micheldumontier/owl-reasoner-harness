//! `compare`: diff two runs. Outcome transitions plus answer identity — the check
//! that was hand-rolled every time it was needed ("286 ontologies, 0 diffs").

use crate::model::Case;
use crate::report::load;
use clap::Args;
use std::collections::HashMap;
use std::path::PathBuf;

#[derive(Args)]
pub struct CompareArgs {
    pub a: PathBuf,
    pub b: PathBuf,
    /// Report wall changes beyond this fraction (0.10 = 10%).
    #[arg(long, default_value_t = 0.10)]
    pub wall_tol: f64,
    #[arg(long, default_value_t = 20)]
    pub top: usize,
}

pub fn main(args: CompareArgs) -> Result<(), String> {
    let (ha, ca) = load(&args.a)?;
    let (hb, cb) = load(&args.b)?;

    println!("# compare");
    println!(
        "  A {}  sha {}  threads {:?} cap {}s",
        args.a.display(),
        &ha.sha256[..12.min(ha.sha256.len())],
        ha.threads,
        ha.cap_secs
    );
    println!(
        "  B {}  sha {}  threads {:?} cap {}s",
        args.b.display(),
        &hb.sha256[..12.min(hb.sha256.len())],
        hb.threads,
        hb.cap_secs
    );

    // Refuse to silently compare incomparable runs — differing pins or caps explain
    // most apparent "behaviour changes".
    if ha.sha256 == hb.sha256 {
        println!("  !! IDENTICAL binaries: any difference below is noise or nondeterminism.");
    }
    if ha.threads != hb.threads {
        println!(
            "  !! DIFFERENT thread pins ({:?} vs {:?}): wall and RSS are NOT comparable.",
            ha.threads, hb.threads
        );
    }
    if ha.cap_secs != hb.cap_secs {
        println!(
            "  !! DIFFERENT caps ({}s vs {}s): dnf counts are NOT comparable.",
            ha.cap_secs, hb.cap_secs
        );
    }
    if ha.args_template != hb.args_template {
        println!(
            "  !! DIFFERENT args ({:?} vs {:?}).",
            ha.args_template, hb.args_template
        );
    }

    let ia: HashMap<&str, &Case> = ca.iter().map(|c| (c.ont.as_str(), c)).collect();
    let ib: HashMap<&str, &Case> = cb.iter().map(|c| (c.ont.as_str(), c)).collect();

    let mut trans: HashMap<(String, String), Vec<&str>> = HashMap::new();
    let mut answer_diff: Vec<&str> = Vec::new();
    let mut answer_same = 0usize;
    let mut faster: Vec<(&str, f64, f64)> = Vec::new();
    let mut slower: Vec<(&str, f64, f64)> = Vec::new();

    for (ont, x) in &ia {
        let Some(y) = ib.get(ont) else { continue };
        if x.outcome != y.outcome {
            trans
                .entry((x.outcome.clone(), y.outcome.clone()))
                .or_default()
                .push(ont);
        }
        // Answer identity: only meaningful where BOTH completed.
        if x.outcome == "ok" && y.outcome == "ok" {
            match (&x.out_sha256, &y.out_sha256) {
                (Some(p), Some(q)) if p == q => answer_same += 1,
                (Some(_), Some(_)) => answer_diff.push(ont),
                _ => {}
            }
            if let (Some(p), Some(q)) = (x.wall_s, y.wall_s) {
                if p > 0.05 {
                    let d = (q - p) / p;
                    if d < -args.wall_tol {
                        faster.push((ont, p, q));
                    } else if d > args.wall_tol {
                        slower.push((ont, p, q));
                    }
                }
            }
        }
    }

    println!("\n## outcome transitions");
    if trans.is_empty() {
        println!("  none");
    }
    let mut tk: Vec<_> = trans.iter().collect();
    tk.sort_by_key(|(_, v)| std::cmp::Reverse(v.len()));
    for ((from, to), onts) in tk {
        let flag = match (from.as_str(), to.as_str()) {
            ("dnf", "ok") | ("err_crash", "ok") => "  <-- RECOVERED",
            ("ok", "dnf") | ("ok", "err_crash") | ("ok", "err_reject") => "  <-- REGRESSION",
            _ => "",
        };
        println!("  {from:>10} -> {:<10} {:>5}{flag}", to, onts.len());
        for o in onts.iter().take(args.top) {
            println!("      {o}");
        }
    }

    println!("\n## answer identity (both completed)");
    // Digest MODE is part of what a digest means. Comparing a raw-stdout digest
    // against a banner-stripped one makes every row differ; comparing two RAW
    // digests makes ~65% of rows differ from timing noise alone (measured: 1133
    // of 1745). Say which regime this reading is in rather than letting the
    // reader assume the strict one.
    match (ha.digest_strip_comments, hb.digest_strip_comments) {
        (true, true) => println!("  digest: banner-stripped (`#` lines excluded) — strict"),
        (false, false) => println!(
            "  digest: RAW stdout — timing banners included, so DIFFERENT is \
             NOT evidence of an answer change (re-run with --digest-strip-comments)"
        ),
        _ => println!(
            "  digest: MODE MISMATCH (A strip={}, B strip={}) — the comparison below \
             is MEANINGLESS; re-run both arms with the same setting",
            ha.digest_strip_comments, hb.digest_strip_comments
        ),
    }
    println!("  identical {answer_same}");
    println!("  DIFFERENT {}", answer_diff.len());
    if answer_diff.is_empty() {
        println!("  => no answer changed anywhere both runs completed.");
    } else {
        println!("  => these need explanation; a subtractive change should be answer-identical:");
        for o in answer_diff.iter().take(args.top) {
            println!("      {o}");
        }
    }

    println!(
        "\n## wall (only where both completed, |delta| > {:.0}%)",
        args.wall_tol * 100.0
    );
    faster.sort_by(|x, y| {
        ((y.1 - y.2) / y.1)
            .partial_cmp(&((x.1 - x.2) / x.1))
            .unwrap()
    });
    slower.sort_by(|x, y| {
        ((y.2 - y.1) / y.1)
            .partial_cmp(&((x.2 - x.1) / x.1))
            .unwrap()
    });
    println!("  faster: {}   slower: {}", faster.len(), slower.len());
    for (o, p, q) in faster.iter().take(args.top) {
        println!(
            "    -{:>5.1}%  {:<20} {:>7.2}s -> {:>7.2}s",
            (p - q) / p * 100.0,
            o,
            p,
            q
        );
    }
    for (o, p, q) in slower.iter().take(args.top) {
        println!(
            "    +{:>5.1}%  {:<20} {:>7.2}s -> {:>7.2}s",
            (q - p) / p * 100.0,
            o,
            p,
            q
        );
    }

    let only_a = ia.keys().filter(|k| !ib.contains_key(*k)).count();
    let only_b = ib.keys().filter(|k| !ia.contains_key(*k)).count();
    if only_a + only_b > 0 {
        println!("\n## coverage mismatch: only in A {only_a}, only in B {only_b}");
    }
    Ok(())
}
