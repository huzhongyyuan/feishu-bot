from query_router import route_query
from paper_search import search_arxiv
from paper_agent import analyze_paper


q="介绍Uni3C这篇论文"

print("=== Router ===")
print(
    route_query(q)
)


print("\n=== Search ===")

papers=search_arxiv(
    "Uni3C Unifying Precisely 3D Enhanced Camera Human Motion"
)

print(
    papers[0]
)


print("\n=== Analysis ===")

result=analyze_paper(
    papers[0]
)

print(result)
