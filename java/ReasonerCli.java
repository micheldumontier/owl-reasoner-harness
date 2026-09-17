// Uniform OWLAPI taxonomy driver for the reasoners that ship no usable CLI.
//
// WHY THIS EXISTS. `robot reason` REFUSES any ontology containing an unsatisfiable
// class: it exits 1 and writes NO output file. The check is ROBOT's own
// (ReasonerHelper), so it is reasoner-independent -- verified on pizza.ofn, where
// HermiT, ELK and JFact each exit 1 with no output, against a clean control (ro.ofn)
// where JFact exits 0 and writes 99 axioms. At least 130 of 1,783 ORE ontologies
// (7.3%) carry an unsatisfiable class or are inconsistent, so driving a benchmark
// through `robot reason` silently drops them. That figure is a FLOOR: it is counted
// from KM's own unsatisfiable reports, and KM's unsat lists are sound but incomplete.
//
// HermiT is not affected in this repo because run-hermit.sh already calls HermiT's
// own CLI (org.semanticweb.HermiT.cli.CommandLine -c), which handles pizza fine.
// ELK and JFact have no equivalent: robot.jar carries org/semanticweb/elk/owlapi/
// but no elk/cli, and JFact is an OWLAPI library (JFactFactory, 2016) that has never
// had a CLI. This driver is what lets them be measured at all.
//
// OUTPUT FORMAT is deliberately byte-compatible with HermiT's `-c` taxonomy --
//   SubClassOf( <sub> <sup> )
//   EquivalentClasses( <a> <b> ... )
// with unsatisfiable classes emitted as an EquivalentClasses group containing
// owl:Nothing, exactly as HermiT does -- so scripts/normalise.py --format hermit
// parses every reasoner driven here with no new parser. Do NOT "improve" this format
// without changing parse_hermit in the same commit.
//
//   javac -cp robot.jar ReasonerCli.java
//   java -cp robot.jar:. ReasonerCli <elk|jfact|hermit> <ontology> <out>
//
// Exit: 0 answered, 2 bad usage / unknown reasoner, 3 the reasoner declined the
// input (unsupported construct -- an honest refusal, NOT a failure), 1 anything else.
import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.model.OWLClass;
import org.semanticweb.owlapi.model.OWLOntology;
import org.semanticweb.owlapi.model.OWLOntologyManager;
import org.semanticweb.owlapi.reasoner.InferenceType;
import org.semanticweb.owlapi.reasoner.Node;
import org.semanticweb.owlapi.reasoner.NodeSet;
import org.semanticweb.owlapi.reasoner.OWLReasoner;
import org.semanticweb.owlapi.reasoner.OWLReasonerFactory;
import org.semanticweb.owlapi.reasoner.UnsupportedEntailmentTypeException;

public final class ReasonerCli {

  public static void main(String[] args) {
    if (args.length < 3) {
      System.err.println("usage: ReasonerCli <elk|jfact|hermit> <ontology> <out>");
      System.exit(2);
    }
    try {
      run(args[0].toLowerCase(), new File(args[1]), new File(args[2]));
    } catch (UnsupportedEntailmentTypeException | UnsupportedOperationException e) {
      // The reasoner declining a construct it does not claim to support is sound
      // behaviour, and must be distinguishable from a crash. See the four-valued
      // outcome taxonomy: declined != failed.
      System.err.println("declined: " + e);
      System.exit(3);
    } catch (Throwable t) {
      // A reasoner may report an unsupported construct as an ordinary exception
      // rather than the typed UnsupportedEntailmentTypeException -- HermiT raises
      // `IllegalArgumentException: A SWRL rule uses a built-in atom, but built-in
      // atoms are not supported yet.` That is a DECLINE, not a crash, and pooling it
      // with failures makes a reasoner look broken for being honest.
      //
      // Matching on message text is a heuristic, so it is kept DELIBERATELY NARROW:
      // only an explicit "not supported"/"unsupported" phrase qualifies, and the full
      // message is always printed so a misclassification is auditable. Widening this
      // would start hiding real defects, which is the failure mode that matters.
      String m = String.valueOf(t.getMessage()).toLowerCase();
      boolean declined = m.contains("not supported") || m.contains("unsupported");
      System.err.println((declined ? "declined: " : "failed: ") + t);
      System.exit(declined ? 3 : 1);
    }
  }

