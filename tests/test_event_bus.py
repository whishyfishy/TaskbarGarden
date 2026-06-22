from desktop_cat.event_bus import EventBus


def test_subscriber_receives_event():
    bus = EventBus()
    received = []
    bus.subscribe("TEST", received.append)
    bus.publish("TEST", {"x": 1})
    bus.tick()
    assert received == [{"x": 1}]


def test_events_queued_not_dispatched_immediately():
    bus = EventBus()
    received = []
    bus.subscribe("TEST", received.append)
    bus.publish("TEST", 42)
    assert received == []  # not dispatched yet
    bus.tick()
    assert received == [42]


def test_multiple_subscribers_all_called():
    bus = EventBus()
    a, b = [], []
    bus.subscribe("EV", a.append)
    bus.subscribe("EV", b.append)
    bus.publish("EV", "hello")
    bus.tick()
    assert a == ["hello"]
    assert b == ["hello"]


def test_unsubscribed_event_type_ignored():
    bus = EventBus()
    received = []
    bus.subscribe("A", received.append)
    bus.publish("B", "ignored")
    bus.tick()
    assert received == []


def test_tick_clears_queue():
    bus = EventBus()
    received = []
    bus.subscribe("X", received.append)
    bus.publish("X", 1)
    bus.tick()
    bus.tick()  # second tick — queue already drained
    assert received == [1]


def test_multiple_events_dispatched_in_order():
    bus = EventBus()
    received = []
    bus.subscribe("N", received.append)
    bus.publish("N", 1)
    bus.publish("N", 2)
    bus.publish("N", 3)
    bus.tick()
    assert received == [1, 2, 3]


def test_publish_during_tick_deferred_to_next_tick():
    bus = EventBus()
    received = []

    def on_first(data):
        bus.publish("SECOND", "deferred")

    bus.subscribe("FIRST", on_first)
    bus.subscribe("SECOND", received.append)
    bus.publish("FIRST", None)
    bus.tick()
    assert received == []  # not dispatched in same tick
    bus.tick()
    assert received == ["deferred"]
