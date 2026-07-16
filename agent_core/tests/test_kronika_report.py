"""Kronika report builder (Tasma-lite) + article_fetcher charset fix.

REAL GoalStore + real files on disk (no mocks that would hide a bad path
join or a silent parse failure). The builder is READ-ONLY: a test asserts
the goals file is byte-identical after a build.
"""

from pathlib import Path

from agent_core.goals.store import GoalStore
from agent_core.goals.goal_model import GoalType, GoalStatus, create_goal
from agent_core.synthesis.kronika_report import (
    build_kronika_report, _fix_mojibake, _parse_article_file,
)

# "przełamał ogłosił" broken the exact way the pre-fix fetcher broke it:
# UTF-8 bytes decoded as latin-1.
_BROKEN = "przełamał ogłosił".encode("utf-8").decode("latin-1")


def _article(path: Path, title: str, url: str, fetched: str, body: str):
    path.write_text(
        f"# Zrodlo: RSS Feed\n# Tytul: {title}\n# URL: {url}\n"
        f"# Pobrano: {fetched}\n# ---\n\n{body}\n",
        encoding="utf-8",
    )


def _project(tmp_path):
    store = GoalStore(tmp_path / "goals.jsonl")
    parent_id = store.create(create_goal(
        GoalType.USER, "Kronika rynku testowa", 0.7,
        status=GoalStatus.ACTIVE))
    # Children carry BOTH linkage fields, exactly like live /project subgoals
    # (parent_goal_id feeds get_children; metadata.project_parent feeds the
    # provenance gate).
    child_id = store.create(create_goal(
        GoalType.USER, "zebrac wydarzenia", 0.6, status=GoalStatus.ACTIVE,
        parent_goal_id=parent_id,
        metadata={
            "project_parent": parent_id,
            "source_kind": "market",
            "provenance_target_n": 3,
            "market_file_ids": ["web_rss_20260710_a.txt",
                                "web_rss_20260711_b.txt"],
        }))
    empty_id = store.create(create_goal(
        GoalType.USER, "podcel z pusta spizarnia", 0.6,
        status=GoalStatus.ACTIVE, parent_goal_id=parent_id,
        metadata={"project_parent": parent_id, "source_kind": "market",
                  "provenance_target_n": 3}))
    return store, parent_id, child_id, empty_id


class TestMojibakeRepair:
    def test_repairs_broken_polish(self):
        assert _fix_mojibake(_BROKEN) == "przełamał ogłosił"

    def test_clean_polish_untouched(self):
        clean = "przełamał ogłosił złoto"
        assert _fix_mojibake(clean) == clean

    def test_ascii_untouched(self):
        assert _fix_mojibake("BTC hits new high") == "BTC hits new high"

    def test_legit_scandinavian_survives(self):
        # "Å" followed by ASCII is not a mojibake byte-shape -- untouched.
        assert _fix_mojibake("Ångström") == "Ångström"

    def test_mixed_mojibake_and_real_curly_quotes(self):
        # The live failure shape: broken Polish NEXT TO genuine curly quotes
        # (U+201C/D). Whole-string repair failed on such text (quotes are not
        # latin-1-encodable); per-sequence repair must fix the Polish runs
        # and keep the quotes byte-identical.
        broken_pl = "zaapelowa\u0142 do spo\u0142eczno\u015bci".encode(
            "utf-8").decode("latin-1")
        mixed = broken_pl.replace("do", "do \u201cVet\u201d")
        out = _fix_mojibake(mixed)
        assert "zaapelowa\u0142" in out
        assert "spo\u0142eczno\u015bci" in out
        assert "\u201cVet\u201d" in out

    def test_broken_curly_apostrophe_repaired(self):
        # English cointelegraph leads: RIGHT SINGLE QUOTE (E2 80 99) read as
        # latin-1 -> "a-circumflex" + two control chars.
        broken = "it\u2019s far too early".encode("utf-8").decode("latin-1")
        assert _fix_mojibake(broken) == "it\u2019s far too early"

class TestParseArticleFile:
    def test_header_and_lead(self, tmp_path):
        p = tmp_path / "web_rss_20260711_x.txt"
        _article(p, "Złoto w górę", "https://www.comparic.pl/art-1",
                 "2026-07-11", "Pierwszy akapit. Drugi akapit.")
        info = _parse_article_file(p)
        assert info["title"] == "Złoto w górę"
        assert info["url"] == "https://www.comparic.pl/art-1"
        assert info["fetched"] == "2026-07-11"
        assert info["lead"].startswith("Pierwszy akapit.")

    def test_mojibake_body_repaired(self, tmp_path):
        p = tmp_path / "web_rss_20260711_y.txt"
        _article(p, "Tytul", "https://bithub.pl/z", "2026-07-11", _BROKEN)
        info = _parse_article_file(p)
        assert "przełamał" in info["lead"]

    def test_missing_file_returns_none(self, tmp_path):
        assert _parse_article_file(tmp_path / "nope.txt") is None


