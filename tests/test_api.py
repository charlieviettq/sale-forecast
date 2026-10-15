import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import ARTIFACT_DIR, app

client = TestClient(app)
pairs = pd.read_parquet(ARTIFACT_DIR / 'predictions.parquet')
items = pd.read_parquet(ARTIFACT_DIR / 'item_forecast.parquet')


def test_health():
    r = client.get('/health')
    assert r.status_code == 200 and r.json()['items'] == pairs.item_id.nunique()


def test_known_item_total_matches_artifact():
    item_id = int(items.sort_values('total_forecast').iloc[-1].item_id)
    body = client.get(f'/api/forecast/{item_id}').json()
    expected = pairs.loc[pairs.item_id == item_id, 'forecast']
    assert body['month'] == '2015-11'
    assert len(body['by_shop']) == len(expected) == 42
    assert body['total_forecast'] == pytest.approx(expected.sum(), abs=0.01)
    assert body['lower_80'] <= body['total_forecast'] <= body['upper_80']


def test_new_item_flagged_low_confidence():
    item_id = int(items[items.is_new_item == 1].iloc[0].item_id)
    body = client.get(f'/api/forecast/{item_id}').json()
    assert body['is_new_item'] is True and body['confidence'] == 'low'


def test_item_outside_scope_returns_404():
    unknown = int(set(range(30000)).difference(items.item_id).pop())
    assert client.get(f'/api/forecast/{unknown}').status_code == 404


@pytest.mark.parametrize('bad', ['abc', '-1', '1.5'])
def test_invalid_input_returns_422(bad):
    assert client.get(f'/api/forecast/{bad}').status_code == 422


def test_index_page():
    r = client.get('/')
    assert r.status_code == 200 and 'item_id' in r.text
