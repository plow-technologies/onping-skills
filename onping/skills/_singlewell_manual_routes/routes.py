"""Routes and server facts for the singlewell-manual create and delete skills.

Read from the OnPing source (2026-10-28):

  POST /singlewellmanual/location/add   postAddSingleWellManualLocationR
  POST /singlewellmanual/get/loc        postGetManualLocationByIdR
  POST /singlewellmanual/locations      postGetAllSingleWellManualLocationsR
  POST /singlewellmanual/delete         postDeleteSingleWellManualLocationR
      all in onping/Handler/SingleWellManual/Service.hs
  GET  /permissions/groups/ownership    Handler/PermissionGraph/Service.hs
  GET  /las/api/v1/lumberjack/profiles  the LAS profile list ([serial, profile])
  GET  /json/listers/siteLister         ?getCompanyLookupList=<company>

The request body is ManualLocationConfig [ManualTag]
(onping-types/onping-handler-types/src/Onping/Types/Handler/SingleWellManual.hs).
The delete logic is deleteManualLocationById
(onping-core, the SingleWellManual Location module).

Both skills check group ownership themselves before they send a write. Servers
before version 2026.11.5.1 checked only that the caller was logged in; servers
at 2026.11.5.1 or later check group ownership on both write routes and answer
403 otherwise. The delete route answered HTTP 200 for every outcome on older
servers; at 2026.11.5.1 or later, a failure answers 400, 403 or 500 with an
`error` key.
"""

from __future__ import annotations

import os

BASE_URL = os.environ.get("ONPING_BASE_URL", "https://onping.plowtech.net")
TIMEOUT_SECONDS = 120

ADD = "POST /singlewellmanual/location/add"
GET_LOC = "POST /singlewellmanual/get/loc"
LIST_AT_SITES = "POST /singlewellmanual/locations"
DELETE = "POST /singlewellmanual/delete"
OWNERSHIP = "GET /permissions/groups/ownership"
PROFILES = "GET /las/api/v1/lumberjack/profiles"
SITES = "GET /json/listers/siteLister"

DEFAULT_PORT = 13001  # Drivers_SingleWellManual_Add_Form.res

# getSingleWellManualByRefId's three Left messages, checked in this order.
MSG_NO_MANUAL = "failed to find single well manual location by id"
MSG_NO_EXTRAS = "failed to find single well extras in mongo"
MSG_NO_GROUP = "failed to find group id by location in mongo"

# The add route writes these in order and stops at the first failure without
# undoing anything. Each entry: (marker in the 500 error text, the stage that
# failed, the records that exist after that failure).
_MYSQL = "MySQL OnpingLocation row"
_SWITCHER = "switcher routing index"
_MANUAL = "manual-server location record"
_MONGO = "Mongo location"
_EXTRAS = "single-well extras record"
_GROUP = "location group join"
ADD_ORDER = (_MYSQL, _SWITCHER, _MANUAL, _MONGO, _EXTRAS, _GROUP)

ADD_FAILURES = (
    ("Failed to convert LocationConfig", "convert after the MySQL insert", (_MYSQL,)),
    ("Failed to insert switcher index", "switcher index", (_MYSQL,)),
    ("Step 1", "Step 1 (addNewManualLocation)", (_MYSQL, _SWITCHER)),
    ("Step 2", "Step 2 (insertLocation)", (_MYSQL, _SWITCHER, _MANUAL)),
    ("Step 3", "Step 3 (insertSingleWellExtras)", (_MYSQL, _SWITCHER, _MANUAL, _MONGO)),
    ("Step 4", "Step 4 (insertLocationGroupJoin)", (_MYSQL, _SWITCHER, _MANUAL, _MONGO, _EXTRAS)),
)

# What the delete removes, and what it leaves. Servers before the 2026.11.5.1
# fix removed the manual record, then the Mongo location if found, even when the
# first removal failed. Fixed servers also remove the group join and the
# switcher index, so DELETE_LEAVES is the larger, older list.
DELETE_REMOVES = (_MANUAL, _MONGO)
DELETE_LEAVES = (_MYSQL, _EXTRAS, _GROUP, _SWITCHER)
PARAMETER_RESIDUE = "the parameters' MySQL rows (their PIDs are orphaned, not removed)"

# The keys create sends. manualLocationId and manualLocationRefId are sent as
# null: a manualLocationId makes the server refuse ("Use update endpoint
# instead"), and the server assigns the refId.
CREATE_KEYS = (
    "manualLocationName",
    "manualLocationId",
    "manualLocationUrl",
    "manualLocationPort",
    "manualLocationGroupId",
    "manualLocationRefId",
    "locationCompanyId",
    "locationSiteId",
    "locationNotes",
    "locationData",
    "coordinates",
)

# Fields the create read-back compares. coordinates is printed, not compared:
# the server stores it on the extras record (singleWellExtrasGps) and get/loc
# rebuilds it from there, so it is a second record's view, not the one sent.
READBACK_FIELDS = (
    "manualLocationName",
    "manualLocationUrl",
    "manualLocationPort",
    "manualLocationGroupId",
    "locationCompanyId",
    "locationSiteId",
    "locationNotes",
    "locationData",
)
