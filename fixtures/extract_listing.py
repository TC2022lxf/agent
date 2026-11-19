"""从保存的亚马逊商品页 HTML 提取一份测试夹具。

用法：python extract_listing.py <html 路径> <输出目录>
输出：<输出目录>/product.json、source.html（复制）、images/main.jpg、pt01.jpg ...

只提取公开页面上可见的字段，不访问需要登录的内容。夹具只做内容样例，不用于核对平台规则。
"""
import html
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def clean(x: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x))).strip()


def first(pattern: str, s: str, flags=re.S):
    m = re.search(pattern, s, flags)
    return m.group(1) if m else None


def main(src: str, out: str) -> None:
    out_dir = Path(out)
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    s = Path(src).read_text(encoding="utf-8", errors="ignore")
    shutil.copyfile(src, out_dir / "source.html")

    title = clean(first(r'id="productTitle"[^>]*>(.*?)</span>', s) or "")
    brand = clean(first(r'id="bylineInfo"[^>]*>(.*?)</a>', s) or "").replace("Visit the ", "").replace(" Store", "").replace("Brand: ", "")

    fb = first(r'id="feature-bullets"(.*?)</ul>', s) or ""
    bullets = [clean(x) for x in re.findall(r'<span class="a-list-item">(.*?)</span>', fb, re.S)]

    attrs = {}
    ov = first(r'id="productOverview_feature_div"(.*?)</table>', s)
    if ov:
        for r in re.findall(r"<tr[^>]*>(.*?)</tr>", ov, re.S):
            tds = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)
            if len(tds) >= 2:
                k, v = clean(tds[0]), clean(tds[1])
                if "function(f)" in v:
                    v = v.split("}));", 1)[-1].replace("See more", "").strip()
                attrs[k] = v

    price = re.findall(r'class="a-offscreen">([^<]+)<', s)[:1]
    rating = re.findall(r"(\d\.\d) out of 5 stars", s)[:1]
    ratings = re.findall(r"([\d,]+) ratings", s)[:1]
    crumbs = [clean(x) for x in re.findall(r'class="a-link-normal a-color-tertiary"[^>]*>(.*?)</a>', s, re.S)[:6]]
    desc_html = first(r'id="productDescription"[^>]*>(.*?)</div>', s)
    desc = clean(desc_html) if desc_html else ""

    hires = list(dict.fromkeys(re.findall(r'"hiRes":"([^"]+)"', s)))
    variants = re.findall(r'"variant":"([^"]+)"', s)[: len(hires)]
    # 页面里还会出现其他颜色变体的图，变体名里 MAIN 第二次出现时，说明本商品的图已经结束
    if "MAIN" in variants[1:]:
        cut = variants.index("MAIN", 1)
        hires, variants = hires[:cut], variants[:cut]
    names = ["main" if v == "MAIN" else v.lower() for v in variants] or [f"img{i}" for i in range(len(hires))]

    images = []
    for i, (url, name) in enumerate(zip(hires, names)):
        small = url.replace("_AC_SL1500_", "_AC_SL800_")
        small = urllib.parse.quote(small, safe=":/._-")
        dest = out_dir / "images" / f"{name}.jpg"
        try:
            urllib.request.urlretrieve(small, dest)
            ok = True
        except Exception as e:  # 网络失败不终止
            print("download failed", name, e)
            ok = False
        images.append({
            "slot": "main_image" if name == "main" else f"secondary_image[{i}]",
            "file": f"images/{name}.jpg" if ok else None,
            "observed": None,
        })

    data = {
        "source": "Amazon product page saved as HTML (source.html)",
        "brand": brand,
        "category_path": crumbs,
        "rating": {"stars": float(rating[0]) if rating else None, "ratings": ratings[0] if ratings else None},
        "price_text": price[0] if price else None,
        "listing": {
            "title": title,
            "title_length": len(title),
            "bullets": [{"index": i + 1, "text": b, "length": len(b)} for i, b in enumerate(bullets)],
            "description": desc or None,
            "search_terms": None,
        },
        "attributes": attrs,
        "images": images,
        "observations": [],
    }
    (out_dir / "product.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("title", len(title), "bullets", [len(b) for b in bullets], "images", len(images), "attrs", list(attrs)[:6])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
