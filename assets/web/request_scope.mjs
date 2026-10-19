/** Small per-view request lifetime helper. It performs no network or DOM work. */
export function createRequestScope() {
  let context = null;
  let generation = 0;
  const lanes = new Map();
  const abort = ticket => ticket.controller.abort();
  function enter(key) {
    if (key !== null && (typeof key !== 'string' || key.length === 0)) {
      throw new TypeError('Context must be a nonempty identity/version key or null');
    }
    for (const ticket of lanes.values()) abort(ticket);
    lanes.clear();
    context = key;
    generation += 1;
  }
  function begin(lane = 'view') {
    if (context === null) throw new Error('No current view context');
    if (typeof lane !== 'string' || lane.length === 0) throw new TypeError('A request lane is required');
    const previous = lanes.get(lane);
    if (previous) abort(previous);
    const controller = new AbortController();
    const ticket = Object.freeze({context, generation, lane, controller, signal: controller.signal});
    lanes.set(lane, ticket);
    return ticket;
  }
  function isCurrent(ticket) {
    return !!ticket && context !== null && ticket.context === context &&
      ticket.generation === generation && lanes.get(ticket.lane) === ticket && !ticket.signal.aborted;
  }
  function finish(ticket) {
    if (!isCurrent(ticket)) return false;
    lanes.delete(ticket.lane);
    return true;
  }
  function cancel(lane = 'view') {
    const ticket = lanes.get(lane);
    if (ticket) { abort(ticket); lanes.delete(lane); }
  }
  return Object.freeze({enter, begin, isCurrent, finish, cancel, close: () => enter(null)});
}
