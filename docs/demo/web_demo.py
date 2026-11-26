"""Record the web page demo, docs/images/web-demo.gif.

Drives a running ``batchslicer web`` in Chrome (Playwright), uploads a
two-colour 3MF and a kit's zip, shows a caption for each step, and writes an
optimised GIF. Needs Google Chrome and, outside BatchSlicer's own
dependencies, ``pip install playwright pillow``.

Start the page first, with a printer configured and a clean output folder
(the demo's results are the only ones it should show), for example:

    batchslicer web --profile k2 --plates --send k2plus --loaded-filaments

then, with bumper.3mf and boat-kit.zip in UPLOAD_DIR (``demo.sh`` makes both
in ~/demo/kits):

    python web_demo.py http://127.0.0.1:8765/ ~/demo/kits ../images/web-demo.gif

The files are sent to the printer as with --send; nothing is started.
"""

import io
import sys
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

URL, UPLOADS, OUT = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
SIZE = {"width": 1100, "height": 900}
FRAME_EVERY = 0.4  # seconds between captured frames
frames: list[tuple[Image.Image, float]] = []

CAPTION_JS = """
(text) => {
  let bar = document.getElementById('demo-caption');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'demo-caption';
    bar.style.cssText = 'position:fixed;left:50%;bottom:22px;transform:translateX(-50%);'
      + 'background:rgba(20,28,24,.92);color:#fff;font:600 19px/1.35 system-ui,sans-serif;'
      + 'padding:12px 22px;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.25);'
      + 'z-index:99999;max-width:88%;text-align:center;pointer-events:none';
    document.body.appendChild(bar);
  }
  bar.textContent = text;
  bar.style.display = text ? 'block' : 'none';
}
"""


def grab(page) -> None:
    png = page.screenshot(type="png")
    frames.append((Image.open(io.BytesIO(png)).convert("RGB"), time.monotonic()))


def hold(page, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        grab(page)
        time.sleep(FRAME_EVERY)


def caption(page, text: str) -> None:
    page.evaluate(CAPTION_JS, text)


def until(page, check, timeout: float = 120) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        grab(page)
        if check():
            return
        time.sleep(FRAME_EVERY)
    raise TimeoutError("step did not finish")


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(viewport=SIZE, device_scale_factor=1)
    page.goto(URL)
    caption(page, "batchslicer web: slice with your own presets, from the browser")
    hold(page, 3.5)

    caption(page, "Drop a two-colour 3MF and a downloaded kit's zip on the page")
    hold(page, 2.0)
    page.set_input_files('input[name="files"]', [str(UPLOADS / "bumper.3mf"), str(UPLOADS / "boat-kit.zip")])
    hold(page, 1.5)
    caption(page, "They're sliced one after another; colours are matched to the CFS")

    def results() -> int:
        return page.locator('a[href^="/results/"]').count()

    until(page, lambda: results() >= 2, timeout=180)
    hold(page, 1.0)
    page.evaluate("document.querySelector('#results, h2:last-of-type')"
                  "?.scrollIntoView({behavior: 'smooth', block: 'start'})")
    caption(page, "Each result: picture, print time and filament, already sent to the K2")
    hold(page, 4.5)

    page.locator('a[href^="/results/bumper"]').first.click()
    page.wait_for_load_state("networkidle")
    caption(page, "Print time, filament per colour, and the G-code named bumper_PETG_1h17m")
    hold(page, 4.5)
    caption(page, "Download the G-code or a ZIP, or send it to a printer")
    hold(page, 3.0)

    page.goto(URL.rstrip("/") + "/printers")
    page.wait_for_load_state("networkidle")
    caption(page, "Printers: what's loaded in each CFS slot, live from the printer")
    hold(page, 4.0)

    page.goto(URL)
    page.wait_for_load_state("networkidle")
    caption(page, 'pipx install "batchslicer[web]"  ·  batchslicer web')
    hold(page, 4.0)
    browser.close()

# Frame durations from the real timing; slow stretches (slicing) stay real time.
images = [image for image, _ in frames]
durations = [max(60, int((frames[i + 1][1] - frames[i][1]) * 1000)) for i in range(len(frames) - 1)] + [1500]
sample = images[:: max(1, len(images) // 12)]
montage = Image.new("RGB", (SIZE["width"], SIZE["height"] * len(sample)))
for index, image in enumerate(sample):
    montage.paste(image, (0, SIZE["height"] * index))
palette = montage.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
quantized = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in images]
quantized[0].save(OUT, save_all=True, append_images=quantized[1:], duration=durations, loop=0, optimize=True)
print(f"{len(frames)} frames, {sum(durations) / 1000:.0f}s, {OUT.stat().st_size / 1e6:.1f} MB")
