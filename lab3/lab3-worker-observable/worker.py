import os
import time
import smtplib
import structlog
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import requests

# OpenTelemetry — tracing
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.instrumentation.requests import RequestsInstrumentor

# OpenTelemetry — metrics
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from prometheus_client import start_http_server

load_dotenv()


# ── Configuration ────────────────────────────────────────────────────────────

MZINGA_URL = os.environ["MZINGA_URL"]
MZINGA_EMAIL = os.environ["MZINGA_EMAIL"]
MZINGA_PASSWORD = os.environ["MZINGA_PASSWORD"]
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", 5))
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", 1025))
EMAIL_FROM = os.getenv("EMAIL_FROM", "worker@mzinga.io")
# [Lab 3 - Step 3.2] Read service name and OTLP endpoint from environment
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "email-worker")
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
# [Lab 3 - Step 4.2] Read Prometheus port from environment
PROMETHEUS_PORT = int(os.getenv("PROMETHEUS_PORT", 8000))


# ── OpenTelemetry: Tracing ────────────────────────────────────────────────────

# [Lab 3 - Step 3.2] Create OpenTelemetry Resource
resource = Resource.create({
    "service.name": OTEL_SERVICE_NAME,
    "service.version": "1.0.0",
})

# [Lab 3 - Step 3.2] Create OTLP exporter (Jaeger endpoint)
otlp_exporter = OTLPSpanExporter(
    endpoint=f"{OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces",
)

# [Lab 3 - Step 3.2] Create TracerProvider and add BatchSpanProcessor
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(tracer_provider)

# [Lab 3 - Step 3.2] Instrument requests library (auto-create spans for HTTP calls)
RequestsInstrumentor().instrument()

tracer = trace.get_tracer(OTEL_SERVICE_NAME)


# ── OpenTelemetry: Metrics ────────────────────────────────────────────────────

# [Lab 3 - Step 4.2] Initialize Prometheus metrics exporter and MeterProvider
prometheus_reader = PrometheusMetricReader()
metrics_provider = MeterProvider(resource=resource, metric_readers=[prometheus_reader])
metrics.set_meter_provider(metrics_provider)
meter = metrics.get_meter(OTEL_SERVICE_NAME)

# [Lab 3 - Step 4.3] Define custom metrics
emails_processed_total = meter.create_counter(
    name="emails_processed_total",
    description="Total number of processed emails",
    unit="1",
)
email_processing_duration_seconds = meter.create_histogram(
    name="email_processing_duration_seconds",
    description="Total duration of processing a communication (seconds)",
    unit="s",
)
smtp_send_duration_seconds = meter.create_histogram(
    name="smtp_send_duration_seconds",
    description="Duration of SMTP send (seconds)",
    unit="s",
)
worker_poll_total = meter.create_counter(
    name="worker_poll_total",
    description="Total number of poll cycles",
    unit="1",
)

# [Lab 3 - Step 4.2] Start Prometheus /metrics endpoint
start_http_server(PROMETHEUS_PORT)


# ── Structured logging ────────────────────────────────────────────────────────

