"""Behavioural tests for MyHOMECover time-based positioning.

These tests exercise the real ``handle_event`` / ``_extrapolate_position`` /
periodic-timer code through the stub harness defined in ``conftest.py``.

They encode the *intended* behaviour of the absolute-formula design:

* the periodic timer must NOT mutate the bus-event reference
  (``_attr_last_event``); it advances position from a fixed movement start;
* a shutter whose position is unknown at movement start (post-restart) still
  recovers to a known end position after a full travel (the "startup trick");
* end-of-travel is reached via elapsed >= travel_time regardless of how many
  intermediate timer ticks fired.

The regression tests (``test_regression_*``) FAIL against the broken v0.4.15
periodic-timer implementation and PASS against the absolute-formula fix.
"""

from custom_components.myhome.cover import MyHOMECover
from conftest import Event


def _fire_last_tick(trackers, clock):
    """Invoke the most recent, still-active periodic tracker callback."""
    active = [t for t in trackers if not t["cancelled"]]
    assert active, "expected an active position tracker"
    active[-1]["action"](clock.now())


# --------------------------------------------------------------------------- #
# Construction / feature exposure
# --------------------------------------------------------------------------- #
def test_cover_accepts_time_configuration(make_cover):
    cover = make_cover(opening_time=3.5, closing_time=4.5)
    assert cover._attr_opening_time == 3.5
    assert cover._attr_closing_time == 4.5


def test_set_position_feature_enabled_with_times(make_cover):
    from homeassistant.components.cover import CoverEntityFeature

    cover = make_cover(opening_time=10, closing_time=10)
    assert cover._attr_supported_features & CoverEntityFeature.SET_POSITION


def test_set_position_feature_disabled_without_times(make_cover):
    from homeassistant.components.cover import CoverEntityFeature

    cover = make_cover(opening_time=0, closing_time=0)
    assert not (cover._attr_supported_features & CoverEntityFeature.SET_POSITION)


# --------------------------------------------------------------------------- #
# Bus-authoritative position (advanced shutter)
# --------------------------------------------------------------------------- #
def test_bus_position_is_trusted(make_cover, clock):
    cover = make_cover()
    cover.handle_event(Event(current_position=42, is_opening=False, is_closing=False))
    assert cover._attr_current_cover_position == 42


# --------------------------------------------------------------------------- #
# Known start position: smooth extrapolation while opening
# --------------------------------------------------------------------------- #
def test_partial_open_extrapolates_from_known_start(make_cover, clock):
    cover = make_cover(opening_time=10, closing_time=10)
    cover._attr_current_cover_position = 20

    # Bus: start opening
    cover.handle_event(Event(is_opening=True, is_closing=False))
    assert cover._attr_current_cover_position == 20  # unchanged at t0

    clock.advance(2)
    _tick(cover, clock)
    assert cover._attr_current_cover_position == 40  # 20 + 100*2/10

    clock.advance(3)  # total 5s
    _tick(cover, clock)
    assert cover._attr_current_cover_position == 70  # 20 + 100*5/10

    # Bus: stop at 5s -> position finalises, movement ends
    cover.handle_event(Event(is_opening=False, is_closing=False))
    assert cover._attr_current_cover_position == 70
    assert not cover._attr_is_opening and not cover._attr_is_closing


def test_full_open_reaches_100(make_cover, clock):
    cover = make_cover(opening_time=10, closing_time=10)
    cover._attr_current_cover_position = 0

    cover.handle_event(Event(is_opening=True, is_closing=False))
    clock.advance(12)  # beyond opening_time
    cover.handle_event(Event(is_opening=False, is_closing=False))

    assert cover._attr_current_cover_position == 100
    assert cover._attr_is_closed is False


def test_full_close_reaches_0(make_cover, clock):
    cover = make_cover(opening_time=10, closing_time=10)
    cover._attr_current_cover_position = 100

    cover.handle_event(Event(is_opening=False, is_closing=True))
    clock.advance(12)  # beyond closing_time
    cover.handle_event(Event(is_opening=False, is_closing=False))

    assert cover._attr_current_cover_position == 0
    assert cover._attr_is_closed is True


# --------------------------------------------------------------------------- #
# Timer lifecycle
# --------------------------------------------------------------------------- #
def test_tracker_starts_on_move_and_cancels_on_stop(make_cover, clock, trackers):
    cover = make_cover()
    cover._attr_current_cover_position = 0

    cover.handle_event(Event(is_opening=True, is_closing=False))
    active = [t for t in trackers if not t["cancelled"]]
    assert len(active) == 1

    cover.handle_event(Event(is_opening=False, is_closing=False))
    active = [t for t in trackers if not t["cancelled"]]
    assert len(active) == 0


