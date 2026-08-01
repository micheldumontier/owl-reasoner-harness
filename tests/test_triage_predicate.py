"""Known-answer tests for the per-format content predicate, positive AND negative.

Both bugs this guards were MINE, not a reasoner's, and both produced a plausible
number rather than an error:
  * a bare IRI= scan matched <Prefix name="" IRI="..."/>, so Konclude's 896-byte
    Thing/Nothing-only output read as CLASSIFIED;
  * the predicate knew only OWL/XML and tab-separated text, so HermiT's functional
    -syntax taxonomy -- a 4 MB file of SubClassOf( <iri> <iri> ) lines -- read as
    EMPTY, misreporting 110 of 192 HermiT runs as front-end failures.
A predicate validated on ONE format is not validated. Run: python3 -m pytest tests/
"""
import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(
    "triage", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "triage.py"
)
triage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(triage)

HERMIT_POS = "SubClassOf( <http://x/A> <http://x/B> )\n"
HERMIT_EQUIV = "EquivalentClasses( <http://x/C> <http://x/D> )\n"
HERMIT_TRIVIAL = (
    "SubClassOf( <http://www.w3.org/2002/07/owl#Nothing> "
    "<http://www.w3.org/2002/07/owl#Thing> )\n"
)
KONCLUDE_EMPTY = (
    '<?xml version="1.0"?><Ontology xmlns="http://www.w3.org/2002/07/owl#">'
    '<Prefix name="" IRI="http://www.w3.org/2002/07/owl#"/>'
    '<Declaration><Class IRI="http://www.w3.org/2002/07/owl#Thing"/></Declaration>'
    "</Ontology>"
)
KONCLUDE_POS = KONCLUDE_EMPTY.replace(
    "</Ontology>", '<Declaration><Class IRI="http://x/A"/></Declaration></Ontology>'
)


def _w(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_hermit_subclassof_is_classified(tmp_path):
    assert triage.declared_real_class(_w(tmp_path, "h.owx", HERMIT_POS), "hermit")


def test_hermit_equivalentclasses_is_classified(tmp_path):
    assert triage.declared_real_class(_w(tmp_path, "h.owx", HERMIT_EQUIV), "hermit")


def test_hermit_empty_is_not_classified(tmp_path):
    assert not triage.declared_real_class(_w(tmp_path, "h.owx", ""), "hermit")


def test_hermit_thing_nothing_only_is_not_classified(tmp_path):
    assert not triage.declared_real_class(_w(tmp_path, "h.owx", HERMIT_TRIVIAL), "hermit")


def test_konclude_real_class_is_classified(tmp_path):
    assert triage.declared_real_class(_w(tmp_path, "k.owx", KONCLUDE_POS), "konclude")


def test_konclude_prefix_iri_does_not_count_as_a_class(tmp_path):
    # The exact 896-byte shape Konclude emits for a nonexistent or junk input.
    assert not triage.declared_real_class(_w(tmp_path, "k.owx", KONCLUDE_EMPTY), "konclude")


def test_rustdl_tab_rows_are_classified(tmp_path):
    assert triage.declared_real_class(_w(tmp_path, "r.txt", "# banner\ndirect\tA\tB\n"), "rustdl")


def test_rustdl_banner_only_is_not_classified(tmp_path):
    assert not triage.declared_real_class(_w(tmp_path, "r.txt", "# banner only\n"), "rustdl")


def test_unknown_format_raises_rather_than_guessing(tmp_path):
    # Silently returning False for an unhandled format is how the HermiT bug
    # produced 110 wrong verdicts instead of an error.
    try:
        triage.declared_real_class(_w(tmp_path, "x", "whatever"), "nonesuch")
    except ValueError:
        return
    raise AssertionError("unknown format must raise, not guess")
