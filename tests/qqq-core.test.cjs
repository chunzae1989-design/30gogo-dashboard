const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../qqq-core.js");

test("30% 손실예산과 70% 스트레스는 QQQ 40%, 현금 60%로 내림한다", () => {
  const target = core.deriveTarget({
    allocation_mode: "loss_budget",
    max_account_loss_pct: 30,
    qqq_stress_drop_pct: 70,
    target_rounding_pp: 5,
  });
  assert.equal(target.target_qqq_weight_pct, 40);
  assert.equal(target.target_cash_weight_pct, 60);
  assert.equal(target.simple_stress_loss_pct, 28);
  assert.ok(Math.abs(target.raw_qqq_weight_pct - 42.8571428571) < 1e-8);
});

test("직접 입력 모드는 입력한 현금비중을 그대로 사용한다", () => {
  const target = core.deriveTarget({ allocation_mode: "direct", target_cash_pct: 45 });
  assert.equal(target.target_qqq_weight_pct, 55);
  assert.equal(target.target_cash_weight_pct, 45);
  assert.equal(target.simple_stress_loss_pct, null);
});

test("무거래 밴드는 0~100% 범위로 제한한다", () => {
  assert.deepEqual(core.bandBounds(3, 5), { lower_pct: 0, upper_pct: 8 });
  assert.deepEqual(core.bandBounds(98, 5), { lower_pct: 93, upper_pct: 100 });
});

test("밴드 안에서 QQQ가 부족할 때만 신규 자금 우선 규칙을 사용한다", () => {
  assert.equal(core.shouldUseContribution({ cash_flow_first: true, within_band: true, drift_pp: -2, new_contribution_usd: 500 }), true);
  assert.equal(core.shouldUseContribution({ cash_flow_first: true, within_band: true, drift_pp: 2, new_contribution_usd: 500 }), false);
  assert.equal(core.shouldUseContribution({ cash_flow_first: true, within_band: false, drift_pp: -7, new_contribution_usd: 500 }), false);
});

test("잘못된 스트레스 입력은 거부한다", () => {
  assert.throws(() => core.deriveTarget({ allocation_mode: "loss_budget", max_account_loss_pct: 30, qqq_stress_drop_pct: 0, target_rounding_pp: 5 }), /0 초과/);
});
