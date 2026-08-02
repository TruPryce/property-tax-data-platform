"""Small, identity-free Dallas contract fixtures authored for this project."""

REQUIRED_HEADER = "ACCOUNT_NUM,APPRAISAL_YR,GIS_PARCEL_ID,TOT_VAL"
VALID_ROW = "00000000000000017,2026,Parcel-0007,-001.20"

VALID_LF = f"{REQUIRED_HEADER}\n{VALID_ROW}\n".encode()
VALID_CRLF = f"{REQUIRED_HEADER}\r\n{VALID_ROW}\r\n".encode()
VALID_BOM = b"\xef\xbb\xbf" + VALID_LF
VALID_REORDERED = (
    b"TOT_VAL,GIS_PARCEL_ID,ACCOUNT_NUM,APPRAISAL_YR\n-001.20,Parcel-0007,00000000000000017,2026\n"
)
VALID_QUOTED_EXTRA = (
    f'{REQUIRED_HEADER},NOTE\n{VALID_ROW},"Synthetic, ""quoted"" note"\n'
).encode()
