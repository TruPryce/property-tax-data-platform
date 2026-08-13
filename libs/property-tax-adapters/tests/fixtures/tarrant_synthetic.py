"""Small, identity-free Tarrant certified-core fixtures authored for this project.

Every member below was written by hand from the accepted contract, not produced
by the parser under test, so the expectations are independent evidence rather
than a restatement of the implementation.  No county bytes, production rows,
owner values, mailing or situs addresses, protected identities, credentials,
host paths, or network responses appear here.

The `Owner_Name` and `Situs_Address` columns that appear in one member carry
invented placeholder text purely to prove those values never leave the parser.
"""

RELEASE_IDENTIFIER = "tarrant-certified-2025-synthetic"
SOURCE_MEMBER_NAME = "tarrant_certified_core_2025.txt"
EXPECTED_SOURCE_YEAR = 2025

#: The sixteen required headers in the canonical order from D1.
HEADER = (
    "RP|Appraisal_Year|Account_Num|PIDN|GIS_Link|Property_Class|State_Use_Code|"
    "Exemption_Code|Land_Value|Improvement_Value|Total_Value|Appraised_Value|"
    "Ag_Value|Deed_Date|Notice_Date|Appraisal_Date"
)

#: A deliberately noncanonical order; binding is by exact name, so this is valid.
HEADER_REORDERED = (
    "Appraisal_Date|Notice_Date|Deed_Date|Ag_Value|Appraised_Value|Total_Value|"
    "Improvement_Value|Land_Value|Exemption_Code|State_Use_Code|Property_Class|"
    "GIS_Link|PIDN|Account_Num|Appraisal_Year|RP"
)

#: One valid row: leading zeroes and punctuation in the account, blank optional
#: fields as source absence, and dates in the D6 form.
VALID_ROW = (
    "R|2025|00123-A|PIDN-0001|GIS-0001|A1|A|EX1|1000|2500.50|3500.50|3500.50|"
    "|3/14/2025|03/14/2025|12/1/2025"
)

#: The same row rewritten for the reordered header.
VALID_ROW_REORDERED = (
    "12/1/2025|03/14/2025|3/14/2025||3500.50|3500.50|2500.50|1000|EX1|A|A1|"
    "GIS-0001|PIDN-0001|00123-A|2025|R"
)

VALID_LF = f"{HEADER}\n{VALID_ROW}\n".encode("iso-8859-1")
VALID_CRLF = f"{HEADER}\r\n{VALID_ROW}\r\n".encode("iso-8859-1")
VALID_NO_TRAILING_NEWLINE = f"{HEADER}\n{VALID_ROW}".encode("iso-8859-1")
VALID_REORDERED = f"{HEADER_REORDERED}\n{VALID_ROW_REORDERED}\n".encode("iso-8859-1")

UTF8_BOM = b"\xef\xbb\xbf" + VALID_LF
UTF16_LE_BOM = b"\xff\xfe" + VALID_LF

#: A quoted `Property_Class` carrying one literal pipe.  If the pipe were read as
#: a delimiter the row would gain a column and fail on width instead.
QUOTED_DELIMITER = (
    f"{HEADER}\n"
    'R|2025|00123-A|PIDN-0001|GIS-0001|"A|1"|A|EX1|1000|2500.50|3500.50|3500.50|'
    "|3/14/2025|03/14/2025|12/1/2025\n"
).encode("iso-8859-1")

#: `"a""|b"` — seven characters, decoding to the four-character `a"|b`.  If the
#: doubled quote closed the field early, the pipe would split the row.
QUOTED_DOUBLED_QUOTE = (
    f"{HEADER}\n"
    'R|2025|00123-A|PIDN-0001|GIS-0001|"a""|b"|A|EX1|1000|2500.50|3500.50|'
    "3500.50||3/14/2025|03/14/2025|12/1/2025\n"
).encode("iso-8859-1")

#: An opening quote that never closes.
UNBALANCED_QUOTE = (
    f"{HEADER}\n"
    'R|2025|00123-A|PIDN-0001|GIS-0001|"A1|A|EX1|1000|2500.50|3500.50|3500.50|'
    "|3/14/2025|03/14/2025|12/1/2025\n"
).encode("iso-8859-1")

#: A quoted field containing an embedded LF, which would otherwise give one
#: logical record two physical row numbers.
MULTILINE_RECORD = (
    f"{HEADER}\n"
    'R|2025|00123-A|PIDN-0001|GIS-0001|"A\n1"|A|EX1|1000|2500.50|3500.50|'
    "3500.50||3/14/2025|03/14/2025|12/1/2025\n"
).encode("iso-8859-1")

#: One metadata extra beside the required sixteen.
HEADER_WITH_EXTRA = f"{HEADER}|Synthetic_Note"
EXTRA_COLUMN = f"{HEADER_WITH_EXTRA}\n{VALID_ROW}|synthetic-note\n".encode("iso-8859-1")

#: Sensitive header names in the layout; their values must never surface.
HEADER_WITH_SENSITIVE = f"{HEADER}|Owner_Name|Situs_Address"
SENSITIVE_COLUMNS = (
    f"{HEADER_WITH_SENSITIVE}\n{VALID_ROW}|PLACEHOLDER-OWNER|PLACEHOLDER-SITUS\n"
).encode("iso-8859-1")
SENSITIVE_PLACEHOLDERS = ("PLACEHOLDER-OWNER", "PLACEHOLDER-SITUS")

