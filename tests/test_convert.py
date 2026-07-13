import unittest

from to_md.convert import get_priority_score, render_markdown, tags_to_text


TEST_TEMPLATE = (
    "{title}|{authors}|{summary}|{url}|{tldr}|{method}|{tags}|{cate}|{idx}"
)


def paper_with_tags(tags):
    return {
        "title": "Example paper",
        "authors": ["Ada Author"],
        "summary": "Original abstract",
        "abs": "https://arxiv.org/abs/1234.5678",
        "categories": ["cond-mat.supr-con"],
        "AI": {
            "tldr": "Concise result",
            "method": "Main method",
            "tags": tags,
        },
    }


class MarkdownConversionTests(unittest.TestCase):
    def test_renders_legacy_string_tags(self):
        markdown = render_markdown(
            [paper_with_tags("vortex physics, quantum geometry")],
            ["cond-mat.supr-con"],
            [],
            TEST_TEMPLATE,
        )

        self.assertIn("vortex physics, quantum geometry", markdown)

    def test_renders_list_tags_as_readable_text(self):
        markdown = render_markdown(
            [paper_with_tags(["vortex physics", "quantum geometry"])],
            ["cond-mat.supr-con"],
            [],
            TEST_TEMPLATE,
        )

        self.assertIn("vortex physics, quantum geometry", markdown)
        self.assertNotIn("['vortex physics'", markdown)

    def test_equivalent_tag_representations_have_same_priority_score(self):
        item = {"title": "", "summary": ""}
        legacy = {"tldr": "", "method": "", "tags": "vortex physics, quantum geometry"}
        current = {"tldr": "", "method": "", "tags": ["vortex physics", "quantum geometry"]}
        keywords = ["vortex physics", "quantum geometry"]

        self.assertEqual(
            get_priority_score(item, legacy, keywords),
            get_priority_score(item, current, keywords),
        )

    def test_historical_record_without_specific_terms_is_rendered(self):
        historical_paper = paper_with_tags("vortex physics")

        markdown = render_markdown(
            [historical_paper],
            ["cond-mat.supr-con"],
            [],
            TEST_TEMPLATE,
        )

        self.assertIn("Example paper", markdown)
        self.assertEqual(tags_to_text(historical_paper["AI"]["tags"]), "vortex physics")


if __name__ == "__main__":
    unittest.main()
