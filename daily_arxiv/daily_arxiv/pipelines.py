# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
import arxiv
import os
from scrapy.exceptions import DropItem

from daily_arxiv.filters import matches_title_keywords, parse_csv, parse_positive_int


class DailyArxivPipeline:
    def __init__(self):
        self.page_size = 100
        self.client = arxiv.Client(self.page_size)
        self.keywords = parse_csv(os.environ.get("KEYWORDS", ""))
        self.keyword_mode = os.environ.get("KEYWORD_MODE", "any").strip().lower()
        self.max_papers = parse_positive_int(os.environ.get("MAX_PAPERS"), default=20)
        self.accepted_count = 0

    def process_item(self, item: dict, spider):
        item["pdf"] = f"https://arxiv.org/pdf/{item['id']}"
        item["abs"] = f"https://arxiv.org/abs/{item['id']}"

        if not all(item.get(field) for field in ["authors", "title", "categories", "summary"]):
            search = arxiv.Search(
                id_list=[item["id"]],
            )
            paper = next(self.client.results(search))
            item["authors"] = [a.name for a in paper.authors]
            item["title"] = paper.title
            item["categories"] = paper.categories
            item["comment"] = paper.comment
            item["summary"] = paper.summary
            item["published"] = paper.published.isoformat() if paper.published else ""
            item["updated"] = paper.updated.isoformat() if paper.updated else ""

        if not matches_title_keywords(item.get("title", ""), self.keywords, self.keyword_mode):
            raise DropItem(f"Filtered by title keywords: {item.get('id')}")

        if self.accepted_count >= self.max_papers:
            raise DropItem(f"Reached MAX_PAPERS={self.max_papers}: {item.get('id')}")

        self.accepted_count += 1
        return item