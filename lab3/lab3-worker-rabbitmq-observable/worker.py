import asyncio
import json
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aio_pika
import requests
import structlog
from dotenv import load_dotenv
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode
from prometheus_client import start_http_server

load_dotenv()


# Configuration

MZINGA_URL = os.environ["MZINGA_URL"]
MZINGA_EMAIL = os.environ["MZINGA_EMAIL"]
MZINGA_PASSWORD = os.environ["MZINGA_PASSWORD"]
RABBITMQ_URL = os.environ["RABBITMQ_URL"]
ROUTING_KEY = os.getenv("ROUTING_KEY", "HOOKSURL_COMMUNICATIONS_AFTERCHANGE")
EXCHANGE_NAME = os.getenv("EXCHANGE_NAME", "mzinga_events_durable")
QUEUE_NAME = os.getenv("QUEUE_NAME", "communications-email-worker")
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", 1025))
EMAIL_FROM = os.getenv("EMAIL_FROM", "worker@mzinga.io")
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "email-worker-rabbitmq")
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv(
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "http://localhost:4318",
)
PROMETHEUS_PORT = int(os.getenv("PROMETHEUS_PORT", 8000))


# OpenTelemetry tracing

resource = Resource.create(
    {
        SERVICE_NAME: OTEL_SERVICE_NAME,
        SERVICE_VERSION: "1.0.0",
    }
)

tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(endpoint=f"{OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces")
    )
)
trace.set_tracer_provider(tracer_provider)
RequestsInstrumentor().instrument()
tracer = trace.get_tracer(OTEL_SERVICE_NAME)


# OpenTelemetry metrics

prometheus_reader = PrometheusMetricReader()
metrics_provider = MeterProvider(resource=resource, metric_readers=[prometheus_reader])
metrics.set_meter_provider(metrics_provider)
meter = metrics.get_meter(OTEL_SERVICE_NAME)

emails_processed_total = meter.create_counter(
    name="emails_processed_total",
    description="Total number of processed emails",
    unit="1",
)
email_processing_duration_seconds = meter.create_histogram(
    name="email_processing_duration_seconds",
    description="Total duration of processing a communication",
    unit="s",
)
smtp_send_duration_seconds = meter.create_histogram(
    name="smtp_send_duration_seconds",
    description="Duration of SMTP send",
    unit="s",
)
worker_messages_total = meter.create_counter(
    name="worker_messages_total",
    description="Total number of RabbitMQ messages consumed",
    unit="1",
)

start_http_server(PROMETHEUS_PORT)


# Structured logging

def add_otel_context(logger, method, event_dict):
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


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

log = structlog.get_logger(service=OTEL_SERVICE_NAME)


# MZinga API helpers

