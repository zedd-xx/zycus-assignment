# DESIGN

## What I eventually understood about these documents

On day one I treated a document as a form: find the fields, copy them into the
schema, done. That view books the easy third and then stalls, because it
assumes the page and the record answer the same question. They do not.

The page is a *statement to a human reader*: it may quote prices with tax
already inside them, print a tax once at the bottom that the lines have already
charged, deduct a deposit that was invoiced earlier, or foot to a total that is
a cent away from its own arithmetic because it rounded. The record is an
*instruction to a machine that will rebuild the total from the parts*. The ERP
does not read; it multiplies quantity by price, subtracts discounts, adds every
tax it finds, then adds charges. So the same printed number means different
things depending on where it sits in that recomputation.

The shift is that a document is not a set of values, it is a set of values
**plus a convention about how they were presented**, and only the convention is
ambiguous. Every failure I had was one convention wearing a different mask:
tax-inclusive pricing, a header tax restating line tax, a line tax restating a
header tax, a prepayment, a printed rounding line, a discount already applied
inside the line extensions, a withholding deducted from what is owed, a tax
charged as though it were a line item. That is why there is no list of special
cases: there is one question — *which presentation convention is this page
using?* — and the oracle is the only thing that can answer it.

So the system is built in two halves that never mix. **Transcription** copies
the page and is not allowed to do arithmetic. **Reconciliation** searches over
conventions, not over numbers: it never edits a value to make a total fit, it
re-reads the same values under a different convention and asks the ERP whether
that reading reproduces the total the page itself states, to the cent.

## The shape of the system

```
read_pdf -> segment -> parse -> build_payable -> reconcile -> master data -> output/X.json
  text layer      logical      Reading      schema        hypothesis     codes only
  or OCR          documents    (verbatim)   record        search         when matched
```

* **Extraction** (`autodraft/extract/`) uses the PDF text layer when there is
  one and Tesseract when there is not, keeping every word's coordinates so rows
  and columns survive. A vision model can replace this step via env vars; it
  transcribes only, and a bad response falls back to the local reading.
* **Segmentation** (`segment.py`) groups pages into logical documents by title,
  invoice-number and continuation cues, then classifies each as a payable
  (invoice, credit note) or not (statement, remittance, order, delivery note,
  receipt, proforma, reminder). Non-payables go to `declined[]` with a reason.
* **Parsing** (`parse.py`, `fields.py`, `lexicon.py`, `money.py`) reads headers,
  parties, a line table located by its own column headings, totals and taxes,
  in the languages and number formats the corpus uses. It records *where* each
  tax was printed, and it records absence as absence — an empty field, never a
  zero and never a derived figure.
* **Reconciliation** (`reconcile.py`) is described below.
* **Master data** (`masters.py`) resolves supplier, buyer org, tax, payment term
  and PO codes.

## When it meets a document unlike any it has seen

Three properties do the generalising, and none of them is a rule about a
specific layout.

**1. Transcription is layout-driven, not template-driven.** Labels come from a
multilingual lexicon and are matched as whole words near their values; the line
table is found by its own column headings rather than by fixed coordinates;
amounts are recognised by their numeric shape across locale conventions
(`1.234,56`, `1,234.56`, `1 234,56`, trailing-minus, parenthesised negatives),
and tokens that are identifiers rather than money — a VAT registration, an
invoice number — are excluded from being read as amounts. An unseen layout in a
known language degrades to missing fields, not to wrong ones.

**2. Correction is a licensed search, not a repair.** For each document the
system asks which conventions the page itself prints evidence for — "prices
include VAT" in the text, a tax rate on lines *and* the same tax restated in the
totals block, a printed "paid in advance" amount, a printed rounding line, a
withholding line. Only those hypotheses are admitted. It then searches the
smallest combination of admitted hypotheses under which the ERP's recomputation
equals the total the page states, exactly, to the cent. If none does, the record
is emitted exactly as transcribed and marked `unreconciled`. Nothing is ever
nudged toward a total.

This is what makes a wrong correction survivable, which the brief asks for
directly. A hypothesis cannot fire on a document that does not print its
evidence, and even when evidence exists it only fires if it lands on the stated
total to the cent — a document that is already correct books as-read before any
hypothesis is considered, so a "fix" cannot corrupt it. The failure mode is a
document left honestly unreconciled, not a document silently altered.

**3. Codes are evidence-ranked, and "no match" is an answer.** Master lookups go
through exact indexes first (VAT id, IBAN, email, PO number, country+rate) and
only then to a fuzzy name match that must clear a high threshold — lowered a
little only when an address corroborates it. A rate that several countries levy,
with no country evidence on the page, resolves to nothing rather than to the
first plausible row. A PO printed on the page but absent from the PO master
yields an empty `po_id` and a note, because it is a supplier's own reference,
not an ERP object.

Scale is handled at load time, not per lookup: each master is read once into
hash indexes plus an inverted token index that produces at most 25 candidates
for any name, so matching cost is independent of master size — the same code
path works against a handful of sample rows or millions.

## The document I could not solve the way the others were solved

The class that cannot be solved from the page is **the buyer organisation when
the document does not print a bill-to**. Supplier, tax, term and PO all have an
anchor printed somewhere on the page. Company / business unit / location often
do not: a small supplier's invoice frequently shows only a delivery address, or
nothing identifying the receiving entity at all. The chart of books cannot be
inverted from an absence, and "the only company in the master" is not evidence —
in a real tenant there are many.

So the system leaves those three codes blank and exposes a `--tenant` hint for
the operator who *does* know which entity the run belongs to. That is the honest
boundary: the answer exists in the environment, not in the document, and a
system that guessed it would be right in the sample and wrong the first time a
second company appeared.

The same reasoning, at line level, applies to tax type codes on documents that
print a rate but no jurisdiction: where the rate is ambiguous across countries
and the page offers no country evidence, the code stays empty.

