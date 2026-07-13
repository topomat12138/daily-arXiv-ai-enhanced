# Configuration foundations

These files reserve stable configuration surfaces for later feedback-based keyword learning and ranking work. They are intentionally inactive in this PR: no current crawler, AI enhancement, Markdown conversion, or website code reads them yet.

- `ranking.yml` defines the planned feedback window, feedback values, and automatic-keyword limits.
- `keywords.manual.yml` contains curated weighted keywords, blocked terms, and aliases. Manual configuration will override future automatic keyword results. Effective keyword weights are restricted to the integers `2` and `1`.
- `topic_tags.yml` provides a canonical foundation for stable topic-level tags and simple formatting guidance.
- `profile.yml` records the research context that future ranking and keyword-learning work may use.

Terms under `blocked` are excluded from the effective keyword set. They are not negative feedback and do not reduce a paper's future score.

Feedback capture, automatic keyword generation, and weighted ranking will be introduced separately before these files are connected to runtime behavior.
