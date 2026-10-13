import os
import re
import time
import hashlib
import requests
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime


SOURCE_URL = "https://newsdigest.jp/category/fire/34/34207"
OUTPUT = "newsdigest_fire.xml"

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
}

DATE_RE = re.compile(
    r"(20\d{2})年"
    r"(\d{1,2})月"
    r"(\d{1,2})日"
    r"\s*"
    r"(\d{1,2}):(\d{2})"
)


def normalize_space(text):
    return re.sub(r"\s+", " ", text or "").strip()


def fetch(url):
    last_error = None

    for attempt in range(1, 4):
        try:
            print(f"取得 {attempt}/3: {url}")

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            print("HTTP:", response.status_code)

            response.raise_for_status()
            return response

        except Exception as e:
            last_error = e
            print("取得失敗:", repr(e))

            if attempt < 3:
                time.sleep(10)

    raise last_error


def make_page_url(page):
    if page == 1:
        return SOURCE_URL

    parsed = urlparse(SOURCE_URL)
    query = parse_qs(parsed.query)
    query["page"] = [str(page)]

    new_query = urlencode(query, doseq=True)

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        )
    )


def detect_last_page(soup):
    pages = {1}

    for a in soup.find_all("a", href=True):
        text = normalize_space(
            a.get_text(" ", strip=True)
        )

        if text.isdigit():
            pages.add(int(text))

        href = urljoin(
            SOURCE_URL,
            a["href"]
        )

        parsed = urlparse(href)
        query = parse_qs(parsed.query)

        if "page" in query:
            for value in query["page"]:
                if value.isdigit():
                    pages.add(int(value))

    return max(pages)


def parse_date(text):
    match = DATE_RE.search(text)

    if not match:
        return None

    year, month, day, hour, minute = map(
        int,
        match.groups()
    )

    try:
        return datetime(
            year,
            month,
            day,
            hour,
            minute,
            tzinfo=JST
        )

    except ValueError:
        return None


def parse_page(soup):
    items = []

    blocks = soup.select(
        "div.article-item.pure-u-1.pure-u-lg-1-2"
    )

    for block in blocks:
        h4 = block.select_one(
            "h4.article-item-title"
        )

        if h4 is None:
            continue

        a = h4.find(
            "a",
            href=True
        )

        if a is None:
            continue

        title = normalize_space(
            a.get_text(
                " ",
                strip=True
            )
        )

        link = urljoin(
            SOURCE_URL,
            a["href"]
        )

        if not title:
            continue

        if "/news/" not in link:
            continue

        full_text = normalize_space(
            block.get_text(
                " ",
                strip=True
            )
        )

        pub_date = parse_date(
            full_text
        )

        if pub_date is None:
            print(
                "日時を取得できないため除外:",
                title
            )
            continue

        description = full_text

        guid = hashlib.sha256(
            (
                "newsdigest-fire-fukuyama|"
                + link
            ).encode("utf-8")
        ).hexdigest()

        items.append(
            {
                "title": title,
                "link": link,
                "description": description,
                "pubDate": pub_date,
                "guid": guid,
            }
        )

    return items


def read_old_items():
    if not os.path.exists(OUTPUT):
        return []

    try:
        tree = ET.parse(OUTPUT)
        root = tree.getroot()

    except Exception as e:
        print(
            "既存RSSの読み込みに失敗しました。",
            "安全のため終了します:",
            repr(e)
        )
        raise

    old_items = []

    for item in root.findall(
        "./channel/item"
    ):
        title = item.findtext(
            "title",
            default=""
        )

        link = item.findtext(
            "link",
            default=""
        )

        description = item.findtext(
            "description",
            default=""
        )

        pub_text = item.findtext(
            "pubDate",
            default=""
        )

        guid = item.findtext(
            "guid",
            default=""
        )

        if not guid:
            continue

        try:
            pub_date = parsedate_to_datetime(
                pub_text
            )

        except Exception:
            continue

        old_items.append(
            {
                "title": title,
                "link": link,
                "description": description,
                "pubDate": pub_date,
                "guid": guid,
            }
        )

    return old_items


