"""Smoke check for kishi836.github.io. Run from anywhere:

    python .github/check.py              # assertions
    python .github/check.py --shots DIR  # assertions, then desktop + 375px screenshots of every view

Needs desktop Chrome (override the path with the CHROME env var).
"""
import atexit
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "index.html"
SRC = PAGE.read_text(encoding="utf-8")
URL = PAGE.as_uri()
CHROME = os.environ.get("CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
VIEWS = ["home", "work", "software", "journey", "about", "contact"]
TMP = Path(tempfile.mkdtemp(prefix="site-check-"))
atexit.register(shutil.rmtree, TMP, True)

# [hash to load, iframe width, hash to switch to after load]
CASES = [[f"#/{v}", 375, None] for v in VIEWS] + [
    ["", 375, None], ["#work", 375, None], ["#/nope", 375, None], ["#/work/x", 375, None], ["#/work/passgen", 375, None],
    ["#/home", 1440, None], ["#/home", 1440, "#/about"],
]

# Headless Chrome will not shrink its window below 500px, so phones are tested inside 375px iframes.
PROBE = """<!doctype html><body><script>
const cases = %s, rows = [];
cases.forEach(([frag, w, next], i) => {
  const f = document.createElement("iframe");
  f.width = w; f.height = 800; f.src = %s + frag;
  f.onload = () => setTimeout(() => {
    if (next) f.contentWindow.location.hash = next;
    setTimeout(() => {
      const d = f.contentDocument, txt = id => d.getElementById(id)?.textContent ?? null;
      rows[i] = {
        shown: [...d.querySelectorAll("[data-view]")].filter(s => !s.hidden).map(s => s.dataset.view),
        current: [...d.querySelectorAll("[aria-current=page]")].map(a => a.getAttribute("href")),
        sw: d.documentElement.scrollWidth, sy: f.contentWindow.scrollY, heroPad: parseFloat(f.contentWindow.getComputedStyle(d.querySelector(".hero")).paddingTop), cls: d.documentElement.className, focus: d.activeElement.id,
        route: txt("route"), clock: txt("clock"), nodes: txt("m-nodes"),
        opened: [...d.querySelectorAll("details[open]")].map(e => e.id),
        marquee: f.contentWindow.getComputedStyle(d.querySelector(".marquee-track")).animationName,
      };
      if (rows.filter(Boolean).length === cases.length) document.body.dataset.out = JSON.stringify(rows);
    }, 400);
  }, 1500);
  document.body.append(f);
});
</script></body>"""


def chrome(url, *flags, size="1440,900"):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        return subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
             "--allow-file-access-from-files", f"--window-size={size}", "--virtual-time-budget=6000",
             *flags, url],
            capture_output=True, text=True, encoding="utf-8", timeout=120).stdout


# Loads a variant of the page and reports which views show and how many .reveal blocks in them are still faded.
VARIANT = """<!doctype html><body><iframe id="f" src="%s" width="1440" height="800"></iframe><script>
f.onload = () => {
  setTimeout(() => {
    const d = f.contentDocument, shown = [...d.querySelectorAll("[data-view]")].filter(s => getComputedStyle(s).display !== "none");
    document.body.dataset.out = JSON.stringify({
      shown: shown.map(s => s.dataset.view),
      faded: shown.flatMap(s => [...s.querySelectorAll(".reveal")]).filter(e => getComputedStyle(e).opacity !== "1").length,
    });
  }, 1500);
};
</script></body>"""


def run_probe(markup, *flags):
    page = TMP / "probe.html"
    page.write_text(markup, encoding="utf-8")
    m = re.search(r'data-out="([^"]*)"', chrome(page.as_uri(), "--dump-dom", *flags))
    assert m, "probe produced no results (Chrome missing, or a page script threw)"
    return json.loads(html.unescape(m[1]))


def probe(*flags):
    return run_probe(PROBE % (json.dumps(CASES), json.dumps(URL)), *flags)


def variant(src, frag="", *flags):
    (TMP / "variant.html").write_text(src, encoding="utf-8")
    return run_probe(VARIANT % ("variant.html" + frag), *flags)


def nojs(src):
    """Chrome's JS-off switches either still run scripts or kill --dump-dom, so "no JS" = the page with its scripts cut out."""
    return variant(re.sub(r"<script>.*?</script>", "", src, flags=re.S))


def views_in(markup):
    """{view name: is hidden} for every <section data-view> in markup."""
    return {m[1]: bool(re.search(r"\shidden[\s=>]", m[0]))
            for m in re.finditer(r'<section[^>]*data-view="(\w+)"[^>]*>', markup)}


# ---- static
assert "\u2014" not in SRC and "\u2013" not in SRC, "em/en dash on the page"
assert not re.search(r"<script[^>]*\ssrc=", SRC), "external script"
assert len(SRC.encode()) < 80_000, f"index.html is {len(SRC.encode())} bytes"
found = views_in(SRC)
assert list(found) == VIEWS, f"views in markup: {list(found)}"
assert not any(found.values()), "a view is hidden in the markup, so no-JS visitors lose it"
for name in VIEWS[1:]:
    assert f'href="#/{name}"' in SRC, f"nothing links to #/{name}"
