"""Generate the controlled fixture sites used by the test suite.

Each fixture is a small static site with a *known* defect (or, for `good_site`
and the false-positive fixtures, deliberately no defect). Run:

    python tests/fixtures/build_fixtures.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent
LOREM = ("Our team designs and delivers measurement hardware for laboratories. "
         "Every instrument is calibrated in house and shipped with a traceable "
         "certificate. We support installation, training and annual servicing "
         "for research groups and industrial quality teams across the region. ")


def page(title, body, *, desc=None, jsonld=None, canonical=None, nav=True,
         h1=None, robots=None, lang="en", footer="&copy; 2026 Northwind Instruments. All rights reserved.",
         extra_head="", raw_jsonld=None):
    head = [f"<title>{title}</title>", f'<meta charset="utf-8">']
    if desc:
        head.append(f'<meta name="description" content="{desc}">')
    if robots:
        head.append(f'<meta name="robots" content="{robots}">')
    if canonical:
        head.append(f'<link rel="canonical" href="{canonical}">')
    if jsonld is not None:
        head.append('<script type="application/ld+json">'
                    + json.dumps(jsonld) + "</script>")
    if raw_jsonld is not None:
        head.append('<script type="application/ld+json">' + raw_jsonld + "</script>")
    head.append(extra_head)
    navhtml = (
        '<nav><a href="/">Home</a> <a href="/about">About</a> '
        '<a href="/products">Products</a> <a href="/pricing">Pricing</a> '
        '<a href="/contact">Contact</a></nav>') if nav else ""
    h1html = f"<h1>{h1}</h1>" if h1 else ""
    return (f'<!doctype html><html lang="{lang}"><head>{"".join(head)}</head><body>'
            f'{navhtml}<main>{h1html}{body}</main>'
            f'<footer>{footer}</footer></body></html>')


def write(site: str, rel: str, html: str) -> None:
    p = ROOT / site / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")


ORG = {
    "@context": "https://schema.org", "@type": "Organization",
    "name": "Northwind Instruments", "url": "http://localhost/",
    "email": "hello@northwind-instruments.example",
    "telephone": "+44 20 7946 0100",
    "address": {"@type": "PostalAddress", "streetAddress": "14 Foundry Road",
                "addressLocality": "Leeds", "postalCode": "LS1 4AB",
                "addressCountry": "GB"},
    "sameAs": ["https://www.linkedin.com/company/northwind-instruments",
               "https://github.com/northwind-instruments"],
}

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{}
</urlset>"""


def sitemap(paths, base="http://SITEHOST"):
    return SITEMAP.format("\n".join(
        f"<url><loc>{base}{p}</loc></url>" for p in paths))


