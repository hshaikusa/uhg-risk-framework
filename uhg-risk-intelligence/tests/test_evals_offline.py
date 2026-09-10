"""Offline eval suites — no API keys required."""

from evals.suites.offline import run_all_offline
from evals.suites.traces import run_trace_evals_offline


def test_all_offline_suites_pass():
    reports = run_all_offline()
    failures = []
    for report in reports:
        for case in report.results:
            if not case.passed:
                failures.append(f"{report.name}/{case.case_id}: {case.detail or case.error}")
    assert not failures, "Offline eval failures:\n" + "\n".join(failures)


def test_trace_evals_offline_covers_core_kinds():
    report = run_trace_evals_offline()
    by_id = {c.case_id: c for c in report.results}
    assert by_id["trace_kind_coverage"].passed
    assert by_id["trace_mcp_tools"].passed
    assert by_id["trace_retriever"].passed