class TestBuildKronikaReport:
    def test_full_report(self, tmp_path):
        store, parent_id, _, _ = _project(tmp_path)
        art_dir = tmp_path / "input"
        art_dir.mkdir()
        _article(art_dir / "web_rss_20260711_b.txt", "Srebro rośnie",
                 "https://bithub.pl/srebro", "2026-07-11", "Tresc B.")
        _article(art_dir / "web_rss_20260710_a.txt", "BTC spada",
                 "https://comparic.pl/btc", "2026-07-10", "Tresc A.")
        report = build_kronika_report(
            store, parent_id, input_dir=art_dir,
            verified_ids={"web_rss_20260710_a.txt"})
        assert report is not None
        assert "Kronika rynku testowa" in report
        # chronological: 07-10 entry before 07-11 entry
        assert report.index("BTC spada") < report.index("Srebro rośnie")
        # verification badges from the injected independent-exam set
        assert "[ZWERYFIKOWANY] BTC spada" in report
        assert "[zebrany] Srebro rośnie" in report
        # pantry math + provenance-honesty footer
        assert "zebrane: 2/3" in report
        assert "Razem: 2 materialow rynkowych, 1 zweryfikowanych" in report
        assert "spizarnia pusta" in report  # empty sibling still listed

    def test_missing_article_file_tolerated(self, tmp_path):
        store, parent_id, _, _ = _project(tmp_path)
        art_dir = tmp_path / "input"
        art_dir.mkdir()  # no files on disk at all
        report = build_kronika_report(store, parent_id, input_dir=art_dir,
                                      verified_ids=set())
        assert report is not None
        # falls back to file-id title + date parsed from the id
        assert "web_rss_20260710_a.txt" in report
        assert "2026-07-10" in report

    def test_unknown_parent_returns_none(self, tmp_path):
        store, _, _, _ = _project(tmp_path)
        assert build_kronika_report(store, "goal-nie-ma", input_dir=tmp_path,
                                    verified_ids=set()) is None

    def test_read_only_no_goal_mutation(self, tmp_path):
        store, parent_id, _, _ = _project(tmp_path)
        store.save()
        goals_path = tmp_path / "goals.jsonl"
        before = goals_path.read_bytes()
        build_kronika_report(store, parent_id, input_dir=tmp_path,
                             verified_ids=set())
        store.save()
        assert goals_path.read_bytes() == before


class TestArticleFetcherCharset:
    def test_missing_charset_header_decodes_utf8(self, monkeypatch):
        # Pre-fix: requests defaulted to latin-1 -> mojibake. The fetcher must
        # now trust the body sniffer when the header omits charset.
        import requests
        from agent_core.web_source.article_fetcher import ArticleFetcher

        html = ("<html><body><article><p>"
                "Złoto przełamało opór i ogłosiło nowe maksima cenowe, "
                "a srebro podążyło tuż za nim w silnym trendzie wzrostowym."
                "</p></article></body></html>")
        resp = requests.models.Response()
        resp.status_code = 200
        resp._content = html.encode("utf-8")
        resp.headers["content-type"] = "text/html"  # NO charset

        fetcher = ArticleFetcher()
        monkeypatch.setattr(fetcher, "_rate_limit", lambda: None)
        monkeypatch.setattr(fetcher._session, "get",
                            lambda url, timeout: resp)
        body = fetcher.fetch_body("https://example.pl/x")
        assert body is not None
        assert "przełamało" in body
        assert "Å" not in body

    def test_declared_charset_still_honored(self, monkeypatch):
        import requests
        from agent_core.web_source.article_fetcher import ArticleFetcher

        html = ("<html><body><article><p>"
                "Treść po polsku zakodowana w iso-8859-2 z ogonkami: "
                "złoto, żółć, gęś - i wystarczająco długa na akapit."
                "</p></article></body></html>")
        resp = requests.models.Response()
        resp.status_code = 200
        resp._content = html.encode("iso-8859-2")
        resp.headers["content-type"] = "text/html; charset=iso-8859-2"
        # The real HTTP adapter parses the header into resp.encoding; a
        # hand-built Response skips the adapter, so mirror it explicitly.
        resp.encoding = "iso-8859-2"

        fetcher = ArticleFetcher()
        monkeypatch.setattr(fetcher, "_rate_limit", lambda: None)
        monkeypatch.setattr(fetcher._session, "get",
                            lambda url, timeout: resp)
        body = fetcher.fetch_body("https://example.pl/y")
        assert body is not None
        assert "żółć" in body
