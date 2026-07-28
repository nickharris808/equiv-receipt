"""Run an external SAT solver in proof-emitting mode and keep the proof.

The bundled :mod:`minisolve` is a demonstration. It cannot reach the instances a
real equivalence check produces, and it says so. This module lets you point the
package at a solver that can — CaDiCaL, Kissat, or anything else that speaks
DIMACS and writes a DRAT proof.

**The trust story does not change, which is the entire point.** The external
solver is not trusted. It is asked for a proof, the proof goes into the receipt,
and the proof is re-checked by :func:`equiv_receipt.forward_rup_check` — code you
can read — before any verdict is asserted. Swapping in a faster solver buys reach,
not credibility. A solver that lies produces a proof that fails to check.

Two consequences worth stating plainly:

* If the solver reports UNSAT but emits no usable proof, this raises rather than
  returning a receipt. An unproven UNSAT is a claim, and this package does not
  package claims.
* If the solver is not on PATH or exits in a way that is not "SAT" or "UNSAT",
  that is an error, not a verdict. Silence is never read as agreement.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .dimacs import to_dimacs
from .rup import forward_rup_check

Clause = List[int]

#: Exit codes the DIMACS convention assigns. Solvers that predate it, or ignore
#: it, are handled by falling back to the ``s SATISFIABLE`` line.
SAT_EXIT, UNSAT_EXIT = 10, 20


class SolverError(RuntimeError):
    """The external solver could not be used, or did not answer usefully."""


class Solver:
    """An external SAT solver, described by how to invoke it.

    ``argv`` is a template list. ``{cnf}`` is replaced by the input path and
    ``{drat}`` by the path the solver should write its proof to. For example::

        Solver("cadical", ["cadical", "-q", "--no-binary", "{cnf}", "{drat}"])
        Solver("kissat",  ["kissat", "-q", "--relaxed", "{cnf}", "{drat}"])

    Nothing here is specific to those two; any solver with a DIMACS-in,
    DRAT-out interface works, and the template is the whole configuration.
    """

    def __init__(self, name: str, argv: Sequence[str], *, timeout: float = 300.0):
        if not any("{cnf}" in a for a in argv):
            raise ValueError("argv template must contain {cnf}")
        if not any("{drat}" in a for a in argv):
            raise ValueError("argv template must contain {drat} — a solver that "
                             "emits no proof cannot be used here, because the "
                             "proof is the product")
        self.name = name
        self.argv = list(argv)
        self.timeout = timeout

    @property
    def executable(self) -> str:
        return self.argv[0]

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def version(self) -> str:
        """Best-effort version string, recorded in the receipt for provenance.

        Provenance only — nothing is trusted on the strength of it. If the solver
        will not report a version, that is not an error.
        """
        try:
            out = subprocess.run([self.executable, "--version"], capture_output=True,
                                 text=True, timeout=10)
            return (out.stdout or out.stderr).strip().splitlines()[0][:80]
        except (OSError, subprocess.SubprocessError, IndexError):
            return ""

    def run(self, cnf_text: str, workdir: Optional[str] = None) -> Dict:
        """Solve ``cnf_text``. Returns ``{"unsat", "drat", "model", "raw_exit"}``.

        Raises :class:`SolverError` if the solver is missing, times out, or gives
        an answer that cannot be read. None of those are verdicts.
        """
        if not self.available():
            raise SolverError(
                f"{self.executable!r} is not on PATH. Install it, or pass a "
                f"Solver(...) describing one that is.")

        tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="equiv-"))
        tmp.mkdir(parents=True, exist_ok=True)
        cnf, drat = tmp / "input.cnf", tmp / "proof.drat"
        cnf.write_text(cnf_text, encoding="utf-8")
        argv = [a.replace("{cnf}", str(cnf)).replace("{drat}", str(drat))
                for a in self.argv]
        try:
            out = subprocess.run(argv, capture_output=True, text=True,
                                 timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise SolverError(f"{self.name} exceeded {self.timeout}s") from exc
        except OSError as exc:
            raise SolverError(f"could not run {self.name}: {exc}") from exc

        stdout = out.stdout or ""
        unsat = out.returncode == UNSAT_EXIT or "s UNSATISFIABLE" in stdout
        sat = out.returncode == SAT_EXIT or "s SATISFIABLE" in stdout
        if unsat and sat:                       # contradictory; refuse to guess
            raise SolverError(f"{self.name} reported both SAT and UNSAT")
        if not (unsat or sat):
            tail = (stdout + out.stderr)[-300:].strip()
            raise SolverError(
                f"{self.name} exited {out.returncode} without reporting SAT or "
                f"UNSAT. This is an error, not a verdict.\n{tail}")

        proof = ""
        if unsat:
            if not drat.exists():
                raise SolverError(
                    f"{self.name} reported UNSAT but wrote no proof to {drat}. "
                    f"An unproven UNSAT is a claim, and this package does not "
                    f"package claims — check the argv template emits a text DRAT "
                    f"proof (CaDiCaL needs --no-binary).")
            proof = drat.read_text(encoding="utf-8", errors="replace")
            if not proof.strip():
                raise SolverError(f"{self.name} wrote an empty proof file")
            if "\x00" in proof[:4096]:
                raise SolverError(
                    f"{self.name} appears to have written a BINARY proof. This "
                    f"checker reads text DRAT; add the solver's flag for text "
                    f"output (CaDiCaL: --no-binary, Kissat: --no-binary).")

        return {"unsat": unsat, "drat": proof, "model": _parse_model(stdout),
                "raw_exit": out.returncode, "workdir": str(tmp)}


def _parse_model(stdout: str) -> Dict[int, bool]:
    """Read ``v`` lines of a DIMACS model. Empty if the solver printed none."""
    model: Dict[int, bool] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("v "):
            continue
        for tok in line[2:].split():
            try:
                lit = int(tok)
            except ValueError:
                continue
            if lit:
                model[abs(lit)] = lit > 0
    return model


#: Solvers this package knows how to invoke out of the box. Naming them is
#: interoperability, not endorsement: each is used only as an untrusted proof
#: source, and its output is re-checked here before anything is asserted.
KNOWN: Dict[str, List[str]] = {
    "cadical": ["cadical", "-q", "--no-binary", "{cnf}", "{drat}"],
    "kissat": ["kissat", "-q", "--no-binary", "{cnf}", "{drat}"],
    "minisat": ["minisat", "-verb=0", "{cnf}", "{drat}"],
}


def known_solver(name: str, **kw) -> Solver:
    if name not in KNOWN:
        raise ValueError(f"unknown solver {name!r}; known: {sorted(KNOWN)}. "
                         f"Any DIMACS-in/DRAT-out solver works — construct a "
                         f"Solver(name, argv) with your own template.")
    return Solver(name, KNOWN[name], **kw)


def detect(**kw) -> Optional[Solver]:
    """The first known solver present on PATH, or None. Never guesses further."""
    env = os.environ.get("EQUIV_RECEIPT_SOLVER")
    if env:
        parts = env.split()
        if len(parts) == 1 and parts[0] in KNOWN:
            return known_solver(parts[0], **kw)
        return Solver(Path(parts[0]).name, parts, **kw)
    for name in KNOWN:
        s = known_solver(name, **kw)
        if s.available():
            return s
    return None


def refute(clauses: Sequence[Clause], solver: Optional[Solver] = None, **kw) -> Dict:
    """Refute ``clauses`` with an external solver. Same result shape as ``minisolve.refute``.

    The returned proof has already been re-checked here, so a solver that emits a
    proof this package cannot verify is reported as such rather than passed on to
    become someone else's problem later.
    """
    solver = solver or detect(**kw)
    if solver is None:
        raise SolverError(
            "no external SAT solver found on PATH. Set EQUIV_RECEIPT_SOLVER to a "
            "command template, or pass Solver(...). Known: " + ", ".join(sorted(KNOWN)))
    res = solver.run(to_dimacs(list(clauses)))
    out = {"unsat": res["unsat"], "drat": res["drat"], "model": res["model"],
           "solver": solver.name, "solver_version": solver.version()}
    if res["unsat"]:
        chk = forward_rup_check(clauses, res["drat"])
        out["n_lemmas"] = chk["n_lemmas"]
        out["proof_checked"] = chk["verified"]
        if not chk["verified"]:
            raise SolverError(
                f"{solver.name} reported UNSAT, but its proof does not check: "
                f"{chk.get('reason', '')}. The verdict is withheld — that is the "
                f"whole reason the proof is required.")
    else:
        out["n_lemmas"] = 0
        out["proof_checked"] = False
    return out
