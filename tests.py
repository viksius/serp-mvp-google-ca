"""Offline tests (no API keys, no network): python -m unittest tests -v"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import run

PAGE = """<html><head><title>Best Canadian Casinos 2026</title></head><body>
<nav>menu</nav><main><h1>Top casinos</h1>%s
<p>1. SpinPalace - great. 2. Jackpot City - fast payouts. Contact: <a href="mailto:ads@site.ca">mail</a></p>
<a href="/contact-us">Contact</a></main><footer>footer</footer></body></html>""" % ("<p>text text text.</p>" * 120)


class FakeResp:
    def __init__(self, body, code=200, url="https://site.ca/", ctype="text/html; charset=utf-8"):
        self.content, self.status_code, self.url = body.encode(), code, url
        self.headers, self.encoding = {"Content-Type": ctype}, "utf-8"


LABELS = {"category": "review_rating", "brands": ["Jackpot City"], "contact": "ads@a.ca",
          "confidence": "high", "reason": "Ranking page."}


class Hop:
    def __init__(self, status, headers=None, content=b""):
        self.status_code, self.headers, self.content = status, headers or {}, content


def serp_payload(links):
    return {"organic_results": [{"position": i, "link": l, "title": f"T{i}", "snippet": f"S{i}"}
                                for i, l in enumerate(links, 1)]}


class Core(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = run.open_db(os.path.join(self.tmp, "t.db"))
        run.STATS.update({k: 0 for k in run.STATS})
        run.RESOLVED.clear()

    def test_normalize(self):
        n = run.normalize_url
        self.assertEqual(n("HTTPS://WWW.Site.CA:443/a/?utm_source=x&b=1&srsltid=z#frag"), "https://www.site.ca/a?b=1")
        self.assertEqual(n("http://site.ca:80"), "http://site.ca/")
        self.assertEqual(n("http://site.ca:443/x"), "http://site.ca:443/x")   # :443 is not default for http
        self.assertEqual(n("https://www.google.ca/goto?x=1"), "")
        self.assertEqual(n("/goto?x"), "")
        self.assertEqual(n("ftp://a.com"), "")

    # ---- Google redirects ------------------------------------------------------------------
    def _google(self, routes):
        """Fake requests.get for google.ca: routes maps (profile, url) -> Hop; profile is read from the UA."""
        calls = []

        def fake_get(url, headers=None, **kw):
            profile = "mobile" if "Android" in ((headers or {}).get("User-Agent", "")) else "plain"
            calls.append((profile, url, kw.get("allow_redirects")))
            return routes.get((profile, url)) or routes.get(("*", url)) or Hop(404)
        return fake_get, calls

    def test_goto_302_absolute_location(self):
        link = "https://www.google.ca/goto?url=TOKEN123&sa=U"
        get, calls = self._google({("*", link): Hop(302, {"Location": "https://real-site.ca/best/?utm_source=google"})})
        with mock.patch("run.requests.get", side_effect=get), mock.patch("run.time.sleep"):
            self.assertEqual(run.resolve_link(link), "https://real-site.ca/best")
        self.assertEqual(calls[0][2], False)              # redirects are followed by hand, never automatically

    def test_goto_relative_location_and_google_hop(self):
        link = "https://www.google.ca/goto?url=TOKEN"
        get, _ = self._google({("*", link): Hop(302, {"Location": "/goto2?x=1"}),
                               ("*", "https://www.google.ca/goto2?x=1"): Hop(302, {"Location": "https://real.ca/p"})})
        with mock.patch("run.requests.get", side_effect=get), mock.patch("run.time.sleep"):
            self.assertEqual(run.resolve_link(link), "https://real.ca/p")

    def test_goto_second_profile_succeeds_when_plain_gets_a_page(self):
        link = "https://www.google.ca/goto?url=TOKEN"
        get, calls = self._google({("plain", link): Hop(200, {"Content-Type": "text/html"}, b"<html>nothing</html>"),
                                   ("mobile", link): Hop(302, {"Location": "https://real.ca/m"})})
        trace = []
        with mock.patch("run.requests.get", side_effect=get), mock.patch("run.time.sleep"):
            self.assertEqual(run.resolve_link(link, trace), "https://real.ca/m")
        self.assertEqual([c[0] for c in calls], ["plain", "mobile"])
        self.assertEqual([t["status"] for t in trace], [200, 302])      # diagnostics record every hop

    def test_goto_body_with_single_outside_url_and_consent_profile(self):
        page = b"<html><title>Redirect Notice</title><a href='https://target.ca/page?utm_source=g'>go</a>" \
               b"<img src='https://www.gstatic.com/x.png'></html>"
        with mock.patch("run.requests.get", return_value=Hop(200, {}, page)), mock.patch("run.time.sleep"):
            self.assertEqual(run.resolve_link("/goto?x=1"), "https://target.ca/page")
        two = b"<a href='https://a.ca/'>a</a><a href='https://b.ca/'>b</a>"
        trace = []
        with mock.patch("run.requests.get", return_value=Hop(200, {}, two)), mock.patch("run.time.sleep"):
            self.assertEqual(run.resolve_link("/goto?x=1", trace), "")      # ambiguous page: never guess
        self.assertEqual(trace[0]["page"]["outside_urls"], ["https://a.ca/", "https://b.ca/"])
        seen = []
        def fake_get(url, headers=None, **kw):
            seen.append(headers or {})
            return Hop(302, {"Location": "https://ok.ca/x"}) if "Cookie" in (headers or {}) else Hop(200, {}, b"<html>consent</html>")
        with mock.patch("run.requests.get", side_effect=fake_get), mock.patch("run.time.sleep"):
            self.assertEqual(run.resolve_link("/goto?x=1"), "https://ok.ca/x")   # third profile carries the consent cookie
        self.assertEqual(len(seen), 3)

    def test_goto_meta_refresh_body(self):
        link = "https://www.google.ca/goto?url=TOKEN"
        body = b'<html><meta http-equiv="refresh" content="0;url=https://real.ca/x?a=1&amp;b=2"></html>'
        get, _ = self._google({("*", link): Hop(200, {}, body)})
        with mock.patch("run.requests.get", side_effect=get), mock.patch("run.time.sleep"):
            self.assertEqual(run.resolve_link(link), "https://real.ca/x?a=1&b=2")

    def test_consent_page_is_not_returned_as_url_and_is_diagnosed(self):
        link = "https://www.google.ca/goto?url=TOKEN"
        get, _ = self._google({("*", link): Hop(302, {"Location": "https://consent.google.com/m?continue=x"})})
        trace = []
        with mock.patch("run.requests.get", side_effect=get), mock.patch("run.time.sleep"):
            self.assertEqual(run.resolve_link(link, trace), "")         # no invented URL
        line = run.fmt_trace(trace)
        self.assertIn("302", line)
        self.assertIn("consent.google.com", line)

    def test_embedded_url_param_needs_no_network(self):
        with mock.patch("run.requests.get", side_effect=AssertionError("no network expected")):
            self.assertEqual(run.resolve_link("https://www.google.ca/goto?url=https%3A%2F%2Fa.com%2Fp%3Futm_x%3D1"),
                             "https://a.com/p")
            self.assertEqual(run.resolve_link("https://www.google.ca/url?q=https://b.com/&sa=U"), "https://b.com/")

    def test_unresolved_links_are_dropped_not_guessed(self):
        payload = serp_payload(["https://ok.ca/", "https://www.google.ca/goto?url=T", "https://ok2.ca/"])
        get, _ = self._google({})                                        # everything 404
        debug = []
        with mock.patch("run.requests.get", side_effect=get), mock.patch("run.time.sleep"):
            rows, unresolved = run.parse_serp(payload, "kw", debug=debug)
        self.assertEqual((len(rows), unresolved), (2, 1))
        self.assertTrue(all("google" not in r["url"] for r in rows))
        self.assertEqual(debug[0]["resolved"], "")
        self.assertEqual(debug[0]["trace"][0]["status"], 404)

    def test_raw_json_saved_without_key_and_replay_is_free(self):
        run.RAW_DIR = os.path.join(self.tmp, "raw")
        self.addCleanup(setattr, run, "RAW_DIR", None)
        payload = serp_payload(["https://a.com/", "https://b.com/"])
        payload["search_metadata"] = {"json_endpoint": "https://serpapi.com/x.json?api_key=SECRETKEY123"}
        with mock.patch("run.serp_fetch", return_value=payload):
            run.collect_serp(self.db, [("kw one", "")], "2026-10-30", "SECRETKEY123")
        raw = open(os.path.join(run.RAW_DIR, "2026-10-30__kw-one.json"), encoding="utf-8").read()
        self.assertNotIn("SECRETKEY123", raw)
        self.db.execute("DELETE FROM serp_results"); self.db.commit()
        with mock.patch("run.serp_fetch", side_effect=AssertionError("SerpApi must not be called")):
            run.collect_serp(self.db, [("kw one", "")], "2026-10-30", "", replay=True)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM serp_results").fetchone()[0], 2)

    def test_parse_serp_dedupes_and_errors(self):
        rows, unresolved = run.parse_serp(serp_payload(["https://a.com/?utm_x=1", "https://a.com/", "https://b.com/"]), "kw")
        self.assertEqual(unresolved, 0)
        self.assertEqual([(r["position"], r["url"]) for r in rows], [(1, "https://a.com/"), (3, "https://b.com/")])
        with self.assertRaises(RuntimeError):
            run.parse_serp({"error": "boom"}, "kw")
        with self.assertRaises(RuntimeError):
            run.parse_serp({}, "kw")

    def test_save_serp_idempotent_and_history(self):
        rows1 = run.parse_serp(serp_payload(["https://a.com/", "https://b.com/"]), "kw")[0]
        run.save_serp(self.db, "2026-10-30", "kw", rows1)
        run.save_serp(self.db, "2026-10-30", "kw", rows1)                  # same day, same data
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM serp_results").fetchone()[0], 2)
        rows2 = run.parse_serp(serp_payload(["https://c.com/", "https://a.com/"]), "kw")[0]
        run.save_serp(self.db, "2026-10-30", "kw", rows2)                  # rerun, b.com dropped out
        got = {r["url"]: r["position"] for r in self.db.execute("SELECT * FROM serp_results")}
        self.assertEqual(got, {"https://c.com/": 1, "https://a.com/": 2})   # no ghost b.com, no dup positions
        run.save_serp(self.db, "2026-10-31", "kw", rows1)                  # next day -> history grows
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM serp_results").fetchone()[0], 4)

    def test_incomplete_serp_never_replaces_full_one(self):
        full = run.parse_serp(serp_payload([f"https://s{i}.com/" for i in range(1, 11)]), "kw")[0]
        run.save_serp(self.db, "2026-10-30", "kw", full)
        with mock.patch("run.requests.get", side_effect=run.requests.ConnectionError("x")), mock.patch("run.time.sleep"):
            payload = serp_payload(["https://a.com/", "/goto?broken", "https://b.com/"])
            part, unresolved = run.parse_serp(payload, "kw")
        self.assertEqual((len(part), unresolved), (2, 1))
        self.assertFalse(run.save_serp(self.db, "2026-10-30", "kw", part, complete=False))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM serp_results").fetchone()[0], 10)
        # but with nothing saved yet, a partial result is better than nothing, and a full run replaces it
        self.assertTrue(run.save_serp(self.db, "2026-10-30", "other", part, complete=False))
        self.assertTrue(run.save_serp(self.db, "2026-10-30", "other", full))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM serp_results WHERE keyword='other'").fetchone()[0], 10)

    def test_report_not_empty_when_llm_did_not_run(self):
        rows = run.parse_serp(serp_payload(["https://a.com/", "https://b.com/"]), "kw")[0]
        run.save_serp(self.db, "2026-10-30", "kw", rows)
        summary, _, _, _ = run.build_tables(self.db, "2026-10-30")
        self.assertEqual([s["relevant"] for s in summary], ["", ""])      # no analysis yet
        out = os.path.join(self.tmp, "o")
        run.export_all(self.db, "2026-10-30", out)
        html = open(os.path.join(out, "report.html"), encoding="utf-8").read()
        self.assertIn("ИИ-разметка ещё не выполнена", html)               # banner + checkbox disabled in JS

    def test_contacts(self):
        c = run.extract_contacts(PAGE, "https://site.ca/")
        self.assertEqual(c["emails"], ["ads@site.ca"])
        self.assertIn("https://site.ca/contact-us", c["links"])

    def test_classify_and_fetch(self):
        self.assertEqual(run.classify_page(403, "", "<html>"), "blocked")
        self.assertEqual(run.classify_page(200, "x" * 100, "Just a moment..."), "blocked")
        self.assertEqual(run.classify_page(200, "x" * 100, "<html>"), "thin")
        self.assertEqual(run.classify_page(404, "", "<html>"), "error")
        with mock.patch("run.http_get", return_value=FakeResp(PAGE)):
            p = run.fetch_page("https://site.ca/")
        self.assertEqual(p["status"], "ok")
        self.assertIn("SpinPalace", p["text"])
        self.assertNotIn("menu", p["text"])
        with mock.patch("run.http_get", side_effect=OSError("down")):
            self.assertEqual(run.fetch_page("https://x.ca/")["status"], "error")

    def test_validate_drops_hallucinations(self):
        raw = {"category": "review_rating", "brands": ["SpinPalace", "Royal Vegas", "spinpalace"],
               "contact": "evil@x.com", "confidence": "high", "reason": "ok"}
        lab = run.validate_labels(raw, "SpinPalace is great", {"emails": ["ads@site.ca"], "links": []}, "page")
        self.assertEqual(lab["brands"], ["SpinPalace"])          # Royal Vegas not on the page, dup removed
        self.assertIsNone(lab["contact"])                        # invented contact rejected, no silent guess
        raw["contact"] = "ads@site.ca"
        lab = run.validate_labels(raw, "SpinPalace", {"emails": ["ads@site.ca"], "links": []}, "page")
        self.assertEqual(lab["contact"], "ads@site.ca")          # a candidate the model really picked is kept
        raw["contact"] = None
        lab = run.validate_labels(raw, "SpinPalace", {"emails": ["ads@site.ca"], "links": []}, "page")
        self.assertIsNone(lab["contact"])                        # model said "none": we do not override it
        self.assertEqual(lab["relevant"], 1)
        lab = run.validate_labels({"category": "wow"}, "", {"emails": [], "links": []}, "snippet")
        self.assertEqual((lab["category"], lab["confidence"], lab["relevant"]), ("other", "low", 0))

    def test_end_to_end_rerun_is_free(self):
        kws = [("best online casino canada", "Рейтинги"), ("interac casino", "Платёжки")]
        links = ["https://en.wikipedia.org/wiki/X", "https://site.ca/best", "https://blocked.ca/", "https://op.ca/"]

        def fake_http(url, tries=3):
            if "blocked" in url:
                return FakeResp("<html>Just a moment...</html>", 403, url)
            return FakeResp(PAGE, 200, url)

        def fake_llm(msg):
            cat = "review_rating" if "site.ca" in msg else "operator"
            return ({"category": cat, "brands": ["SpinPalace"], "contact": "ads@site.ca",
                     "confidence": "high", "reason": "r"}, 1000, 100)

        os.environ["ANTHROPIC_API_KEY"] = "k"
        with mock.patch("run.serp_fetch", return_value=serp_payload(links)), \
                mock.patch("run.http_get", side_effect=fake_http), \
                mock.patch("run.llm_call", side_effect=fake_llm) as llm:
            run.collect_serp(self.db, kws, "2026-10-30", "key")
            run.process_pages(self.db, "2026-10-30")
            run.analyze_all(self.db, "2026-10-30")
            first_calls = llm.call_count
            run.collect_serp(self.db, kws, "2026-10-30", "key")      # full rerun, same day
            run.process_pages(self.db, "2026-10-30")
            run.analyze_all(self.db, "2026-10-30")
            self.assertEqual(llm.call_count, first_calls)            # cache: zero new LLM spend
        self.assertEqual(first_calls, 3)                             # 3 non-wikipedia URLs, once each
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM serp_results").fetchone()[0], 8)
        basis = {r["url"]: r["basis"] for r in self.db.execute("SELECT url, basis FROM analyses")}
        self.assertEqual(basis["https://blocked.ca/"], "snippet")    # blocked -> explicit fallback
        self.assertEqual(basis["https://en.wikipedia.org/wiki/X"], "rule")
        out = os.path.join(self.tmp, "out")
        self.assertEqual(run.export_all(self.db, "2026-10-30", out), 4)
        self.assertTrue(all(os.path.exists(os.path.join(out, f))
                            for f in ("analysis.csv", "serp_history.csv", "position_matrix.csv", "report.xlsx",
                                      "report.html")))
        html = open(os.path.join(out, "report.html"), encoding="utf-8").read()
        self.assertIn("site.ca", html)
        self.assertNotIn("__DATA__", html)

    # ---- text cleaning ---------------------------------------------------------------------
    def test_clean_text_drops_menu_keeps_rankings(self):
        long1 = "Our experts reviewed every casino on this page and tested withdrawals with real money accounts."
        lines = (["Menu"] + [f"Nav item {i}" for i in range(40)] + ["Best Online Casinos Canada 2026", long1,
                 "1. Jackpot City Casino", "100% up to $1,600 + 420 Free Spins"] + ["Visit casino"] * 5 +
                 ["Share", "Facebook", "Copy current article link", long1, "&dollar;5 deposit casinos"])
        out = run.clean_text_for_llm("\n".join(lines), "Best Online Casinos Canada 2026 | Reviews")
        self.assertNotIn("Nav item", out)                            # navigation block removed
        self.assertNotIn("Facebook", out)
        self.assertIn("Best Online Casinos Canada 2026", out)       # the page heading survives
        self.assertIn("1. Jackpot City Casino", out)                # ranking data survives
        self.assertIn("100% up to $1,600 + 420 Free Spins", out)
        self.assertEqual(out.count("Visit casino"), 2)               # repeats capped, not wiped out
        self.assertEqual(out.count("reviewed every casino"), 1)      # long duplicate paragraph kept once
        self.assertIn("$5 deposit casinos", out)                     # HTML entity decoded

    def test_clean_text_leaves_normal_page_alone(self):
        lines = ["Short heading here today", "A real paragraph that has plenty of words in it to count as text.",
                 "Casino One", "Casino Two", "Casino Three"]
        self.assertEqual(run.clean_text_for_llm("\n".join(lines)), "\n".join(lines))

    def test_html_entities_in_title_and_text(self):
        self.assertEqual(run.extract_title("<title>Top &amp; Trusted &#8211; Casinos</title>"), "Top & Trusted – Casinos")
        self.assertIn("$5 deposit & more", run.extract_text("<html><body><p>&dollar;5 deposit &amp; more</p></body></html>"))

    # ---- contacts --------------------------------------------------------------------------
    def test_filter_contacts(self):
        raw = {"emails": ["example@gmail.com", "support@spincasino.com", "info@site.ca", "ads@site.ca",
                          "pr@thirdparty.com", "john@gmail.com", "bad@@x"],
               "links": ["https://reddit.com/submit?url=x", "https://www.canada.ca/en/revenue-agency/x",
                         "https://site.ca/about/", "https://site.ca/advertise", "https://site.ca/contact/",
                         "https://site.ca/culture/some-article/", "https://site.ca/shop"]}
        text = "Questions?\nFor advertising inquiries write to pr@thirdparty.com today."
        res = run.filter_contacts(raw, ["site.ca"], text)
        self.assertEqual(res["emails"], ["ads@site.ca", "info@site.ca", "pr@thirdparty.com"])   # own domain first
        self.assertEqual(res["links"], ["https://site.ca/advertise", "https://site.ca/contact/", "https://site.ca/about/"])
        why = dict(res["rejected"])
        self.assertIn("placeholder", why["example@gmail.com"])
        self.assertIn("service mailbox", why["support@spincasino.com"])
        self.assertIn("personal/free", why["john@gmail.com"])
        self.assertEqual(why["https://reddit.com/submit?url=x"], "share button")
        self.assertEqual(why["https://www.canada.ca/en/revenue-agency/x"], "another website")
        self.assertEqual(why["https://site.ca/culture/some-article/"], "not a contact page")
        self.assertEqual(why["https://site.ca/shop"], "not a contact page")
        self.assertEqual(run.filter_contacts({"links": ["https://x.ca/advertize"]}, ["x.ca"])["links"], ["https://x.ca/advertize"])
        # a free-mail address is accepted only when the page itself says it is for advertising
        res = run.filter_contacts({"emails": ["john@gmail.com"]}, ["site.ca"], "Advertise with us: john@gmail.com")
        self.assertEqual(res["emails"], ["john@gmail.com"])
        # %20 junk is stripped, subdomains count as the same site
        res = run.filter_contacts({"emails": ["%20editor@durhampost.ca"]}, ["www.durhampost.ca"], "")
        self.assertEqual(res["emails"], ["editor@durhampost.ca"])

    def test_unconfirmed_contact_label_in_report(self):
        rows = run.parse_serp(serp_payload(["https://a.com/", "https://en.wikipedia.org/wiki/X"]), "kw")[0]
        run.save_serp(self.db, "2026-10-30", "kw", rows)
        lab = dict(category="review_rating", relevant=1, brands=[], contact=None, confidence="high", reason="r")
        run.save_analysis(self.db, "https://a.com/", "h", "m", "page", lab)
        run.save_analysis(self.db, "https://en.wikipedia.org/wiki/X", "rule", "rule", "rule", dict(lab, relevant=0))
        summary = {s["url"]: s for s in run.build_tables(self.db, "2026-10-30")[0]}
        self.assertEqual(summary["https://a.com/"]["contact"], "Не подтверждён")
        self.assertEqual(summary["https://en.wikipedia.org/wiki/X"]["contact"], "")    # rule-skipped: not applicable

    # ---- LLM cost guards -------------------------------------------------------------------
    def _seed(self, urls):
        rows = [dict(keyword="kw", cluster="", position=i, url=u, domain=run.domain_of(u), title=f"T{i}", snippet="s")
                for i, u in enumerate(urls, 1)]
        run.save_serp(self.db, "2026-10-30", "kw", rows)
        for u in urls:
            run.save_page(self.db, {"url": u, "final_url": u, "domain": run.domain_of(u), "status": "ok",
                                    "http_code": 200, "title": "Best casinos", "text": ("Casino review text. " * 40),
                                    "text_hash": "x", "contacts": {"emails": [f"ads@{run.domain_of(u)}"], "links": []}})

    def test_llm_limit_only_budget_and_dry_run(self):
        urls = ["https://a.ca/", "https://b.ca/", "https://c.ca/"]
        self._seed(urls)
        ok = ({"category": "review_rating", "brands": [], "contact": None, "confidence": "high", "reason": "r"}, 1000, 50)
        with mock.patch("run.llm_call", return_value=ok) as llm:
            run.analyze_all(self.db, "2026-10-30", dry_run=True)
            self.assertEqual(llm.call_count, 0)                                   # dry run never calls the API
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0], 0)
            run.analyze_all(self.db, "2026-10-30", token_budget=500)             # budget below one call
            self.assertEqual(llm.call_count, 0)
            run.analyze_all(self.db, "2026-10-30", limit=2)                      # hard cap on calls
            self.assertEqual(llm.call_count, 2)
            run.analyze_all(self.db, "2026-10-30", limit=2)                      # cached ones are free: only c.ca is new
            self.assertEqual(llm.call_count, 3)
            run.analyze_all(self.db, "2026-10-30", limit=2)                      # everything cached: zero spend
            self.assertEqual(llm.call_count, 3)
        self.db.execute("DELETE FROM analyses"); self.db.commit()
        with mock.patch("run.llm_call", return_value=ok) as llm:
            run.analyze_all(self.db, "2026-10-30", only=["b.ca"])                # restrict to chosen URLs
            self.assertEqual(llm.call_count, 1)
            self.assertEqual([r[0] for r in self.db.execute("SELECT url FROM analyses")], ["https://b.ca/"])

    def test_cli_llm_only_dry_run_needs_no_keys_and_no_network(self):
        self._seed(["https://a.ca/", "https://b.ca/"])
        out = os.path.join(self.tmp, "o2")
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "SERPAPI_KEY")}
        self.addCleanup(setattr, run, "RAW_DIR", None)
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("run.requests.get", side_effect=AssertionError("no network")), \
                mock.patch("run.requests.post", side_effect=AssertionError("no network")):
            code = run.main(["--db", os.path.join(self.tmp, "t.db"), "--llm-only", "--llm-dry-run",
                             "--llm-limit", "2", "--out", out, "--date", "2099-01-01"])   # date absent -> latest in DB
        self.assertEqual(code, 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0], 0)
        self.assertTrue(os.path.exists(os.path.join(out, "report.html")))

    # ---- LLM (Anthropic) -----------------------------------------------------------------------
    def _env(self, **kw):
        base = {k: v for k, v in os.environ.items() if not k.startswith(("LLM_", "ANTHROPIC_"))}
        base.update(kw)
        return mock.patch.dict(os.environ, base, clear=True)

    @staticmethod
    def _anthropic_ok():
        r = mock.Mock(status_code=200)
        r.json.return_value = {"content": [{"type": "tool_use", "input": LABELS}],
                               "usage": {"input_tokens": 1234, "output_tokens": 75}}
        return r

    def test_anthropic_request_and_response(self):
        with self._env(ANTHROPIC_API_KEY="AKEY123"), \
                mock.patch("run.requests.post", return_value=self._anthropic_ok()) as post:
            raw, t_in, t_out = run.llm_call("USER MESSAGE")
        (url,), kw = post.call_args
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(kw["headers"]["x-api-key"], "AKEY123")
        body = kw["json"]
        self.assertEqual(body["model"], "claude-haiku-5-5")
        self.assertEqual(body["max_tokens"], 700)
        self.assertEqual(body["tool_choice"], {"type": "tool", "name": run.TOOL["name"]})
        self.assertEqual(body["messages"][0]["content"], "USER MESSAGE")
        self.assertEqual((raw, t_in, t_out), (LABELS, 1234, 75))

    def test_anthropic_errors_and_retries(self):
        with self._env(ANTHROPIC_API_KEY="AKEY123"), mock.patch("run.time.sleep"):
            with mock.patch("run.requests.post",
                            side_effect=[mock.Mock(status_code=529, text="overloaded"), self._anthropic_ok()]) as post:
                self.assertEqual(run.llm_call("m")[0], LABELS)          # 5xx is retried
            self.assertEqual(post.call_count, 2)
            bad = mock.Mock(status_code=401, text="invalid x-api-key AKEY123")
            with mock.patch("run.requests.post", return_value=bad) as post:
                with self.assertRaises(RuntimeError) as cm:
                    run.llm_call("m")
            self.assertEqual(post.call_count, 1)                         # 4xx is not retried
            self.assertNotIn("AKEY123", str(cm.exception))               # the key never leaks into messages

    def test_cli_needs_the_key_but_dry_run_does_not(self):
        self._seed(["https://a.ca/"])
        args = ["--db", os.path.join(self.tmp, "t.db"), "--llm-only", "--out", os.path.join(self.tmp, "o3")]
        self.addCleanup(setattr, run, "RAW_DIR", None)
        with self._env():
            with self.assertRaises(SystemExit) as cm:
                run.main(args)
            self.assertIn("ANTHROPIC_API_KEY", str(cm.exception))
            self.assertEqual(run.main(args + ["--llm-dry-run"]), 0)

    def test_cli_end_to_end_cache_and_reanalyze(self):
        self._seed(["https://a.ca/", "https://b.ca/"])
        out = os.path.join(self.tmp, "o4")
        args = ["--db", os.path.join(self.tmp, "t.db"), "--llm-only", "--only", "a.ca", "--llm-limit", "1", "--out", out]
        self.addCleanup(setattr, run, "RAW_DIR", None)
        with self._env(ANTHROPIC_API_KEY="AKEY"), \
                mock.patch("run.requests.post", return_value=self._anthropic_ok()) as post, \
                mock.patch("run.requests.get", side_effect=AssertionError("no downloads / no SerpApi")):
            self.assertEqual(run.main(args), 0)
            self.assertEqual(post.call_count, 1)                           # --only + --llm-limit: exactly one call
            row = self.db.execute("SELECT * FROM analyses").fetchone()
            self.assertEqual((row["url"], row["model"], row["contact"]), ("https://a.ca/", "claude-haiku-5-5", "ads@a.ca"))
            self.assertEqual(json.loads(row["brands"]), [])                # "Jackpot City" is not on the page: dropped
            run.main(args)
            self.assertEqual(post.call_count, 1)                           # cached: no second call
            run.main(args + ["--llm-reanalyze"])
            self.assertEqual(post.call_count, 2)                           # explicit re-run overwrites
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0], 1)

    def test_check_llm(self):
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {"data": [{"id": "claude-haiku-5-5"}, {"id": "claude-opus-5-5"}]}
        with self._env(ANTHROPIC_API_KEY="AKEY"), mock.patch("run.requests.get", return_value=ok):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(run.check_llm(), 0)
            self.assertIn("AVAILABLE", buf.getvalue())
        with self._env(ANTHROPIC_API_KEY="AKEY", LLM_MODEL="claude-9"), mock.patch("run.requests.get", return_value=ok):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(run.check_llm(), 1)
            self.assertIn("NOT FOUND", buf.getvalue())
        denied = mock.Mock(status_code=401, text="denied for key AKEY")
        with self._env(ANTHROPIC_API_KEY="AKEY"), mock.patch("run.requests.get", return_value=denied):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(run.check_llm(), 1)
            self.assertNotIn("AKEY", buf.getvalue())

    def test_push_to_sheets(self):
        rows = [{"url": "=HYPERLINK(1)", "domain": "a.ca"}]
        sent = {}
        def fake_post(url, json=None, timeout=None):
            sent.update(url=url, body=json)
            return mock.Mock(json=lambda: {"ok": True, "rows": 1})
        args = (rows, [{"keyword": "k", "url": "u", "domain": "d"}], [{"date": "2026-10-30"}],
                ["url", "domain"], ["keyword", "url", "domain"], ["date"])
        with self._env():                                              # not configured: silently skipped
            self.assertFalse(run.push_to_sheets(*args))
        with self._env(SHEETS_WEBHOOK_URL="https://script.google.com/x", SHEETS_SECRET="S3CRET"), \
                mock.patch("run.requests.post", side_effect=fake_post):
            self.assertTrue(run.push_to_sheets(*args))
        self.assertEqual([t["name"] for t in sent["body"]["tabs"]], ["Площадки", "Матрица позиций", "История (все строки)"])
        self.assertEqual(sent["body"]["secret"], "S3CRET")
        self.assertEqual(sent["body"]["tabs"][0]["rows"][0][0], "'=HYPERLINK(1)")   # no formula injection
        with self._env(SHEETS_WEBHOOK_URL="https://script.google.com/x", SHEETS_SECRET="S3CRET"), \
                mock.patch("run.requests.post", return_value=mock.Mock(json=lambda: {"ok": False, "error": "wrong secret S3CRET"})):
            with self.assertLogs("serp", level="WARNING") as logs:
                self.assertFalse(run.push_to_sheets(*args))
        self.assertNotIn("S3CRET", "\n".join(logs.output))

    def test_fallback_contact_order(self):
        f = run.fallback_contact
        self.assertEqual(f({"emails": ["news@a.ca"], "links": ["https://a.ca/advertise/", "https://a.ca/about/"]}),
                         "https://a.ca/advertise/")                       # ad page beats a news desk
        self.assertEqual(f({"emails": ["info@a.ca", "ads@a.ca"], "links": []}), "ads@a.ca")
        self.assertEqual(f({"emails": [], "links": ["https://a.ca/about-us/", "https://a.ca/contact-us/"]}),
                         "https://a.ca/contact-us/")
        self.assertEqual(f({"emails": [], "links": ["https://a.ca/about/", "https://a.ca/advertising-page/"]}),
                         "https://a.ca/advertising-page/")
        self.assertIsNone(f({"emails": ["news@a.ca"], "links": ["https://a.ca/about/"]}))   # nothing suitable: no guess
        self.assertIsNone(f({}))

    def test_missing_flag_fetches_only_absent_keywords(self):
        kw = os.path.join(self.tmp, "k.csv")
        open(kw, "w", encoding="utf-8").write("keyword,cluster\na one,X\nb two,Y\n")
        dbp = os.path.join(self.tmp, "m.db")
        db = run.open_db(dbp)
        run.save_serp(db, "2026-10-30", "a one", [dict(date="2026-10-30", keyword="a one", cluster="X", device="mobile", market="ca", position=1, url="https://a.ca/", domain="a.ca", title="t", snippet="s")])
        db.commit(); db.close()
        asked = []
        with mock.patch("run.collect_serp", side_effect=lambda db, kws, d, key, replay=False: asked.extend(k[0] for k in kws)), \
                mock.patch("run.process_pages"), mock.patch("run.export_all", return_value=1), \
                self._env(SERPAPI_KEY="K"):
            run.main(["--db", dbp, "--keywords", kw, "--date", "2026-10-30", "--missing", "--skip-llm",
                      "--out", os.path.join(self.tmp, "o")])
        self.assertEqual(asked, ["b two"])

    def test_verifying_page_is_retried_later(self):
        run.RESOLVED.clear()
        wait_page = b"<html><head><title>Google</title></head><body>Verifying your request. Continue</body></html>"
        calls = []
        def fake_get(url, headers=None, **kw):
            calls.append(url)
            return Hop(200, {}, wait_page) if len(calls) <= 3 else Hop(302, {"Location": "https://real.ca/page"})
        payload = serp_payload(["/goto?url=ABC"])
        with mock.patch("run.requests.get", side_effect=fake_get), mock.patch("run.time.sleep") as slp, \
                self._env(SERPAPI_KEY="K"):
            dbp = os.path.join(self.tmp, "w.db")
            db = run.open_db(dbp)
            with mock.patch("run.get_payload", return_value=payload):
                run.collect_serp(db, [("kw", "c")], "2026-10-30", "K")
        self.assertIn(15.0, [c.args[0] for c in slp.call_args_list])           # it waited, then retried
        self.assertEqual(db.execute("SELECT url FROM serp_results").fetchone()[0], "https://real.ca/page")
        self.assertEqual(run.STATS["serp_failed"], 0)
        run.RESOLVED.clear()

    def test_manager_launcher_choices(self):
        import update
        def feed(*vals):
            it = iter(vals)
            return lambda prompt="": next(it)
        self.assertEqual(update.choose(0, feed("д")), [])                 # no data yet: yes -> full run
        self.assertIsNone(update.choose(0, feed("н")))                    # no -> nothing runs
        self.assertEqual(update.choose(5, feed("x", "1")), ["--export-only"])   # invalid input is asked again
        self.assertEqual(update.choose(5, feed("2")), [])
        self.assertEqual(update.choose(5, feed("3")), ["--missing"])
        self.assertIsNone(update.choose(5, feed("0")))

    def test_formula_injection(self):
        self.assertEqual(run.safe("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(run.safe("normal"), "normal")


if __name__ == "__main__":
    unittest.main()
