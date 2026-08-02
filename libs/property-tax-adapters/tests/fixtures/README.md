# Dallas Synthetic Fixtures

The byte strings in [`dallas_synthetic.py`](dallas_synthetic.py) were independently authored for
this repository. They are small, identity-free, redistribution-safe examples of the approved
parser contract; they contain no Dallas CAD or production source bytes and do not claim live-release
compatibility.

The fixtures cover the four required normalized headers, a zero-padded synthetic account, a
synthetic parcel reference, a source-native decimal, alternate line endings, reordered columns, an
optional UTF-8 BOM, and standard CSV quoting. Their payload SHA-256 checksums are verified in the
adapter test suite so fixture changes remain explicit.

## Related

- [Dallas parser foundation](../../../../docs/sources/dallas-parser-foundation.md)
- [Normative OpenSpec contract](../../../../openspec/changes/add-dallas-cad-parser-foundation/specs/dallas-cad-source-contract/spec.md)
