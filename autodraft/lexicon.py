"""Multilingual vocabulary of the words supplier documents print.

The parser never keys off a specific supplier or layout; it keys off the role a
word plays (a total, a tax, a credit note title). Adding a language means adding
words here, not adding a branch anywhere else.
"""
from __future__ import annotations

# ── document titles ────────────────────────────────────────────────────────
INVOICE_TITLES = (
    "invoice", "tax invoice", "vat invoice", "rechnung", "faktura", "arve",
    "factura", "fatura", "factuur", "facture", "fattura", "faktur",
    "invois", "ansa", "sales invoice", "commercial invoice",
)
CREDIT_TITLES = (
    "credit note", "credit memo", "creditnote", "gutschrift", "kreditnota",
    "kreditarve", "nota de credito", "nota de crédito", "nota credito",
    "avoir", "nota di credito", "credit invoice", "rechnungskorrektur",
    "stornorechnung", "storno", "credit adjustment", "nota kredit",
)
PROFORMA_TITLES = (
    "proforma", "pro forma", "pro-forma", "proforma invoice", "quotation",
    "quote", "offer", "angebot", "pakkumine", "sebut harga", "orcamento",
    "orçamento", "estimate", "kostenvoranschlag",
)
STATEMENT_TITLES = (
    "statement", "statement of account", "account statement", "kontoauszug",
    "kontoubersicht", "kontoübersicht", "kontoväljavõte", "extrato de conta",
    "penyata akaun", "aging report", "open items", "offene posten",
)
REMITTANCE_TITLES = (
    "remittance advice", "remittance", "payment advice", "zahlungsavis",
    "maksekorraldus", "payment confirmation", "receipt of payment",
    "aviso de pagamento",
)
RECEIPT_TITLES = (
    "receipt", "quittung", "kviitung", "recibo", "resit", "payment receipt",
    "cash receipt", "kassenbon", "till receipt",
)
ORDER_TITLES = (
    "purchase order", "order confirmation", "auftragsbestatigung",
    "auftragsbestätigung", "bestellung", "tellimus", "pesanan belian",
    "sales order", "order acknowledgement",
)
DELIVERY_TITLES = (
    "delivery note", "packing list", "lieferschein", "saateleht",
    "guia de remessa", "nota de entrega", "nota penghantaran", "waybill",
    "consignment note", "goods received note",
)
REMINDER_TITLES = (
    "reminder", "dunning", "mahnung", "zahlungserinnerung", "meeldetuletus",
    "aviso de cobranca", "aviso de cobrança", "overdue notice", "peringatan",
    "final demand",
)
CONTRACT_TITLES = (
    "terms and conditions", "agreement", "contract", "vertrag", "leping",
    "general terms", "allgemeine geschaftsbedingungen", "privacy notice",
    "cover letter", "compliment slip",
)

# ── header field labels ────────────────────────────────────────────────────
INVOICE_NUMBER_LABELS = (
    "invoice number", "invoice no", "invoice #", "invoice nr", "inv no",
    "rechnungsnummer", "rechnung nr", "rechnungs-nr", "beleg nr", "belegnummer",
    "arve number", "arve nr", "arve nr.", "faktura nr", "numero", "número",
    "numero da fatura", "número da fatura", "fatura n", "factura n",
    "no. invois", "nombor invois", "document number", "document no",
    "credit note number", "credit note no", "gutschrift nr", "tax invoice no",
)
INVOICE_DATE_LABELS = (
    "invoice date", "date of invoice", "rechnungsdatum", "belegdatum",
    "arve kuupaev", "arve kuupäev", "kuupaev", "kuupäev", "data da fatura",
    "data de emissao", "data de emissão", "fecha", "tarikh invois", "tarikh",
    "issue date", "issued", "date", "datum", "document date",
)
DUE_DATE_LABELS = (
    "due date", "payment due", "due", "date due", "faelligkeit", "fälligkeit",
    "faellig am", "fällig am", "zahlbar bis", "zahlungsziel",
    "maksetahtaeg", "maksetähtaeg", "tahtaeg", "tähtaeg",
    "data de vencimento", "vencimento", "pagar ate", "pagar até",
    "tarikh akhir bayaran", "payable by", "pay by",
)
PAYMENT_TERM_LABELS = (
    "payment terms", "terms of payment", "payment term", "terms",
    "zahlungsbedingungen", "zahlungskonditionen", "maksetingimused",
    "condicoes de pagamento", "condições de pagamento", "syarat pembayaran",
)
PO_LABELS = (
    "purchase order", "po number", "po no", "p.o.", "po#", "order number",
    "your order", "bestellnummer", "bestell-nr", "auftragsnummer",
    "tellimuse nr", "tellimus nr", "numero da encomenda", "no. pesanan",
    "customer order", "order ref", "order reference",
)
VAT_ID_LABELS = (
    "vat id", "vat no", "vat number", "vat reg", "ust-idnr", "ustid",
    "umsatzsteuer-identifikationsnummer", "steuernummer", "tax id", "tin",
    "kmkr", "kmkr nr", "km registrinumber", "nif", "nipc", "contribuinte",
    "no. cukai", "gst no", "sst no", "abn", "tax registration",
)
# Rows that print a registration number, not an amount.
IDENTIFIER_LABELS = (
    "vat id", "vat no", "vat number", "vat reg", "ust-idnr", "ustid",
    "umsatzsteuer-identifikationsnummer", "steuernummer", "tax id",
    "tax registration", "registration no", "company no", "reg no",
    "kmkr", "nif", "nipc", "contribuinte", "no. cukai", "gst no", "sst no",
    "abn", "tin no", "handelsregister", "registrikood",
)
IBAN_LABELS = ("iban", "bank account", "account no", "kontonummer", "konto", "no akaun")

