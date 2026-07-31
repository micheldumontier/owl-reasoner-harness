//! Reasoner-agnostic corpus measurement harness. See README.md for why each
//! discipline feature exists — every one of them prevents a specific measurement
//! failure that actually happened.

mod compare;
mod model;
mod report;
mod run;

use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(
    name = "owl-corpus-harness",
    about = "Measure a reasoner over an ontology corpus: fingerprint, run, report, compare"
)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Measure a reasoner over a corpus, streaming one JSONL record per ontology.
    Run(run::RunArgs),
    /// Aggregate a run into a summary, a CSV of cases, and a markdown report.
    Report(report::ReportArgs),
    /// Diff two runs: outcome transitions and (optionally) answer identity.
    Compare(compare::CompareArgs),
}

fn main() -> std::process::ExitCode {
    let cli = Cli::parse();
    let r = match cli.cmd {
        Cmd::Run(a) => run::main(a),
        Cmd::Report(a) => report::main(a),
        Cmd::Compare(a) => compare::main(a),
    };
    match r {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("error: {e}");
            std::process::ExitCode::FAILURE
        }
    }
}
