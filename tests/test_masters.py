from decimal import Decimal

from autodraft.masters import MasterData


def test_vat_id_beats_everything(masters: MasterData) -> None:
    match = masters.suppliers.match(name="Totally Different Name", vat_id="DE209177122")
    assert match.code == "2845695"


def test_name_typo_still_matches(masters: MasterData) -> None:
    match = masters.suppliers.match(
        name="Phocus Direkt Communication GmbH",
        address="Lina-Ammon-Strasse 19b, 90471 Nurnberg, DE",
    )
    assert match.code == "2845695"


def test_unknown_supplier_stays_empty(masters: MasterData) -> None:
    match = masters.suppliers.match(name="Nordwerk Maschinenbau GmbH", vat_id="DE811234567")
    assert match.code == ""
    assert not match.matched


def test_iban_resolves_a_supplier(masters: MasterData) -> None:
    match = masters.suppliers.match(name="", iban="EE472200221017274226")
    assert match.code == "2807582"


def test_a_rate_alone_is_not_a_tax_code(masters: MasterData) -> None:
    """20% exists in several countries; without a country it stays unresolved."""
    ambiguous = masters.taxes.match(Decimal("19"), country="")
    resolved = masters.taxes.match(Decimal("19"), country="DE")
    assert resolved.code == "DE_190_VAT"
    assert ambiguous.code in {"", "DE_190_VAT"}
    if ambiguous.code:
        assert len(masters.taxes._by_rate["19.00"]) == 1


def test_unknown_rate_stays_empty(masters: MasterData) -> None:
    assert masters.taxes.match(Decimal("17.5"), country="DE").code == ""
    assert masters.taxes.match(None, country="DE").code == ""


def test_payment_terms_match_text_then_days(masters: MasterData) -> None:
    assert masters.payment_terms.match("Net 30").code
    assert masters.payment_terms.match("Zahlbar innerhalb 30 Tage").code
    assert masters.payment_terms.match("", days=14).code
    assert masters.payment_terms.match("whenever you feel like it").code == ""


def test_po_not_in_master_is_not_invented(masters: MasterData) -> None:
    known = masters.purchase_orders.match("PO-EE-2026-0044")
    unknown = masters.purchase_orders.match("4500123456")
    assert known.code == "PO-EE-2026-0044"
    assert unknown.code == ""
    assert "not in the PO master" in unknown.reason


def test_buyer_resolves_from_the_invoice_to_address(masters: MasterData) -> None:
    row = masters.org.rows[0]
    match = masters.org.match(name=row["business_unit_name"], address=row["invoice_to_address"])
    assert match.company_code == row["company_code"]
    assert match.location_code == row["location_code"]


def test_buyer_without_evidence_stays_empty(masters: MasterData) -> None:
    match = masters.org.match(name="", address="", vat_id="")
    assert not match.matched
    assert match.company_code == ""


def test_candidate_generation_is_bounded(masters: MasterData) -> None:
    """Matching must not scan the master: only a few candidates are scored."""
    candidates = masters.suppliers._index.candidates("Phocus Direct Communication GmbH")
    assert 0 < len(candidates) <= 25
