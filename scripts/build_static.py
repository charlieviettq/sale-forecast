"""Build a static version of the forecast service for GitHub Pages.

Batch predictions are already computed, so every API answer can be written to a JSON file:
    site/index.html                     same page as the FastAPI app, reading the JSON files
    site/api/forecast/{item_id}.json    same payload as GET /api/forecast/{item_id}
    site/api/health.json                same payload as GET /health
The payloads are produced by the FastAPI app's own ForecastStore, so both deployments always agree.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import STATIC_DIR, store  # noqa: E402

SITE = ROOT / 'site'
API_LINE = 'const apiUrl = (id) => `/api/forecast/${id}`;'
STATIC_API_LINE = 'const apiUrl = (id) => `api/forecast/${id}.json`;'


def main():
    shutil.rmtree(SITE, ignore_errors=True)
    out = SITE / 'api' / 'forecast'
    out.mkdir(parents=True)

    for item_id in store.items.index:
        payload = store.get(int(item_id)).model_dump(mode='json')
        (out / f'{int(item_id)}.json').write_text(json.dumps(payload, separators=(',', ':')))

    health = {'status': 'ok', 'items': len(store.items), **store.model_info}
    (SITE / 'api' / 'health.json').write_text(json.dumps(health))

    # Same page as the API version; only the data URL changes (relative, so it works under /<repo>/)
    html = (STATIC_DIR / 'index.html').read_text()
    assert API_LINE in html, 'apiUrl() not found in app/static/index.html'
    (SITE / 'index.html').write_text(html.replace(API_LINE, STATIC_API_LINE))
    (SITE / '.nojekyll').touch()

    print(f'Built {len(store.items):,} item files into {SITE.relative_to(ROOT)}/')


if __name__ == '__main__':
    main()
