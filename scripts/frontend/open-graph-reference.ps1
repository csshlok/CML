param(
  [string]$Path = "apps/desktop/design/reference/graphify_graph_sample.html"
)

$resolved = Resolve-Path -LiteralPath $Path -ErrorAction Stop
Start-Process $resolved.Path
