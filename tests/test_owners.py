from permitpipe.owners import address_key, companies_named, entity_key, page_header, parse_cover_letter

BELMONT = """September 28, 2026
Mr. Jordan Example
Authorized Signatory
Buildings 3 & 4: Belmont Holdings I, LLC
Building 5: Loudoun Prop 1, LLC
Building 2: Loudoun Prop 2, LLC
817 Broadway, 10th Floor
New York, NY 10003
Location: Loudoun County
Registration No.: 74321
Dear Mr. Example:
"""
DIGITAL = """June 24, 2026
Mr. Sam Placeholder
Sr Director, Portfolio Management Group
Digital Realty
10 Post Office Square, Suite 500
Boston, MA  02109
Location:  Prince William County and City of Manassas
"""


def test_cover_letter_entities_address_and_no_person():
    c = parse_cover_letter(BELMONT)
    assert c.entities == ["Belmont Holdings I, LLC", "Loudoun Prop 1, LLC", "Loudoun Prop 2, LLC"]
    assert c.address == "817 Broadway, 10th Floor, New York, NY 10003"
    assert c.title == "Authorized Signatory"
    assert "Example" not in " ".join(c.entities) + (c.address or "") + (c.title or "")


def test_cover_letter_names_operator():
    c = parse_cover_letter(DIGITAL)
    assert c.entities == ["Digital Realty"] and companies_named(c.entities[0]) == ["Digital Realty"]
    assert c.title.startswith("Sr Director")


def test_keys():
    assert entity_key("Loudoun Prop 1, LLC") == entity_key("LOUDOUN PROP 1 L.L.C.")
    assert address_key("817 Broadway, 10th Floor, New York, NY 10003") == \
        address_key("817 Broadway, Floor 12, New York, NY 10003-1234")
    assert address_key("1401 Meadowville Technology Parkway") == address_key("1401 Meadowville Technology Pkwy")


def test_page_header():
    assert page_header("Yondr JK 2, LLC\nRegistration Number:  74265\nAugust 13, 2026\nPage 3") == "Yondr JK 2, LLC"


def test_people_never_stored():
    from permitpipe.owners import redact_people
    amazon = """July 7, 2026
Authorized Representative
c/o Mr. Alex “AJ” Sample
Amazon Data Services, Inc.
13200 Woodland Park Road
Herndon, VA 20171
Location: Loudoun County
"""
    c = parse_cover_letter(amazon.replace("July 7, 2026\n", "July 7, 2026\nMs. Someone Else\n"))
    blob = " ".join(c.entities) + c.quote + (c.address or "")
    assert "Sample" not in blob and "Alex" not in blob
    assert c.entities == ["Amazon Data Services, Inc."]
    assert redact_people("c/o Ms. Robin Lee Doe / Amazon") == "c/o [person] / Amazon"


def test_research_file_meets_evidence_rules():
    import json

    from permitpipe.owners import RESEARCH_FILE, validate_research
    for link in json.loads(RESEARCH_FILE.read_text())["links"]:
        assert validate_research(link) == [], link["site_id"]
        assert all("Mr." not in e["claim"] and "Ms." not in e["claim"] for e in link["evidence"])


def test_validation_rejects_weak_links():
    from permitpipe.owners import validate_research
    weak = {"link_type": "direct", "evidence": [
        {"kind": "permit", "claim": "x"}, {"kind": "directory", "url": "u", "claim": "y"}]}
    problems = validate_research(weak)
    assert "outside evidence rests on a single directory listing" in problems
    assert any("direct link needs" in p for p in problems)


def test_addressee_without_honorific_and_without_location_line():
    a = """June 1, 2026
Jordan Example
Authorized Representative
c/o Ms. Someone Else
Amazon Data Services, Inc.
13820 Sunrise Valley Drive
Herndon, VA 20171
Location:  Spotsylvania County
"""
    c = parse_cover_letter(a)
    assert c.entities == ["Amazon Data Services, Inc."] and "Jordan" not in c.quote
    b = """May 22, 2026
Ms. Pat Placeholder
Vice President
13832 Redskin Acquisition, LP
14555 Avion Parkway, Suite 110
Chantilly, VA 20151
Dear Ms. Placeholder:
"""
    c = parse_cover_letter(b)
    assert c.entities == ["13832 Redskin Acquisition, LP"] and c.address.startswith("14555 Avion")
