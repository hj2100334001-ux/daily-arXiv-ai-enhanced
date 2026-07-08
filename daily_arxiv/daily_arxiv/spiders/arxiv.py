import arxiv
import os
import scrapy
from datetime import datetime, timedelta, timezone

from daily_arxiv.filters import (
    build_submitted_date_query,
    matches_title_keywords,
    parse_csv,
    parse_positive_int,
    strip_arxiv_version,
)


class ArxivSpider(scrapy.Spider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categories = parse_csv(os.environ.get("CATEGORIES", "")) or ["cs.CV"]
        # 保存目标分类列表，用于后续验证
        self.target_categories = set(categories)
        today = datetime.now(timezone.utc)
        default_start_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        default_end_date = today.strftime("%Y-%m-%d")
        self.start_date = os.environ.get("START_DATE") or default_start_date
        self.end_date = os.environ.get("END_DATE") or default_end_date
        self.keywords = parse_csv(os.environ.get("KEYWORDS", ""))
        self.keyword_mode = os.environ.get("KEYWORD_MODE", "any").strip().lower()
        self.max_papers = parse_positive_int(os.environ.get("MAX_PAPERS"), default=20)
        self.search_pool_size = parse_positive_int(
            os.environ.get("SEARCH_POOL_SIZE"),
            default=max(self.max_papers * 10, 100),
        )
        self.start_urls = ["https://arxiv.org/"]
        self.client = arxiv.Client(page_size=min(self.search_pool_size, 100), delay_seconds=3)

    name = "arxiv"  # 爬虫名称
    allowed_domains = ["arxiv.org"]  # 允许爬取的域名

    def parse(self, response):
        query = build_submitted_date_query(
            sorted(self.target_categories),
            self.start_date,
            self.end_date,
        )
        self.logger.info(
            "Searching arXiv query=%s max_papers=%s keywords=%s mode=%s",
            query,
            self.max_papers,
            self.keywords,
            self.keyword_mode,
        )

        search = arxiv.Search(
            query=query,
            max_results=self.search_pool_size,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        emitted = 0
        for paper in self.client.results(search):
            paper_categories = set(paper.categories)
            if paper_categories and not paper_categories.intersection(self.target_categories):
                continue
            if not matches_title_keywords(paper.title, self.keywords, self.keyword_mode):
                continue

            yield {
                "id": strip_arxiv_version(paper.entry_id),
                "categories": paper.categories,
                "pdf": paper.pdf_url,
                "abs": paper.entry_id,
                "authors": [author.name for author in paper.authors],
                "title": paper.title,
                "comment": paper.comment,
                "summary": paper.summary,
                "published": paper.published.isoformat() if paper.published else "",
                "updated": paper.updated.isoformat() if paper.updated else "",
            }
            emitted += 1
            if emitted >= self.max_papers:
                break
