"""Forecast lookup service: serves precomputed Nov-2015 forecasts (batch-prediction pattern)."""
import json
import os
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Path as PathParam
from fastapi.responses import FileResponse
from pydantic import BaseModel

ARTIFACT_DIR = Path(os.getenv('ARTIFACT_DIR', Path(__file__).resolve().parent.parent / 'artifacts'))
STATIC_DIR = Path(__file__).resolve().parent / 'static'


class ShopForecast(BaseModel):
    shop_id: int
    forecast: float


class ItemForecast(BaseModel):
    item_id: int
    item_category_id: int
    month: str
    total_forecast: float
    lower_80: float
    upper_80: float
    is_new_item: bool
    confidence: str
    n_shops: int
    by_shop: list[ShopForecast]


class ForecastStore:
    """In-memory index of the batch predictions, loaded once at startup."""

    def __init__(self, artifact_dir: Path):
        meta = json.loads((artifact_dir / 'metadata.json').read_text())
        self.month = meta['forecast_month']
        self.model_info = {k: meta[k] for k in ('model', 'n_trees', 'trained_on_months', 'created_at')}
        pairs = pd.read_parquet(artifact_dir / 'predictions.parquet')
        self.items = pd.read_parquet(artifact_dir / 'item_forecast.parquet').set_index('item_id')
        self.by_item = {
            int(i): [ShopForecast(shop_id=int(s), forecast=round(float(f), 3)) for s, f in zip(g.shop_id, g.forecast)]
            for i, g in pairs.sort_values(['item_id', 'forecast'], ascending=[True, False]).groupby('item_id')
        }

    def get(self, item_id: int) -> ItemForecast | None:
        if item_id not in self.items.index:
            return None
        r = self.items.loc[item_id]
        new = bool(r.is_new_item)
        return ItemForecast(
            item_id=item_id, item_category_id=int(r.item_category_id), month=self.month,
            total_forecast=round(float(r.total_forecast), 2), lower_80=round(float(r.lower_80), 2),
            upper_80=round(float(r.upper_80), 2), is_new_item=new, confidence='low' if new else 'normal',
            n_shops=int(r.n_shops), by_shop=self.by_item[item_id])


app = FastAPI(title='Sales Forecast 2015-11', version='1.0.0')
store = ForecastStore(ARTIFACT_DIR)


@app.get('/health')
def health():
    return {'status': 'ok', 'items': len(store.items), **store.model_info}


@app.get('/api/forecast/{item_id}', response_model=ItemForecast)
def forecast(item_id: int = PathParam(..., ge=0, description='item_id from items.csv')):
    result = store.get(item_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f'item_id {item_id} is not in the 2015-11 forecast scope (test set).')
    return result


@app.get('/', include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / 'index.html')
