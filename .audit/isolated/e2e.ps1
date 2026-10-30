$ErrorActionPreference = "Stop"
$B = "http://127.0.0.1:8199/api"
$pass = 0; $fail = 0
function Step($n, $block) {
  try { $r = & $block; Write-Output ("PASS  {0}" -f $n); $script:pass++; return $r }
  catch { Write-Output ("FAIL  {0} :: {1}" -f $n, $_.Exception.Message.Substring(0,[Math]::Min(200,$_.Exception.Message.Length))); $script:fail++; return $null }
}

Write-Output "===== 1. create goal ====="
$goal = Step "POST /goals" {
  Invoke-RestMethod "$B/goals" -Method Post -ContentType "application/json" -Body (@{
    title="E2E 测试目标：掌握 grep 日志排查"
    domain_key="cs_it"
    motivation="排查线上错误日志"
    application_context="在真实项目中快速定位异常"
    current_level="零基础"
    time_budget="共 10 小时"
    hard_constraints="每章必须给出可复现命令`n禁止出现第 X 天等日程表述"
    capability_level="L2"
    generation_tier="fast"
    generate_extra_exercises=$true
  } | ConvertTo-Json)
}
if (-not $goal) { Write-Output "ABORT: no goal"; exit 1 }
$gid = $goal.id
Write-Output "  goal id=$gid status=$($goal.status) tier=$($goal.generation_tier) level=$($goal.capability_level) demo=$($goal.demo)"

Write-Output "===== 2. diagnose ====="
$d = Step "POST /goals/{id}/diagnose" { Invoke-RestMethod "$B/goals/$gid/diagnose" -Method Post -ContentType "application/json" -Body "{}" }
if ($d) { Write-Output "  recommendation present: $([bool]$d.recommendation); demo=$($d.demo)" }

Write-Output "===== 3. decision ====="
Step "POST /goals/{id}/decision" { Invoke-RestMethod "$B/goals/$gid/decision" -Method Post -ContentType "application/json" -Body (@{decision="proceed";reason="E2E"}|ConvertTo-Json) } | Out-Null

Write-Output "===== 4. plan ====="
$p = Step "POST /goals/{id}/plan" { Invoke-RestMethod "$B/goals/$gid/plan" -Method Post -ContentType "application/json" -Body "{}" }
if ($p) { Write-Output "  steps=$($p.steps.Count) status=$($p.status)" }

Write-Output "===== 5. criteria ====="
$c = Step "POST /goals/{id}/criteria" { Invoke-RestMethod "$B/goals/$gid/criteria" -Method Post -ContentType "application/json" -Body "{}" }
if ($c) { Write-Output "  criteria=$($c.Count) first-status=$($c[0].status)" }

Write-Output "===== 6. confirm-all ====="
$ca = Step "POST /goals/{id}/criteria/confirm-all" { Invoke-RestMethod "$B/goals/$gid/criteria/confirm-all" -Method Post -ContentType "application/json" -Body "{}" }
if ($ca) { Write-Output "  confirmed=$($ca.confirmed) changed=$($ca.changed)" }

Write-Output "===== 7. usage ====="
$u = Step "GET /goals/{id}/usage" { Invoke-RestMethod "$B/goals/$gid/usage" }
if ($u) { Write-Output "  total_tokens=$($u.totals.total_tokens) source=$($u.totals.usage_source) by_feature=$($u.by_feature.Count)" }

Write-Output "===== 8. goal status advanced ====="
$g2 = Invoke-RestMethod "$B/goals/$gid"
Write-Output "  status=$($g2.status)"

Write-Output ""
Write-Output ("SUMMARY pass=$pass fail=$fail")
Write-Output "GOAL_ID=$gid"
