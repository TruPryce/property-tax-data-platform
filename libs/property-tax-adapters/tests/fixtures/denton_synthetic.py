"""Small, identity-free Denton PACS fixtures authored for this project.

Every member below was written by hand from the accepted contract, not produced
by the parser under test, so the expectations are independent evidence rather
than a restatement of the implementation. No county bytes, production rows,
PACS exports, archives, published layouts, owner values, mailing or situs
addresses, credentials, host paths, or network responses appear here.

The owner and situs columns carry invented placeholder text purely to prove
those values never leave the parser.
"""

RELEASE_IDENTIFIER = "denton-certified-2025-synthetic"
SOURCE_MEMBER_NAME = "denton_property_2025.txt"
EXPECTED_TAX_YEAR = 2025

#: Declared field widths, from the synthetic property layout. Written out here
#: so a fixture row can be assembled without importing the layout it tests.
PROPERTY_WIDTHS = (
    ("prop_id", 12),
    ("owner_sequence", 4),
    ("tax_year", 4),
    ("ownership_percentage", 10),
    ("market_value", 15),
    ("appraised_value", 15),
    ("assessed_value", 15),
    ("land_value", 15),
    ("improvement_value", 15),
    ("agricultural_value", 15),
    ("ten_percent_cap", 15),
    ("owner_name", 50),
    ("owner_address", 60),
    ("situs_address", 60),
)
PROPERTY_WIDTH = sum(width for _, width in PROPERTY_WIDTHS)

CHILD_WIDTHS = (("prop_id", 12), ("child_sequence", 4), ("child_value", 15))
CHILD_WIDTH = sum(width for _, width in CHILD_WIDTHS)

OWNER_PLACEHOLDER = "PLACEHOLDER-OWNER-NAME"
ADDRESS_PLACEHOLDER = "PLACEHOLDER-OWNER-ADDRESS"
SITUS_PLACEHOLDER = "PLACEHOLDER-SITUS-ADDRESS"

_PROPERTY_DEFAULTS = {
    "prop_id": "000123",
    "owner_sequence": "1",
    "tax_year": "2025",
    "ownership_percentage": "100",
    "market_value": "250000.00",
    "appraised_value": "250000.00",
    "assessed_value": "230000.00",
    "land_value": "50000.00",
    "improvement_value": "200000.00",
    "agricultural_value": "",
    "ten_percent_cap": "20000.00",
    "owner_name": OWNER_PLACEHOLDER,
    "owner_address": ADDRESS_PLACEHOLDER,
    "situs_address": SITUS_PLACEHOLDER,
}


def property_row(**overrides: str) -> str:
    """One valid property record, left-justified and space-padded to width."""

    unknown = set(overrides) - set(_PROPERTY_DEFAULTS)
    if unknown:
        raise KeyError(f"unknown Denton field: {sorted(unknown)}")
    values = {**_PROPERTY_DEFAULTS, **overrides}
    return "".join(_pad(values[name], width, name) for name, width in PROPERTY_WIDTHS)


def child_row(prop_id: str = "000123", sequence: str = "1", value: str = "1000.00") -> str:
    """One valid child record."""

    fields = {"prop_id": prop_id, "child_sequence": sequence, "child_value": value}
    return "".join(_pad(fields[name], width, name) for name, width in CHILD_WIDTHS)


def _pad(value: str, width: int, name: str) -> str:
    """Left-justify to the declared width, refusing to truncate.

    Silently clipping an over-wide value would make a fixture claim to carry
    something it does not, and the test asserting on it would pass for the
    wrong reason.
    """

    if len(value) > width:
        raise ValueError(f"{name}: {len(value)} characters exceeds the declared width {width}")
    return value.ljust(width)


def member(*rows: str, newline: str = "\n", trailing: bool = True) -> bytes:
    """Assemble a synthetic member from literal rows.

    Assembly only: it applies no validation and mirrors no parser behaviour.
    """

    body = newline.join(rows)
    if trailing:
        body += newline
    return body.encode("iso-8859-1")


VALID_LF = member(property_row())
VALID_CRLF = member(property_row(), newline="\r\n")
VALID_NO_TRAILING_NEWLINE = member(property_row(), trailing=False)

UTF8_BOM = b"\xef\xbb\xbf" + VALID_LF
UTF16_LE_BOM = b"\xff\xfe" + VALID_LF

#: Two records whose widths disagree: the second is three characters short.
WIDTH_MISMATCH = member(property_row(), property_row()[:-3])

#: Every record short enough that a required field's declared end is beyond it.
TRUNCATED_REQUIRED = member(property_row()[:20], property_row()[:20])

#: Uniform width beyond the layout's declared end, so the trailing region is a
#: property of the member rather than of one record.
TRAILING_REGION_TEXT = "UNDOCUMENTED-TRAILING-CONTENT"
WITH_TRAILING_REGION = member(
    property_row() + TRAILING_REGION_TEXT,
    property_row(prop_id="000124") + TRAILING_REGION_TEXT,
)

#: An undivided-interest allocation: one account, three owner sequences, and
#: identical account-level facts.
OWNER_ALLOCATION = member(
    property_row(owner_sequence="1", ownership_percentage="50"),
    property_row(owner_sequence="2", ownership_percentage="25"),
    property_row(owner_sequence="3", ownership_percentage="25"),
)

#: The same account and the same owner sequence twice.
DUPLICATE_OWNER_ROW = member(
    property_row(owner_sequence="1"),
    property_row(owner_sequence="1"),
)

#: One account, two owner sequences, disagreeing on an account-level fact.
CONFLICTING_ACCOUNT_FACTS = member(
    property_row(owner_sequence="1", market_value="250000.00"),
    property_row(owner_sequence="2", market_value="999000.00"),
)

#: Account identifiers that differ only by leading zeroes are distinct accounts,
#: which only holds if they are compared as text.
LEADING_ZERO_ACCOUNTS = member(
    property_row(prop_id="000123", owner_sequence="1"),
    property_row(prop_id="123", owner_sequence="1"),
)

ACCEPTED_ACCOUNT_IDS = ("000123",)
CHILD_RESOLVED = member(child_row(prop_id="000123"))
CHILD_ORPHANED = member(child_row(prop_id="999999"))

EMPTY_MEMBER = b""

#: Literal expectations authored from the contract, not from the parser.
EXPECTED_PROPERTY_WIDTH = 305
EXPECTED_CHILD_WIDTH = 31
EXPECTED_DIAGNOSTIC_CODE_COUNT = 18
EXPECTED_SENSITIVE_FIELD_COUNT = 3