# ── totals & tax labels ────────────────────────────────────────────────────
GROSS_LABELS = (
    "total due", "amount due", "balance due", "total amount due", "grand total",
    "total payable", "amount payable", "total to pay", "please pay",
    "gesamtbetrag", "rechnungsbetrag", "endbetrag", "zu zahlen",
    "zahlbetrag", "bruttobetrag", "brutto", "gesamtsumme",
    "kokku tasuda", "tasumisele kuulub", "summa kokku", "kogusumma",
    "total a pagar", "total geral", "valor total", "montante total",
    "jumlah perlu dibayar", "jumlah besar", "jumlah", "total", "invoice total",
)
SUBTOTAL_LABELS = (
    "subtotal", "sub-total", "sub total", "net amount", "net total",
    "total net", "total excl", "total excluding", "amount excl",
    "zwischensumme", "nettobetrag", "netto", "summe netto",
    "kokku ilma kaibemaksuta", "kokku ilma käibemaksuta", "neto",
    "total sem iva", "valor liquido", "valor líquido",
    "jumlah kecil", "taxable amount", "net goods",
)
TAX_TOTAL_LABELS = (
    "total vat", "vat total", "total tax", "tax total", "vat amount",
    "tax amount", "mehrwertsteuer", "umsatzsteuer", "mwst", "ust",
    "kaibemaks", "käibemaks", "km 24", "km 22", "km",
    "total iva", "iva", "total de imposto", "sst", "gst", "total gst",
)
TAX_WORDS = (
    "vat", "mwst", "ust", "mehrwertsteuer", "umsatzsteuer", "kaibemaks",
    "käibemaks", "km", "iva", "tva", "igv", "gst", "sst", "consumption tax",
    "sales tax", "service tax", "tax", "steuer", "imposto", "cukai",
    "nhil", "getfund", "covid levy", "levy", "withholding", "wht",
    "quellensteuer", "retencao", "retenção", "potongan cukai", "tds",
)
WITHHOLDING_WORDS = (
    "withholding", "wht", "retention", "retencao", "retenção", "quellensteuer",
    "einbehalt", "tds", "kinnipeetav", "potongan cukai", "withheld",
)
REVERSE_CHARGE_WORDS = (
    "reverse charge", "reverse-charge", "umkehr der steuerschuldnerschaft",
    "steuerschuldnerschaft des leistungsempfangers",
    "steuerschuldnerschaft des leistungsempfängers", "poordmaksustamine",
    "pöördmaksustamine", "autoliquidacao", "autoliquidação", "art. 194",
    "article 196", "intra-community supply", "innergemeinschaftliche",
)
TAX_INCLUSIVE_WORDS = (
    "incl. vat", "incl vat", "including vat", "vat included", "inclusive of vat",
    "inkl. mwst", "inkl mwst", "inkl. ust", "brutto preis", "bruttopreis",
    "preise inkl", "kaibemaksuga", "käibemaksuga", "hind koos km",
    "com iva incluido", "com iva incluído", "iva incluido", "iva incluído",
    "harga termasuk cukai", "tax inclusive", "gross price", "prices include",
    "price incl", "incl. tax", "including tax", "amounts include",
)
TAX_EXCLUSIVE_WORDS = (
    "excl. vat", "excl vat", "excluding vat", "plus vat", "net of vat",
    "zzgl. mwst", "zzgl mwst", "exkl. mwst", "netto preise", "preise netto",
    "km-ta", "ilma kaibemaksuta", "ilma käibemaksuta", "sem iva",
    "tidak termasuk cukai", "tax exclusive", "excl. tax", "prices exclude",
)

