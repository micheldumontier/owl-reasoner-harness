//! Record types. One `Header` then one `Case` per ontology, streamed as JSONL so
//! partial progress survives an interruption (a buffered pipeline lost a whole
//! sweep once when an outer timeout killed the loop).

use serde::{Deserialize, Serialize};

/// Outcome derived from the child's **exit status**, never from parsing its output.
///
/// A row-count heuristic once scored two ontologies "complete" because they had
/// streamed partial output before being killed at the cap. Exit codes do not lie.
///
/// `ErrReject` is kept distinct from `Dnf` deliberately: a front-end rejection
/// (unsupported construct) is a different and usually far cheaper problem than a
/// reasoning blowup. Collapsing them is what makes a DNF roster unactionable.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Outcome {
    Ok,
    Dnf,
    ErrReject,
    ErrCrash,
    Skipped,
}

impl Outcome {
    /// `timeout(1)` reports 124 when it kills the child; a signal death shows up as
    /// `None` from `ExitStatus::code()`.
    pub fn from_status(code: Option<i32>, cap_code: i32) -> Self {
        match code {
            Some(0) => Outcome::Ok,
            Some(c) if c == cap_code => Outcome::Dnf,
            Some(_) => Outcome::ErrReject,
            None => Outcome::ErrCrash,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Outcome::Ok => "ok",
            Outcome::Dnf => "dnf",
            Outcome::ErrReject => "err_reject",
            Outcome::ErrCrash => "err_crash",
            Outcome::Skipped => "skipped",
        }
    }
}

/// The reproducibility contract. When two runs disagree, compare headers first —
/// in practice most "behaviour changes" turned out to be a different binary, a
/// different thread pin, or a different cap.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Header {
    pub kind: String,
    pub reasoner: String,
    /// sha256 of the reasoner binary. This is the field that catches a stale or
    /// instrumented build being mistaken for the real one.
    pub sha256: String,
    pub version: Option<String>,
    /// If `--require-marker` was used, the marker that was found in the binary.
    pub marker_checked: Option<String>,
    pub args_template: String,
    pub threads: Option<usize>,
    pub cap_secs: u64,
    pub max_bytes: Option<u64>,
    pub corpus: String,
    pub n_candidates: usize,
    pub host_cores: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Case {
    pub kind: String,
    pub ont: String,
    pub outcome: String,
    /// Wall seconds. Recorded even for `Dnf`/`ErrCrash` rows so that any threshold
    /// below the cap is derivable later without re-running the sweep.
    pub wall_s: Option<f64>,
    /// Peak RSS in kB. Meaningless without `Header::threads`; `report` refuses to
    /// print RSS without it.
    pub peak_rss_kb: Option<u64>,
    pub bytes: Option<u64>,
    /// Why a `Skipped` row was skipped — skips are counted, never silently dropped.
    pub skip_reason: Option<String>,
    /// Optional digest of the reasoner's stdout, for answer-identity comparison.
    pub out_sha256: Option<String>,
    pub out_lines: Option<usize>,
}
