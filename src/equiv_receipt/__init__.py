"""equiv-receipt — portable, independently re-derivable logic-equivalence receipts."""
from .dimacs import parse_dimacs, to_dimacs  # noqa: F401
from .minisolve import refute  # noqa: F401
from .prove import prove_equivalence  # noqa: F401
from .receipt import (  # noqa: F401
    FORMAT, ReceiptError, build_receipt, canon, read_receipt, verify_receipt,
    write_receipt,
)
from .report import emit, to_json, to_junit, to_jsonl, to_sarif  # noqa: F401
from .rup import ClauseDB, bcp, forward_rup_check, parse_drat  # noqa: F401
from .seq import (  # noqa: F401
    prove_sequential_equivalence, read_seq_receipt, verify_seq_receipt,
    write_seq_receipt,
)
from .tseitin import Netlist, miter  # noqa: F401

__version__ = "1.0.0"
__all__ = ["FORMAT", "ReceiptError", "prove_equivalence", "build_receipt",
           "verify_receipt", "write_receipt", "read_receipt", "canon",
           "forward_rup_check", "parse_drat", "bcp", "ClauseDB", "refute", "miter",
           "Netlist", "parse_dimacs", "to_dimacs",
           "prove_sequential_equivalence", "verify_seq_receipt",
           "write_seq_receipt", "read_seq_receipt",
           "emit", "to_json", "to_jsonl", "to_sarif", "to_junit", "__version__"]
