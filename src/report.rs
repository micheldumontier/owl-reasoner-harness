//! `report`: aggregate a run. Enforces two reporting rules that exist because the
//! opposite produced retracted numbers.

use crate::model::{Case, Header};
use clap::Args;
use std::fs;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;

#[derive(Args)]
pub struct ReportArgs {
    pub run: PathBuf,
    /// Comma-separated caps (seconds) at which to derive would-miss counts. Only
    /// values <= the run's own cap are meaningful; larger ones are refused.
    #[arg(long, default_value = "1,5,10,30")]
    pub at: String,
    #[arg(long, default_value_t = 25)]
    pub top_rss: usize,
    /// Also write summary.json / cases.csv / report.md beside the run file.
    #[arg(long)]
    pub write: bool,
}

pub fn load(p: &PathBuf) -> Result<(Header, Vec<Case>), String> {
    let f = fs::File::open(p).map_err(|e| format!("opening {}: {e}", p.display()))?;
    let mut header = None;
    let mut cases = Vec::new();
    for line in BufReader::new(f).lines().map_while(Result::ok) {
        if line.trim().is_empty() {
            continue;
        }
        if header.is_none() {
            if let Ok(h) = serde_json::from_str::<Header>(&line) {
                header = Some(h);
                continue;
            }
        }
        if let Ok(c) = serde_json::from_str::<Case>(&line) {
            cases.push(c);
        }
    }
    header
        .map(|h| (h, cases))
        .ok_or_else(|| "no header record; is this a harness run file?".to_string())
}

