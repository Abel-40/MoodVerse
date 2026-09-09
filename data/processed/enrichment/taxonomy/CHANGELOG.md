# Taxonomy changelog

## 1.0.0

First version. Created in Phase 1B from the design in `PHASE1A_DESIGN.md`.

| Axis | Values |
| --- | ---: |
| Emotions | 17 |
| Intensity levels | 4 |
| Themes | 47 |
| Reflection intents | 17 |
| Situations | 30 |
| Scripture purposes | 18 |
| Context dependency levels | 5 |
| Dependency reasons | 14 |
| Blockers | 11 |
| Content advisories | 10 |

### Versioning policy

- **minor_bump** - Adding a value to any axis. Existing annotations remain valid.
- **major_bump** - Removing a value, or changing what an existing value means. Requires re-annotation of every affected record.
- **identifier_stability** - An id is never reused for a different concept. A retired id is tombstoned, never recycled.
