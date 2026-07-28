"""equiv-receipt — portable, independently re-derivable logic-equivalence receipts."""
from .dimacs import parse_dimacs, to_dimacs  # noqa: F401
from .minisolve import refute  # noqa: F401
from .prove import prove_equivalence  # noqa: F401
from .receipt import (  # noqa: F401
    FORMAT, ReceiptError, build_receipt, canon, read_receipt, verify_receipt,
    write_receipt,
)
from .rup import bcp, forward_rup_check, parse_drat  # noqa: F401
from .tseitin import Netlist, miter  # noqa: F401

__version__ = "1.0.0"
__all__ = ["FORMAT", "ReceiptError", "prove_equivalence", "build_receipt",
           "verify_receipt", "write_receipt", "read_receipt", "canon",
           "forward_rup_check", "parse_drat", "bcp", "refute", "miter",
           "Netlist", "parse_dimacs", "to_dimacs", "__version__"]
