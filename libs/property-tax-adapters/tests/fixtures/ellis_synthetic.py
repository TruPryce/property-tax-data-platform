"""Small, identity-free Ellis PACS fixtures authored for this project.

Every member and package below was written by hand from the accepted contract,
not produced by the parser under test. No county bytes, production rows, PACS
exports, archives, published ODS or XLSX layouts, owner values, mailing or situs
addresses, credentials, host paths, or network responses appear here.

The owner and situs columns carry invented placeholder text purely to prove
those values never leave the parser. The package fixtures are hand-assembled
byte prefixes, not real spreadsheet files.
"""

RELEASE_IDENTIFIER = "ellis-certified-2025-synthetic"
SOURCE_MEMBER_NAME = "ellis_property_2025.txt"
CERTIFIED_LABEL = "certified-all-property"
EXPECTED_TAX_YEAR = 2025

#: Declared field widths, from the synthetic Ellis layout. Written out here so a
#: fixture row can be assembled without importing the layout it tests.
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
    ("owner_name", 50),
    ("owner_address", 60),
    ("situs_address", 60),
)
PROPERTY_WIDTH = sum(width for _, width in PROPERTY_WIDTHS)

OWNER_PLACEHOLDER = "PLACEHOLDER-OWNER-NAME"
ADDRESS_PLACEHOLDER = "PLACEHOLDER-OWNER-ADDRESS"
SITUS_PLACEHOLDER = "PLACEHOLDER-SITUS-ADDRESS"

_DEFAULTS = {
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
    "owner_name": OWNER_PLACEHOLDER,
    "owner_address": ADDRESS_PLACEHOLDER,
    "situs_address": SITUS_PLACEHOLDER,
}


def _pad(value: str, width: int, name: str) -> str:
    """Left-justify to the declared width, refusing to truncate.

    Silently clipping an over-wide value would make a fixture claim to carry
    something it does not, and an assertion on it would pass for the wrong
    reason.
    """

    if len(value) > width:
        raise ValueError(f"{name}: {len(value)} characters exceeds the declared width {width}")
    return value.ljust(width)


def property_row(**overrides: str) -> str:
    """One valid Ellis property record."""

    unknown = set(overrides) - set(_DEFAULTS)
    if unknown:
        raise KeyError(f"unknown Ellis field: {sorted(unknown)}")
    values = {**_DEFAULTS, **overrides}
    return "".join(_pad(values[name], width, name) for name, width in PROPERTY_WIDTHS)


def member(*rows: str, newline: str = "\n", trailing: bool = True) -> bytes:
    """Assemble a synthetic member from literal rows. Assembly only."""

    body = newline.join(rows)
    if trailing:
        body += newline
    return body.encode("iso-8859-1")


VALID_LF = member(property_row(), property_row(prop_id="000124"))
VALID_CRLF = member(property_row(), newline="\r\n")

UTF8_BOM = b"\xef\xbb\xbf" + VALID_LF
WIDTH_MISMATCH = member(property_row(), property_row()[:-3])
TRUNCATED_REQUIRED = member(property_row()[:20], property_row()[:20])

TRAILING_REGION_TEXT = "UNDOCUMENTED-ELLIS-TRAILING"
WITH_TRAILING_REGION = member(
    property_row() + TRAILING_REGION_TEXT,
    property_row(prop_id="000124") + TRAILING_REGION_TEXT,
)

OWNER_ALLOCATION = member(
    property_row(owner_sequence="1", ownership_percentage="50"),
    property_row(owner_sequence="2", ownership_percentage="25"),
    property_row(owner_sequence="3", ownership_percentage="25"),
)
DUPLICATE_OWNER_ROW = member(property_row(owner_sequence="1"), property_row(owner_sequence="1"))
CONFLICTING_ACCOUNT_FACTS = member(
    property_row(owner_sequence="1", market_value="250000.00"),
    property_row(owner_sequence="2", market_value="999000.00"),
)
LEADING_ZERO_ACCOUNTS = member(
    property_row(prop_id="000123", owner_sequence="1"),
    property_row(prop_id="123", owner_sequence="1"),
)

# --------------------------------------------------------------------------
# Layout package signatures
#
# Hand-assembled byte prefixes matching the OpenDocument layout: the ZIP
# local-file-header, then `mimetype` as the first member with its media type
# stored uncompressed. These are signature fixtures, not spreadsheet files, and
# nothing here is a real published layout.
# --------------------------------------------------------------------------

