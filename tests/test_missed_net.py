"""Known-answer tests for the MISSED net's own arithmetic.

A net that reports 0 for everything is indistinguishable from a working net, so the
things that must be pinned are the ones whose failure mode is a PLAUSIBLE ZERO:

  * the oracle is the UNION of the two peers -- if the union silently degraded to
    "Konclude only", every pair Konclude under-reports would vanish from MISSED and the
    net would look cleaner than the reasoner is. `ore_ont_9540` is a real instance
    (Konclude 66 pairs, HermiT 71);
  * a CONTESTED oracle must be excluded, not adjudicated. If a disagreeing ontology
    stayed in the total, a peer's error would be booked as rustdl's;
  * an arm that produced NO CLOSURE (timeout, crash, front-end reject) must not be
    scored 0. Scoring it 0 would make "turn answers into timeouts" read as a free win --
    the single most dangerous way for this net to lie about a completeness trade;
  * ΔMISSED must count a scored->unscored transition, for the same reason.

Every assertion below is a known answer computed by hand from the fixture, and the
fixtures deliberately include an asymmetric pair (HermiT-only) so a union that is not a
union FAILS rather than merely losing precision.

Run: python3 -m pytest tests/test_missed_net.py -q
"""

import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _mn(scratch: pathlib.Path):
    """Load missed-net.py with SCRATCH pointed at a tmp dir (it is read at import)."""
    import os

    os.environ["MISSED_NET_SCRATCH"] = str(scratch)
    sys.path.insert(0, str(ROOT / "scripts"))
    return _load("missed_net", ROOT / "scripts" / "missed-net.py")


# ── fixtures ────────────────────────────────────────────────────────────────

A, B, C, D = "http://x#A", "http://x#B", "http://x#C", "http://x#D"


def _owx(pairs, equivs=()):
    body = "".join(
        f'<SubClassOf><Class IRI="{s}"/><Class IRI="{t}"/></SubClassOf>' for s, t in pairs
    )
    body += "".join(
        "<EquivalentClasses>"
        + "".join(f'<Class IRI="{m}"/>' for m in g)
        + "</EquivalentClasses>"
        for g in equivs
    )
    return (
        '<?xml version="1.0"?><Ontology xmlns="http://www.w3.org/2002/07/owl#" '
        'ontologyIRI="http://x">' + body + "</Ontology>"
    )


def _hermit(pairs):
    return "".join(f"SubClassOf( <{s}> <{t}> )\n" for s, t in pairs)


def _rustdl(pairs):
    return "# classes: 4\n# fragment: Horn (x)\n# subsumption: saturation=1 tableau=1\n" + "".join(
        f"direct\t{s}\t{t}\n" for s, t in pairs
    )


def _write(scratch, ont, *, kon=None, her=None, arm=None, arm_name="ARM"):
    for sub, name, body, ext in (
        ("konclude", "konclude", kon, ".owx"),
        ("hermit", "hermit", her, ".owx"),
        (arm_name, arm_name, arm, ".out"),
    ):
        if body is None:
            continue
        d = scratch / "raw" / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{ont}{ext}").write_text(body)


def _cases(onts, outcome="ok"):
    return {o: {"kind": "case", "ont": o, "outcome": outcome} for o in onts}


# ── the union oracle ────────────────────────────────────────────────────────


def test_oracle_is_the_union_not_one_peer(tmp_path):
    """A pair ONLY HermiT reports must count as MISSED. This is the `ore_ont_9540`
    shape: Konclude under-reports, so a Konclude-only oracle hides the miss."""
    mn = _mn(tmp_path)
    ont = "u1"
    # Konclude: A<B. HermiT: A<B and C<D. rustdl: A<B only -> MISSED must be 1.
    _write(
        tmp_path,
        ont,
        kon=_owx([(A, B)]),
        her=_hermit([(A, B), (C, D)]),
        arm=_rustdl([(A, B)]),
    )
    row = mn.one_ontology(ont, "ARM", _cases([ont]), _cases([ont]), _cases([ont]))
    assert row["status"] == "peer_disagreement", row  # the peers differ, so it is contested
    assert row["MISSED"] == 1, row
    # and the oracle really did take the union, not just one side
    assert row["oracle_closure"] == 2, row


def test_agreeing_peers_are_scored_and_missed_is_exact(tmp_path):
    mn = _mn(tmp_path)
    ont = "u2"
    # both peers: A<B, B<C  (closure adds A<C = 3 pairs). rustdl: A<B only.
    _write(
        tmp_path,
        ont,
        kon=_owx([(A, B), (B, C)]),
        her=_hermit([(A, B), (B, C)]),
        arm=_rustdl([(A, B)]),
    )
    row = mn.one_ontology(ont, "ARM", _cases([ont]), _cases([ont]), _cases([ont]))
    assert row["status"] == "scored", row
    assert (row["oracle_closure"], row["arm_closure"]) == (3, 1), row
    assert row["MISSED"] == 2 and row["FP"] == 0, row


