# src/observability.py
from __future__ import annotations

import atexit
import json
import os
from contextlib import contextmanager
from typing import Any, Iterator, Literal

Backend = Literal["phoenix", "langsmith", "none"]

_tracer_provider = None
_phoenix_project: str | None = None


def _env(name: str, default: str = "") -> str:
    """Read env var, stripping inline comments (common when loading .env in PowerShell)."""
    raw = os.getenv(name, default).split("#", 1)[0].strip().strip('"').strip("'")
    return raw


def get_backend() -> Backend:
    value = _env("OBSERVABILITY_BACKEND", "none").lower()
    if value in ("phoenix", "langsmith", "none"):
        return value  # type: ignore[return-value]
    return "none"


def phoenix_project_name() -> str:
    return _phoenix_project or _env("PHOENIX_PROJECT") or _env("PHOENIX_PROJECT_NAME") or "default"


def flush_traces(timeout_millis: int = 10000) -> None:
    """Export buffered spans — call at end of CLI runs."""
    if get_backend() != "phoenix" or _tracer_provider is None:
        return
    if hasattr(_tracer_provider, "force_flush"):
        _tracer_provider.force_flush(timeout_millis=timeout_millis)


def setup_observability() -> None:
    """Call once at process startup, BEFORE importing graph/LLM modules."""
    backend = get_backend()
    if backend == "none":
        return
    if backend == "phoenix":
        _setup_phoenix()
    elif backend == "langsmith":
        _setup_langsmith()


def _setup_phoenix() -> None:
    global _tracer_provider, _phoenix_project
    os.environ.pop("LANGSMITH_TRACING", None)

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from openinference.instrumentation.langchain import LangChainInstrumentor
    from openinference.instrumentation.openai import OpenAIInstrumentor
    from openinference.semconv.resource import ResourceAttributes

    endpoint = _env("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006/v1/traces")
    project = phoenix_project_name()
    _phoenix_project = project

    resource = Resource.create(
        {
            ResourceAttributes.PROJECT_NAME: project,
            "service.name": "uhg-risk-intelligence",
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    )
    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    atexit.register(flush_traces)

    LangChainInstrumentor().instrument(tracer_provider=provider)
    OpenAIInstrumentor().instrument(tracer_provider=provider)

    try:
        from openinference.instrumentation.instructor import InstructorInstrumentor
        InstructorInstrumentor().instrument(tracer_provider=provider)
    except ImportError:
        print("WARN: openinference-instrumentation-instructor not installed; skipping")

    print(f"[observability] Phoenix tracing ON -> project={project!r} endpoint={endpoint}")


@contextmanager
def mcp_span(
    name: str,
    *,
    server: str | None = None,
    tool: str | None = None,
    arguments: dict[str, Any] | None = None,
    span_kind: str = "TOOL",
) -> Iterator[Any]:
    """OpenTelemetry span for MCP client calls (exported to Phoenix when enabled)."""
    if get_backend() != "phoenix":
        yield None
        return

    from opentelemetry import trace

    tracer = trace.get_tracer("uhg-risk-intelligence.mcp")
    with tracer.start_as_current_span(name) as span:
        if server:
            span.set_attribute("mcp.server", server)
        if tool:
            span.set_attribute("mcp.tool", tool)
        try:
            from openinference.semconv.trace import (
                OpenInferenceMimeTypeValues,
                OpenInferenceSpanKindValues,
                SpanAttributes,
            )

            # Phoenix reads the string value (e.g. "TOOL"), not the enum object.
            kind = getattr(OpenInferenceSpanKindValues, span_kind, OpenInferenceSpanKindValues.TOOL)
            span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, kind.value)
            if server and tool:
                span.set_attribute(SpanAttributes.TOOL_NAME, f"{server}.{tool}")
            if arguments is not None:
                span.set_attribute(
                    SpanAttributes.INPUT_VALUE,
                    json.dumps(arguments, default=str),
                )
                span.set_attribute(
                    SpanAttributes.INPUT_MIME_TYPE,
                    OpenInferenceMimeTypeValues.JSON.value,
                )
        except ImportError:
            if arguments is not None:
                span.set_attribute("mcp.input", json.dumps(arguments, default=str))

        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
            raise


def set_span_output(span: Any, result: str) -> None:
    if span is None:
        return
    preview = result[:4000] + ("..." if len(result) > 4000 else "")
    try:
        from openinference.semconv.trace import OpenInferenceMimeTypeValues, SpanAttributes

        span.set_attribute(SpanAttributes.OUTPUT_VALUE, preview)
        span.set_attribute(
            SpanAttributes.OUTPUT_MIME_TYPE,
            OpenInferenceMimeTypeValues.JSON.value,
        )
    except ImportError:
        span.set_attribute("output", preview)


def set_mcp_span_output(span: Any, result: str) -> None:
    set_span_output(span, result)


@contextmanager
def retriever_span(
    name: str,
    *,
    query: str,
    provider: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """OpenTelemetry span for search/retrieval calls (e.g. Tavily) → Phoenix RETRIEVER."""
    if get_backend() != "phoenix":
        yield None
        return

    from opentelemetry import trace

    tracer = trace.get_tracer("uhg-risk-intelligence.search")
    with tracer.start_as_current_span(name) as span:
        span.set_attribute("search.provider", provider)
        try:
            from openinference.semconv.trace import (
                OpenInferenceMimeTypeValues,
                OpenInferenceSpanKindValues,
                SpanAttributes,
            )

            span.set_attribute(
                SpanAttributes.OPENINFERENCE_SPAN_KIND,
                OpenInferenceSpanKindValues.RETRIEVER.value,
            )
            span.set_attribute(SpanAttributes.INPUT_VALUE, query)
            span.set_attribute(SpanAttributes.INPUT_MIME_TYPE, OpenInferenceMimeTypeValues.TEXT.value)
            for key, value in (attributes or {}).items():
                span.set_attribute(f"search.{key}", str(value))
        except ImportError:
            span.set_attribute("search.query", query)

        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
            raise


def _setup_langsmith() -> None:
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ.setdefault("LANGSMITH_PROJECT", "uhg-risk-intelligence")
    if not os.getenv("LANGSMITH_API_KEY"):
        raise RuntimeError("OBSERVABILITY_BACKEND=langsmith but LANGSMITH_API_KEY is missing")


def make_openai_client():
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    if get_backend() == "langsmith":
        from langsmith.wrappers import wrap_openai
        client = wrap_openai(client)
    return client