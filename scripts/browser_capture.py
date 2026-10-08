import sys, os, asyncio
from pathlib import Path

# Expect two arguments: URL and output_path
if len(sys.argv) < 3:
    print('Usage: browser_capture.py <url> <output_path>')
    sys.exit(1)

url = sys.argv[1]
output_path = Path(sys.argv[2])

# Use pyppeteer for headless Chrome screenshot
async def capture():
    from pyppeteer import launch
    browser = await launch(headless=True, args=['--no-sandbox'])
    page = await browser.newPage()
    await page.setViewport({'width': 1280, 'height': 800})
    await page.goto(url, {'waitUntil': 'networkidle2'} )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot({'path': str(output_path), 'fullPage': True})
    await browser.close()

asyncio.get_event_loop().run_until_complete(capture())
print(f'Screenshot saved to {output_path}')