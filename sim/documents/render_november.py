#!/usr/bin/env python3
"""Render the scenario's November documents as the PDFs and phone photos the releaser sends (needs Pillow and Chrome)."""
import html
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import zlib
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "sim" / "scenario" / "out" / "november_documents.json"
OUT = Path(__file__).resolve().parent / "november"
BROWSERS = [os.environ.get("CHROME"), r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe", "chromium", "chromium-browser", "google-chrome",
            "microsoft-edge"]
VAT_LETTER = {"23": "A", "8": "B", "5": "C", "0": "D", "zw": "E"}
LABELS = {
    "pl": {"invoice": "FAKTURA VAT", "no": "Nr", "issued": "Data wystawienia", "sold": "Data sprzedaży",
           "due": "Termin płatności", "seller": "Sprzedawca", "buyer": "Nabywca", "tax": "NIP", "lp": "Lp.",
           "item": "Nazwa towaru lub usługi", "qty": "Ilość", "unit": "Cena netto", "net": "Wartość netto",
           "rate": "VAT %", "vat": "Kwota VAT", "gross": "Wartość brutto", "total": "Razem do zapłaty",
           "method": "Forma płatności", "account": "Numer rachunku", "paid": "Zapłacono",
           "card": "karta", "transfer": "przelew", "cash": "gotówka", "summary": "Podsumowanie"},
    "en": {"invoice": "INVOICE", "no": "No.", "issued": "Issue date", "sold": "Date of supply", "due": "Due date",
           "seller": "Seller", "buyer": "Bill to", "tax": "Tax ID", "lp": "#", "item": "Description", "qty": "Qty",
           "unit": "Unit price", "net": "Net", "rate": "VAT", "vat": "VAT amount", "gross": "Gross",
           "total": "Total due", "method": "Payment", "account": "Bank account", "paid": "Paid",
           "card": "card", "transfer": "bank transfer", "cash": "cash", "summary": "Summary"},
}


def fmt(amount, lang: str) -> str:
    """'1299.00' -> '1 299,00' (pl) / '1,299.00' (en)."""
    s = f"{Decimal(amount):,.2f}"
    return s.replace(",", " ").replace(".", ",") if lang == "pl" else s


def nip(tax_id: str | None) -> str:
    if tax_id and tax_id.isdigit() and len(tax_id) == 10:
        return f"{tax_id[:3]}-{tax_id[3:6]}-{tax_id[6:8]}-{tax_id[8:]}"
    return tax_id or ""


def date_pl(iso: str | None) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if iso else ""


e = html.escape


CSS_COMMON = """
* { box-sizing: border-box; }
body { margin: 0; background: #fff; color: #111; }
.watermark { position: absolute; left: 0; right: 0; top: 38%; text-align: center; transform: rotate(-30deg);
  font: bold 96px Arial, sans-serif; color: rgba(0,0,0,0.07); letter-spacing: 14px; pointer-events: none; }
.sample-footer { font: 9px Arial, sans-serif; color: #666; text-align: center; margin-top: 18px; }
"""

CSS_INVOICE = CSS_COMMON + """
@page { size: A4; margin: 14mm; }
.page { position: relative; width: 182mm; font: 11px Arial, sans-serif; }
h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: 1px; }
.meta { text-align: right; line-height: 1.6; }
.top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.parties { display: flex; gap: 24px; margin-bottom: 16px; }
.party { flex: 1; border: 1px solid #bbb; padding: 8px 10px; line-height: 1.5; }
.party b.h { display: block; font-size: 10px; color: #555; text-transform: uppercase; margin-bottom: 4px; }
table { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
th, td { border: 1px solid #bbb; padding: 5px 6px; }
th { background: #f0f0f0; font-size: 10px; text-align: left; }
td.n { text-align: right; white-space: nowrap; }
.totals { width: 55%; margin-left: auto; }
.due { font-size: 15px; font-weight: bold; text-align: right; margin: 10px 0 16px; }
.pay { line-height: 1.7; border-top: 1px solid #bbb; padding-top: 8px; }
.note { margin-top: 10px; font-style: italic; color: #333; }
"""