def login() -> str:
    resp = requests.post(
        f"{MZINGA_URL}/api/users/login",
        json={"email": MZINGA_EMAIL, "password": MZINGA_PASSWORD},
    )
    resp.raise_for_status()
    log.info("authenticated_with_mzinga_api")
    return resp.json()["token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def fetch_doc(token: str, doc_id: str) -> dict:
    resp = requests.get(
        f"{MZINGA_URL}/api/communications/{doc_id}",
        params={"depth": 1},
        headers=auth_headers(token),
    )
    resp.raise_for_status()
    return resp.json()


def update_status(token: str, doc_id: str, status: str):
    resp = requests.patch(
        f"{MZINGA_URL}/api/communications/{doc_id}",
        json={"status": status},
        headers=auth_headers(token),
    )
    resp.raise_for_status()


# Email helpers

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
    for relationship in relationship_list or []:
        value = relationship.get("value") or {}
        if isinstance(value, dict) and value.get("email"):
            emails.append(value["email"])
    return emails


def send_email(
    to_addresses: list[str],
    subject: str,
    html: str,
    cc_addresses: list[str] | None = None,
    bcc_addresses: list[str] | None = None,
):
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


# Processing

def process(token: str, doc: dict) -> str:
    doc_id = doc["id"]
    status = doc.get("status")
    structlog.contextvars.bind_contextvars(doc_id=doc_id)

    with tracer.start_as_current_span("process_communication") as span:
        span.set_attribute("doc_id", doc_id)
        span.set_attribute("status_before_processing", status or "")

        if status in ("sent", "processing"):
            log.info("processing_skipped", status=status)
            structlog.contextvars.unbind_contextvars("doc_id")
            return token

        t0 = time.perf_counter()
        update_status(token, doc_id, "processing")
        log.info("processing_started")

        try:
            to_emails = extract_emails(doc.get("tos"))
            if not to_emails:
                raise ValueError("No valid 'to' email addresses found")

            cc_emails = extract_emails(doc.get("ccs"))
            bcc_emails = extract_emails(doc.get("bccs"))

            with tracer.start_as_current_span("serialize_body") as serialize_span:
                nodes = doc.get("body") or []
                serialize_span.set_attribute("node_count", len(nodes))
                html = slate_to_html(nodes)

            send_email(to_emails, doc["subject"], html, cc_emails, bcc_emails)
            update_status(token, doc_id, "sent")

            duration = time.perf_counter() - t0
            email_processing_duration_seconds.record(duration)
            emails_processed_total.add(
                1,
                {"status": "sent", "recipient_count": len(to_emails)},
            )
            log.info("processing_completed", status="sent", duration_s=round(duration, 3))

        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            update_status(token, doc_id, "failed")
            emails_processed_total.add(1, {"status": "failed", "recipient_count": 0})
            log.error("processing_failed", error=str(exc))

    structlog.contextvars.unbind_contextvars("doc_id")
    return token


def event_doc_id(event: dict) -> str | None:
    data = event.get("data") or {}
    doc = data.get("doc") or {}
    return doc.get("id")


def event_operation(event: dict) -> str | None:
    data = event.get("data") or {}
    return data.get("operation")


async def consume_message(message: aio_pika.IncomingMessage, token: str) -> str:
    async with message.process(requeue=True):
        event = json.loads(message.body.decode())
        operation = event_operation(event)
        doc_id = event_doc_id(event)
        worker_messages_total.add(1, {"operation": operation or "unknown"})

        if not doc_id:
            log.warning("message_missing_doc_id")
            return token

        structlog.contextvars.bind_contextvars(doc_id=doc_id)
        with tracer.start_as_current_span("rabbitmq_message") as span:
            span.set_attribute("messaging.system", "rabbitmq")
            span.set_attribute("messaging.destination", EXCHANGE_NAME)
            span.set_attribute("messaging.rabbitmq.routing_key", ROUTING_KEY)
            span.set_attribute("operation", operation or "")

            if operation != "create":
                log.info("message_ignored", operation=operation)
                structlog.contextvars.unbind_contextvars("doc_id")
                return token

            log.info("message_received", operation=operation)
            doc = fetch_doc(token, doc_id)
            token = process(token, doc)

        structlog.contextvars.unbind_contextvars("doc_id")
        return token


async def connect_rabbitmq():
    while True:
        try:
            connection = await aio_pika.connect_robust(RABBITMQ_URL)
            log.info("connected_to_rabbitmq")
            return connection
        except Exception as exc:
            log.warning("rabbitmq_connection_failed_retrying", error=str(exc))
            await asyncio.sleep(2)


async def main():
    token = login()
    connection = await connect_rabbitmq()

    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)

        exchange = await channel.declare_exchange(
            EXCHANGE_NAME,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
            internal=True,
            auto_delete=False,
        )
        queue = await channel.declare_queue(QUEUE_NAME, durable=True)
        await queue.bind(exchange, routing_key=ROUTING_KEY)

        log.info(
            "worker_started",
            exchange=EXCHANGE_NAME,
            queue=QUEUE_NAME,
            routing_key=ROUTING_KEY,
        )

        async with queue.iterator() as messages:
            async for message in messages:
                try:
                    token = await consume_message(message, token)
                except requests.HTTPError as exc:
                    if exc.response.status_code == 401:
                        log.warning("token_expired_reauthenticating")
                        token = login()
                    raise


if __name__ == "__main__":
    asyncio.run(main())
