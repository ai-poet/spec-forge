from specforge.runtime.events import EventBroker, EventEnvelope


def test_event_broker_bounds_queue_and_coalesces_snapshots():
    broker = EventBroker(max_queue_size=3)
    queue = broker.subscribe("iter-events")

    broker.publish("iter-events", EventEnvelope(type="snapshot", snapshot={"version": 1}))
    broker.publish("iter-events", EventEnvelope(type="event", event={"id": "evt-1"}))
    broker.publish("iter-events", EventEnvelope(type="snapshot", snapshot={"version": 2}))
    broker.publish("iter-events", EventEnvelope(type="event", event={"id": "evt-2"}))
    broker.publish("iter-events", EventEnvelope(type="event", event={"id": "evt-3"}))

    assert queue.qsize() <= 3
    items = [queue.get_nowait() for _ in range(queue.qsize())]
    snapshots = [item for item in items if item.type == "snapshot"]
    assert len(snapshots) <= 1
    if snapshots:
        assert snapshots[0].snapshot == {"version": 2}
    assert items[-1].event == {"id": "evt-3"}
