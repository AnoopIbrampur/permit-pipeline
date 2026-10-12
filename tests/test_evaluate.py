from permitpipe.evaluate import canon_id, gold_ids


def test_canon_id_keeps_inner_zeros():
    assert canon_id("EG100") == "EG100"
    assert canon_id("GEN001") == "GEN1" and canon_id("EG-16") == "EG16"
    assert canon_id("ENG 155") == "ENG155" and canon_id("00GEN-1") != canon_id("01GEN-1")


def test_gold_ids_forms():
    assert len(gold_ids("EG1-EG20, EG22-EG41, EG43-EG62, EG64-EG83, EG85-EG104")) == 100
    assert gold_ids("EG-16 thru EG-20") == {f"EG{i}" for i in range(16, 21)}
    assert gold_ids("1, 2, 3, and 4") == {"1", "2", "3", "4"}
    assert gold_ids("1-5") == {"1", "2", "3", "4", "5"}
    assert gold_ids("EG1-EG3 and EGR") == {"EG1", "EG2", "EG3", "EGR"}
    assert gold_ids("A/B10, C12-C15") == {"A/B10", "C12", "C13", "C14", "C15"}
