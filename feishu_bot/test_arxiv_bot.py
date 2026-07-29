import feedparser
import re

url="https://arxiv.org/abs/2504.14899"

paper_id=re.findall(r'abs/([\d.]+)',url)[0]

print("paper id:", paper_id)

feed_url=f"https://export.arxiv.org/api/query?id_list={paper_id}"

feed=feedparser.parse(feed_url)

entry=feed.entries[0]

print("\ntitle:")
print(entry.title)

print("\nauthors:")
print([a.name for a in entry.authors])

print("\nabstract:")
print(entry.summary[:500])