for s in ["600k", "&lt;30s", "FLL Asia Pacific Open", "mailto:gskshitij0638@gmail.com",
          "linkedin.com/in/kshitijgshettigar", "resume.pdf", "github.com/Kishi836/parakaya",
          "github.com/Kishi836/repo6uard", "touch-action: pan-y pinch-zoom", ".js .reveal"]:
    assert s in SRC, f"missing {s!r}"
assert not re.search(r"^\.reveal\s*\{[^}]*opacity:\s*0", SRC, re.M), ".reveal hides content without JS"
print("static ok")

# ---- no JS: every view visible
bare = nojs(SRC)
assert bare["shown"] == VIEWS, f"no-JS visible views: {bare['shown']}"
assert bare["faded"] == 0, f"no-JS: {bare['faded']} .reveal blocks stuck below full opacity"
print("no-js ok")

# ---- the mesh crashing (e.g. no ResizeObserver, iOS < 13.4) must not take routing or content down with it
broken = variant(SRC.replace("<head>", "<head><script>delete window.ResizeObserver</script>", 1), "#/about",
                 "--force-prefers-reduced-motion")
assert broken["shown"] == ["about"], f"mesh crash broke routing: shown {broken['shown']}"
assert broken["faded"] == 0, f"mesh crash left {broken['faded']} .reveal blocks invisible"
print("crash ok")

# ---- routing, aria-current, focus, 375px overflow
rows = probe()
for (frag, w, nxt), r in zip(CASES, rows):
    want = (nxt or frag).lstrip("#/").split("/")[0]
    want = want if want in VIEWS else "home"
    label = f"{frag or '(no hash)'}{' -> ' + nxt if nxt else ''} @{w}px"
    assert r["shown"] == [want], f"{label}: shown {r['shown']}"
    assert r["current"] == ([] if want == "home" else [f"#/{want}"]), f"{label}: aria-current {r['current']}"
    assert r["sw"] <= w, f"{label}: page is {r['sw']}px wide, horizontal scroll"
    if frag == "#/work/passgen":
        assert "case-passgen" in r["opened"] and r["sy"] > 0, f"{label}: PassGen case not opened/scrolled to: {r['opened']}, y={r['sy']}"
    else:
        assert r["sy"] == 0, f"{label}: opened scrolled {r['sy']}px down, header covers the top"
    assert r["heroPad"] >= 40, f"{label}: hero top padding {r['heroPad']}px, name jammed under the header"
    if nxt:
        assert r["focus"] == f"h-{want}", f"{label}: focus on {r['focus']!r}"
print("routing ok")

# ---- HUD chrome (Task 3)
for (frag, w, nxt), r in zip(CASES, rows):
    want = (nxt or frag).lstrip("#/").split("/")[0]
    want = want if want in VIEWS else "home"
    assert r["route"] == want.upper(), f"{frag}: VIEW:// label {r['route']!r}"
    assert re.fullmatch(r"IST \d\d:\d\d:\d\d", r["clock"] or ""), f"clock {r['clock']!r}"
assert any(re.search(r"\bboot\b", r["cls"]) for r in rows), "boot screen never shown on first visit"
calm = probe("--force-prefers-reduced-motion")
assert not any(re.search(r"\bboot\b", r["cls"]) for r in calm), "boot screen shown under reduced motion"
print("hud ok")

# ---- mesh (Task 4)
desk = [r for (frag, w, nxt), r in zip(CASES, rows) if w == 1440 and not nxt][0]
phone = rows[0]
assert desk["nodes"] == "112", f"desktop mesh nodes {desk['nodes']!r}, want 4 x 28"
assert phone["nodes"] == "64", f"375px mesh nodes {phone['nodes']!r}, want 4 x 16"
# Headless Chrome doesn't advance requestAnimationFrame here, so the mesh's own reduced-motion gate is checked by eye;
# the marquee is pure CSS and can be checked.
assert rows[0]["marquee"] == "marquee", f"marquee not animating: {rows[0]['marquee']!r}"
assert all(r["marquee"] == "none" for r in calm), "marquee still moves under reduced motion"
print("mesh ok")

if "--shots" in sys.argv:
    out = Path(sys.argv[sys.argv.index("--shots") + 1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for v in VIEWS:
        chrome(f"{URL}#/{v}", f"--screenshot={out / f'{v}-desktop.png'}", "--force-prefers-reduced-motion",
               size="1440,2000")
        frame = TMP / f"m-{v}.html"
        frame.write_text(f'<!doctype html><body style="margin:0"><iframe src="{URL}#/{v}" width="375" '
                         f'height="2000" style="border:0"></iframe></body>', encoding="utf-8")
        chrome(frame.as_uri(), f"--screenshot={out / f'{v}-mobile.png'}", "--force-prefers-reduced-motion",
               size="500,2000")
    print("screenshots in", out)

print("all checks passed")
