from permitpipe.llm import grounding, to_unit_rows

TEXT = """Equipment to be Constructed:
EG-81 through EG-121
(41) MTU Model 16V4000G84S emergency diesel engine gen-sets
2,250 ekW
3,357 bhp
"""


def model_row(**over):
    row = {"ref_ids": "EG-81 through EG-121", "count": 41, "equipment": "generator",
           "manufacturer": "MTU", "model": "16V4000G84S", "rating_value": 2250,
           "rating_unit": "ekW", "section": "new", "duty": "emergency"}
    row.update(over)
    return row


def test_faithful_row_passes_everything():
    (r,) = to_unit_rows([model_row()], TEXT)
    assert not r.held and len(r.ref_ids) == 41 and r.unit_kw == 2250
    assert all(v for k, v in r.checks.items() if k.startswith("grounded"))


def test_made_up_values_are_held():
    for bad in (dict(count=40, ref_ids="EG-81 through EG-120"),   # consistent but not in the text
                dict(model="16V4000G94S"),                         # model from another permit
                dict(rating_value=2500),                           # rating not printed
                dict(ref_ids="EG-1 through EG-41")):               # IDs not printed
        (r,) = to_unit_rows([model_row(**bad)], TEXT)
        assert r.held, bad


def test_count_can_be_grounded_by_words_or_ids():
    text = TEXT.replace("(41)", "Forty-one (41)")
    assert grounding(model_row(), text)["grounded_count"]
    no_count = TEXT.replace("(41) ", "")
    assert grounding(model_row(), no_count)["grounded_count"]       # 41 IDs printed


def test_duplicate_ids_across_rows_held():
    rows = to_unit_rows([model_row(), model_row()], TEXT)
    assert all(r.held for r in rows)


def test_ids_with_internal_dashes_and_split_models_are_grounded():
    text = """00GEN-1 Emergency engine-generator set (Kohler/Rehlko KD3000 or equivalent) 3000 kWe
GEN-29 through GEN-32 (4) MTU 20V4000G94S Emergency diesel engine gen-sets
(Generator 20V4000
DS3000) 3,490 mkW (3,000 ekW)"""
    g = grounding(model_row(ref_ids="00GEN-1", count=None, model="KD3000", rating_value=3000), text)
    assert g["grounded_ids"] and g["grounded_model"]
    g = grounding(model_row(ref_ids="GEN-29 through GEN-32", count=4,
                            model="20V4000G94S (Generator 20V4000 DS3000)", rating_value=3000), text)
    assert g["grounded_ids"] and g["grounded_model"] and g["grounded_count"]


def test_row_without_printed_count_counts_its_ids():
    text = "00GEN-1 Emergency engine-generator set (Kohler/Rehlko KD3000 or equivalent) 3000 kWe"
    (r,) = to_unit_rows([model_row(ref_ids="00GEN-1", count=None, manufacturer="Kohler",
                                   model="KD3000", rating_value=3000, rating_unit="kWe")], text)
    assert r.count == 1 and not r.held and "count_from_ref_ids" in r.flags


def test_mislabelled_generator_cannot_escape_checks():
    text = "D1 through D22 Twenty-two (22) Caterpillar model 3516E emergency diesel engine gen-sets 2,750 kW"
    (r,) = to_unit_rows([model_row(ref_ids="D1 through D22", count=22, equipment="cooling_tower",
                                   manufacturer="Caterpillar", model="3516E", rating_value=2750,
                                   rating_unit="kW")], text)
    assert r.checks["class_consistent"] is False and r.held
