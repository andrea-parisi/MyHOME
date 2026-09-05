# MyHOME (Modernized) — Andrea Parisi's fork

Home Assistant integration for BTicino / Legrand MyHome (OpenWebNet)
wired home automation systems.

This fork tracks [mantovanellimatteo/MyHOME](https://github.com/mantovanellimatteo/MyHOME)
and adds **time-based position control for shutters that lack native
position feedback**.

## Attribution

This project stands on the work of two previous efforts:

- **[`anotherjulien/MyHOME`](https://github.com/anotherjulien/MyHOME)** —
  the original integration. Developed by Julien A. from 2020 to early
  2024 (last release `0.9.3`), then archived by the author. Also
  author of the underlying [OWNd](https://pypi.org/project/OWNd/)
  library that this integration still depends on at runtime.

- **[`mantovanellimatteo/MyHOME`](https://github.com/mantovanellimatteo/MyHOME)** —
  active modernization for Home Assistant 2024+. Adds config-flow UI,
  active/passive bus discovery, WHO 22 sound diffusion, WHO 0 scenario
  device triggers, WHO 3 load management, WHO 18 energy metering, and
  many other improvements. See
  [mantovanelli's README](https://github.com/mantovanellimatteo/MyHOME/blob/master/README.md)
  for the complete feature list and detailed changelog.

This fork ([`andrea-parisi/MyHOME`](https://github.com/andrea-parisi/MyHOME))
tracks mantovanelli's `master` and layers additional work on top.

## What this fork adds

### Time-based position control for non-advanced shutters (v0.4.12+)

Cover entities without native position feedback from the bus can now
expose a `SET_POSITION` action, once you configure the movement times.
The integration then:

- Sends `raise` / `lower` commands and issues a timed `stop` to reach
  the requested position;
- Extrapolates `current_cover_position` from elapsed time on each
  start/stop bus event — so physical button presses on the wall
  keypad also converge to the correct state in Home Assistant.

### Configuration

In your `myhome.yaml`, add `opening_time` and `closing_time` (in
seconds) to each cover entity that should support time-based
positioning:

```yaml
cover:
  living_room_shutter:
    who: "2"
    where: "41"
    name: "Living room shutter"
    opening_time: 15
    closing_time: 14
```

Measure real end-to-end times on your hardware — opening and closing
values often differ (gravity typically makes closing faster).

Advanced shutters (with native `SET_POSITION` support from the
gateway) are unaffected and continue to use bus-reported positions
directly.

## Installation

Via HACS, as a custom repository:

1. HACS → three-dot menu → **Custom repositories**
2. URL: `https://github.com/andrea-parisi/MyHOME`, category: **Integration**
3. Download the latest release
4. Restart Home Assistant

## Requirements

- Home Assistant **2024.3.0** or newer
- A BTicino / Legrand MyHome gateway (F452, F454, F455, F453AV,
  MH200N, MH200, MH201, MH202, MyHomeServer1, HL4684, AM4890)
- Wired MyHome bus devices (covers, lights, climate, sound diffusion,
  scenarios, energy meters, load management…)

## Support

Please open issues on this fork:
[github.com/andrea-parisi/MyHOME/issues](https://github.com/andrea-parisi/MyHOME/issues)

For questions or issues related to features inherited from
mantovanelli's fork (everything except the time-based shutter
extension), the upstream README is usually the best reference.

## License

Same as upstream — see the `LICENSE` file at the repository root.