def test_tracker_cancelled_on_remove(make_cover, clock, trackers):
    import asyncio

    cover = make_cover()
    cover._attr_current_cover_position = 0
    cover.handle_event(Event(is_opening=True, is_closing=False))
    assert [t for t in trackers if not t["cancelled"]]

    asyncio.run(cover.async_will_remove_from_hass())
    assert not [t for t in trackers if not t["cancelled"]]


# --------------------------------------------------------------------------- #
# REGRESSIONS against the broken v0.4.15 periodic timer
# --------------------------------------------------------------------------- #
def test_regression_timer_does_not_touch_last_event(make_cover, clock):
    """The periodic tick must not overwrite the bus-event reference.

    v0.4.15 set ``_attr_last_event = now`` on every tick, which reset the
    elapsed-time baseline and broke the end-of-travel fallback.
    """
    cover = make_cover(opening_time=10, closing_time=10)
    cover._attr_current_cover_position = 0
    cover.handle_event(Event(is_opening=True, is_closing=False))

    reference = cover._attr_last_event
    clock.advance(0.5)
    _tick(cover, clock)
    assert cover._attr_last_event == reference


def test_regression_startup_trick_recovers_from_unknown(make_cover, clock):
    """Post-restart the position is None; a full travel must recover it to 100.

    This is the concrete symptom of v0.4.15: with periodic ticks firing, the
    elapsed baseline never exceeds opening_time, so the fallback that snaps to
    100 never runs and the shutter is stuck at ``unknown`` forever.
    """
    cover = make_cover(opening_time=10, closing_time=10)
    assert cover._attr_current_cover_position is None  # post-restart

    cover.handle_event(Event(is_opening=True, is_closing=False))

    # Simulate HA firing the 500ms timer for the whole travel + margin.
    for _ in range(24):  # 24 * 0.5s = 12s > opening_time
        clock.advance(0.5)
        _tick(cover, clock)

    cover.handle_event(Event(is_opening=False, is_closing=False))
    assert cover._attr_current_cover_position == 100
    assert cover._attr_is_closed is False


def test_regression_movement_reference_tracked(make_cover, clock):
    """The fix keeps an absolute movement reference, cleared when stopped."""
    cover = make_cover(opening_time=10, closing_time=10)
    cover._attr_current_cover_position = 30

    cover.handle_event(Event(is_opening=True, is_closing=False))
    assert cover._movement_start_time is not None
    assert cover._movement_start_position == 30

    cover.handle_event(Event(is_opening=False, is_closing=False))
    assert cover._movement_start_time is None
    assert cover._movement_start_position is None


def test_regression_ticks_do_not_overshoot_or_stall(make_cover, clock):
    """With a known start, periodic ticks converge to 100 and clamp there."""
    cover = make_cover(opening_time=10, closing_time=10)
    cover._attr_current_cover_position = 0
    cover.handle_event(Event(is_opening=True, is_closing=False))

    for _ in range(30):  # 15s of ticks, well past opening_time
        clock.advance(0.5)
        _tick(cover, clock)

    assert cover._attr_current_cover_position == 100


# --------------------------------------------------------------------------- #
# Direction reversal
# --------------------------------------------------------------------------- #
def test_reversal_uses_extrapolated_position_as_new_start(make_cover, clock):
    cover = make_cover(opening_time=10, closing_time=10)
    cover._attr_current_cover_position = 0

    cover.handle_event(Event(is_opening=True, is_closing=False))
    clock.advance(4)  # opened to ~40
    _tick(cover, clock)
    assert cover._attr_current_cover_position == 40

    # Reverse to closing without an explicit stop event
    cover.handle_event(Event(is_opening=False, is_closing=True))
    assert cover._movement_start_position == 40

    clock.advance(2)  # close 20 from 40
    _tick(cover, clock)
    assert cover._attr_current_cover_position == 20


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _trackers():
    from conftest import TRACKERS

    return TRACKERS


def _tick(cover, clock):
    """Fire the most recent still-active periodic tracker callback."""
    from conftest import TRACKERS

    active = [t for t in TRACKERS if not t["cancelled"]]
    assert active, "expected an active position tracker"
    active[-1]["action"](clock.now())
