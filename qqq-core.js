(function (root, factory) {
  const api = factory();
  root.QqqRebalanceCore = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function finiteNumber(value, name) {
    const number = Number(value);
    if (!Number.isFinite(number)) throw new Error(`${name}은(는) 유효한 숫자여야 합니다.`);
    return number;
  }

  function deriveTarget(input) {
    const mode = input.allocation_mode === "direct" ? "direct" : "loss_budget";
    if (mode === "direct") {
      const targetCashPct = finiteNumber(input.target_cash_pct, "목표 현금비중");
      if (targetCashPct < 0 || targetCashPct > 100) throw new Error("목표 현금비중은 0 이상 100 이하여야 합니다.");
      return {
        mode,
        raw_qqq_weight_pct: 100 - targetCashPct,
        target_qqq_weight_pct: 100 - targetCashPct,
        target_cash_weight_pct: targetCashPct,
        simple_stress_loss_pct: null,
      };
    }

    const maxLossPct = finiteNumber(input.max_account_loss_pct, "감당 가능한 계좌 손실");
    const stressDropPct = finiteNumber(input.qqq_stress_drop_pct, "QQQ 스트레스 하락률");
    const roundingPp = finiteNumber(input.target_rounding_pp, "비중 내림 단위");
    if (maxLossPct < 0 || maxLossPct > 100) throw new Error("감당 가능한 계좌 손실은 0 이상 100 이하여야 합니다.");
    if (stressDropPct <= 0 || stressDropPct > 100) throw new Error("QQQ 스트레스 하락률은 0 초과 100 이하여야 합니다.");
    if (roundingPp <= 0 || roundingPp > 100) throw new Error("비중 내림 단위는 0 초과 100 이하여야 합니다.");

    const rawQqqPct = Math.min(100, Math.max(0, (maxLossPct / stressDropPct) * 100));
    const targetQqqPct = Math.min(100, Math.max(0, Math.floor((rawQqqPct + 1e-10) / roundingPp) * roundingPp));
    return {
      mode,
      raw_qqq_weight_pct: rawQqqPct,
      target_qqq_weight_pct: targetQqqPct,
      target_cash_weight_pct: 100 - targetQqqPct,
      simple_stress_loss_pct: (targetQqqPct * stressDropPct) / 100,
    };
  }

  function bandBounds(targetQqqPct, bandPp) {
    const target = finiteNumber(targetQqqPct, "목표 QQQ 비중");
    const band = finiteNumber(bandPp, "무거래 밴드");
    if (band < 0) throw new Error("무거래 밴드는 음수일 수 없습니다.");
    return {
      lower_pct: Math.max(0, target - band),
      upper_pct: Math.min(100, target + band),
    };
  }

  function shouldUseContribution(input) {
    return Boolean(
      input.cash_flow_first &&
      input.within_band &&
      Number(input.drift_pp) < 0 &&
      Number(input.new_contribution_usd) > 0
    );
  }

  return { deriveTarget, bandBounds, shouldUseContribution };
});