def test_contested_ontology_is_excluded_from_the_total(tmp_path):
    mn = _mn(tmp_path)
    rows = [
        {"ont": "a", "status": "scored", "MISSED": 5, "FP": 0, "oracle_closure": 9},
        {"ont": "b", "status": "peer_disagreement", "MISSED": 900, "FP": 0},
        {"ont": "c", "status": "arm_no_closure"},
        {"ont": "d", "status": "no_oracle"},
    ]
    s = mn.summarise(rows, "ARM")
    assert s["MISSED_total"] == 5, s          # 900 must NOT be in the total
    assert s["peer_disagreement"] == 1, s
    assert s["scored"] == 1, s
    assert s["status"]["arm_no_closure"] == 1 and s["status"]["no_oracle"] == 1, s


# ── the dangerous zero ──────────────────────────────────────────────────────


def test_arm_that_did_not_finish_is_not_scored_zero(tmp_path):
    """A DNF arm has no closure. Booking it MISSED=0 would make a change that trades
    answers for timeouts read as free."""
    mn = _mn(tmp_path)
    ont = "u3"
    _write(tmp_path, ont, kon=_owx([(A, B)]), her=_hermit([(A, B)]))
    row = mn.one_ontology(
        ont, "ARM", _cases([ont]), _cases([ont]), _cases([ont], outcome="dnf")
    )
    assert row["status"] == "arm_no_closure", row
    assert "MISSED" not in row, row


def test_no_oracle_when_both_peers_fail(tmp_path):
    mn = _mn(tmp_path)
    ont = "u4"
    _write(tmp_path, ont, arm=_rustdl([(A, B)]))
    row = mn.one_ontology(
        ont, "ARM", _cases([ont], outcome="dnf"), _cases([ont], outcome="dnf"), _cases([ont])
    )
    assert row["status"] == "no_oracle", row


def test_empty_peer_output_is_not_an_oracle(tmp_path):
    """Konclude exits 0 on junk and still writes a Thing/Nothing-only hierarchy. That
    must not become an oracle asserting nothing (which would read MISSED=0 forever)."""
    mn = _mn(tmp_path)
    ont = "u5"
    _write(
        tmp_path,
        ont,
        kon='<?xml version="1.0"?><Ontology xmlns="http://www.w3.org/2002/07/owl#">'
        '<Prefix name="" IRI="http://www.w3.org/2002/07/owl#"/>'
        '<SubClassOf><Class abbreviatedIRI="owl:Nothing"/>'
        '<Class abbreviatedIRI="owl:Thing"/></SubClassOf></Ontology>',
        arm=_rustdl([(A, B)]),
    )
    row = mn.one_ontology(ont, "ARM", _cases([ont]), _cases([ont], outcome="dnf"), _cases([ont]))
    assert row["konclude"] == "EMPTY", row
    assert row["status"] == "no_oracle", row


# ── ΔMISSED ─────────────────────────────────────────────────────────────────


def test_delta_reports_losses_gains_and_newly_unscored(tmp_path):
    mn = _mn(tmp_path)
    base = [
        {"ont": "a", "status": "scored", "MISSED": 0},
        {"ont": "b", "status": "scored", "MISSED": 7},
        {"ont": "c", "status": "scored", "MISSED": 3},
    ]
    p = tmp_path / "base.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in base))
    now = [
        {"ont": "a", "status": "scored", "MISSED": 4},       # lost 4
        {"ont": "b", "status": "scored", "MISSED": 2},       # gained 5
        {"ont": "c", "status": "arm_no_closure"},            # regressed to a timeout
    ]
    d = mn.delta(now, str(p))
    assert d["delta_MISSED_total"] == 4 - 5, d
    assert d["onts_lost_pairs"] == 1 and d["onts_gained_pairs"] == 1, d
    assert d["n_newly_unscored"] == 1 and d["newly_unscored"][0][0] == "c", d


# ── population selection ────────────────────────────────────────────────────


def test_selection_is_seeded_and_reproducible(tmp_path):
    mn = _mn(tmp_path)
    rows = []
    for i in range(300):
        rows.append(
            {
                "ont": f"o{i:03d}",
                "outcome": "ok",
                "fragment": ["pure-EL", "Horn", "out-of-EL"][i % 3],
                "sub_tableau": 1 if i % 10 == 0 else 0,
                "probe_tableau": 0,
            }
        )
    man = tmp_path / "m.jsonl"
    man.write_text("".join(json.dumps(r) + "\n" for r in rows))

    class Args:
        manifest = str(man)
        n = 60
        n_tableau = 20
        seed = 1234
        out = str(tmp_path / "pop.txt")

    mn.cmd_select(Args())
    first = pathlib.Path(Args.out).read_text()
    meta = json.loads((tmp_path / "pop.meta.json").read_text())
    mn.cmd_select(Args())
    assert pathlib.Path(Args.out).read_text() == first, "same seed must give the same sample"
    assert meta["n_selected"] == 60, meta
    # the tableau over-sample took ALL 30 available? no: capped at n_tableau=20.
    assert sum(v for k, v in meta["sample_strata"].items() if k.endswith("/search")) == 20, meta
    # and all three fragments are represented among the no-tableau rows
    assert len([k for k in meta["sample_strata"] if k.endswith("/nosearch")]) == 3, meta

    class Args2(Args):
        seed = 999
        out = str(tmp_path / "pop2.txt")

    mn.cmd_select(Args2())
    assert pathlib.Path(Args2.out).read_text() != first, "a different seed must differ"