_ZIP_LOCAL_HEADER = b"PK\x03\x04"
_ODS_MEDIA_TYPE = b"application/vnd.oasis.opendocument.spreadsheet"

#: A valid ODS signature. The file this stands for is named `.xlsx.ods`, which
#: is exactly why classification must read content rather than the extension.
MISLEADING_ODS_NAME = "ellis_appraisal_layout.xlsx.ods"
#: A well-formed local file header: signature, version, flags, compression 0
#: (stored), times, CRC, sizes, name length 8, extra length 0, then `mimetype`
#: and its stored value.
VALID_ODS_PACKAGE = (
    _ZIP_LOCAL_HEADER
    + b"\x14\x00"  # version needed
    + b"\x00\x00"  # flags
    + b"\x00\x00"  # compression: stored
    + b"\x00" * 4  # mod time and date
    + b"\x00" * 4  # crc
    + b"\x00" * 4  # compressed size
    + b"\x00" * 4  # uncompressed size
    + b"\x08\x00"  # file name length
    + b"\x00\x00"  # extra field length
    + b"mimetype"
    + _ODS_MEDIA_TYPE
)

#: A ZIP whose first member is not `mimetype`: structurally a ZIP, not an ODS.
ZIP_WITHOUT_MIMETYPE = (
    _ZIP_LOCAL_HEADER
    + b"\x14\x00\x00\x00\x00\x00"
    + b"\x00" * 12
    + b"\x0b\x00"
    + b"\x00\x00"
    + b"content.xml"
    + b"\x00" * 32
)

#: A ZIP whose `mimetype` member carries a different media type.
ZIP_WITH_OTHER_MEDIA_TYPE = (
    _ZIP_LOCAL_HEADER
    + b"\x14\x00\x00\x00\x00\x00"
    + b"\x00" * 12
    + b"\x08\x00"
    + b"\x00\x00"
    + b"mimetype"
    + b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

#: Shorter than the signature it would need to carry.
TRUNCATED_PACKAGE = _ZIP_LOCAL_HEADER[:2]

#: No ZIP signature at all, despite an `.ods` name.
NOT_A_PACKAGE = b"This is plain text pretending to be a layout package."

EMPTY_PACKAGE = b""

#: A ZIP whose `mimetype` member is deflated rather than stored. ODS requires it
#: uncompressed, which is what makes the media type readable without
#: decompressing anything.
DEFLATED_MIMETYPE = (
    b"PK\x03\x04\x14\x00\x00\x00\x08\x00"
    + b"\x00" * 16
    + b"\x08\x00\x00\x00"
    + b"mimetype"
    + _ODS_MEDIA_TYPE
)

#: The marker appears after the signature but the header is not a `mimetype`
#: entry. Searching for the bytes rather than parsing the header accepted this.
MARKER_WITHOUT_HEADER = b"PK\x03\x04" + b"\x00" * 40 + b"mimetype" + _ODS_MEDIA_TYPE

#: `mimetype` is not the first member: the name length says something else.
WRONG_NAME_LENGTH = (
    b"PK\x03\x04\x14\x00\x00\x00\x00\x00"
    + b"\x00" * 16
    + b"\x0b\x00\x00\x00"
    + b"content.xml"
    + _ODS_MEDIA_TYPE
)

#: Uniformly short Ellis member, and child fixtures.
UNIFORMLY_SHORT = member(property_row()[:75], property_row(prop_id="000124")[:75])

CHILD_WIDTHS = (("prop_id", 12), ("child_sequence", 4), ("child_value", 15))


def child_row(prop_id: str = "000123", sequence: str = "1", value: str = "1000.00") -> str:
    """One valid Ellis child record."""

    fields = {"prop_id": prop_id, "child_sequence": sequence, "child_value": value}
    return "".join(_pad(fields[name], width, name) for name, width in CHILD_WIDTHS)


ACCEPTED_ACCOUNT_IDS = ("000123",)
CHILD_RESOLVED = member(child_row(prop_id="000123"))
CHILD_ORPHANED = member(child_row(prop_id="999999"))

#: Literal expectations authored from the contract, not from the parser.
EXPECTED_PROPERTY_WIDTH = 290
EXPECTED_DIAGNOSTIC_CODE_COUNT = 19
EXPECTED_VALID_ROWS = 2
UNSUPPORTED_LABELS = (
    "RC2 Potential",
    "rc2-potential-exemption",
    "mineral-only",
    "certified",
    "",
)
