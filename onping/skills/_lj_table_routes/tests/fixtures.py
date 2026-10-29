"""Synthetic TableSource / LogTableSource fixtures in the live wire shapes.

The shapes follow live reads from 2026-10-09 (data-table positions start at
1, log-table positions at 0, schemas listed newest first). Every PID, UUID,
and group id here is made up.
"""

from __future__ import annotations

import copy

GROUP = "o000000000000000000000001"

C_TEXT = "11111111-1111-4111-8111-111111111111"
C_RES1 = "22222222-2222-4222-8222-222222222222"
C_RES2 = "33333333-3333-4333-8333-333333333333"
C_TIME = "44444444-4444-4444-8444-444444444444"


def datatable() -> dict:
    return copy.deepcopy({
        "tableId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "tableName": "Synthetic Data Table",
        "tableLJSerial": 9999,
        "tableGroupId": GROUP,
        "tableDeleted": False,
        "tableFrozenRows": [],
        "tableFrozenColumn": C_RES2,
        "tablePagination": {"tablePaginationLimit": 10, "tablePaginationOffset": 0},
        "tableDimensions": {
            "tableDimensionsCellWidth": 0, "tableDimensionsCellHeight": 0,
            "tableDimensionsHeaderXPadding": 0, "tableDimensionsHeaderYPadding": 0,
            "tableDimensionsCellXPadding": 0, "tableDimensionsCellYPadding": 0,
            "tableDimensionsCustomColumns": {C_TEXT: 150, C_RES2: 200},
        },
        "tableHeader": {
            "tableHeaderColumns": {
                C_TEXT: {"columnHeaderId": C_TEXT, "columnHeaderNewOrDuplicate": None,
                         "columnHeaderName": "Well", "columnHeaderSelector": "TextTagSelector"},
                C_RES1: {"columnHeaderId": C_RES1, "columnHeaderNewOrDuplicate": None,
                         "columnHeaderName": "Casing", "columnHeaderSelector": "ResultTagSelector"},
                C_RES2: {"columnHeaderId": C_RES2, "columnHeaderNewOrDuplicate": None,
                         "columnHeaderName": "Tubing", "columnHeaderSelector": "ResultTagSelector"},
                C_TIME: {"columnHeaderId": C_TIME, "columnHeaderNewOrDuplicate": None,
                         "columnHeaderName": "Updated",
                         "columnHeaderSelector": "LastUpdateDateTimeTagSelector"},
            },
            # Deliberately stored out of order, as the live JSON is ("1","10","11",...).
            "tableHeaderColumnsPosition": {"3": C_RES2, "1": C_TEXT, "4": C_TIME, "2": C_RES1},
            "tableHeaderColumnsOrder": {C_RES2: "ColumnOrderNumericDESC"},
            "tableHeaderHiddenColumns": [C_RES2],
            "tableHeaderFilters": [],
        },
    })


def datatable_rows() -> list[dict]:
    return [
        {"rowId": 1, "values": ["Alpha 1H", "101.5", "55.0", "2026-10-01 00:00:00"],
         "pointers": ["Alpha 1H", "500001", "500002", "500001"]},
        {"rowId": 2, "values": ["Bravo 2H", "99.0", "7.5", "2026-10-01 00:00:00"],
         "pointers": ["Bravo 2H", "500011", "77 VPID", "500011"]},
        {"rowId": 3, "values": [None, None, None, None],
         "pointers": [None, None, None, None]},
    ]


def single_filter(column: str) -> dict:
    return {"tag": "SingleFilterRule", "contents": {
        "singleFilterColumnRef": column,
        "singleFilterConcatenationOperator": "FilterConcatenationAND",
        "singleFilterOperator": "FilterIsNotBlank",
        "singleFilterInputValue": "",
        "singleFilterInputType": "FilterInputTypeNumber",
    }}


def group_filter(*columns: str) -> dict:
    return {"tag": "GroupFilterRule", "contents": {
        "groupFilterConcatenationOperator": "FilterConcatenationOR",
        "groupFilterSubFilters": [single_filter(c)["contents"] for c in columns],
    }}


L_EVENT = "55555555-5555-4555-8555-555555555555"
L_FLOW = "66666666-6666-4666-8666-666666666666"
L_VP = "77777777-7777-4777-8777-777777777777"


def _schema(version: int, cols: dict, positions: dict) -> dict:
    return {
        "logSchemaVersion": version,
        "logSchemaHeader": {
            "schemaHeaderEventSource": 600001,
            "schemaHeaderColumns": cols,
            "schemaHeaderColumnsPosition": positions,
            "schemaHeaderColumnsOrder": {L_EVENT: "ColumnOrderLexicographicDESC"},
            "schemaHeaderHiddenColumns": [L_VP],
            "schemaHeaderFilters": [],
        },
        "logSchemaPagination": None,
        "logSchemaFrozenRows": [],
        "logSchemaFrozenColumn": None,
        "logSchemaDimensions": {
            "tableDimensionsCellWidth": 0, "tableDimensionsCellHeight": 0,
            "tableDimensionsHeaderXPadding": 0, "tableDimensionsHeaderYPadding": 0,
            "tableDimensionsCellXPadding": 0, "tableDimensionsCellYPadding": 0,
            "tableDimensionsCustomColumns": {L_FLOW: 120},
        },
    }


def logtable() -> dict:
    event = {"columnSchemaId": L_EVENT, "columnSchemaKey": 600001,
             "columnSchemaName": "eventDateTime", "columnSchemaSelector": "LastUpdateDateTimeTagSelector"}
    flow = {"columnSchemaId": L_FLOW, "columnSchemaKey": 600002,
            "columnSchemaName": "flow", "columnSchemaSelector": "ResultTagSelector"}
    vp = {"columnSchemaId": L_VP, "columnSchemaKey": {"keyType": "VPID", "keyValue": 88},
          "columnSchemaName": "message", "columnSchemaSelector": "ResultTagSelector"}
    v2 = _schema(2, {L_EVENT: event, L_FLOW: flow, L_VP: vp},
                 {"0": L_EVENT, "1": L_FLOW, "2": L_VP})
    v1 = _schema(1, {L_EVENT: copy.deepcopy(event), L_FLOW: copy.deepcopy(flow)},
                 {"0": L_EVENT, "1": L_FLOW})
    return copy.deepcopy({
        "logTableSourceId": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "logTableSourceName": "Synthetic Log Table",
        "logTableSourceLJSerial": 9999,
        "logTableSourceGroupId": GROUP,
        "logTableSourceSchemaVersion": 2,
        "logTableSourceSchemas": [v2, v1],  # newest first, as listed live
        "logTableSourceDeleted": False,
        "logTableSourceRequiresRestore": False,
    })