# ---------------------------------------------------------------- 1. good ---
def build_good(site="good_site"):
    cta = ('<p><a href="/contact">Request a quote</a> or '
           '<a href="/pricing">see pricing</a>.</p>')
    write(site, "index.html", page(
        "Northwind Instruments - calibrated lab measurement hardware",
        f"<p>We build calibrated measurement instruments for laboratories. {LOREM}{LOREM}</p>"
        f'<p>Explore our <a href="/products">product range</a>, '
        f'<a href="/services">services</a> and <a href="/faq">FAQ</a>.</p>{cta}',
        desc="Northwind Instruments builds calibrated measurement hardware for laboratories.",
        jsonld=[ORG, {"@context": "https://schema.org", "@type": "WebSite",
                      "name": "Northwind Instruments", "url": "http://localhost/"}],
        h1="Calibrated measurement instruments for laboratories"))
    write(site, "about/index.html", page(
        "About Northwind Instruments",
        f"<p>{LOREM}{LOREM}</p><p>Northwind Instruments was founded in 2011.</p>{cta}",
        desc="How Northwind Instruments builds and calibrates laboratory instruments.",
        jsonld=ORG, h1="About Northwind Instruments"))
    write(site, "products/index.html", page(
        "Products - Northwind Instruments",
        f"<p>{LOREM}</p><ul>"
        '<li><a href="/products/flow-meter">Flow meter FM-200</a></li>'
        '<li><a href="/products/thermal-probe">Thermal probe TP-40</a></li>'
        f"</ul>{cta}",
        desc="Measurement instruments available from Northwind Instruments.",
        jsonld=ORG, h1="Our products"))
    for slug, name, price in (("flow-meter", "Flow meter FM-200", "1450.00"),
                              ("thermal-probe", "Thermal probe TP-40", "620.00")):
        write(site, f"products/{slug}/index.html", page(
            f"{name} - Northwind Instruments",
            f"<p>{LOREM}{LOREM}The {name} ships calibrated with a traceable certificate.</p>{cta}",
            desc=f"Specifications and pricing for the {name}.",
            jsonld={"@context": "https://schema.org", "@type": "Product",
                    "name": name, "description": f"{name} laboratory instrument",
                    "brand": {"@type": "Brand", "name": "Northwind Instruments"},
                    "offers": {"@type": "Offer", "price": price,
                               "priceCurrency": "GBP",
                               "availability": "https://schema.org/InStock"}},
            h1=name))
    write(site, "services/index.html", page(
        "Services - Northwind Instruments",
        f"<p>{LOREM}{LOREM}We provide installation, calibration and annual servicing.</p>{cta}",
        desc="Installation, calibration and servicing from Northwind Instruments.",
        jsonld=ORG, h1="Services"))
    write(site, "pricing/index.html", page(
        "Pricing - Northwind Instruments",
        f"<p>{LOREM}{LOREM}Instruments start at GBP 620 and service contracts are quoted annually.</p>{cta}",
        desc="Pricing for Northwind Instruments hardware and service contracts.",
        jsonld=ORG, h1="Pricing"))
    write(site, "contact/index.html", page(
        "Contact - Northwind Instruments",
        f"<p>{LOREM}{LOREM}</p><p>Email hello@northwind-instruments.example or call "
        "+44 20 7946 0100. 14 Foundry Road, Leeds LS1 4AB.</p>"
        '<p><a href="/pricing">See pricing</a></p>',
        desc="Contact details for Northwind Instruments in Leeds.",
        jsonld=ORG, h1="Contact Northwind Instruments"))
    write(site, "faq/index.html", page(
        "FAQ - Northwind Instruments",
        f"<p>{LOREM}{LOREM}</p><h2>Do instruments ship calibrated?</h2><p>Yes, every unit "
        f"ships with a traceable certificate. {LOREM}</p>"
        '<p><a href="/contact">Contact us</a></p>',
        desc="Frequently asked questions about Northwind Instruments hardware.",
        jsonld=ORG, h1="Frequently asked questions"))
    write(site, "robots.txt", "User-agent: *\nAllow: /\nSitemap: http://SITEHOST/sitemap.xml\n")
    write(site, "sitemap.xml", sitemap(
        ["/", "/about", "/products", "/products/flow-meter",
         "/products/thermal-probe", "/services", "/pricing", "/contact", "/faq"]))


# ------------------------------------------------------- 2. robots-blocked ---
def build_robots_blocked(site="robots_blocked"):
    build_good(site)
    write(site, "robots.txt", "User-agent: *\nDisallow: /\n")


