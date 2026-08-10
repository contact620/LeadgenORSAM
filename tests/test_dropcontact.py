from unittest.mock import patch

import pytest

from api.provider_status import ProviderFailure, ProviderRegistry
from enrichers.dropcontact import _reset_state, enrich_leads_dropcontact


def _leads(n):
    return [{"first_name": f"A{i}", "last_name": "B", "company": "Acme"} for i in range(n)]


def test_first_batch_failure_aborts_the_run():
    _reset_state()
    with patch("enrichers.dropcontact.config.DROPCONTACT_API_KEY", "key"), \
         patch("enrichers.dropcontact._post_batch", return_value=None):
        with pytest.raises(ProviderFailure) as exc:
            enrich_leads_dropcontact(_leads(3), registry=ProviderRegistry())
    assert exc.value.provider == "dropcontact"


def test_missing_key_is_recorded_as_skipped_not_failed():
    _reset_state()
    reg = ProviderRegistry()
    with patch("enrichers.dropcontact.config.DROPCONTACT_API_KEY", ""):
        enrich_leads_dropcontact(_leads(2), registry=reg)
    assert reg.to_dict()["dropcontact"]["status"] == "skipped"
    assert reg.has_critical_failure() is False