  private static void run(String which, File in, File out) throws Exception {
    OWLOntologyManager m = OWLManager.createOWLOntologyManager();
    OWLOntology onto = m.loadOntologyFromOntologyDocument(in);

    OWLReasonerFactory factory;
    switch (which) {
      case "elk":
        factory = new org.semanticweb.elk.owlapi.ElkReasonerFactory();
        break;
      case "jfact":
        factory = new uk.ac.manchester.cs.jfact.JFactFactory();
        break;
      case "hermit":
        factory = new org.semanticweb.HermiT.ReasonerFactory();
        break;
      default:
        System.err.println("unknown reasoner: " + which);
        System.exit(2);
        return;
    }

    OWLReasoner r = factory.createReasoner(onto);
    r.precomputeInferences(InferenceType.CLASS_HIERARCHY);

    File parent = out.getParentFile();
    if (parent != null) {
      parent.mkdirs();
    }

    try (PrintWriter w = new PrintWriter(out, "UTF-8")) {
      // Unsatisfiable classes first, as one owl:Nothing group -- HermiT's own shape.
      // Emitted even when the ontology is inconsistent, where EVERY class is
      // unsatisfiable; that is a real answer, not a reason to refuse the file.
      Node<OWLClass> bottom = r.getEquivalentClasses(
          m.getOWLDataFactory().getOWLNothing());
      List<String> unsat = new ArrayList<>();
      for (OWLClass c : bottom.getEntities()) {
        if (!c.isOWLNothing() && !c.isOWLThing()) {
          unsat.add(c.getIRI().toString());
        }
      }
      if (!unsat.isEmpty()) {
        StringBuilder sb = new StringBuilder(
            "EquivalentClasses( <http://www.w3.org/2002/07/owl#Nothing>");
        for (String u : unsat) {
          sb.append(" <").append(u).append(">");
        }
        w.println(sb.append(" )"));
      }

      for (OWLClass c : onto.getClassesInSignature()) {
        if (c.isOWLNothing() || c.isOWLThing()) {
          continue;
        }
        // An unsatisfiable class subsumes everything; its rows are trivially true and
        // are excluded on both sides when scoring, so do not emit them here either.
        if (unsat.contains(c.getIRI().toString())) {
          continue;
        }

        // ONE ROW PER EQUIVALENCE CLASS, NOT ONE PER MEMBER. Equivalent classes form
        // a node; emitting from every member restates the same entailment once per
        // member and prints each group twice. On pizza that inflated the taxonomy by
        // 16 rows (SpicyPizzaEquivalent = SpicyPizza, VegetarianPizzaEquivalent2 =
        // VegetarianPizzaEquivalent1) -- not extra entailments, just a different
        // representative. Defer to the node's representative, as HermiT's CLI does.
        Node<OWLClass> eq = r.getEquivalentClasses(c);
        Set<OWLClass> peers = eq.getEntities();
        if (peers.size() > 1 && !c.equals(eq.getRepresentativeElement())) {
          continue;
        }
        if (peers.size() > 1) {
          StringBuilder sb = new StringBuilder("EquivalentClasses(");
          boolean any = false;
          for (OWLClass p : peers) {
            if (!p.isOWLNothing() && !p.isOWLThing()) {
              sb.append(" <").append(p.getIRI()).append(">");
              any = true;
            }
          }
          if (any) {
            w.println(sb.append(" )"));
          }
        }

        NodeSet<OWLClass> parents = r.getSuperClasses(c, true);
        for (Node<OWLClass> node : parents.getNodes()) {
          for (OWLClass p : node.getEntities()) {
            // owl:Thing parents are SUPPRESSED, matching HermiT's CLI. Counting
            // Thing rows is a recorded trap in this project: 73% of an apparent
            // ~1,795-row gap against another reasoner was this convention alone.
            if (p.isOWLNothing() || p.isOWLThing()) {
              continue;
            }
            w.println("SubClassOf( <" + c.getIRI() + "> <" + p.getIRI() + "> )");
          }
        }
      }
    }
    r.dispose();
  }
}