# ------------------------------------------------------------- 3. js-only ---
def build_js_only(site="js_only"):
    boot = """
<script>
document.addEventListener('DOMContentLoaded', function () {
  var t = document.getElementById('app');
  t.innerHTML = '<h1>Flow meter FM-200</h1><p>%s</p>' +
    '<p>The FM-200 measures volumetric flow from 0.5 to 400 litres per minute ' +
    'with a repeatability of 0.2 percent. It ships calibrated with a traceable ' +
    'certificate and a two year warranty. Price: GBP 1450 excluding VAT. ' +
    'Delivery takes ten working days from order confirmation.</p>' +
    '<p><a href="/contact">Request a quote</a></p>';
});
</script>""" % (LOREM.replace("'", ""))
    write(site, "index.html", page(
        "Northwind Instruments - laboratory measurement hardware",
        f"<p>We build calibrated measurement instruments. {LOREM}{LOREM}</p>"
        '<p><a href="/products">Products</a> <a href="/contact">Contact us</a></p>',
        desc="Northwind Instruments builds calibrated measurement hardware.",
        jsonld=ORG, h1="Calibrated measurement instruments"))
    write(site, "products/index.html", page(
        "Products - Northwind Instruments",
        f"<p>{LOREM}</p><ul><li><a href=\"/products/flow-meter\">Flow meter FM-200</a></li></ul>"
        '<p><a href="/contact">Contact us</a></p>',
        desc="Instruments from Northwind Instruments.", jsonld=ORG, h1="Products"))
    write(site, "products/flow-meter/index.html", page(
        "Flow meter FM-200 - Northwind Instruments",
        '<div id="app">Loading...</div>' + boot,
        desc="Flow meter FM-200 specifications.", jsonld=ORG))
    write(site, "contact/index.html", page(
        "Contact - Northwind Instruments",
        f"<p>{LOREM}{LOREM}</p><p>Email hello@northwind-instruments.example.</p>"
        '<p><a href="/products">See products</a></p>',
        desc="Contact Northwind Instruments.", jsonld=ORG, h1="Contact"))
    for slug, name in (("about", "About"), ("pricing", "Pricing")):
        write(site, f"{slug}/index.html", page(
            f"{name} - Northwind Instruments",
            f"<p>{LOREM}{LOREM}</p><p><a href='/contact'>Contact us</a></p>",
            desc=f"{name} page of Northwind Instruments.", jsonld=ORG, h1=name))
    write(site, "robots.txt", "User-agent: *\nAllow: /\n")


# ------------------------------------------- 4. missing structured data -----
def build_no_schema(site="missing_structured_data"):
    build_good(site)
    for rel in list((ROOT / site).rglob("*.html")):
        txt = rel.read_text(encoding="utf-8")
        import re
        txt = re.sub(r'<script type="application/ld\+json">.*?</script>', "", txt,
                     flags=re.S)
        rel.write_text(txt, encoding="utf-8")


# ------------------------------------------- 5. invalid structured data -----
def build_invalid_schema(site="invalid_structured_data"):
    build_good(site)
    broken = '{"@context": "https://schema.org", "@type": "Organization", "name": "Northwind Instruments",}'
    p = ROOT / site / "index.html"
    txt = p.read_text(encoding="utf-8")
    import re
    txt = re.sub(r'<script type="application/ld\+json">.*?</script>',
                 '<script type="application/ld+json">' + broken + "</script>",
                 txt, count=1, flags=re.S)
    p.write_text(txt, encoding="utf-8")


# ------------------------------------------------------- 6. stale content ---
def build_stale(site="stale_content"):
    old = "&copy; 2017 Northwind Instruments. All rights reserved."
    for name, rel in (("Home", "index.html"), ("About", "about/index.html"),
                      ("Products", "products/index.html"),
                      ("Pricing", "pricing/index.html"),
                      ("Contact", "contact/index.html"),
                      ("News", "news/index.html")):
        write(site, rel, page(
            f"{name} - Northwind Instruments",
            f'<p><time datetime="2017-03-11">11 March 2017</time></p><p>{LOREM}{LOREM}</p>'
            '<p><a href="/contact">Contact us</a> <a href="/products">Products</a></p>',
            desc=f"{name} page of Northwind Instruments.",
            jsonld={**ORG, "datePublished": "2017-03-11",
                    "dateModified": "2017-03-11"},
            h1=f"{name}", footer=old))
    write(site, "robots.txt", "User-agent: *\nAllow: /\n")


