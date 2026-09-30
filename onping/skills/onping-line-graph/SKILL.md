---
name: onping-line-graph
description: Build OnPing line graph / chart widgets in Dhall
allowed-tools:
  - Read
---

# OnPing Line Graph Chart — Dhall Schema Reference

## Reference template

`docs/helpful_templates/single_run_chart.dhall` in the plunger_lift_optimizer repo.

---

## Top-level record

```dhall
{ title : Text
, timePeriod : Integer          -- minutes shown on x-axis (e.g. +60, +1440)
, timeUnit : Text               -- "minute"
, updateInterval : Integer      -- refresh interval in seconds (e.g. +60)
, yAxes : List YAxis
, eventParameters : List EventParameter
, maxStep : Integer             -- +1 for continuous, higher for stepped
, normalizeValue : Bool         -- normalize all series to 0-1
, latestValueLine : Optional Bool
, legendWithCurrentValue : Bool
}
```

## Y-Axis record

```dhall
{ opposite : Bool               -- False = left axis, True = right axis
, description : Text            -- axis label
, scale : Text                  -- "linear" or "logarithmic"
, rangeMin : Optional Integer   -- None Integer for auto, Some +N for fixed
, rangeMax : Optional Integer
, parameters : List Parameter
}
```

## Parameter record

```dhall
{ pid : Optional { type : Text, value : Integer }
    -- { type = "PID", value = +12345 }  for hardware PIDs
    -- { type = "VPID", value = +12345 } for virtual PIDs
    -- None { type : Text, value : Integer } for placeholder
, name : Text                   -- internal reference name
, display_name_config : DisplayNameConfig
, graph_type : Text             -- "line" or "column"
, color : Text                  -- hex "#0758bb" or rgba "rgba(0,112,0,1)"
, line_width : Double           -- e.g. 1.0, 2.0
, hidden : Bool                 -- True = hidden by default (toggle on in UI)
}
```

## Event Parameter record

```dhall
{ pid : Optional { type : Text, value : Integer }
, name : Text
, display_name_config : DisplayNameConfig
, should_display : Bool         -- show event marker on chart
, icon : Text                   -- FontAwesome icon name: "dot-circle-o", "bell", "drop", etc.
, color : Text
, hidden : Bool
}
```

## DisplayNameConfig union type

This is the trickiest part of the schema. Full Dhall type:

```dhall
let DisplayParameter =
      < DisplayParameterPID : { _1 : Natural, _2 : List Text }
      | DisplayParameterVPID :
          { _1 : Natural
          , _2 : < VPIDName | InputMetadata : List Text >
          }
      >

let DisplayNameConfig =
      < DisplayByText : Text
      | DisplayByParameter : DisplayParameter
      | DisplayByOtherParameter : DisplayParameter
      >
```

### Variants

**DisplayByText** — static label (most common):
```dhall
< DisplayByText : Text
| DisplayByParameter : ...
| DisplayByOtherParameter : ...
>.DisplayByText "My Label"
```

**DisplayByParameter** — dynamic name from the parameter's own metadata:
```dhall
.DisplayByParameter
  ( < DisplayParameterPID : { _1 : Natural, _2 : List Text }
    | DisplayParameterVPID : ...
    >.DisplayParameterPID
      { _1 = 500027, _2 = [ "parameterName", "locationName" ] }
  )
```
`_1` = PID number, `_2` = metadata fields to concatenate for the display name.

**DisplayByOtherParameter** — dynamic name from a *different* parameter's metadata. Same inner structure as DisplayByParameter.

**DisplayParameterVPID** — for virtual PIDs:
```dhall
.DisplayParameterVPID
  { _1 = 12345
  , _2 = < VPIDName | InputMetadata : List Text >.VPIDName
  }
```

---

## Design patterns

### Dual-axis overlay
Put related series on one axis, context on another:
```dhall
-- Left axis (opposite = False): primary metric
-- Right axis (opposite = True): secondary/context metric with fixed range
{ opposite = True, rangeMin = Some +0, rangeMax = Some +1, ... }
```

### Column vs Line
- Use `"column"` for discrete per-cycle values (rewards, counts) — bars prevent misleading interpolation
- Use `"line"` for continuous time series (pressures, flow rates, progress)

### Hidden by default
Set `hidden = True` for context parameters that would clutter the default view. Users can toggle them on in the OnPing UI.

### PID vs VPID
- Hardware sensor readings use `type = "PID"`
- Computed/ML outputs use `type = "PID"` (they are still OnPing PIDs, just written by scripts)
- True virtual parameters use `type = "VPID"`

### Event parameters
- Use for binary state changes (valve open/close) or discrete events (plunger arrival)
- Render as vertical markers/icons on the chart timeline
- `icon` values: `"dot-circle-o"` (state change), `"bell"` (alert/arrival), `"drop"` (fluid event)

### Color conventions
Common colors used across charts:
- Blue: `"#0758bb"` or `"rgba(0, 0, 239, 1)"` — primary series, plunger progress
- Green: `"rgba(0, 112, 0, 1)"` or `"rgba(0, 255, 0, 1)"` — casing pressure, rewards
- Red: `"rgba(241, 14, 14, 1)"` — alerts, simulated values
- Gray: `"#888888"` — background context series
