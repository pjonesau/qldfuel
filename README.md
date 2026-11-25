# Queensland Fuel

A [Home Assistant](https://www.home-assistant.io/) custom integration for the
[Fuel Prices Qld](https://www.fuelpricesqld.com.au/) subscriber API. It tracks
fuel prices at stations near a fixed zone or a moving entity (e.g. your
phone), and surfaces the cheapest price nearby for each fuel type you care
about.

## Features

- **"Cheapest nearby" sensors** — one sensor per selected fuel type, showing
  the lowest current price among stations within radius, with the winning
  station's name, address, brand and distance as attributes.
- **Map entities** — every station currently within radius is exposed as a
  `geo_location` entity, so they show up on the HA map with live prices,
  brand and address.
- **Two origin modes** — measure the radius from a fixed HA `zone`, or from a
  `device_tracker`/`person` entity so the station list follows you as you
  move.
- **Shared polling** — multiple config entries using the same API key share
  a single poller against the upstream API, so tracking several origins
  (e.g. more than one person) doesn't multiply API calls.

## Requirements

You need a free subscriber API key from
[fuelpricesqld.com.au](https://www.fuelpricesqld.com.au/). You'll be asked
for it during setup.

## Installation

### HACS (recommended)

1. In HACS, go to **Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/pjonesau/qldfuel` as an **Integration**.
3. Install "Queensland Fuel" and restart Home Assistant.

### Manual

1. Copy the `qldfuel` folder into `<config>/custom_components/`.
2. Restart Home Assistant.

## Setup

1. Go to **Settings → Devices & Services → Add Integration**, search for
   "Queensland Fuel".
2. Enter your API key.
3. Choose what the search radius is measured from:
   - **A fixed zone** — pick an existing HA `zone` entity, a radius, and a
     poll interval.
   - **A tracked entity** — pick a `device_tracker` or `person` entity, a
     radius, and a poll interval; the station list updates as that entity
     moves.
4. Select which fuel types to track. A "cheapest nearby" sensor is created
   for each one.

You can add multiple entries — for example, one per household member's
phone, or one for home and one for a regular commute zone. Each entry is
named after its origin, e.g. "Queensland Fuel Prices (Home)".

Origin, radius, poll interval and fuel type selections can be changed later
from the integration's **Configure** option without re-adding it.

## Notes

- Entries sharing an API key share a single poller against the upstream
  API — adding another origin never multiplies polling. If those entries
  request different poll intervals, the shared poller runs at the fastest
  one currently in use.
- Prices refresh on every poll. When the origin is a tracked entity, the
  station list is only recomputed for movement once it has moved more than
  ~1 km, so GPS jitter doesn't churn entities.
- Prices are in dollars per litre to the tenth of a cent (e.g. 1.899).
- Station names, brands and locations are refreshed every 6 hours; prices on
  every poll.
- While polling fails, the sensors and map entities show as unavailable.
- If the API rejects your key, Home Assistant asks you to re-authenticate.
  The new key is applied to every entry that used the old one.

## Support

This is provided as-is, with no support.

## License

[MIT](LICENSE)
