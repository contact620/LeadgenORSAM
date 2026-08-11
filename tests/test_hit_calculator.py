import config
from processors.hit_calculator import calculate_hit_score


def test_incoherent_website_does_not_earn_points():
    # website is set but was rejected by the coherence check: the 10 points
    # must not be awarded. With website=None this test would pass even
    # without the coherence guard, proving nothing.
    lead = {
        "email": None,
        "linkedin_url": "https://linkedin.com/in/x",
        "phone": None,
        "website": "https://rentkasa.com",
        "website_coherent": False,
    }
    calculate_hit_score(lead)
    assert lead["hit_score"] == config.SCORE_LINKEDIN


def test_coherent_website_earns_points():
    lead = {
        "email": None,
        "linkedin_url": "https://linkedin.com/in/x",
        "phone": None,
        "website": "https://acme.ma",
        "website_coherent": True,
    }
    calculate_hit_score(lead)
    assert lead["hit_score"] == config.SCORE_LINKEDIN + config.SCORE_WEBSITE


def test_website_without_coherence_flag_still_earns_points():
    # Backward compatibility with pools scraped before this change
    lead = {"email": None, "linkedin_url": None, "phone": None, "website": "https://acme.ma"}
    calculate_hit_score(lead)
    assert lead["hit_score"] == config.SCORE_WEBSITE
