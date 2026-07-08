from datetime import datetime


def parse_csv(value):
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_positive_int(value, default=20):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def matches_title_keywords(title, keywords, mode="any"):
    if not keywords:
        return True

    title_text = (title or "").lower()
    checks = [keyword.lower() in title_text for keyword in keywords]
    return all(checks) if mode == "all" else any(checks)


def normalize_arxiv_date(date_value, end_of_day=False):
    parsed = datetime.strptime(date_value, "%Y-%m-%d")
    suffix = "2359" if end_of_day else "0000"
    return parsed.strftime("%Y%m%d") + suffix


def build_submitted_date_query(categories, start_date, end_date):
    clean_categories = [category.strip() for category in categories if category.strip()]
    category_query = " OR ".join(f"cat:{category}" for category in clean_categories)
    start = normalize_arxiv_date(start_date, end_of_day=False)
    end = normalize_arxiv_date(end_date, end_of_day=True)
    return f"({category_query}) AND submittedDate:[{start} TO {end}]"


def strip_arxiv_version(arxiv_id):
    return arxiv_id.rsplit("/", 1)[-1].split("v")[0]