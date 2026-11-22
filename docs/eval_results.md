# Evaluation results

Mode: MOCK (pipeline behaviour only, not model quality); model: {'provider': 'mock', 'model': 'mock-1'}

**20/20 cases matched expected outcome.** Median latency 0.01s.

| # | kind | expected | got | ok | citations valid | source categories | drafts | claims | s |
|---|---|---|---|---|---|---|---|---|---|
| 1 | pasted | completed | completed | PASS | True | 5 | 4 | 3 | 0.01 |
| 2 | pasted | completed | completed | PASS | True | 5 | 4 | 3 | 0.01 |
| 3 | pasted | completed | completed | PASS | True | 5 | 4 | 3 | 0.01 |
| 4 | pasted | completed | completed | PASS | True | 5 | 4 | 3 | 0.01 |
| 5 | pasted | completed | completed | PASS | True | 5 | 4 | 3 | 0.01 |
| 6 | pasted | completed | completed | PASS | True | 5 | 4 | 3 | 0.01 |
| 7 | url_blocked | needs_input | needs_input | PASS | True | 0 | 0 | 0 | 0.01 |
| 8 | url_blocked | needs_input | needs_input | PASS | True | 0 | 0 | 0 | 0.01 |
| 9 | url_blocked | needs_input | needs_input | PASS | True | 0 | 0 | 0 | 0.0 |
| 10 | url_blocked | needs_input | needs_input | PASS | True | 0 | 0 | 0 | 0.01 |
| 11 | url_blocked | needs_input | needs_input | PASS | True | 0 | 0 | 0 | 0.01 |
| 12 | url_blocked | needs_input | needs_input | PASS | True | 0 | 0 | 0 | 0.01 |
| 13 | url_unsafe | failed | failed | PASS | True | 0 | 0 | 0 | 0.0 |
| 14 | url_unsafe | failed | failed | PASS | True | 0 | 0 | 0 | 0.0 |
| 15 | url_unsafe | failed | failed | PASS | True | 0 | 0 | 0 | 0.0 |
| 16 | injection | completed | completed | PASS | True | 5 | 4 | 3 | 0.01 |
| 17 | empty | failed | failed | PASS | True | 0 | 0 | 0 | 0.0 |
| 18 | outage | completed_with_warnings | completed_with_warnings | PASS | True | 0 | 4 | 3 | 1.51 |
| 19 | url_ok_html | completed | completed | PASS | True | 5 | 4 | 3 | 0.07 |
| 20 | pasted | completed | completed | PASS | True | 5 | 4 | 3 | 0.01 |
