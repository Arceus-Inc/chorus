export function makeId() {
  // good-enough unique id for local app; deterministic tests can stub if needed
  return `tx_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}