CSS_RECEIPT = CSS_COMMON + """
@page { size: A4; margin: 20mm; }
.receipt { position: relative; width: 340px; margin: 10px auto; padding: 14px 16px; background: #fff;
  font: 13px "Courier New", Courier, monospace; line-height: 1.35; overflow: hidden; }
.c { text-align: center; } .b { font-weight: bold; } .s { font-size: 11px; }
.row { display: flex; justify-content: space-between; gap: 8px; }
.rule { border-top: 1px dashed #000; margin: 6px 0; }
.title { font-size: 15px; letter-spacing: 1px; margin-top: 6px; }
.total { font-size: 17px; font-weight: bold; }
.receipt .watermark { font-size: 54px; top: 42%; letter-spacing: 6px; }
"""


def invoice_html(d: dict) -> str:
    lang = d.get("language") or "pl"
    L = LABELS[lang]
    seller, buyer = d["seller"], d.get("buyer") or {}
    ccy = d["currency"]
    rows = "".join(
        f"<tr><td>{i}</td><td>{e(line['description'])}</td><td class=n>{e(str(line['quantity']))}</td>"
        f"<td class=n>{fmt(line['unit_price_net'], lang)}</td><td class=n>{fmt(line['net'], lang)}</td>"
        f"<td class=n>{e(line['vat_rate'])}{'%' if line['vat_rate'].replace('.', '').isdigit() else ''}</td>"
        f"<td class=n>{fmt(line['vat'], lang)}</td><td class=n>{fmt(line['gross'], lang)}</td></tr>"
        for i, line in enumerate(d["lines"], start=1))
    pay = d["payment"]
    pay_lines = [f"{L['method']}: <b>{L.get(pay['method'], pay['method'])}</b>"]
    if d.get("due_date"):
        pay_lines.append(f"{L['due']}: <b>{date_pl(d['due_date']) if lang == 'pl' else d['due_date']}</b>")
    if pay.get("bank_account"):
        pay_lines.append(f"{L['account']}: {e(pay['bank_account'])}")
    if pay.get("paid_date"):
        card = f" (**** {e(pay['card_last4'])})" if pay.get("card_last4") else ""
        pay_lines.append(f"{L['paid']}: {date_pl(pay['paid_date']) if lang == 'pl' else pay['paid_date']}{card}")
    dt = date_pl if lang == "pl" else (lambda x: x or "")

    def party(p, head):
        if not p:
            return f"<div class=party><b class=h>{head}</b>—</div>"
        address = "<br>".join(e(a) for a in (p.get("address") or []))
        tax = f"<br>{L['tax']}: {e(nip(p.get('tax_id')))}" if p.get("tax_id") else ""
        return f"<div class=party><b class=h>{head}</b><b>{e(p['name'])}</b><br>{address}{tax}</div>"

    note = f"<div class=note>{e(d['note'])}</div>" if d.get("note") and d["direction"] == "purchase" else ""
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{e(d['number'])}</title>
<style>{CSS_INVOICE}</style></head><body><div class="page"><div class="watermark">SAMPLE</div>
<div class="top"><div><h1>{L['invoice']}</h1><div>{L['no']} <b>{e(d['number'])}</b></div></div>
<div class="meta">{L['issued']}: {dt(d['issue_date'])}<br>{L['sold']}: {dt(d['issue_date'])}</div></div>
<div class="parties">{party(seller, L['seller'])}{party(buyer, L['buyer'])}</div>
<table><tr><th>{L['lp']}</th><th>{L['item']}</th><th>{L['qty']}</th><th>{L['unit']}</th><th>{L['net']}</th>
<th>{L['rate']}</th><th>{L['vat']}</th><th>{L['gross']}</th></tr>{rows}</table>
<table class="totals"><tr><th>{L['net']}</th><th>{L['vat']}</th><th>{L['gross']}</th></tr>
<tr><td class=n>{fmt(d['totals']['net'], lang)} {ccy}</td><td class=n>{fmt(d['totals']['vat'], lang)} {ccy}</td>
<td class=n>{fmt(d['totals']['gross'], lang)} {ccy}</td></tr></table>
<div class="due">{L['total']}: {fmt(d['totals']['gross'], lang)} {ccy}</div>
<div class="pay">{'<br>'.join(pay_lines)}</div>{note}
<div class="sample-footer">SAMPLE · NOT A REAL INVOICE · Collabothon 2026 test document · invented company and tax ids</div>
</div></body></html>"""


def receipt_html(d: dict) -> str:
    seller, pay = d["seller"], d["payment"]
    rows, by_letter = [], {}
    for line in d["lines"]:
        letter = VAT_LETTER.get(line["vat_rate"], "A")
        qty = Decimal(line["quantity"])
        unit = Decimal(line["gross"]) / qty if qty else Decimal(line["gross"])
        rows.append(f'<div>{e(line["description"])}</div><div class="row"><span>{e(line["quantity"])} x{fmt(unit, "pl")}'
                    f'</span><span>{fmt(line["gross"], "pl")} {letter}</span></div>')
        acc = by_letter.setdefault(letter, [Decimal(0), Decimal(0), line["vat_rate"]])
        acc[0] += Decimal(line["gross"])
        acc[1] += Decimal(line["vat"])
    vat_rows = "".join(
        f'<div class="row"><span>Sprzed. opod. PTU {k}</span><span>{fmt(v[0], "pl")}</span></div>'
        f'<div class="row"><span>Kwota PTU {k} {v[2]},00%</span><span>{fmt(v[1], "pl")}</span></div>'
        for k, v in sorted(by_letter.items()))
    buyer = d.get("buyer") or {}
    buyer_row = f'<div class="c b">NIP nabywcy: {e(nip(buyer["tax_id"]))}</div>' if buyer.get("tax_id") else ""
    method = {"card": "Karta płatnicza", "cash": "Gotówka", "transfer": "Przelew"}.get(pay["method"], pay["method"])
    card = (f'<div class="row s"><span>Karta</span><span>**** **** **** {e(pay["card_last4"])}</span></div>'
            if pay.get("card_last4") else "")
    address = "".join(f'<div class="c">{e(a)}</div>' for a in seller.get("address") or [])
    number = d["number"].split()[-1] if d["number"] else ""
    return f"""<!doctype html><html lang="pl"><head><meta charset="utf-8"><title>{e(d['number'] or d['id'])}</title>