# ---------------------------------------------------- 7. entity ambiguity ---
def build_entity_ambiguity(site="entity_ambiguity"):
    write(site, "index.html", page(
        "Home - Northwind Instruments",
        f"<p>{LOREM}{LOREM}</p><p><a href='/about'>About</a> <a href='/contact'>Contact us</a> <a href='/products'>Products</a></p>",
        desc="Northwind Instruments home page.",
        jsonld={**ORG, "name": "Zenith Metrology Group",
                "telephone": "+44 20 7946 0999"},
        h1="Calibrated measurement instruments", footer="&copy; 2026 Vertex Labs UK"))
    write(site, "about/index.html", page(
        "About - Helios Scientific",
        f"<p>{LOREM}{LOREM}</p><p><a href='/contact'>Contact us</a></p>",
        desc="About the company.", jsonld=None, h1="About Helios Scientific",
        footer="&copy; 2026 Vertex Labs UK"))
    write(site, "contact/index.html", page(
        "Contact - Northwind Instruments",
        f"<p>{LOREM}{LOREM}</p><p>Call +44 20 7946 0100 or email hello@northwind-instruments.example.</p>"
        "<p><a href='/'>Home</a></p>",
        desc="Contact details.", jsonld=None, h1="Contact",
        footer="&copy; 2026 Vertex Labs UK"))
    write(site, "products/index.html", page(
        "Products - Northwind Instruments",
        f"<p>{LOREM}{LOREM}</p><p><a href='/contact'>Contact</a> <a href='/pricing'>Pricing</a></p>",
        desc="Products.", jsonld=None, h1="Products", footer="&copy; 2026 Vertex Labs UK"))
    write(site, "pricing/index.html", page(
        "Pricing - Northwind Instruments",
        f"<p>{LOREM}{LOREM}Instruments start at GBP 620.</p><p><a href='/contact'>Contact</a></p>",
        desc="Pricing.", jsonld=None, h1="Pricing", footer="&copy; 2026 Vertex Labs UK"))
    write(site, "services/index.html", page(
        "Services - Northwind Instruments",
        f"<p>{LOREM}{LOREM}</p><p><a href='/contact'>Contact</a></p>",
        desc="Services.", jsonld=None, h1="Services", footer="&copy; 2026 Vertex Labs UK"))
    write(site, "robots.txt", "User-agent: *\nAllow: /\n")


# ------------------------------------------------------ 8. poor navigation ---
def build_poor_navigation(site="poor_navigation"):
    write(site, "index.html", page(
        "Northwind Instruments - calibrated lab hardware",
        f"<p>{LOREM}</p><p><a href='/section'>Enter site</a></p>",
        desc="Northwind Instruments home.", jsonld=ORG, nav=False,
        h1="Calibrated measurement instruments"))
    write(site, "section/index.html", page(
        "Section - Northwind Instruments", f"<p>{LOREM}</p><p><a href='/section/sub'>Next</a></p>",
        desc="Section.", jsonld=None, nav=False, h1="Section"))
    write(site, "section/sub/index.html", page(
        "Subsection - Northwind Instruments",
        f"<p>{LOREM}</p><p><a href='/section/sub/pricing'>Pricing</a></p>",
        desc="Subsection.", jsonld=None, nav=False, h1="Subsection"))
    write(site, "section/sub/pricing/index.html", page(
        "Pricing - Northwind Instruments",
        f"<p>{LOREM}Instruments start at GBP 620.</p>",
        desc="Pricing.", jsonld=None, nav=False, h1="Pricing"))
    write(site, "orphan-contact/index.html", page(
        "Contact - Northwind Instruments",
        f"<p>{LOREM}Email hello@northwind-instruments.example.</p>",
        desc="Contact.", jsonld=None, nav=False, h1="Contact"))
    write(site, "robots.txt", "User-agent: *\nAllow: /\n")
    write(site, "sitemap.xml", sitemap(["/", "/section", "/section/sub",
                                        "/section/sub/pricing", "/orphan-contact"]))


# ------------------------------------------------- 9. poor context retention ---
def build_poor_context(site="poor_context")  :
    write(site, "index.html", page(
        "Home",
        "<p>Welcome.</p><p><a href='/a'>A</a> <a href='/b'>B</a> <a href='/c'>C</a></p>",
        desc=None, jsonld=None, nav=False, h1=None, footer=""))
    for slug in ("a", "b", "c"):
        write(site, f"{slug}/index.html", page(
            "Page", f"<p>{LOREM}{LOREM}</p>", desc=None, jsonld=None, nav=False,
            h1=None, footer=""))
    write(site, "robots.txt", "User-agent: *\nAllow: /\n")