# ?
def add_otel_context(logger, method, event_dict):
    """Inject active trace_id and span_id into every log entry."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict

# [Lab 3 - Step 2.2] Configure structlog for structured JSON logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        add_otel_context,
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

# [Lab 3 - Step 2.2] Create a logger with the fixed service name
log = structlog.get_logger(service=OTEL_SERVICE_NAME)


# ── MZinga API helpers ────────────────────────────────────────────────────────

# [Lab 2 - Step A3] Build the REST API Worker
def login() -> str:
    resp = requests.post(
        f"{MZINGA_URL}/api/users/login",
        json={"email": MZINGA_EMAIL, "password": MZINGA_PASSWORD},
    )
    resp.raise_for_status()
    log.info("Authenticated with MZinga API")
    return resp.json()["token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# [Lab 2 - Step A4.5] worker fetches the document via REST with depth=1
def fetch_pending(token: str) -> list:
    resp = requests.get(
        f"{MZINGA_URL}/api/communications",
        params={"where[status][equals]": "pending", "depth": 1},
        headers=auth_headers(token),
    )
    resp.raise_for_status()
    return resp.json().get("docs", [])

# [Lab 2 - Step A4.5] worker writes status: sent back via PATCH 
def update_status(token: str, doc_id: str, status: str):
    resp = requests.patch(
        f"{MZINGA_URL}/api/communications/{doc_id}",
        json={"status": status},
        headers=auth_headers(token),
    )
    resp.raise_for_status()


# ── Email helpers ─────────────────────────────────────────────────────────────

def slate_to_html(nodes: list) -> str:
    html = ""
    for node in nodes or []:
        if node.get("type") == "paragraph":
            html += f"<p>{slate_to_html(node.get('children', []))}</p>"
        elif node.get("type") == "h1":
            html += f"<h1>{slate_to_html(node.get('children', []))}</h1>"
        elif node.get("type") == "h2":
            html += f"<h2>{slate_to_html(node.get('children', []))}</h2>"
        elif node.get("type") == "ul":
            html += f"<ul>{slate_to_html(node.get('children', []))}</ul>"
        elif node.get("type") == "li":
            html += f"<li>{slate_to_html(node.get('children', []))}</li>"
        elif node.get("type") == "link":
            url = node.get("url", "#")
            html += f'<a href="{url}">{slate_to_html(node.get("children", []))}</a>'
        elif "text" in node:
            text = node["text"]
            if node.get("bold"):
                text = f"<strong>{text}</strong>"
            if node.get("italic"):
                text = f"<em>{text}</em>"
            html += text
        else:
            html += slate_to_html(node.get("children", []))
    return html


def extract_emails(relationship_list: list) -> list[str]:
    emails = []
    for r in relationship_list or []:
        value = r.get("value") or {}
        if isinstance(value, dict) and value.get("email"):
            emails.append(value["email"])
    return emails

# [Lab 2 - Step A4.5] worker sends email 
def send_email(to_addresses: list[str], subject: str, html: str,
               cc_addresses: list[str] = None, bcc_addresses: list[str] = None):
    # [Lab 3 - Step 4.4] Record smtp_send_duration_seconds inside send_email span
    with tracer.start_as_current_span("send_email") as span:
        span.set_attribute("recipient_count", len(to_addresses))
        t0 = time.perf_counter()
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = ", ".join(to_addresses)
        if cc_addresses:
            msg["Cc"] = ", ".join(cc_addresses)
        msg.attach(MIMEText(html, "html"))
        all_recipients = to_addresses + (cc_addresses or []) + (bcc_addresses or [])
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.sendmail(EMAIL_FROM, all_recipients, msg.as_string())
        smtp_send_duration_seconds.record(time.perf_counter() - t0)


# ── Processing ────────────────────────────────────────────────────────────────

# [Lab 3 - Step 3.3] Add manual root span for process_communication
def process(token: str, doc: dict):
    doc_id = doc["id"]
    structlog.contextvars.bind_contextvars(doc_id=doc_id)
    # [Lab 3 - Step 4.4] Record metrics for processed emails and durations
    with tracer.start_as_current_span("process_communication") as span:
        span.set_attribute("doc_id", doc_id)
        t0 = time.perf_counter()

        update_status(token, doc_id, "processing")
        log.info("processing_started")

        try:
            to_emails = extract_emails(doc.get("tos"))
            if not to_emails:
                raise ValueError("No valid 'to' email addresses found")
            cc_emails = extract_emails(doc.get("ccs"))
            bcc_emails = extract_emails(doc.get("bccs"))

            with tracer.start_as_current_span("serialize_body") as s:
                nodes = doc.get("body") or []
                s.set_attribute("node_count", len(nodes))
                html = slate_to_html(nodes)

            send_email(to_emails, doc["subject"], html, cc_emails, bcc_emails)
            update_status(token, doc_id, "sent")

            duration = time.perf_counter() - t0
            email_processing_duration_seconds.record(duration)
            emails_processed_total.add(1, {"status": "sent", "recipient_count": len(to_emails)})
            log.info("processing_completed", status="sent", duration_s=round(duration, 3))

        except Exception as e:
            span.set_status(trace.StatusCode.ERROR, str(e))
            span.record_exception(e)
            update_status(token, doc_id, "failed")
            emails_processed_total.add(1, {"status": "failed", "recipient_count": 0})
            log.error("processing_failed", error=str(e))

    structlog.contextvars.unbind_contextvars("doc_id")
    return token


# ── Poll loop ─────────────────────────────────────────────────────────────────

# [Lab 2 - Step A4.5] worker polling mechanism
def poll():
    token = login()
    log.info(f"Worker started. Polling every {POLL_INTERVAL}s")
    while True:
        try:
            docs = fetch_pending(token)
            # [Lab 3 - Step 4.4] Increment worker_poll_total in the poll loop
            if docs:
                worker_poll_total.add(1, {"result": "found"})
            else:
                worker_poll_total.add(1, {"result": "empty"})
            for doc in docs:
                process(token, doc)
            if not docs:
                time.sleep(POLL_INTERVAL)
        except requests.HTTPError as e:
            if e.response.status_code == 401:
                log.warning("Token expired, re-authenticating")
                token = login()
            else:
                log.error(f"HTTP error: {e}")
                time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    poll()