<style>{CSS_RECEIPT}</style></head><body><div class="receipt"><div class="watermark">SAMPLE</div>
<div class="c b">{e(seller['name'])}</div>{address}<div class="c">NIP {e(nip(seller.get('tax_id')))}</div>
<div class="row s"><span>{date_pl(d['issue_date'])} {12 + zlib.crc32(d['id'].encode()) % 8:02d}:{zlib.crc32(d['id'].encode()) % 60:02d}</span>
<span>{e(number)}</span></div>{buyer_row}
<div class="c b title">PARAGON FISKALNY</div><div class="rule"></div>{''.join(rows)}<div class="rule"></div>{vat_rows}
<div class="row"><span>Suma PTU</span><span>{fmt(d['totals']['vat'], 'pl')}</span></div>
<div class="row total"><span>SUMA PLN</span><span>{fmt(d['totals']['gross'], 'pl')}</span></div>
<div class="rule"></div><div class="row"><span>{method}</span><span>{fmt(d['totals']['gross'], 'pl')} PLN</span></div>{card}
<div class="rule"></div><div class="c s">SAMPLE · NOT A REAL RECEIPT<br>Collabothon 2026 test document · no fiscal value</div>
</div></body></html>"""


def browser() -> str:
    for candidate in BROWSERS:
        if candidate and (Path(candidate).is_file() or shutil.which(candidate)):
            return shutil.which(candidate) or candidate
    sys.exit("No Chrome/Chromium/Edge found: set CHROME to the browser executable.")


def run_browser(exe: str, profile: Path, html_file: Path, *args: str) -> None:
    """Headless Chrome/Edge sometimes hangs on a run: retry with a fresh profile."""
    for attempt in range(1, 4):
        try:
            subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-pdf-header-footer",
                            f"--user-data-dir={profile}-{attempt}", *args, html_file.resolve().as_uri()],
                           check=True, capture_output=True, timeout=45)
            return
        except subprocess.TimeoutExpired:
            print(f"  browser timed out on {html_file.name}, attempt {attempt}", file=sys.stderr)
    raise RuntimeError(f"browser failed 3 times on {html_file.name}")


def screenshot(exe: str, profile: Path, html_file: Path, width: int, height: int) -> Image.Image:
    png = html_file.with_suffix(".png")
    run_browser(exe, profile, html_file, f"--window-size={width},{height}", f"--screenshot={png}")
    img = Image.open(png).convert("RGB")
    box = ImageChops.difference(img, Image.new("RGB", img.size, "white")).getbbox()  # crop to the paper
    if box:
        pad = 18
        img = img.crop((max(box[0] - pad, 0), max(box[1] - pad, 0), min(box[2] + pad, img.width),
                        min(box[3] + pad, img.height)))
    return img


def desk(size: tuple[int, int], rnd: random.Random) -> Image.Image:
    base = (rnd.randint(120, 160), rnd.randint(95, 120), rnd.randint(70, 90))  # wooden desk
    img = Image.new("RGB", size, base)
    draw = ImageDraw.Draw(img)
    for y in range(0, size[1], 3):  # wood grain
        shade = rnd.randint(-14, 14)
        draw.line([(0, y), (size[0], y + rnd.randint(-6, 6))], fill=tuple(max(0, c + shade) for c in base), width=2)
    return img.filter(ImageFilter.GaussianBlur(1.2))


def noise(img: Image.Image, rnd: random.Random, amount: int) -> Image.Image:
    grain = Image.effect_noise(img.size, amount).convert("RGB")
    return ImageChops.add(ImageChops.subtract(img, grain.point(lambda p: p // 6)), grain.point(lambda p: p // 8))


def crumple(paper: Image.Image, rnd: random.Random) -> Image.Image:
    """Smooth wrinkles: one displacement per grid vertex, shared by the neighbouring tiles (no tearing)."""
    w, h = paper.size
    step = 60
    xs, ys = list(range(0, w, step)) + [w], list(range(0, h, step)) + [h]
    waves = [(rnd.uniform(0.004, 0.012), rnd.uniform(0, 6.3), rnd.uniform(1.5, 3.0)) for _ in range(3)]

    def moved(x, y):
        dx = sum(a * math.sin(f * y + p) for f, p, a in waves)
        dy = sum(a * math.cos(f * x + p) for f, p, a in waves)
        return x + dx, y + dy

    mesh = []
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            x0, x1, y0, y1 = xs[i], xs[i + 1], ys[j], ys[j + 1]
            quad = (*moved(x0, y0), *moved(x0, y1), *moved(x1, y1), *moved(x1, y0))
            mesh.append(((x0, y0, x1, y1), quad))
    out = paper.transform(paper.size, Image.MESH, mesh, Image.BICUBIC, fillcolor="white")
    draw = ImageDraw.Draw(out, "RGBA")
    for _ in range(6):  # creases
        x0, y0 = rnd.randint(0, w), rnd.randint(0, h)
        draw.line([(x0, y0), (x0 + rnd.randint(-w // 2, w // 2), y0 + rnd.randint(-h // 3, h // 3))],
                  fill=(0, 0, 0, 28), width=2)
    return out


def perspective_coeffs(src, dst):
    """Coefficients for Image.PERSPECTIVE mapping dst quad -> src quad."""
    matrix = []
    for (x, y), (u, v) in zip(dst, src):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    rhs = [c for point in src for c in point]
    n = 8  # solve the 8x8 system (Gauss-Jordan)
    a = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(n):
            if r != col:
                f = a[r][col] / a[col][col]
                a[r] = [x - f * y for x, y in zip(a[r], a[col])]
    return [a[i][n] / a[i][i] for i in range(n)]


def photo(paper: Image.Image, defects: list[str], rnd: random.Random) -> Image.Image:
    if "crumpled" in defects:
        paper = crumple(paper, rnd)
    if "cropped_edge" in defects:  # the photo cut off the left edge of the paper (amounts stay readable)
        paper = paper.crop((int(paper.width * 0.07), 0, paper.width, paper.height))
    w, h = paper.size
    margin = (1.45, 1.25) if w < 600 else (1.12, 1.10)  # narrow receipt vs a whole A4 page filling the frame
    canvas = desk((int(w * margin[0]), int(h * margin[1])), rnd)
    shadow = Image.new("L", canvas.size, 0)  # soft drop shadow under the paper
    ox, oy = (canvas.width - w) // 2, (canvas.height - h) // 2
    ImageDraw.Draw(shadow).rectangle([ox + 10, oy + 14, ox + w + 10, oy + h + 14], fill=110)
    canvas.paste((40, 30, 20), mask=shadow.filter(ImageFilter.GaussianBlur(14)))
    canvas.paste(paper, (ox, oy))
    angle = 8 if "rotated_8deg" in defects else rnd.uniform(-2.5, 2.5)
    canvas = canvas.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=canvas.getpixel((2, 2)))
    if "perspective" in defects:
        cw, ch = canvas.size
        dst = [(0, 0), (cw, 0), (cw, ch), (0, ch)]
        src = [(cw * 0.10, ch * 0.04), (cw * 0.90, 0), (cw, ch), (0, ch * 0.97)]
        canvas = canvas.transform(canvas.size, Image.PERSPECTIVE, perspective_coeffs(src, dst), Image.BICUBIC)
    if "shadow" in defects:  # a hand/phone shadow over a third of the receipt
        layer = Image.new("L", canvas.size, 0)
        ImageDraw.Draw(layer).polygon([(0, canvas.height * 0.35), (canvas.width * 0.7, canvas.height * 0.55),
                                       (canvas.width * 0.5, canvas.height), (0, canvas.height)], fill=120)
        canvas.paste((20, 15, 10), mask=layer.filter(ImageFilter.GaussianBlur(40)))
    if "glare" in defects:  # ceiling light reflected on glossy paper
        layer = Image.new("L", canvas.size, 0)
        cx, cy, r = canvas.width * 0.58, canvas.height * 0.42, canvas.width * 0.18
        ImageDraw.Draw(layer).ellipse([cx - r, cy - r * 0.6, cx + r, cy + r * 0.6], fill=235)
        canvas.paste((255, 255, 250), mask=layer.filter(ImageFilter.GaussianBlur(r * 0.35)))
    if "low_light" in defects:
        canvas = ImageEnhance.Brightness(canvas).enhance(0.55)
        canvas = noise(canvas, rnd, 60)
    else:
        canvas = noise(canvas, rnd, 25)
    canvas = ImageEnhance.Color(canvas).enhance(0.92)  # slightly warm, phone-like
    if "blur" in defects:  # out of focus, but a careful reader still gets the numbers
        canvas = canvas.filter(ImageFilter.GaussianBlur(1.2))
    else:
        canvas = canvas.filter(ImageFilter.GaussianBlur(0.5))
    scale = 1600 / max(canvas.size)
    return canvas.resize((int(canvas.width * scale), int(canvas.height * scale)), Image.LANCZOS)


def render(d: dict, exe: str, work: Path) -> Path:
    is_receipt = d["kind"] == "receipt"
    page = receipt_html(d) if is_receipt else invoice_html(d)
    html_file = work / f"{d['id']}.html"
    html_file.write_text(page, encoding="utf-8")
    target = ROOT / "sim" / "documents" / d["artefact"]
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix == ".pdf":
        target.unlink(missing_ok=True)
        run_browser(exe, work / "profile", html_file, f"--print-to-pdf={target}")
        if not target.exists():  # a browser that hands the job to an already open window exits 0 and writes nothing
            raise RuntimeError(f"{exe} wrote no {target.name}; close that browser or set CHROME to another one")
    else:
        size = (420, 2400) if is_receipt else (900, 1400)
        paper = screenshot(exe, work / "profile", html_file, *size)
        rnd = random.Random(zlib.crc32(d["id"].encode()))
        photo(paper, d.get("photo_defects") or [], rnd).save(target, "JPEG", quality=86, optimize=True)
    return target


def main(ids: list[str]) -> None:
    docs = json.loads(DATA.read_text(encoding="utf-8"))
    if ids:
        docs = [d for d in docs if d["id"] in ids]
    exe = browser()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:  # Edge may still hold its profile lock
        for d in docs:
            path = render(d, exe, Path(tmp))
            print(f"{d['id']:16} {d['kind']:8} {','.join(d.get('photo_defects') or []) or '-':14} -> "
                  f"{path.relative_to(ROOT)}")
    print(f"{len(docs)} documents rendered into {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1:])