# ── deductions that reduce what is owed ────────────────────────────────────
PREPAYMENT_WORDS = (
    "prepayment", "prepaid", "advance payment", "deposit", "down payment",
    "anzahlung", "vorauszahlung", "ettemaks", "adiantamento", "sinal",
    "bayaran pendahuluan", "paid on account", "payment received",
    "already paid", "less payment", "amount paid", "bereits gezahlt",
    "bereits bezahlt", "juba tasutud", "ja pago", "já pago", "retainer applied",
)
DISCOUNT_WORDS = (
    "discount", "rabatt", "skonto", "nachlass", "allahindlus", "soodustus",
    "desconto", "diskaun", "rebate", "less discount", "trade discount",
)
FREIGHT_WORDS = (
    "freight", "shipping", "delivery charge", "carriage", "versand",
    "versandkosten", "fracht", "transport", "saatekulu", "transpordikulu",
    "portes", "frete", "penghantaran", "postage", "handling",
)
INSURANCE_WORDS = ("insurance", "versicherung", "kindlustus", "seguro", "insurans")
ROUNDING_WORDS = (
    "rounding", "rounded", "rundung", "rundungsdifferenz", "umardamine",
    "arredondamento", "pembundaran", "round off", "rounding adjustment",
)
CHARGE_WORDS = (
    "service charge", "surcharge", "handling fee", "admin fee", "fee",
    "gebuhr", "gebühr", "zuschlag", "teenustasu", "taxa", "caj", "levy",
    "environmental fee", "recycling fee", "packaging",
)
EXCISE_WORDS = ("excise", "duty", "verbrauchsteuer", "aktsiis", "imposto especial", "duti", "customs duty")

# ── line-item table headers ────────────────────────────────────────────────
COLUMN_DESCRIPTION = (
    "description", "item", "article", "product", "service", "details",
    "bezeichnung", "artikel", "leistung", "beschreibung", "position",
    "kirjeldus", "nimetus", "toode", "descricao", "descrição", "artigo",
    "keterangan", "perkara", "particulars",
)
COLUMN_QUANTITY = (
    "qty", "quantity", "menge", "anzahl", "kogus", "tk", "quantidade", "qtd",
    "kuantiti", "bil", "hours", "hrs", "units", "stk",
)
COLUMN_UNIT_PRICE = (
    "unit price", "price", "rate", "einzelpreis", "preis", "e-preis", "hind",
    "uhiku hind", "ühiku hind", "preco unitario", "preço unitário", "preco",
    "harga seunit", "harga", "unit cost", "per unit",
)
COLUMN_TOTAL = (
    "amount", "total", "line total", "net amount", "value", "betrag", "summe",
    "gesamt", "summa", "kokku", "valor", "montante", "jumlah", "extension",
)
COLUMN_TAX = (
    "vat", "tax", "mwst", "ust", "km", "iva", "gst", "sst", "vat %", "tax %",
    "vat rate", "steuersatz", "maksumaar", "maksumäär", "taxa iva", "kadar cukai",
)
COLUMN_DISCOUNT = ("discount", "disc", "rabatt", "allahindlus", "desconto", "diskaun", "%")
COLUMN_UOM = ("uom", "unit", "einheit", "uhik", "ühik", "unidade", "unit ukuran", "measure")

# ── item type hints ────────────────────────────────────────────────────────
SERVICE_WORDS = (
    "service", "consulting", "consultancy", "support", "maintenance", "licence",
    "license", "subscription", "hosting", "rental", "rent", "fee", "labour",
    "labor", "hours", "training", "audit", "management", "dienstleistung",
    "beratung", "wartung", "miete", "teenus", "konsultatsioon", "servico",
    "serviço", "manutencao", "manutenção", "perkhidmatan", "sewa",
    "consultoria", "consultadoria", "projektmanagement", "beratungsleistung",
)
FREIGHT_ITEM_WORDS = FREIGHT_WORDS

ALL_DOC_TITLES = {
    "INVOICE": INVOICE_TITLES,
    "CREDIT_NOTE": CREDIT_TITLES,
    "PROFORMA": PROFORMA_TITLES,
    "STATEMENT": STATEMENT_TITLES,
    "REMITTANCE": REMITTANCE_TITLES,
    "RECEIPT": RECEIPT_TITLES,
    "ORDER": ORDER_TITLES,
    "DELIVERY_NOTE": DELIVERY_TITLES,
    "REMINDER": REMINDER_TITLES,
    "CONTRACT": CONTRACT_TITLES,
}
