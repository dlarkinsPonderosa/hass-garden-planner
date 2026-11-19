"""The card is registered with a real dashboard resource collection."""

from homeassistant.components.lovelace import resources as ll_res
from custom_components.reap import CARD_URL, _async_ensure_resource
from types import SimpleNamespace

async def test_real_collection(hass):
    class Cfg:
        async def async_load(self, force):
            return {}
    col = ll_res.ResourceStorageCollection(hass, Cfg())
    hass.data["lovelace"] = SimpleNamespace(resource_mode="storage", resources=col)
    await _async_ensure_resource(hass, f"{CARD_URL}?v=1")
    await _async_ensure_resource(hass, f"{CARD_URL}?v=2")
    items = col.async_items()
    assert len(items) == 1 and items[0]["url"] == f"{CARD_URL}?v=2" and items[0]["type"] == "module"
