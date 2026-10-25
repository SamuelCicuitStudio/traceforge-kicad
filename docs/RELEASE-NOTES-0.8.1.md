# TraceForge 0.8.1

Adds a dedicated **Via Fencing** tab for ground vias along selected RF/antenna-feed
traces, distinct from the perimeter pattern in Via Stitching.

- Follow selected connected straight tracks and arcs on one net/layer.
- Choose left, right or both sides, spacing, lateral copper gap and via sizes.
- Preview source identity, accepted/rejected locations and largest fence gap.
- Native clearance/connectivity checks and undoable managed set operations.
- Separate trace-fence lists from ordinary stitching sets.
- Reject branches, disconnections, loops, signal-net fences and stale source paths.

See [Via Fencing](VIA-FENCING.md) for the workflow and limitations.
This uses through vias; it does not add HDI or automatic RF design.
