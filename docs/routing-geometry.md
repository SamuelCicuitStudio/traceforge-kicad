# Routing geometry in Signals / xSignals

The routing table is visible above signal timing results, including when no chains
are detected. Refresh reads the saved PCB stackup and project impedance profiles.
It shows profile and assigned netclasses, single-ended/RF or differential type,
target impedance, signal layer, reference planes, width and differential edge gap
in millimetres. Board copper thickness, dielectric thickness, material and Er are
shown above the table. A local PCBWay stackup selection identifier is shown when present.

Geometry comes from KiCad's saved profile layer entries (native nanometres converted
to millimetres), not from the DRC report or a generic recommendation. This display
does not run an impedance solver or certify an old profile against a changed stackup.
Recompute profiles when construction changes, then save the PCB/project and refresh.
Unprofiled netclasses remain visible as settings only, explicitly NOT computed.
Missing or zero profile widths/gaps are marked NOT COMPUTED, never replaced by defaults.
RF uses the corresponding single-ended impedance profile; coplanar geometry requires
its own solved profile and must not be inferred from the RF label.