BLANK_HEADER = f"{HEADER}|\n{VALID_ROW}|x\n".encode("iso-8859-1")
PADDED_HEADER = f"{HEADER} \n{VALID_ROW}\n".encode("iso-8859-1")
DUPLICATE_HEADER = f"{HEADER}|Account_Num\n{VALID_ROW}|00999\n".encode("iso-8859-1")
CASE_FOLD_COLLISION = f"{HEADER}|ACCOUNT_NUM\n{VALID_ROW}|00999\n".encode("iso-8859-1")
#: `Ag_Value` and its blank field are both removed, so the layout is fifteen
#: wide and the row matches it. The only defect is the absent required header.
_HEADER_NAMES = HEADER.split("|")
_AG_VALUE_INDEX = _HEADER_NAMES.index("Ag_Value")
MISSING_REQUIRED_HEADER = (
    "|".join(name for name in _HEADER_NAMES if name != "Ag_Value")
    + "\n"
    + "|".join(
        value for index, value in enumerate(VALID_ROW.split("|")) if index != _AG_VALUE_INDEX
    )
    + "\n"
).encode("iso-8859-1")

#: Sixteen headers, fifteen fields.
ROW_WIDTH_MISMATCH = (
    f"{HEADER}\nR|2025|00123-A|PIDN-0001|GIS-0001|A1|A|EX1|1000|2500.50|3500.50|"
    "3500.50||3/14/2025|03/14/2025\n"
).encode("iso-8859-1")

#: A spanning record followed by an otherwise valid row: the continuation
#: belongs to the rejected record, so only one diagnostic should result.
MULTILINE_RECORD_THEN_VALID = (
    f"{HEADER}\n"
    'R|2025|00123-A|PIDN-0001|GIS-0001|"A\n1"|A|EX1|1000|2500.50|3500.50|'
    "3500.50||3/14/2025|03/14/2025|12/1/2025\n"
    f"{VALID_ROW}\n"
).encode("iso-8859-1")

#: The same defect with a CRLF inside the quoted field.
MULTILINE_RECORD_CRLF = (
    f"{HEADER}\r\n"
    'R|2025|00123-A|PIDN-0001|GIS-0001|"A\r\n1"|A|EX1|1000|2500.50|3500.50|'
    "3500.50||3/14/2025|03/14/2025|12/1/2025\r\n"
).encode("iso-8859-1")

#: U+00DF, representable in ISO-8859-1.  `"SS".casefold()` and
#: `SHARP_S.casefold()` are both "ss", so Unicode folding reports a collision
#: between two headers that D1's ASCII rule treats as distinct names.
SHARP_S = "\N{LATIN SMALL LETTER SHARP S}"
NON_ASCII_DISTINCT_EXTRAS = (f"{HEADER}|SS|{SHARP_S}\n{VALID_ROW}|x|y\n").encode("iso-8859-1")

#: A closing quote followed by ordinary characters. Appending them to the field
#: would silently accept a value the physical contract never described.
TRAILING_TEXT_AFTER_QUOTE = (
    f"{HEADER}\n"
    'R|2025|00123-A|PIDN-0001|GIS-0001|"A"junk|A|EX1|1000|2500.50|3500.50|'
    "3500.50||3/14/2025|03/14/2025|12/1/2025\n"
).encode("iso-8859-1")

#: A malformed row at physical row 2 and a division defect at row 3, in both
#: line endings. Consuming only the CR of a CRLF during recovery would leave the
#: LF to open a phantom blank record and shift row 3 to row 4.
_MALFORMED_ROW = 'R|2025|A1|P|G|"bad"x|A|E|1|2|3|4||3/1/2025|3/1/2025|3/1/2025'


def malformed_then_bad_row(newline: str = "\n") -> bytes:
    """Header, a malformed record, then a record with an invalid division."""

    body = newline.join((HEADER, _MALFORMED_ROW, row(RP="X", Account_Num="ACC-3")))
    return (body + newline).encode("iso-8859-1")


#: D1 accepts LF and CRLF. A member separated only by bare CR is not a valid
#: physical layout, and must not parse as though it were.
BARE_CR_MEMBER = f"{HEADER}\r{VALID_ROW}\r".encode("iso-8859-1")

EMPTY_MEMBER = b""


def member(*rows: str, header: str = HEADER) -> bytes:
    """Assemble a synthetic member from literal rows.

    Assembly only: it applies no validation and mirrors no parser behaviour.
    """

    return ("\n".join((header, *rows)) + "\n").encode("iso-8859-1")


def row(**overrides: str) -> str:
    """One valid row with named field overrides, for boundary fixtures."""

    fields = {
        "RP": "R",
        "Appraisal_Year": "2025",
        "Account_Num": "00123-A",
        "PIDN": "PIDN-0001",
        "GIS_Link": "GIS-0001",
        "Property_Class": "A1",
        "State_Use_Code": "A",
        "Exemption_Code": "EX1",
        "Land_Value": "1000",
        "Improvement_Value": "2500.50",
        "Total_Value": "3500.50",
        "Appraised_Value": "3500.50",
        "Ag_Value": "",
        "Deed_Date": "3/14/2025",
        "Notice_Date": "03/14/2025",
        "Appraisal_Date": "12/1/2025",
    }
    unknown = set(overrides) - set(fields)
    if unknown:
        raise KeyError(f"unknown Tarrant field: {sorted(unknown)}")
    fields.update(overrides)
    return "|".join(fields[name] for name in HEADER.split("|"))


#: Literal expectations authored from the contract, not from the parser.
EXPECTED_VALID_ACCEPTED_ROWS = 1
EXPECTED_REQUIRED_HEADER_COUNT = 16
EXPECTED_DIAGNOSTIC_CODE_COUNT = 21
EXPECTED_DOUBLED_QUOTE_DECODED = 'a"|b'