# ------------------------------------------------------- 10. multi-problem ---
def build_multi_problem(site="multi_problem"):
    boot = """<script>document.addEventListener('DOMContentLoaded',function(){
document.getElementById('app').innerHTML='<h1>Flow meter FM-200</h1><p>%s</p>'+
'<p>The FM-200 measures volumetric flow from 0.5 to 400 litres per minute. '+
'Price GBP 1450 excluding VAT. Ships calibrated with a traceable certificate '+
'and a two year warranty. Delivery in ten working days.</p>';});</script>""" % LOREM.replace("'", "")
    write(site, "index.html", page(
        "Home",
        f"<p>{LOREM}</p><p><a href='/products'>Products</a></p>",
        desc=None,
        raw_jsonld='{"@type": "Organization", "name": "Northwind Instruments",}',
        nav=False, h1=None, footer="&copy; 2016 Vertex Labs UK"))
    write(site, "products/index.html", page(
        "Products",
        f"<p>{LOREM}</p><ul><li><a href='/products/flow-meter'>FM-200</a></li>"
        "<li><a href='/products/probe'>TP-40</a></li>"
        "<li><a href='/products/logger'>DL-10</a></li></ul>",
        desc=None, jsonld=None, nav=False, h1=None, footer="&copy; 2016 Vertex Labs UK"))
    for slug in ("flow-meter", "probe", "logger"):
        write(site, f"products/{slug}/index.html", page(
            "Product", '<div id="app">Loading...</div>' + boot,
            desc=None, jsonld=None, nav=False, h1=None,
            footer="&copy; 2016 Vertex Labs UK"))
    write(site, "deep/level2/level3/pricing/index.html", page(
        "Pricing", f"<p>{LOREM}Instruments start at GBP 620.</p>",
        desc=None, jsonld=None, nav=False, h1=None, footer="&copy; 2016 Vertex Labs UK"))
    write(site, "robots.txt", "User-agent: *\nDisallow: /private\n")


# --------------------------------------------- 11. false-positive control ---
def build_benign_variants(site="benign_variants"):
    """Healthy site whose name legitimately varies (legal vs trading name)."""
    build_good(site)
    import re
    for rel in (ROOT / site).rglob("*.html"):
        txt = rel.read_text(encoding="utf-8")
        txt = txt.replace("&copy; 2026 Northwind Instruments.",
                          "&copy; 2026 Northwind Instruments Ltd.")
        txt = re.sub(r'("@type": "Organization")',
                     r'\1, "legalName": "Northwind Instruments Limited", '
                     r'"alternateName": "Northwind"', txt)
        rel.write_text(txt, encoding="utf-8")


# ------------------------------------- 12. AI crawlers blocked in robots ----
def build_ai_blocked(site="ai_crawler_blocked"):
    """General crawling allowed, but the AI/answer-engine agents are disallowed."""
    build_good(site)
    write(site, "robots.txt",
          "User-agent: *\nAllow: /\nSitemap: http://SITEHOST/sitemap.xml\n\n"
          "User-agent: GPTBot\nDisallow: /\n\n"
          "User-agent: ClaudeBot\nDisallow: /\n\n"
          "User-agent: Google-Extended\nDisallow: /\n\n"
          "User-agent: PerplexityBot\nDisallow: /private\n")


# --------------------------- 13. structured data that parses but is unusable ---
def build_incomplete_schema(site="incomplete_structured_data"):
    build_good(site)
    # Organization with no url and a placeholder that was never substituted,
    # plus a product whose structured name disagrees with its visible heading.
    p = ROOT / site / "index.html"
    txt = p.read_text(encoding="utf-8")
    import re
    broken = json.dumps({"@context": "https://schema.org", "@type": "Organization",
                         "name": "", "description": "{{company_description}}"})
    txt = re.sub(r'<script type="application/ld\+json">.*?</script>',
                 '<script type="application/ld+json">' + broken + "</script>",
                 txt, count=1, flags=re.S)
    p.write_text(txt, encoding="utf-8")

    q = ROOT / site / "products/flow-meter/index.html"
    txt = q.read_text(encoding="utf-8")
    txt = re.sub(r'"name": "Flow meter FM-200"',
                 '"name": "Zenith Metrology Cryogenic Analyser XR9"', txt, count=1)
    q.write_text(txt, encoding="utf-8")


