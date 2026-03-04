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
from enrichers.retry import retry_api_call, AuthError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dropcontact.io"
POLL_INTERVAL = 15      # seconds between polls (Dropcontact recommends ~30s)
MAX_POLL_ATTEMPTS = 40  # 10 min max wait


_dropcontact_disabled = False


def _reset_state():
    """Reset module state between pipeline runs."""
    global _dropcontact_disabled
    _dropcontact_disabled = False


def _post_batch(leads_batch: list[dict]) -> Optional[str]:
    """Submit a batch to Dropcontact with retry. Returns request_id."""
    global _dropcontact_disabled
    if _dropcontact_disabled:
        return None

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

    def _do_request():
        resp = requests.post(f"{BASE_URL}/batch", json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        request_id = data.get("request_id")
        if not request_id:
            raise ValueError(f"Dropcontact returned no request_id: {data}")
        return request_id

    try:
        return retry_api_call(_do_request, max_retries=3, operation_name="Dropcontact POST /batch")
    except AuthError as e:
        _dropcontact_disabled = True
        logger.error(f"Dropcontact auth failed — disabled for this run: {e}")
        return None
    except Exception as e:
        logger.error(f"Dropcontact POST /batch failed after retries: {e}")
        return None


def _poll_batch(request_id: str) -> Optional[list[dict]]:
    """Poll Dropcontact with progressive backoff until the batch is ready."""
    headers = {"X-Access-Token": config.DROPCONTACT_API_KEY}
    poll_delay = float(POLL_INTERVAL)

    for attempt in range(MAX_POLL_ATTEMPTS):
        try:
            resp = requests.get(f"{BASE_URL}/batch/{request_id}", headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError as e:
            if resp is not None and resp.status_code in (401, 403):
                logger.error(f"Dropcontact auth failed during polling: {e}")
                return None
            logger.error(f"Dropcontact poll HTTP error (attempt {attempt + 1}): {e}")
            time.sleep(poll_delay)
            poll_delay = min(poll_delay * 1.5, 60)
            continue
        except Exception as e:
            logger.error(f"Dropcontact poll error (attempt {attempt + 1}): {e}")
            time.sleep(poll_delay)
            poll_delay = min(poll_delay * 1.5, 60)
            continue

        if data.get("success") and data.get("data"):
            logger.info(f"Dropcontact batch {request_id} ready after {attempt + 1} polls")
            return data["data"]

        reason = data.get("reason", "pending")
        logger.info(f"Batch {request_id} not ready ({reason}), poll {attempt + 1}/{MAX_POLL_ATTEMPTS}, next in {poll_delay:.0f}s...")
        time.sleep(poll_delay)
        poll_delay = min(poll_delay * 1.2, 45)

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

        emails_in_batch = sum(1 for l in batch if l.get("email"))
        phones_in_batch = sum(1 for l in batch if l.get("phone"))
        logger.info(
            f"Batch {batch_num} done: "
            f"{emails_in_batch}/{len(batch)} emails, {phones_in_batch}/{len(batch)} phones"
        )

        # Log leads that got no email
        no_email = [l for l in batch if not l.get("email")]
        if no_email:
            names = ", ".join(
                f"{l.get('first_name')} {l.get('last_name')} ({l.get('company', '?')})"
                for l in no_email[:5]
            )
            suffix = f" (+{len(no_email) - 5} autres)" if len(no_email) > 5 else ""
            logger.info(f"Dropcontact: no email for {len(no_email)} leads: {names}{suffix}")

    phone_count = sum(1 for l in leads if l.get("phone"))
    logger.info(
        f"Dropcontact enrichment complete. "
        f"{enriched_count}/{total} emails, {phone_count}/{total} phones found."
    )
    return leads


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    test_leads = [
        {"first_name": "Scott", "last_name": "Paschall", "company": "Custom Concrete Creations"},
        {"first_name": "Collen", "last_name": "Crosby", "company": "Crosby Roofing Columbia LLC"},
        {"first_name": "Sandro", "last_name": "Mahler", "company": "CSIA"},
        {"first_name": "Arne", "last_name": "Kirchner", "company": "Alp Financial"},
        {"first_name": "Stephane", "last_name": "Tyc", "company": "Quincy Data"},
    ]

    result = enrich_leads_dropcontact(test_leads)
    for lead in result:
        print(f"{lead['first_name']} {lead['last_name']} — email: {lead.get('email')} | phone: {lead.get('phone')}")
