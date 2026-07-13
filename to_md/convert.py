import argparse
import json
import os
import re
from itertools import count
from pathlib import Path


TAG_SEPARATOR_PATTERN = re.compile(r"[,;，；、。]+")


def parse_keywords(value: str):
    return [keyword.strip().lower() for keyword in value.split(",") if keyword.strip()]


def normalize_tags(value) -> list[str]:
    """Normalize legacy string tags and current list tags to a clean list."""
    if value is None:
        return []
    if isinstance(value, str):
        values = TAG_SEPARATOR_PATTERN.split(value)
    elif isinstance(value, list):
        values = value
    else:
        values = [value]

    tags = []
    seen = set()
    for tag in values:
        cleaned = str(tag).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            tags.append(cleaned)
    return tags


def tags_to_text(value) -> str:
    return ", ".join(normalize_tags(value))


def get_priority_score(item, ai_data, priority_keywords):
    if not priority_keywords:
        return 0

    searchable_parts = [
        item.get("title", ""),
        item.get("summary", ""),
        ai_data.get("tldr", ""),
        ai_data.get("method", ""),
        tags_to_text(ai_data.get("tags")),
    ]
    searchable_text = " ".join(searchable_parts).lower()
    return sum(1 for keyword in priority_keywords if keyword in searchable_text)


def get_output_path(data_path: str) -> Path:
    input_path = Path(data_path)
    if "_AI_enhanced_" in input_path.name:
        output_name = input_path.name.split("_AI_enhanced_", 1)[0] + ".md"
    else:
        output_name = input_path.stem + ".md"
    return input_path.with_name(output_name)


def render_markdown(data, preference, priority_keywords, template) -> str:
    def rank(cate):
        if cate in preference:
            return preference.index(cate)
        return len(preference)

    categories = {item["categories"][0] for item in data}
    categories = sorted(categories, key=rank)
    cnt = {cate: 0 for cate in categories}
    for item in data:
        if item["categories"][0] not in cnt:
            continue
        cnt[item["categories"][0]] += 1

    markdown = "<div id=toc></div>\n\n# Table of Contents\n\n"
    for cate in categories:
        markdown += f"- [{cate}](#{cate}) [Total: {cnt[cate]}]\n"

    idx = count(1)
    for cate in categories:
        markdown += f"\n\n<div id='{cate}'></div>\n\n"
        markdown += f"# {cate} [[Back]](#toc)\n\n"
        papers = []
        for order, item in enumerate(data):
            if item["categories"][0] == cate:
                ai_data = item.get("AI", {})
                if not ai_data or not isinstance(ai_data, dict):
                    print(f"Skipping item '{item.get('title', 'Unknown')}' due to missing or invalid AI data")
                    continue

                required_fields = ["tldr", "method", "tags"]
                if not all(field in ai_data for field in required_fields):
                    print(f"Skipping item '{item.get('title', 'Unknown')}' due to incomplete AI fields")
                    continue

                papers.append(
                    {
                        "priority": get_priority_score(item, ai_data, priority_keywords),
                        "order": order,
                        "item": item,
                        "ai_data": ai_data,
                    }
                )

        papers.sort(key=lambda paper: (-paper["priority"], paper["order"]))
        rendered_papers = []
        for paper in papers:
            item = paper["item"]
            ai_data = paper["ai_data"]
            rendered_papers.append(
                template.format(
                    title=item["title"],
                    authors=", ".join(item["authors"]),
                    summary=item["summary"],
                    url=item["abs"],
                    tldr=ai_data.get("tldr", ""),
                    method=ai_data.get("method", ""),
                    tags=tags_to_text(ai_data.get("tags")),
                    cate=item["categories"][0],
                    idx=next(idx),
                )
            )
        markdown += "\n\n".join(rendered_papers)
    return markdown


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, help="Path to the jsonline file")
    args = parser.parse_args()
    preference = [item.strip() for item in os.environ.get("CATEGORIES", "cs.CV, cs.CL").split(",")]
    priority_keywords = parse_keywords(os.environ.get("PRIORITY_KEYWORDS", ""))

    with open(args.data, "r", encoding="utf-8") as f:
        data = [json.loads(line) for line in f]

    template_path = Path(__file__).with_name("paper_template.md")
    with template_path.open("r", encoding="utf-8") as f:
        template = f.read()

    markdown = render_markdown(data, preference, priority_keywords, template)
    with open(get_output_path(args.data), "w", encoding="utf-8") as f:
        f.write(markdown)


if __name__ == "__main__":
    main()
