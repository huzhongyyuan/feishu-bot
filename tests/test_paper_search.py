import paper_search


class _Response:
    text = """
    <html><head>
      <meta name="citation_title" content="A &amp; B" />
      <meta name="citation_author" content="Zhang, San" />
      <meta name="citation_author" content="Li, Si" />
      <meta name="citation_date" content="2026/08/05" />
      <meta name="citation_pdf_url" content="https://arxiv.org/pdf/2608.05070" />
      <meta name="citation_abstract" content="An official abstract." />
    </head></html>
    """

    def raise_for_status(self):
        return None


def test_arxiv_id_falls_back_to_official_abs_metadata(monkeypatch):
    monkeypatch.setattr(paper_search, "_query_arxiv", lambda params: [])
    monkeypatch.setattr(paper_search.requests, "get", lambda *args, **kwargs: _Response())

    papers = paper_search.search_arxiv("2608.05070", limit=1)

    assert papers[0]["title"] == "A & B"
    assert papers[0]["authors"] == ["San Zhang", "Si Li"]
    assert papers[0]["metadata_source"] == "official_arxiv_abs"
    assert papers[0]["verified_source"] is True
