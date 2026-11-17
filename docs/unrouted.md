# Unrouted connection navigator

Open **Unrouted** in TraceForge. The list refreshes when opening the tab or
returning from PCB Editor; **Refresh gaps** or F5 forces an update. No continuous
polling, DRC run, board reload or zone refill is needed.

Click a row to highlight its two copper endpoints and fit the camera around the
missing connection. **Next** and **Previous** navigate the filtered list, shortest
gaps first. **Highlight whole net** expands highlighting while keeping the camera
focused on the selected gap. **Clear highlight** uses the existing transient
highlight cleanup. No footprint, pad, track, via or zone is moved or saved.

The table shows net, netclass, endpoint references, coordinates and anchor-to-anchor
distance in mm. **Unrouted net** means its disconnected clusters contain only pads;
**Remaining gap** means routed copper or filled-zone copper already exists on the
net. The search covers net names, endpoint references and netclasses. A connection
that was just completed is detected again before focusing and triggers a refresh.

## Connectivity semantics

This uses KiCad's live connected-copper cluster searches, including the current
filled polygons. It does not infer connectivity from coincident coordinates,
common net labels or a footprint bounding box. Separate fill islands belonging to
one zone parent remain separate. The tool does not refill zones; refill stale pours
in KiCad before relying on their connection state.

KiCad's Python wrapper does not expose its RN_NET edge iterator. The navigator
therefore constructs shortest anchor links between the disconnected native
pad/track/via clusters. These are real remaining connections, but their spanning
tree can differ from the particular ratsnest lines KiCad chooses to draw. Equal
length alternatives can give different endpoint pairs. Gap distance is between
anchors, not a clearance or an optimized routed length. Pure orphan zone islands
without a pad/track/via terminal are not listed separately. The native total airwire
count is displayed alongside the navigator count, so a mismatch is visible rather
than hidden. Excluded or hidden ratsnest settings are not used as a filter.

A focus operation rechecks endpoint existence and live connectivity. It highlights
the actual items and zooms around two temporary, unregistered focus points; these
points are never inserted in the board. This avoids zooming to the entire length
of a long track when only a tiny gap at its endpoint needs work. Existing KiCad
ratsnest visibility preferences remain unchanged; highlighting and zoom work even
when ratsnest lines are hidden. No schematic changes or project settings are made.

## Validation

Native fixtures cover an incomplete routed net, pad-only nets, a connection completed
after scanning and two separate filled islands in one zone. Hidden wx tests cover
row/Next/Previous focusing, filtering and whole-net highlighting. Read-only scans of
the saved front-board and CAN-WiFi projects matched native totals (276 and 1 at the
time of the checks). These are snapshots, not routing-completion claims.
