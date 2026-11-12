"""Config and options flow for LubeLogger Sync."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from yarl import URL

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_API_KEY, CONF_URL, UnitOfLength
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    LubeLoggerApi,
    LubeLoggerAuthError,
    LubeLoggerConnectionError,
    LubeLoggerError,
)
from .const import (
    CONF_ATTRIBUTE,
    CONF_ENTITY_ID,
    CONF_MAX_INCREASE,
    CONF_MULTIPLIER,
    CONF_NOTES,
    CONF_OFFSET,
    CONF_SCHEDULE,
    CONF_TEMPLATE,
    CONF_TIME,
    CONF_UNIT,
    CONF_VEHICLE,
    CONF_VEHICLES,
    DEFAULT_MAX_INCREASE,
    DEFAULT_NOTES,
    DEFAULT_SCHEDULE,
    DEFAULT_TIME,
    DOMAIN,
    SCHEDULES,
    TRACCAR_DISTANCE_ATTRIBUTE,
)
from .coordinator import LubeLoggerConfigEntry

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
        ),
        vol.Required(CONF_API_KEY): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)

SOURCE_DOMAINS = ["device_tracker", "sensor", "number", "input_number"]


def default_unit(metric: bool) -> str:
    """Return the default odometer unit for the HA unit system."""
    return UnitOfLength.KILOMETERS if metric else UnitOfLength.MILES


class LubeLoggerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup: URL + API key."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: LubeLoggerConfigEntry,
    ) -> LubeLoggerOptionsFlow:
        """Return the options flow."""
        return LubeLoggerOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the server URL and API key and validate them."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            if "://" not in url:
                url = f"http://{url}"
            api_key = user_input[CONF_API_KEY].strip()
            await self.async_set_unique_id(url.lower())
            self._abort_if_unique_id_configured()
            try:
                await LubeLoggerApi(
                    async_get_clientsession(self.hass), url, api_key
                ).vehicle_info()
            except LubeLoggerAuthError:
                errors["base"] = "invalid_auth"
            except LubeLoggerConnectionError:
                errors["base"] = "cannot_connect"
            except LubeLoggerError:
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"LubeLogger ({URL(url).host or url})",
                    data={CONF_URL: url, CONF_API_KEY: api_key},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )


class LubeLoggerOptionsFlow(OptionsFlow):
    """Map vehicles to odometer sources and tune the sync."""

    _vehicle_id: str
    _entity_id: str

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the menu."""
        return self.async_show_menu(step_id="init", menu_options=["vehicle", "settings"])

    def _save(self, **changes: Any) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    def _save_mapping(self, mapping: dict[str, Any] | None) -> ConfigFlowResult:
        vehicles = dict(self.config_entry.options.get(CONF_VEHICLES, {}))
        if mapping is None:
            vehicles.pop(self._vehicle_id, None)
        else:
            vehicles[self._vehicle_id] = mapping
        return self._save(**{CONF_VEHICLES: vehicles})

    async def async_step_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the vehicle to configure."""
        coordinator = self.config_entry.runtime_data
        if user_input is not None:
            self._vehicle_id = user_input[CONF_VEHICLE]
            return await self.async_step_source()

        vehicles = coordinator.data or {}
        if not vehicles:
            return self.async_abort(reason="no_vehicles")
        options = [
            selector.SelectOptionDict(
                value=str(vehicle.id),
                label=vehicle.name + (" ✓" if coordinator.mapping(vehicle.id) else ""),
            )
            for vehicle in vehicles.values()
        ]
        # Pre-select the first vehicle that has no source yet.
        first = next(
            (str(v) for v in vehicles if not coordinator.mapping(v)),
            options[0]["value"],
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_VEHICLE, default=first): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options, mode=selector.SelectSelectorMode.LIST
                    )
                )
            }
        )
        return self.async_show_form(step_id="vehicle", data_schema=schema)

    def _placeholders(self) -> dict[str, str]:
        vehicle = (self.config_entry.runtime_data.data or {}).get(int(self._vehicle_id))
        return {
            "vehicle": vehicle.name if vehicle else self._vehicle_id,
            "odometer": "?"
            if vehicle is None or vehicle.odometer is None
            else str(vehicle.odometer),
        }

    async def async_step_source(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose where the odometer value comes from: an entity or a template."""
        coordinator = self.config_entry.runtime_data
        errors: dict[str, str] = {}
        if user_input is not None:
            template = (user_input.get(CONF_TEMPLATE) or "").strip()
            entity_id = user_input.get(CONF_ENTITY_ID)
            if template:
                if coordinator.read_source({CONF_TEMPLATE: template}) is None:
                    errors[CONF_TEMPLATE] = "template_not_number"
                else:
                    return self._save_mapping({CONF_TEMPLATE: template})
            elif entity_id:
                self._entity_id = entity_id
                return await self.async_step_entity()
            else:
                return self._save_mapping(None)

        current = self.config_entry.options.get(CONF_VEHICLES, {}).get(
            self._vehicle_id, {}
        )
        schema = vol.Schema(
            {
                vol.Optional(CONF_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=SOURCE_DOMAINS)
                ),
                vol.Optional(CONF_TEMPLATE): selector.TemplateSelector(),
            }
        )
        return self.async_show_form(
            step_id="source",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or current
            ),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    async def async_step_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose attribute, multiplier and offset for an entity source."""
        coordinator = self.config_entry.runtime_data
        if user_input is not None:
            return self._save_mapping(
                {
                    CONF_ENTITY_ID: self._entity_id,
                    CONF_ATTRIBUTE: user_input.get(CONF_ATTRIBUTE) or None,
                    CONF_MULTIPLIER: user_input[CONF_MULTIPLIER],
                    CONF_OFFSET: user_input[CONF_OFFSET],
                }
            )

        state = self.hass.states.get(self._entity_id)
        attributes = state.attributes if state else {}
        current = self.config_entry.options.get(CONF_VEHICLES, {}).get(
            self._vehicle_id, {}
        )
        if current.get(CONF_ENTITY_ID) == self._entity_id:
            suggested = current
        elif TRACCAR_DISTANCE_ATTRIBUTE in attributes:
            # Traccar reports the total distance in metres.
            suggested = {
                CONF_ATTRIBUTE: TRACCAR_DISTANCE_ATTRIBUTE,
                CONF_MULTIPLIER: 0.001,
            }
        elif attributes.get("unit_of_measurement") == UnitOfLength.METERS:
            suggested = {CONF_MULTIPLIER: 0.001}
        else:
            suggested = {}
        suggested = {CONF_MULTIPLIER: 1, CONF_OFFSET: 0, **suggested}

        preview = coordinator.read_source({CONF_ENTITY_ID: self._entity_id, **suggested})
        schema = vol.Schema(
            {
                vol.Optional(CONF_ATTRIBUTE): selector.AttributeSelector(
                    selector.AttributeSelectorConfig(entity_id=self._entity_id)
                ),
                vol.Required(CONF_MULTIPLIER): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX, step="any", min=0
                    )
                ),
                vol.Required(CONF_OFFSET): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX, step="any"
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="entity",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            description_placeholders={
                **self._placeholders(),
                "entity": self._entity_id,
                "preview": "?" if preview is None else str(preview),
            },
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Schedule, note text, safety limit and unit."""
        if user_input is not None:
            user_input[CONF_MAX_INCREASE] = int(user_input[CONF_MAX_INCREASE])
            user_input.setdefault(CONF_NOTES, "")
            return self._save(**user_input)

        defaults = {
            CONF_SCHEDULE: DEFAULT_SCHEDULE,
            CONF_TIME: DEFAULT_TIME,
            CONF_NOTES: DEFAULT_NOTES,
            CONF_MAX_INCREASE: DEFAULT_MAX_INCREASE,
            CONF_UNIT: default_unit(
                self.hass.config.units.length_unit == UnitOfLength.KILOMETERS
            ),
            **self.config_entry.options,
        }
        schema = vol.Schema(
            {
                vol.Required(CONF_SCHEDULE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=SCHEDULES,
                        translation_key=CONF_SCHEDULE,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_TIME): selector.TimeSelector(),
                vol.Optional(CONF_NOTES): selector.TextSelector(),
                vol.Required(CONF_MAX_INCREASE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX, min=0, step=1
                    )
                ),
                vol.Required(CONF_UNIT): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[UnitOfLength.KILOMETERS, UnitOfLength.MILES],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(schema, defaults),
        )