def deduplicate(items):
    result = []
    seen = set()

    for item in items:
        guid = item["guid"]

        if guid in seen:
            continue

        seen.add(guid)
        result.append(item)

    return result


def write_rss(items):
    rss = ET.Element(
        "rss",
        version="2.0"
    )

    channel = ET.SubElement(
        rss,
        "channel"
    )

    ET.SubElement(
        channel,
        "title"
    ).text = "NewsDigest 広島県福山市の火災"

    ET.SubElement(
        channel,
        "link"
    ).text = SOURCE_URL

    ET.SubElement(
        channel,
        "description"
    ).text = (
        "NewsDigest「広島県福山市の火災」の更新情報"
    )

    ET.SubElement(
        channel,
        "language"
    ).text = "ja"

    for data in items:
        item = ET.SubElement(
            channel,
            "item"
        )

        ET.SubElement(
            item,
            "title"
        ).text = data["title"]

        ET.SubElement(
            item,
            "link"
        ).text = data["link"]

        ET.SubElement(
            item,
            "description"
        ).text = data["description"]

        guid = ET.SubElement(
            item,
            "guid",
            isPermaLink="false"
        )

        guid.text = data["guid"]

        ET.SubElement(
            item,
            "pubDate"
        ).text = format_datetime(
            data["pubDate"]
        )

    tree = ET.ElementTree(rss)

    ET.indent(
        tree,
        space="  "
    )

    tree.write(
        OUTPUT,
        encoding="utf-8",
        xml_declaration=True
    )


def main():
    try:
        old_items = read_old_items()

    except Exception:
        return

    print(
        "既存RSS件数:",
        len(old_items)
    )

    try:
        first_response = fetch(
            SOURCE_URL
        )

        first_soup = BeautifulSoup(
            first_response.content,
            "html.parser"
        )

        last_page = detect_last_page(
            first_soup
        )

        print(
            "検出した最終ページ:",
            last_page
        )

        current_items = []

        page1_items = parse_page(
            first_soup
        )

        print(
            "1ページ目:",
            len(page1_items),
            "件"
        )

        current_items.extend(
            page1_items
        )

        for page in range(
            2,
            last_page + 1
        ):
            url = make_page_url(page)

            response = fetch(url)

            soup = BeautifulSoup(
                response.content,
                "html.parser"
            )

            page_items = parse_page(
                soup
            )

            print(
                f"{page}ページ目:",
                len(page_items),
                "件"
            )

            current_items.extend(
                page_items
            )

    except Exception as e:
        print()
        print(
            "サイト取得に失敗しました。",
            "既存XMLは変更しません。"
        )
        print(
            "エラー:",
            repr(e)
        )
        return

    current_items = deduplicate(
        current_items
    )

    print(
        "全ページ取得:",
        len(current_items),
        "件"
    )

    if len(current_items) == 0:
        print()
        print(
            "記事を1件も取得できませんでした。"
        )
        print(
            "安全のため既存XMLは変更しません。"
        )
        return

    merged = current_items + old_items

    merged = deduplicate(
        merged
    )

    merged.sort(
        key=lambda x: x["pubDate"],
        reverse=True
    )

    write_rss(
        merged
    )

    print()
    print("=" * 70)
    print("RSS作成成功")
    print("=" * 70)

    print(
        "現在サイトから取得:",
        len(current_items),
        "件"
    )

    print(
        "RSS保存件数:",
        len(merged),
        "件"
    )

    print(
        "保存先:",
        os.path.abspath(OUTPUT)
    )

    print()
    print("最新20件:")

    for i, item in enumerate(
        merged[:20],
        start=1
    ):
        print()

        print(
            f"[{i}]",
            format_datetime(
                item["pubDate"]
            ),
            item["title"]
        )

        print(
            "    ",
            item["link"]
        )


if __name__ == "__main__":
    main()