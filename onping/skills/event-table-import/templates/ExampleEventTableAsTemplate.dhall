let mkResultColumn =
      \(idx : Integer) ->
      \(keyType : Text) ->
      \(pid : Integer) ->
      \(name : Text) ->
        { eventColumnIndex = idx
        , eventColumnKey = { type = keyType, value = pid }
        , eventColumnName = name
        , eventColumnShowCompanyId = False
        , eventColumnShowSiteId = False
        , eventColumnShowLocId = False
        , eventColumnShowCompany = False
        , eventColumnShowSite = False
        , eventColumnShowLoc = False
        , eventColumnShowResult = True
        , eventColumnShowName = False
        , eventColumnShowPID = False
        , eventColumnShowReadWrite = False
        , eventColumnShowLastUpdateDate = False
        , eventColumnShowLastUpdateTime = False
        }

let mkEventColumn =
      \(idx : Integer) ->
      \(keyType : Text) ->
      \(pid : Integer) ->
      \(name : Text) ->
        { eventColumnIndex = idx
        , eventColumnKey = { type = keyType, value = pid }
        , eventColumnName = name
        , eventColumnShowCompanyId = False
        , eventColumnShowSiteId = False
        , eventColumnShowLocId = False
        , eventColumnShowCompany = False
        , eventColumnShowSite = False
        , eventColumnShowLoc = False
        , eventColumnShowResult = False
        , eventColumnShowName = False
        , eventColumnShowPID = False
        , eventColumnShowReadWrite = False
        , eventColumnShowLastUpdateDate = True
        , eventColumnShowLastUpdateTime = True
        }

in  { eventTableUUID.unEventTableUUID =
        "00000000-0000-4000-8000-000000000001"
    , eventTableDashboardId = Some
        { unDashboardUUID = "000000000000000000000001" }
    , eventTableDeleted = False
    , eventTableSortOrder = < Desc | Asc >.Desc
    , eventTableMaxEvents =
        < FixedMaxEvents : Integer
        | DynamicMaxEvents : { type : Text, value : Integer }
        >.FixedMaxEvents
          +24
    , eventTableEventColumn = +2
    , eventTableParams =
      [ mkEventColumn
          +0
          "PID"
          +200001
          "REWARD: Reward                                     (dimensionless)"
      , mkResultColumn
          +1
          "PID"
          +200001
          "REWARD: Reward                                     (dimensionless)"
      , mkResultColumn
          +2
          "PID"
          +200002
          "REWARD: Lifting time                               (seconds)"
      , mkResultColumn
          +3
          "PID"
          +200003
          "REWARD: Afterflow time                             (seconds)"
      , mkResultColumn
          +4
          "PID"
          +200004
          "REWARD: Total cycle time                           (seconds)"
      , mkResultColumn
          +5
          "PID"
          +200005
          "REWARD: Total production                           (barrels)"
      , mkResultColumn
          +6
          "PID"
          +200006
          "REWARD: Production rate per hour                   (barrels/hour)"
      , mkResultColumn
          +7
          "PID"
          +200007
          "REWARD: Plunger arrived                            (boolean)"
      , mkResultColumn
          +8
          "PID"
          +200008
          "REWARD: Average tubing pressure                    (psi)"
      , mkResultColumn
          +9
          "PID"
          +200009
          "REWARD: Average casing pressure                    (psi)"
      , mkResultColumn
          +10
          "PID"
          +200010
          "REWARD: Average flow rate                          (barrels/hour)"
      , mkResultColumn
          +11
          "PID"
          +200011
          "REWARD: Peak casing pressure before valve open     (psi)"
      , mkResultColumn
          +12
          "PID"
          +200012
          "REWARD: Production reward                          (dimensionless)"
      , mkResultColumn
          +13
          "PID"
          +200013
          "REWARD: Arrival reward                             (dimensionless)"
      , mkResultColumn +14 "VPID" +200101 "Recommended Off Time (mins)"
      , mkResultColumn +15 "VPID" +200102 "Recommended Afterflow Time"
      ]
    }
