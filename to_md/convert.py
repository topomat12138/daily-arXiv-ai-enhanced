import json
import argparse
import os
from itertools import count
from pathlib import Path


def parse_keywords(value: str):
    return [keyword.strip().lower() for keyword in value.split(",") if keyword.strip()]


def get_priority_score(item, ai_data, priority_keywords):
    if not priority_keywords:
        return 0

    searchable_parts = [
        item.get("title", ""),
        item.get("summary", ""),
        ai_data.get("tldr", ""),
        ai_data.get("method", ""),
        ai_data.get("tags", ""),
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, help="Path to the jsonline file")
    args = parser.parse_args()
    data = []
    preference = os.environ.get("CATEGORIES", "cs.CV, cs.CL").split(",")
    preference = [item.strip() for item in preference]
    priority_keywords = parse_keywords(os.environ.get("PRIORITY_KEYWORDS", ""))

    def rank(cate):
        if cate in preference:
            return preference.index(cate)
        return len(preference)

    with open(args.data, "r", encoding="utf-8") as f:
        for line in f:
            data.append(json.loads(line))

    categories = {item["categories"][0] for item in data}
    with open("paper_template.md", "r", encoding="utf-8") as f:
        template = f.read()
    categories = sorted(categories, key=rank)
    cnt = {cate: 0 for cate in categories}
    for item in data:
        if item["categories"][0] not in cnt:
            continue
        cnt[item["categories"][0]] += 1

    markdown = f"<div id=toc></div>\n\n# Table of Contents\n\n"
    for cate in categories:
        markdown += f"- [{cate}](#{cate}) [Total: {cnt[cate]}]\n"

    idx = count(1)
    for cate in categories:
        markdown += f"\n\n<div id='{cate}'></div>\n\n"
        markdown += f"# {cate} [[Back]](#toc)\n\n"
        papers = []
        for order, item in enumerate(data):
            if item["categories"][0] == cate:
                # Safely access AI fields with default values
                ai_data = item.get("AI", {})
                if not ai_data or not isinstance(ai_data, dict):
                    print(f"Skipping item '{item.get('title', 'Unknown')}' due to missing or invalid AI data")
                    continue

                # Check if all required AI fields are present
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
                    tags=ai_data.get("tags", ""),
                    cate=item["categories"][0],
                    idx=next(idx),
                )
            )
        markdown += "\n\n".join(rendered_papers)
    with open(get_output_path(args.data), "w", encoding="utf-8") as f:
        f.write(markdown)
