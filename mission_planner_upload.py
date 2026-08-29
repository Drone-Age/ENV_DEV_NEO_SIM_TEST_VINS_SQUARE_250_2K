# Mission Planner IronPython script: upload the canonical test mission.
from __future__ import print_function

import os
import time

import clr
clr.AddReference("MissionPlanner")
clr.AddReference("MAVLink")
import MAVLink
from MissionPlanner.Utilities import Locationwp


mission_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mission", "gerono-10km-150m.waypoints")
rows = []
with open(mission_path, "r") as stream:
    header = stream.readline().strip()
    if header != "QGC WPL 110":
        raise Exception("Unsupported mission header: " + header)
    for line in stream:
        if not line.strip():
            continue
        fields = line.strip().split("\t")
        if len(fields) != 12:
            raise Exception("Malformed mission row: " + line)
        rows.append(fields)

deadline = time.time() + 180.0
while not MAV.BaseStream.IsOpen and time.time() < deadline:
    Script.Sleep(500)
if not MAV.BaseStream.IsOpen:
    raise Exception("Mission Planner did not connect to SITL within 180 seconds")

print("[VINS-10KM] Uploading %d Mission Planner mission items" % len(rows))
MAV.setWPTotal(len(rows))
for fields in rows:
    sequence = int(fields[0])
    frame = int(fields[2])
    waypoint = Locationwp()
    Locationwp.id.SetValue(waypoint, int(fields[3]))
    Locationwp.p1.SetValue(waypoint, float(fields[4]))
    Locationwp.p2.SetValue(waypoint, float(fields[5]))
    Locationwp.p3.SetValue(waypoint, float(fields[6]))
    Locationwp.p4.SetValue(waypoint, float(fields[7]))
    Locationwp.lat.SetValue(waypoint, float(fields[8]))
    Locationwp.lng.SetValue(waypoint, float(fields[9]))
    Locationwp.alt.SetValue(waypoint, float(fields[10]))
    # Mission Planner's public scripting example deliberately ignores the
    # return value: older builds expose a void/implementation-detail result,
    # so treating a falsey value as MAVLink rejection aborts valid uploads.
    # The ROS controller pulls the completed mission twice and verifies every
    # field against the signed canonical file before ARM.
    MAV.setWP(waypoint, sequence, MAVLink.MAV_FRAME(frame))
MAV.setWPACK()
print("[VINS-10KM] Mission upload complete; ARM/AUTO remain controlled by the test controller")
