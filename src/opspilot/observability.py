from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Literal, Protocol

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import Counter, Histogram, Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode, Tracer

AttributeValue = str | bool | int | float
_ALLOWED_OPERATION_ATTRIBUTES = frozenset({"component", "backend", "recovered"})


def _safe_operation_attributes(
    attributes: Mapping[str, AttributeValue] | None,
) -> dict[str, AttributeValue]:
    values = dict(attributes or {})
    unsupported = set(values) - _ALLOWED_OPERATION_ATTRIBUTES
    if unsupported:
        raise ValueError(f"unsupported telemetry attributes: {sorted(unsupported)}")
    if any(isinstance(value, str) and len(value) > 64 for value in values.values()):
        raise ValueError("telemetry string attributes cannot exceed 64 characters")
    return values


class Observability(Protocol):
    def operation(
        self,
        name: str,
        attributes: Mapping[str, AttributeValue] | None = None,
    ) -> AbstractContextManager[None]: ...

    def record_http(
        self, *, route: str, method: str, status_code: int, duration: float
    ) -> None: ...

    def record_auth(self, *, outcome: Literal["allowed", "denied"], reason: str) -> None: ...

    def record_lease_recovery(self) -> None: ...

    def record_model_usage(self, *, input_tokens: int, output_tokens: int) -> None: ...

    def shutdown(self) -> None: ...


class NoopObservability:
    @contextmanager
    def operation(
        self,
        name: str,
        attributes: Mapping[str, AttributeValue] | None = None,
    ) -> Iterator[None]:
        del name
        _safe_operation_attributes(attributes)
        yield

    def record_http(self, *, route: str, method: str, status_code: int, duration: float) -> None:
        del route, method, status_code, duration

    def record_auth(self, *, outcome: Literal["allowed", "denied"], reason: str) -> None:
        del outcome, reason

    def record_lease_recovery(self) -> None:
        return None

    def record_model_usage(self, *, input_tokens: int, output_tokens: int) -> None:
        del input_tokens, output_tokens

    def shutdown(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class RecordedSignal:
    name: str
    attributes: dict[str, AttributeValue]
    value: float


class RecordingObservability(NoopObservability):
    """In-memory signal sink for assertions; never used by production bootstrap."""

    def __init__(self) -> None:
        self.signals: list[RecordedSignal] = []

    @contextmanager
    def operation(
        self,
        name: str,
        attributes: Mapping[str, AttributeValue] | None = None,
    ) -> Iterator[None]:
        started = perf_counter()
        outcome = "success"
        try:
            yield
        except Exception:
            outcome = "error"
            raise
        finally:
            values = _safe_operation_attributes(attributes)
            values["outcome"] = outcome
            self.signals.append(
                RecordedSignal(
                    name=f"operation:{name}",
                    attributes=values,
                    value=perf_counter() - started,
                )
            )

    def record_http(self, *, route: str, method: str, status_code: int, duration: float) -> None:
        self.signals.append(
            RecordedSignal(
                name="http",
                attributes={"route": route, "method": method, "status_code": status_code},
                value=duration,
            )
        )

    def record_auth(self, *, outcome: Literal["allowed", "denied"], reason: str) -> None:
        self.signals.append(
            RecordedSignal(name="auth", attributes={"outcome": outcome, "reason": reason}, value=1)
        )

    def record_lease_recovery(self) -> None:
        self.signals.append(RecordedSignal(name="lease_recovery", attributes={}, value=1))

    def record_model_usage(self, *, input_tokens: int, output_tokens: int) -> None:
        self.signals.extend(
            [
                RecordedSignal(
                    name="model_tokens",
                    attributes={"type": "input"},
                    value=input_tokens,
                ),
                RecordedSignal(
                    name="model_tokens",
                    attributes={"type": "output"},
                    value=output_tokens,
                ),
            ]
        )


class OpenTelemetryObservability:
    def __init__(
        self,
        *,
        tracer_provider: TracerProvider,
        meter_provider: MeterProvider,
    ) -> None:
        self._tracer_provider = tracer_provider
        self._meter_provider = meter_provider
        self._tracer: Tracer = tracer_provider.get_tracer("opspilot")
        meter: Meter = meter_provider.get_meter("opspilot")
        self._http_requests: Counter = meter.create_counter("opspilot.http.server.requests")
        self._http_duration: Histogram = meter.create_histogram(
            "opspilot.http.server.duration", unit="s"
        )
        self._workflow_operations: Counter = meter.create_counter("opspilot.workflow.operations")
        self._workflow_duration: Histogram = meter.create_histogram(
            "opspilot.workflow.operation.duration", unit="s"
        )
        self._auth_decisions: Counter = meter.create_counter("opspilot.auth.decisions")
        self._lease_recoveries: Counter = meter.create_counter(
            "opspilot.remediation.lease.recoveries"
        )
        self._model_tokens: Counter = meter.create_counter("opspilot.model.tokens", unit="{token}")

    @contextmanager
    def operation(
        self,
        name: str,
        attributes: Mapping[str, AttributeValue] | None = None,
    ) -> Iterator[None]:
        started = perf_counter()
        outcome = "success"
        safe_attributes = _safe_operation_attributes(attributes)
        with self._tracer.start_as_current_span(
            f"opspilot.{name}",
            attributes=safe_attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield
            except Exception:
                outcome = "error"
                span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                duration = perf_counter() - started
                metric_attributes = {"operation": name, "outcome": outcome}
                self._workflow_operations.add(1, metric_attributes)
                self._workflow_duration.record(duration, metric_attributes)

    def record_http(self, *, route: str, method: str, status_code: int, duration: float) -> None:
        attributes = {"route": route, "method": method, "status_code": str(status_code)}
        self._http_requests.add(1, attributes)
        self._http_duration.record(duration, attributes)

    def record_auth(self, *, outcome: Literal["allowed", "denied"], reason: str) -> None:
        self._auth_decisions.add(1, {"outcome": outcome, "reason": reason})

    def record_lease_recovery(self) -> None:
        self._lease_recoveries.add(1)

    def record_model_usage(self, *, input_tokens: int, output_tokens: int) -> None:
        self._model_tokens.add(input_tokens, {"type": "input"})
        self._model_tokens.add(output_tokens, {"type": "output"})

    def shutdown(self) -> None:
        self._meter_provider.shutdown()
        self._tracer_provider.shutdown()


def build_observability(
    *,
    exporter: str,
    endpoint: str | None,
    service_version: str,
    environment: str,
) -> Observability:
    if exporter == "none":
        return NoopObservability()
    if exporter != "otlp" or endpoint is None:
        raise ValueError("OTLP telemetry requires an endpoint")
    base_endpoint = endpoint.rstrip("/")
    resource = Resource.create(
        {
            "service.name": "opspilot",
            "service.version": service_version,
            "deployment.environment.name": environment,
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{base_endpoint}/v1/traces"))
    )
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{base_endpoint}/v1/metrics")
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    return OpenTelemetryObservability(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
    )