pub fn main(a: ReportArgs) -> Result<(), String> {
    let (h, cases) = load(&a.run)?;

    println!("# run: {}", a.run.display());
    println!("## provenance (compare this FIRST when two runs disagree)");
    println!("  reasoner     {}", h.reasoner);
    println!("  sha256       {}", h.sha256);
    println!(
        "  version      {}",
        h.version.as_deref().unwrap_or("<none>")
    );
    if let Some(m) = &h.marker_checked {
        println!("  marker       {m} (verified present before the run)");
    }
    println!("  args         {}", h.args_template);
    println!(
        "  threads      {}   <- peak RSS is uninterpretable without this",
        h.threads
            .map(|t| t.to_string())
            .unwrap_or_else(|| "UNPINNED".into())
    );
    println!("  cap          {}s", h.cap_secs);
    println!("  host cores   {}", h.host_cores);

    let n = cases.len();
    let count = |o: &str| cases.iter().filter(|c| c.outcome == o).count();
    let (ok, dnf, rej, crash, skip) = (
        count("ok"),
        count("dnf"),
        count("err_reject"),
        count("err_crash"),
        count("skipped"),
    );

    println!(
        "\n## outcomes ({n} records of {} candidates)",
        h.n_candidates
    );
    if let (Some(req), Some(res)) = (h.only_requested, h.only_resolved) {
        println!(
            "  [--only mode: {req} requested, {res} resolved, {} missing]",
            req.saturating_sub(res)
        );
    }
    for (label, c) in [
        ("ok", ok),
        ("dnf", dnf),
        ("err_reject", rej),
        ("err_crash", crash),
        ("skipped", skip),
    ] {
        if c > 0 {
            // RULE 3: never print a dnf count without the cap it was measured at.
            // A `dnf` without its cap was once read as "does not terminate"; 55 of 312
            // "DNF" ontologies later completed at a larger budget — that misreading drove
            // a retracted spec, plan, and soundness argument.
            if label == "dnf" {
                println!(
                    "  {label:<11} {c:>6}  ({:.1}%)  [cap {}s — exceeded cap, NOT 'does not terminate']",
                    pct(c, n),
                    h.cap_secs
                );
            } else {
                println!("  {label:<11} {c:>6}  ({:.1}%)", pct(c, n));
            }
        }
    }
    if rej > 0 {
        println!(
            "  NOTE err_reject is a FRONT-END rejection, a different and usually cheaper\n       \
             problem than dnf. Do not merge the two into one \"DNF\" figure."
        );
    }

    // RULE 1: a share whose denominator silently excluded items is not a share.
    if skip > 0 {
        println!("\n## EXCLUDED SET ({skip}) — any percentage above is over the INCLUDED set");
        for c in cases.iter().filter(|c| c.outcome == "skipped").take(20) {
            println!(
                "  {:<20} {}",
                c.ont,
                c.skip_reason.as_deref().unwrap_or("?")
            );
        }
        println!(
            "  A per-item cap is NOT a neutral sampler: it selects against the largest\n  \
             items. A corpus share computed with the largest items missing came out 3x\n  \
             too high once and had to be retracted."
        );
    }

    println!("\n## would-miss at a smaller cap (derived from recorded wall; no re-run)");
    let unfinished = dnf + crash;
    for t in a.at.split(',').filter_map(|s| s.trim().parse::<f64>().ok()) {
        if t > h.cap_secs as f64 {
            println!(
                "  at {t}s: REFUSED — above this run's own {}s cap",
                h.cap_secs
            );
            continue;
        }
        let slow = cases
            .iter()
            .filter(|c| c.outcome == "ok" && c.wall_s.unwrap_or(0.0) > t)
            .count();
        println!(
            "  at {:>4}s: {:>6}   ({} slow + {} unfinished)",
            t,
            slow + unfinished,
            slow,
            unfinished
        );
    }

    // RULE 2: never print RSS without the thread pin.
    println!(
        "\n## peak RSS (threads = {})",
        match h.threads {
            Some(t) => t.to_string(),
            None => "UNPINNED — treat these numbers as this host's fan-out, not per-ontology cost"
                .into(),
        }
    );
    let mut by_rss: Vec<&Case> = cases.iter().filter(|c| c.peak_rss_kb.is_some()).collect();
    by_rss.sort_by_key(|c| std::cmp::Reverse(c.peak_rss_kb.unwrap_or(0)));
    for c in by_rss.iter().take(a.top_rss) {
        println!(
            "  {:<20} {:<11} {:>8.1}s {:>9.2} GB",
            c.ont,
            c.outcome,
            c.wall_s.unwrap_or(0.0),
            gb(c.peak_rss_kb.unwrap_or(0))
        );
    }
    println!("  --- bands ---");
    for g in [1.0f64, 4.0, 16.0, 64.0] {
        let c = by_rss
            .iter()
            .filter(|c| gb(c.peak_rss_kb.unwrap_or(0)) > g)
            .count();
        println!("  > {g:>4} GB: {c}");
    }

    // The actionable cross-tab: cheap to convert, expensive to run = a local cause.
    println!(
        "\n## candidates: unfinished but SMALL input (local cause likelier than a search blowup)"
    );
    let mut cands: Vec<&Case> = cases
        .iter()
        .filter(|c| {
            (c.outcome == "dnf" || c.outcome == "err_crash")
                && c.bytes.unwrap_or(u64::MAX) < 20_000_000
        })
        .collect();
    cands.sort_by_key(|c| std::cmp::Reverse(c.peak_rss_kb.unwrap_or(0)));
    if cands.is_empty() {
        println!("  (none)");
    }
    for c in cands.iter().take(20) {
        println!(
            "  {:<20} {:>6.1} MB input  {:>9.2} GB peak",
            c.ont,
            c.bytes.unwrap_or(0) as f64 / 1_048_576.0,
            gb(c.peak_rss_kb.unwrap_or(0))
        );
    }

    if a.write {
        let dir = a.run.parent().unwrap_or(std::path::Path::new("."));
        let csv = dir.join("cases.csv");
        let mut s = String::from("ont,outcome,wall_s,peak_rss_kb,bytes,out_sha256,out_lines\n");
        for c in &cases {
            s.push_str(&format!(
                "{},{},{},{},{},{},{}\n",
                c.ont,
                c.outcome,
                c.wall_s.map(|v| v.to_string()).unwrap_or_default(),
                c.peak_rss_kb.map(|v| v.to_string()).unwrap_or_default(),
                c.bytes.map(|v| v.to_string()).unwrap_or_default(),
                c.out_sha256.clone().unwrap_or_default(),
                c.out_lines.map(|v| v.to_string()).unwrap_or_default(),
            ));
        }
        fs::write(&csv, s).map_err(|e| e.to_string())?;
        println!("\nwrote {}", csv.display());
    }
    Ok(())
}

fn pct(a: usize, b: usize) -> f64 {
    if b == 0 {
        0.0
    } else {
        a as f64 / b as f64 * 100.0
    }
}
fn gb(kb: u64) -> f64 {
    kb as f64 / 1_048_576.0
}
