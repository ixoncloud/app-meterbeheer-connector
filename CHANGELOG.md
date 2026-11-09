# Changelog

All notable changes to the MeterBeheer Connector. Version numbers follow the UI Component's `manifest.json` version; Cloud Function changes are listed under the same release.

## Version 3 (06-11-2026)

### Added
- **Component icon** (`icon.svg`) for the UI Component, shown in the IXON Cloud component picker.

### Changed
- Renamed the app from IXON Energy Connector to **MeterBeheer Connector**.
- Renamed the project from `ixon-energy-monitor` to `meterbeheer-connector` (folders, component, element and Cloud Function module). The component is now `pct-meterbeheer-connector` and the Cloud Function calls are `functions.meterbeheer_connector.*`.

## Version 2 (04-11-2026)

### Added
- **Contracted capacity per building** in the component settings: the admin adds one entry per building with its name and contracted capacity (kW). The kW is optional.
- **"Contracted capacity not set"** in the legend for a building without a kW value. The chart is then shown without the capacity line.

### Changed
- The building dropdown shows only the building name (the provider after the dash was removed).
- Font set to Montserrat, Roboto, Helvetica.
- More spacing between the building picker, the heading, the totals, the legend and the chart.
- More room above the chart so the "kWh" and "kW" axis labels no longer touch the top values.

### Fixed
- Overlapping "02:00 AM" labels in the quarter-hour view on the autumn clock-change day.

### Removed
- The single **Contracted capacity (kW)** setting.

## Version 1 (28-10-2026)

### Added
- First release: UI Component `ixon-energy-monitor` (element `pct-ixon-energy-monitor`) and Cloud Function `functions.ixon_energy_monitor` (`get_feeds`, `get_consumption_series`).
- Quarter-hour, day, month and year views with zoom-in, contracted-capacity check and "Limit exceeded!" note.

### Changed
- Renamed the project from `smart-meter-monitor` to `ixon-energy-monitor` (folders, component, element and Cloud Function module).
