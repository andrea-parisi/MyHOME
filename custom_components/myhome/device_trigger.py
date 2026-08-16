"""Provides device triggers for MyHOME."""
import logging
import voluptuous as vol

from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

TRIGGER_TYPES = {"scenario_button_pressed"}

TRIGGER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PLATFORM): "device",
        vol.Required(CONF_DOMAIN): DOMAIN,
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES),
        vol.Required("scenario"): vol.All(vol.Coerce(int), vol.Range(min=1, max=31)),
        vol.Optional("metadata"): dict,
    }
)

async def async_get_triggers(hass, device_id):
    """List device triggers for MyHOME devices."""
    try:
        _LOGGER.warning("MyHOME async_get_triggers called for device: %s", device_id)
        device_registry = dr.async_get(hass)
        device = device_registry.async_get(device_id)

        if not device:
            _LOGGER.warning("MyHOME device not found in registry")
            return []

        # Check if this device is a scenario module
        is_scenario = False
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN and "-scenario-" in identifier[1]:
                is_scenario = True
                break

        if not is_scenario:
            _LOGGER.warning("MyHOME device is not a scenario module")
            return []

        triggers = []
        # Provide triggers for button 1 to 8 in the UI dropdown
        for i in range(1, 9):
            triggers.append(
                {
                    CONF_PLATFORM: "device",
                    CONF_DOMAIN: DOMAIN,
                    CONF_DEVICE_ID: device_id,
                    CONF_TYPE: "scenario_button_pressed",
                    "scenario": i,
                    "metadata": {"secondary": False},
                }
            )

        _LOGGER.warning("MyHOME returning triggers: %s", triggers)
        return triggers

    except Exception as e:
        _LOGGER.error("MyHOME error in async_get_triggers: %s", e)
        return []


async def async_attach_trigger(hass, config, action, trigger_info):
    """Attach a trigger."""
    try:
        device_registry = dr.async_get(hass)
        device = device_registry.async_get(config[CONF_DEVICE_ID])

        control_panel = None
        if device:
            for identifier in device.identifiers:
                if identifier[0] == DOMAIN and "-scenario-" in identifier[1]:
                    control_panel = identifier[1].split("-scenario-")[1]
                    break

        if not control_panel:
            return None

        # Attach to the native event myhome_scenario_event
        event_config = {
            "platform": "event",
            "event_type": "myhome_scenario_event",
            "event_data": {
                "scenario": config["scenario"],
                "control_panel": control_panel,
            },
        }

        from homeassistant.helpers import trigger as trigger_helper
        return await trigger_helper.async_attach_trigger(
            hass, event_config, action, trigger_info
        )
    except Exception as e:
        _LOGGER.error("MyHOME error in async_attach_trigger: %s", e)
        return None
