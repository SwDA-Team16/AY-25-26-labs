import os
import time
import html
import smtplib
from typing import Any, Iterable
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient, ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
EMAIL_FROM = os.getenv("EMAIL_FROM", "worker@mzinga.io")


if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI not configured in the .env file")

def get_database() -> Database:
    """
    Opens the connection to MongoDB using MONGODB_URI and returns
    the default database included in the URI (mzinga).
    """
    client = MongoClient(MONGODB_URI)
    return client.get_default_database()

def extract_relation_ids(relations: Any) -> list[ObjectId]:
    """
    Extracts ObjectIds from relational Payload fields of the form:
    { "relationTo": "users", "value": <ObjectId> }

    Returns a list of valid ObjectIds.
    """
    if not relations or not isinstance(relations, list):
        return []

    ids: list[ObjectId] = []

    for item in relations:
        if not isinstance(item, dict):
            continue

        if item.get("relationTo") != "users":
            continue

        value = item.get("value")

        if isinstance(value, ObjectId):
            ids.append(value)
        elif isinstance(value, str):
            try:
                ids.append(ObjectId(value))
            except Exception:
                pass

    return ids

def resolve_user_emails(users_collection: Collection, relations: Any) -> list[str]:
    """
    Takes the Payload references in tos/ccs/bccs,
    queries the users collection, and returns the actual email addresses.
    """
    user_ids = extract_relation_ids(relations)

    if not user_ids:
        return []

    users = users_collection.find(
        {"_id": {"$in": user_ids}},
        {"email": 1}
    )

    emails: list[str] = []
    for user in users:
        email = user.get("email")
        if email:
            emails.append(email)

    return emails

def render_text_node(node: dict[str, Any]) -> str:
    """
    Serializes a Slate text node.
    
    Supports:
    - plain text
    - bold
    - italic
    """
    text = html.escape(str(node.get("text", "")))

    if node.get("bold"):
        text = f"<strong>{text}</strong>"

    if node.get("italic"):
        text = f"<em>{text}</em>"

    return text

def render_slate_nodes(nodes: Any) -> str:
    """
    Serializes a list of Slate nodes by concatenating the resulting HTML.
    """
    if not nodes or not isinstance(nodes, list):
        return ""

    return "".join(render_slate_node(node) for node in nodes)

def render_slate_node(node: Any) -> str:
    """
    Recursive function that converts a Slate node into HTML.

    Handles:
    - paragraph
    - h1
    - h2
    - ul
    - li
    - link
    - text with bold and italic
    """
    if not isinstance(node, dict):
        return ""

    if "text" in node:
        return render_text_node(node)

    node_type = node.get("type")
    children_html = render_slate_nodes(node.get("children", []))

    if node_type == "paragraph":
        return f"<p>{children_html}</p>"
    if node_type == "h1":
        return f"<h1>{children_html}</h1>"
    if node_type == "h2":
        return f"<h2>{children_html}</h2>"
    if node_type == "ul":
        return f"<ul>{children_html}</ul>"
    if node_type == "li":
        return f"<li>{children_html}</li>"
    if node_type == "link":
        url = html.escape(str(node.get("url", "#")))
        return f'<a href="{url}">{children_html}</a>'

    return children_html

def build_email_message(
    subject: str,
    html_body: str,
    to_emails: Iterable[str],
    cc_emails: Iterable[str],
    bcc_emails: Iterable[str],
) -> MIMEMultipart:
    """
    Builds the MIMEMultipart email message with:
    - to
    - cc
    - subject
    - HTML body
    """
    message = MIMEMultipart("alternative")
    message["From"] = EMAIL_FROM
    message["To"] = ", ".join(to_emails)
    message["Cc"] = ", ".join(cc_emails)
    message["Subject"] = subject

    html_part = MIMEText(html_body, "html", "utf-8")
    message.attach(html_part)

    return message

def send_email(
    subject: str,
    html_body: str,
    to_emails: list[str],
    cc_emails: list[str],
    bcc_emails: list[str],
) -> None:
    """
    Sends the email using smtplib to the configured SMTP host and port.
    """
    if not to_emails and not cc_emails and not bcc_emails:
        raise RuntimeError("No valid recipients found")

    message = build_email_message(subject, html_body, to_emails, cc_emails, bcc_emails)
    all_recipients = to_emails + cc_emails + bcc_emails

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.sendmail(EMAIL_FROM, all_recipients, message.as_string())

def claim_pending_document(communications: Collection) -> dict[str, Any] | None:
    """
    Finds a document with status = "pending" and immediately updates it
    to "processing" before performing any other operation.

    This accomplishes both:
    - polling for pending documents
    - claiming the document
    """
    return communications.find_one_and_update(
        {"status": "pending"},
        {"$set": {"status": "processing"}},
        return_document=ReturnDocument.AFTER,
    )

def process_document(db: Database, document: dict[str, Any]) -> None:
    """
    Performs the full processing of a communication document:
    - resolves the recipients
    - serializes the body to HTML
    - sends the email
    - updates the final status to sent
    """
    communications = db["communications"]
    users = db["users"]

    doc_id = document["_id"]
    subject = document.get("subject", "(missing subject)")
    body = document.get("body", [])

    # [Lab 1 - Step 5.4.4] Resolve recipient emails from Payload relations (ObjectId -> email via users collection)
    to_emails = resolve_user_emails(users, document.get("tos"))
    cc_emails = resolve_user_emails(users, document.get("ccs"))
    bcc_emails = resolve_user_emails(users, document.get("bccs"))

    # [Lab 1 - Step 5.4.5] Recursive Slate AST -> HTML renderer
    # Supports: paragraph, h1, h2, ul, li, link, text
    html_body = render_slate_nodes(body)

    # [Lab 1 - Step 5.4.6] Send email via SMTP using MIMEMultipart 
    send_email(
        subject=subject,
        html_body=html_body,
        to_emails=to_emails,
        cc_emails=cc_emails,
        bcc_emails=bcc_emails,
    )

    # [Lab 1 - Step 5.4.7] Mark as "sent" on success
    communications.update_one(
        {"_id": doc_id},
        {"$set": {"status": "sent"}}
    )

# [Lab 1 - Step 5] Worker main loop (polling + processing)
def worker_loop() -> None:
    """
    Main worker loop.
    """

    # [Lab 1 - Step 5.4.1] Connect to MongoDB using pymongo and MONGODB_URI
    db = get_database()
    communications = db["communications"]
    print("Worker started. Waiting for pending documents...")

    while True:

        # [Lab 1 - Step 5.4.2] Poll for documents with status = "pending"
        # [Lab 1 - Step 5.4.3] Atomically claim the document by setting status = "processing"
        document = claim_pending_document(communications)

        if not document:
            print(f"No pending documents found. Waiting {POLL_INTERVAL_SECONDS}s...")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        doc_id = document.get("_id")
        print(f"Document claimed: {doc_id}")

        try:
            process_document(db, document)
            print(f"Document {doc_id} sent successfully")
        except Exception as exc:
            print(f"Error while processing document {doc_id}: {exc}")

            # [Lab 1 - Step 5.4.7] Mark as "failed" on error
            communications.update_one(
                {"_id": doc_id},
                {"$set": {"status": "failed"}}
            )


if __name__ == "__main__":
    worker_loop()