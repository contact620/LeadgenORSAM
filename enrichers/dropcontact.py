"""
Step 3b — Dropcontact API enricher.

Sends leads in batches to Dropcontact to retrieve:
  - Professional email (validated)
  - Phone number (if available)

Pricing: ~0.10 € per lead. The API is asynchronous:
  POST /batch → get a request_id → poll GET /batch/{id} until status='done'.

Docs: https://developer.dropcontact.com/
"""
import logging
import time
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dropcontact.com"
POLL_INTERVAL = 5       # seconds between polls
MAX_POLL_ATTEMPTS = 60  # 5 min max wait


def _post_batch(leads_batch: list[dict]) -> Optional[str]:
    """Submit a batch to Dropcontact. Returns request_id."""
    payload = {
        "data": [
            {
                "first_name": l.get("first_name", ""),
                "last_name": l.get("last_name", ""),
                "company": l.get("company", ""),
            }
            for l in leads_batch
        ],
        "siren": True,
        "language": "FR",
    }
    headers = {
        "X-Access-Token": config.DROPCONTACT_API_KEY,
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(f"{BASE_URL}/batch", json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        request_id = data.get("request_id")
        if not request_id:
            logger.error(f"Dropcontact batch submission failed: {data}")
        return request_id
    except Exception as e:
        logger.error(f"Dropcontact POST /batch error: {e}")
        return None


def _poll_batch(request_id: str) -> Optional[list[dict]]:
    """Poll Dropcontact until the batch is ready. Returns enriched data list."""
    headers = {"X-Access-Token": config.DROPCONTACT_API_KEY}
    for attempt in range(MAX_POLL_ATTEMPTS):
        try:
            resp = requests.get(f"{BASE_URL}/batch/{request_id}", headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Dropcontact poll error (attempt {attempt + 1}): {e}")
            time.sleep(POLL_INTERVAL)
            continue

        if data.get("success") and data.get("data"):
            logger.debug(f"Dropcontact batch {request_id} ready after {attempt + 1} polls")
            return data["data"]

        # Not ready yet
        reason = data.get("reason", "pending")
        logger.debug(f"Batch {request_id} not ready ({reason}), waiting {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)

    logger.error(f"Dropcontact batch {request_id} timed out after {MAX_POLL_ATTEMPTS} polls")
    return None


def _extract_email(dc_item: dict) -> Optional[str]:
    """Extract the best email from a Dropcontact result item."""
    emails = dc_item.get("email", [])
    if isinstance(emails, list):
        for e in emails:
            if isinstance(e, dict) and e.get("email"):
                return e["email"]
    elif isinstance(emails, str) and emails:
        return emails
    return None


def _extract_phone(dc_item: dict) -> Optional[str]:
    """Extract phone number from a Dropcontact result item."""
    phones = dc_item.get("phone", [])
    if isinstance(phones, list):
        for p in phones:
            if isinstance(p, dict) and p.get("number"):
                return p["number"]
    elif isinstance(phones, str) and phones:
        return phones
    return None


def enrich_leads_dropcontact(leads: list[dict]) -> list[dict]:
    """
    Enrich a list of leads with email and phone via Dropcontact.

    Processes in batches of DROPCONTACT_BATCH_SIZE. Modifies leads in place.
    """
    if not config.DROPCONTACT_API_KEY:
        logger.info("DROPCONTACT_API_KEY not set. Skipping email/phone enrichment.")
        for lead in leads:
            lead.setdefault("email", None)
            lead.setdefault("phone", None)
        return leads

    batch_size = config.DROPCONTACT_BATCH_SIZE
    total = len(leads)
    enriched_count = 0

    for batch_start in range(0, total, batch_size):
        batch = leads[batch_start : batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        logger.info(f"Dropcontact batch {batch_num}: submitting {len(batch)} leads")

        request_id = _post_batch(batch)
        if not request_id:
            logger.warning(f"Batch {batch_num} submission failed. Setting email/phone to None.")
            for lead in batch:
                lead.setdefault("email", None)
                lead.setdefault("phone", None)
            continue

        enriched_data = _poll_batch(request_id)
        if not enriched_data:
            logger.warning(f"Batch {batch_num} polling failed. Setting email/phone to None.")
            for lead in batch:
                lead.setdefault("email", None)
                lead.setdefault("phone", None)
            continue

        for i, lead in enumerate(batch):
            if i < len(enriched_data):
                dc_item = enriched_data[i]
                lead["email"] = _extract_email(dc_item)
                lead["phone"] = _extract_phone(dc_item)
                if lead["email"]:
                    enriched_count += 1
            else:
                lead["email"] = None
                lead["phone"] = None

        logger.info(
            f"Batch {batch_num} done. "
            f"{sum(1 for l in batch if l.get('email'))} emails found in this batch."
        )

    logger.info(f"Dropcontact enrichment complete. {enriched_count}/{total} emails found.")
    return leads


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    test_leads = [
        {"first_name": "Jean", "last_name": "Dupont", "company": "Acme Corp"},
        {"first_name": "Marie", "last_name": "Martin", "company": "Beta SAS"},
    ]

    result = enrich_leads_dropcontact(test_leads)
    for lead in result:
        print(f"{lead['first_name']} {lead['last_name']} — email: {lead.get('email')} | phone: {lead.get('phone')}")