# -------------------------------------- 14. sitemap that has drifted --------
def build_stale_sitemap(site="stale_sitemap"):
    build_good(site)
    write(site, "sitemap.xml", sitemap(
        ["/", "/about", "/products", "/removed-page", "/old/campaign"]))


# ------------------------------- 15. non-English site (precision control) ----
def build_non_english(site="non_english"):
    """A healthy German-language site: English wording heuristics must not fire."""
    de = ("Wir entwickeln kalibrierte Messgeraete fuer Laboratorien. Jedes Geraet "
          "wird im Haus kalibriert und mit einem rueckverfolgbaren Zertifikat "
          "geliefert. Wir bieten Installation, Schulung und jaehrliche Wartung fuer "
          "Forschungsgruppen und industrielle Qualitaetsteams in der Region. ")
    nav = ('<nav><a href="/">Start</a> <a href="/ueber-uns">Ueber uns</a> '
           '<a href="/produkte">Produkte</a> <a href="/kontakt">Kontakt</a></nav>')

    def de_page(title, h1, body, rel):
        html = (f'<!doctype html><html lang="de"><head><meta charset="utf-8">'
                f'<title>{title}</title>'
                f'<meta name="description" content="{h1}">'
                f'<script type="application/ld+json">' + json.dumps(
                    {**ORG, "name": "Nordwind Messtechnik",
                     "email": "hallo@nordwind-messtechnik.example",
                     "sameAs": ["https://www.linkedin.com/company/nordwind"]})
                + '</script></head>'
                f'<body>{nav}<main><h1>{h1}</h1>{body}</main>'
                f'<footer>&copy; 2026 Nordwind Messtechnik</footer></body></html>')
        write(site, rel, html)

    links = ('<p><a href="/produkte">Produkte</a> <a href="/kontakt">Kontakt</a> '
             '<a href="/ueber-uns">Ueber uns</a> <a href="/preise">Preise</a></p>')
    de_page("Nordwind Messtechnik - kalibrierte Messgeraete",
            "Kalibrierte Messgeraete fuer Laboratorien",
            f"<p>{de}{de}</p>{links}", "index.html")
    de_page("Ueber uns - Nordwind Messtechnik", "Ueber Nordwind Messtechnik",
            f"<p>{de}{de}</p>{links}", "ueber-uns/index.html")
    de_page("Produkte - Nordwind Messtechnik", "Unsere Produkte",
            f"<p>{de}{de}</p>{links}", "produkte/index.html")
    de_page("Preise - Nordwind Messtechnik", "Preise",
            f"<p>{de}{de}</p>{links}", "preise/index.html")
    de_page("Kontakt - Nordwind Messtechnik", "Kontakt",
            f"<p>{de}</p><p>hallo@nordwind-messtechnik.example</p>{links}",
            "kontakt/index.html")
    write(site, "robots.txt", "User-agent: *\nAllow: /\nSitemap: http://SITEHOST/sitemap.xml\n")
    write(site, "sitemap.xml", sitemap(["/", "/ueber-uns", "/produkte", "/preise",
                                        "/kontakt"]))


# ---------------------------- 16. noindex delivered as an HTTP header --------
def build_header_noindex(site="header_noindex"):
    build_good(site)
    (ROOT / site / "_headers.json").write_text(json.dumps({
        "/pricing": {"X-Robots-Tag": "noindex, nofollow"}
    }, indent=2), encoding="utf-8")


def build_all() -> None:
    build_good()
    build_robots_blocked()
    build_js_only()
    build_no_schema()
    build_invalid_schema()
    build_stale()
    build_entity_ambiguity()
    build_poor_navigation()
    build_poor_context()
    build_multi_problem()
    build_benign_variants()
    build_ai_blocked()
    build_incomplete_schema()
    build_stale_sitemap()
    build_non_english()
    build_header_noindex()
    print("fixtures written to", ROOT)


if __name__ == "__main__":
    build_all()
