"""Structured output: JSON, JSON Lines, SARIF 2.1.0, JUnit XML.

One place decides how a verdict renders, so the formats cannot drift apart.

The discipline that matters here: SARIF and JUnit have only "passed" and
"failed". ``UNDECIDED-AT-K`` is neither — it is an abstention, and it is rendered
as a **failure with the reason attached**. A green check mark on a question that
was not answered is exactly the confident wrong answer this package exists to
avoid.
"""
from __future__ import annotations

import json
from typing import Dict, Tuple
from xml.etree import ElementTree as ET

#: verdict -> (counts as success, SARIF level, one-line summary)
_VERDICT_META: Dict[str, Tuple[bool, str, str]] = {
    "EQUIVALENT": (True, "note",
                   "the two circuits agree, and the proof re-derives"),
    "COUNTEREXAMPLE": (False, "error",
                       "the two circuits differ, and the witness re-simulates"),
    "UNDECIDED-AT-K": (False, "warning",
                       "ABSTAINED: base cases hold but no inductive argument "
                       "closed at this k — sound but incomplete, so no verdict "
                       "follows. Raising k may resolve it."),
}


def verdict_meta(verdict: str) -> Tuple[bool, str, str]:
    """Metadata for a verdict. An unrecognised one is a failure, never a pass."""
    return _VERDICT_META.get(
        verdict, (False, "error",
                  f"unrecognised verdict {verdict!r} — treated as a failure, "
                  f"because a verdict this tool does not understand cannot be "
                  f"reported as success"))


def _fields(res: Dict, source: str) -> Dict:
    verdict = res.get("verdict")
    ok, level, summary = verdict_meta(verdict)
    return {"verdict": verdict, "ok": bool(res.get("ok")) and ok, "level": level,
            "summary": summary, "source": source,
            "errors": list(res.get("errors") or []),
            "detail": res.get("detail") or {},
            "method": res.get("method"), "k": res.get("k")}


def to_json(res: Dict, source: str = "receipt") -> str:
    return json.dumps(_fields(res, source), indent=2, sort_keys=True)


def to_jsonl(res: Dict, source: str = "receipt") -> str:
    return json.dumps(_fields(res, source), sort_keys=True)


def to_sarif(res: Dict, source: str = "receipt") -> str:
    f = _fields(res, source)
    message = f["summary"]
    if f["errors"]:
        message += "\n" + "\n".join(f"- {e}" for e in f["errors"])
    results = []
    if not f["ok"]:
        results.append({
            "ruleId": "equiv-receipt/verdict",
            "level": f["level"],
            # The verdict name goes in the message and in properties: a reader
            # in a code-scanning UI needs to know WHICH outcome this is.
            "message": {"text": f"{f['verdict']}: {message}"},
            "properties": {"verdict": f["verdict"]},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": source}}}],
        })
    return json.dumps({
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "equiv-receipt",
                "informationUri": "https://github.com/nickharris808/equiv-receipt",
                "rules": [{"id": "equiv-receipt/verdict",
                           "shortDescription": {"text": "Equivalence verdict re-derivation"},
                           "fullDescription": {"text": (
                               "The verdict is recomputed from the committed formula "
                               "and proof. An abstention is reported as a failure "
                               "because it is not a pass.")}}],
            }},
            "invocations": [{"executionSuccessful": f["ok"]}],
            "results": results,
        }],
    }, indent=2)


def to_junit(res: Dict, source: str = "receipt") -> str:
    f = _fields(res, source)
    suite = ET.Element("testsuite", name="equiv-receipt", tests="1",
                       failures="0" if f["ok"] else "1", errors="0", skipped="0")
    case = ET.SubElement(suite, "testcase", classname="equiv-receipt",
                         name=f"verify {source}")
    if not f["ok"]:
        # A missing or None verdict must still render: ElementTree refuses to
        # serialise None, and a result that cannot be reported is worse than one
        # that reports "unknown".
        fail = ET.SubElement(case, "failure",
                             type=str(f["verdict"] or "UNKNOWN"),
                             message=str(f["summary"]))
        fail.text = "\n".join(f["errors"]) or f["summary"]
    out = ET.SubElement(suite, "system-out")
    out.text = (f"verdict={f['verdict']} method={f['method']} k={f['k']} "
                f"detail={json.dumps(f['detail'], sort_keys=True)}")
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            + ET.tostring(suite, encoding="unicode"))


EMITTERS = {"json": to_json, "jsonl": to_jsonl, "sarif": to_sarif, "junit": to_junit}


def emit(res: Dict, fmt: str, **kw) -> str:
    if fmt not in EMITTERS:
        raise ValueError(f"unknown format {fmt!r}; known: {sorted(EMITTERS)}")
    return EMITTERS[fmt](res, **kw)
