"""Tests for the evidence checks. Several cases replay real mistakes from the
review audit: an unverified 2.9-star pick, a fabricated quote, and affiliate
listicles treated as evidence."""

from product_finder import verify
from product_finder.config import DEFAULT_CONFIG
from product_finder.models import Quote, Recommendation, SourceSnippet, Tier, REDDIT, REVIEW, WEB
from product_finder.pipeline import run_search

TRUST = DEFAULT_CONFIG["trust"]


def snip(url, text, title="", stype=WEB):
    return SourceSnippet(source_type=stype, title=title, url=url, text=text)


def tier(product, quotes=(), rating=None):
    return Tier(tier="best", product=product, why="", consensus="",
                quotes=[Quote(t, u) for t, u in quotes], rating=rating or {})


# ---- Source trust ----------------------------------------------------------

def test_source_tiers():
    assert verify.source_tier("https://www.rtings.com/x", TRUST) == verify.TRUSTED
    assert verify.source_tier("https://www.nytimes.com/wirecutter/x", TRUST) == verify.TRUSTED
    assert verify.source_tier("https://old.reddit.com/r/Tools/x", TRUST) == verify.COMMUNITY
    assert verify.source_tier("https://example-forum.com/t", TRUST) == verify.UNKNOWN


def test_affiliate_spam_is_dropped():
    snippets = [
        snip("https://www.clevelandheart.com/best-massagers", "8 Best Massagers"),
        snip("https://avasreviewcom.pages.dev/best-5", "We tested 21"),
        snip("https://www.rtings.com/review", "Measured results"),
    ]
    kept, blocked = verify.filter_blocked(snippets, TRUST)
    assert [s.url for s in kept] == ["https://www.rtings.com/review"]
    assert set(blocked) == {"clevelandheart.com", "avasreviewcom.pages.dev"}


# ---- Quotes ----------------------------------------------------------------

SOURCE = snip("https://www.rtings.com/a",
              "After testing, the US Wire & Cable model held voltage best at 100ft.")


def test_real_quote_kept_even_with_curly_quotes_and_case():
    assert verify.quote_found("the US Wire & Cable model held voltage best",
                              [SOURCE], SOURCE.url)
    assert verify.quote_found("“the us wire & cable model held voltage best”",
                              [SOURCE])


def test_quote_with_ellipsis_checks_each_piece():
    assert verify.quote_found("After testing ... held voltage best at 100ft", [SOURCE])
    assert not verify.quote_found("After testing ... lasted twenty years", [SOURCE])


def test_fabricated_quote_is_removed_and_tier_marked_unverified():
    rec = Recommendation(query="q", summary="", snippets=[SOURCE], tiers=[
        tier("US Wire & Cable 12/3", quotes=[
            ("Bulletproof for 6 years of daily use", SOURCE.url),
        ]),
    ])
    dropped = verify.verify_quotes(rec)
    assert dropped == 1
    assert rec.tiers[0].quotes == []
    assert rec.tiers[0].verified is False


# ---- Ratings ---------------------------------------------------------------

LISTING = snip("https://www.chewy.com/petsafe-outdoor",
               "PetSafe Outdoor Ultrasonic Bark Control. 2.9 out of 5 stars, 825 ratings.")


def test_rating_kept_only_when_in_cited_source():
    good = tier("PetSafe Outdoor Ultrasonic", rating={
        "stars": 2.9, "count": 825, "source_url": LISTING.url})
    verify.verify_rating(good, [LISTING])
    assert good.rating["stars"] == 2.9

    made_up = tier("PetSafe Outdoor Ultrasonic", rating={
        "stars": 4.6, "source_url": LISTING.url})
    verify.verify_rating(made_up, [LISTING])
    assert made_up.rating == {}


def test_low_rating_gets_not_recommended_warning():
    t = tier("PetSafe Outdoor Ultrasonic", rating={
        "stars": 2.9, "count": 825, "source_url": LISTING.url})
    verify.verify_rating(t, [LISTING])
    verify.grade_evidence(t, [LISTING], TRUST)
    assert "below the 4 minimum" in t.warning


# ---- Consensus grading -----------------------------------------------------

def test_grade_counts_independent_domains_not_claims():
    snippets = [
        snip("https://www.rtings.com/a", "The Southwire 2588 is our top pick."),
        snip("https://www.reddit.com/r/BuyItForLife/x", "Southwire 2588 lasts forever", stype=REDDIT),
        snip("https://www.reddit.com/r/Tools/y", "my southwire 2588 is ten years old", stype=REDDIT),
        snip("https://forum.example.com/t", "Get a Southwire 2588."),
    ]
    t = tier("Southwire 2588 12/3")
    verify.grade_evidence(t, snippets, TRUST)
    assert t.source_count == 3          # two reddit threads count as one domain
    assert t.trusted_count == 1
    assert t.evidence_grade == "High"


def test_single_source_is_low():
    t = tier("Iron Forge Cable 12/3")
    verify.grade_evidence(t, [snip("https://forum.example.com/t",
                                   "Iron Forge cable is fine")], TRUST)
    assert t.evidence_grade == "Low"


def test_brand_must_match_not_just_generic_words():
    t = tier("Level Lock Plus")
    verify.grade_evidence(t, [snip("https://forum.example.com/t",
                                   "Any lock plus a deadbolt is fine")], TRUST)
    assert t.source_count == 0


# ---- End to end (offline) --------------------------------------------------

def test_mock_pipeline_runs_checks():
    rec = run_search("best extension cord", mock=True)
    assert rec.coverage["reddit"] >= 1
    assert rec.dropped_quotes == 0       # mock quotes are cut from the fixtures
    assert all(t.evidence_grade for t in rec.tiers)
