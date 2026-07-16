(function () {
  "use strict";

  if (!window.QqqRebalanceCore || !document.getElementById("qqqRebalance")) return;

  const core = window.QqqRebalanceCore;
  const base = {
    defaultRequest: window.qqqDefaultRequest,
    loadRequest: window.qqqLoadRequest,
    readRequest: window.qqqReadRequest,
    fieldSet: window.qqqFieldSet,
    validate: window.qqqValidate,
    calculate: window.calculateQqqRebalance,
    render: window.qqqRenderPlan,
    statusLabel: window.qqqStatusLabel,
    statusTone: window.qqqStatusTone,
    ticketText: window.qqqTicketText,
    csvText: window.qqqCsvText,
    init: window.initQqqRebalancer,
  };

  function insertUpgradeUi() {
    const targetField = document.getElementById("qqqTargetCashPct")?.closest(".reb-field");
    const cashField = document.getElementById("qqqUsdCash")?.closest(".reb-field");
    const bandField = document.getElementById("qqqNoTradeBand")?.closest(".reb-field");
    if (!targetField || document.getElementById("qqqAllocationModeBlock")) return;

    const style = document.createElement("style");
    style.textContent = `
      .qqq-span-2{grid-column:1/-1}.qqq-upgrade-panel{padding:15px;border:1px solid rgba(66,215,255,.22);border-radius:16px;background:rgba(66,215,255,.055)}
      .qqq-mode-row{display:flex;gap:10px;flex-wrap:wrap}.qqq-mode-row label{display:flex;align-items:center;gap:7px;min-height:40px;padding:8px 11px;border:1px solid rgba(255,255,255,.1);border-radius:12px;background:rgba(4,8,18,.45);color:#e6eefc;font-weight:850}
      .qqq-budget-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px}.qqq-budget-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px}
      .qqq-budget-stat{padding:10px;border-radius:12px;background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.08)}.qqq-budget-stat span{display:block;color:#9da8bf;font-size:11px;font-weight:850}.qqq-budget-stat b{display:block;margin-top:5px;font-size:17px}
      .qqq-cash-warning{margin-top:12px;padding:12px;border-radius:14px;background:rgba(245,200,107,.08);border:1px solid rgba(245,200,107,.25);color:#ffe8b1;font-size:12px;line-height:1.55}
      @media(max-width:700px){.qqq-budget-grid,.qqq-budget-summary{grid-template-columns:1fr 1fr}.qqq-span-2{grid-column:auto}.qqq-mode-row label{width:100%}}
    `;
    document.head.appendChild(style);

    const mode = document.createElement("div");
    mode.id = "qqqAllocationModeBlock";
    mode.className = "qqq-upgrade-panel qqq-span-2";
    mode.innerHTML = `
      <div class="reb-field"><label>목표비중 결정 방식</label><div class="qqq-mode-row">
        <label><input type="radio" name="qqqAllocationMode" value="loss_budget" checked> 손실예산으로 계산</label>
        <label><input type="radio" name="qqqAllocationMode" value="direct"> 현금비중 직접 입력</label>
      </div></div>
      <div class="qqq-budget-grid" id="qqqLossBudgetFields">
        <div class="reb-field"><label for="qqqMaxAccountLoss">감당 가능한 계좌 손실 (%)</label><input class="reb-input" id="qqqMaxAccountLoss" type="number" min="0" max="100" step="1" value="30"></div>
        <div class="reb-field"><label for="qqqStressDrop">QQQ 스트레스 하락률 (%)</label><input class="reb-input" id="qqqStressDrop" type="number" min="0.01" max="100" step="1" value="70"></div>
        <div class="reb-field"><label for="qqqTargetRounding">비중 내림 단위 (%p)</label><input class="reb-input" id="qqqTargetRounding" type="number" min="0.01" max="100" step="1" value="5"></div>
      </div>
      <div class="qqq-budget-summary">
        <div class="qqq-budget-stat"><span>계산상 QQQ 상한</span><b id="qqqRawTargetPct">42.86%</b></div>
        <div class="qqq-budget-stat"><span>적용 QQQ 비중</span><b id="qqqAppliedTargetPct">40.00%</b></div>
        <div class="qqq-budget-stat"><span>적용 현금 비중</span><b id="qqqAppliedCashPct">60.00%</b></div>
        <div class="qqq-budget-stat"><span>단순 스트레스 손실</span><b id="qqqStressLossPct">28.00%</b></div>
      </div>
      <p class="reb-note">손실예산 ÷ QQQ 스트레스 하락률로 QQQ 비중 상한을 계산한 뒤 지정 단위로 내립니다. 추천이나 수익률 최적화가 아닌 단순 위험 한도입니다.</p>
    `;
    targetField.parentElement.insertBefore(mode, targetField);

    const contribution = document.createElement("div");
    contribution.className = "reb-field";
    contribution.innerHTML = `<label for="qqqNewContribution">이번 달 신규 자금 ($)</label><input class="reb-input" id="qqqNewContribution" type="number" min="0" step="0.01" value="0"><span class="reb-note" style="margin:0">현재 달러 예수금에 아직 포함하지 않은 금액만 입력합니다.</span>`;
    cashField.parentElement.insertBefore(contribution, cashField);

    const cashFlow = document.createElement("div");
    cashFlow.className = "reb-field";
    cashFlow.innerHTML = `<label>현금흐름 우선</label><div class="qqq-radio-row"><label><input type="checkbox" id="qqqCashFlowFirst" checked> 밴드 안에서는 신규 자금만 부족한 쪽에 사용</label></div>`;
    bandField.parentElement.insertBefore(cashFlow, bandField.nextSibling);

    const accountNote = document.createElement("div");
    accountNote.className = "qqq-cash-warning";
    accountNote.textContent = "이 화면의 현금은 달러 전략계좌 안의 대기자금입니다. 원화 생활비와 비상금은 전략계좌 밖에서 별도로 관리하세요.";
    document.getElementById("qqqFetchPriceBtn")?.closest("article")?.appendChild(accountNote);

    const subtitle = document.querySelector("#qqqRebalance .section-head p");
    if (subtitle) subtitle.textContent = "감당 가능한 손실로 QQQ 비중을 정하고, 월 1회 밴드를 벗어날 때만 수동 리밸런싱합니다.";
    const ops = document.querySelectorAll("#qqqRebalance .qqq-ops > div");
    if (ops[1]) ops[1].innerHTML = "<b>2.</b> 손실예산 또는 직접 입력으로 목표비중을 정합니다. 손실예산은 추천값이 아니라 위험 한도입니다.";
    if (ops[2]) ops[2].innerHTML = "<b>3.</b> ±5%p 밴드 안에서는 매매하지 않고, 신규 자금이 있으면 부족한 자산에 먼저 사용합니다.";
    if (ops[3]) ops[3].innerHTML = "<b>4.</b> 밴드 밖이면 목표비중으로 복귀하되 실제 주문은 사용자가 직접 검토하고 실행합니다.";
  }

  function deriveFromRequest(req) {
    return core.deriveTarget(req);
  }

  window.qqqDefaultRequest = function () {
    return {
      ...base.defaultRequest(),
      allocation_mode: "loss_budget",
      target_cash_pct: 60,
      max_account_loss_pct: 30,
      qqq_stress_drop_pct: 70,
      target_rounding_pp: 5,
      new_contribution_usd: 0,
      cash_flow_first: true,
      no_trade_band_percentage_points: 5,
    };
  };

  window.qqqLoadRequest = function () {
    const request = base.loadRequest();
    try {
      const saved = JSON.parse(localStorage.getItem(QQQ_REBALANCE_STORAGE_KEY) || "null");
      if (saved?.__save_inputs && !Object.prototype.hasOwnProperty.call(saved, "allocation_mode")) request.allocation_mode = "direct";
    } catch (error) {}
    return { ...window.qqqDefaultRequest(), ...request };
  };

  window.qqqFieldSet = function (req) {
    base.fieldSet(req);
    const set = (id, value) => { const element = document.getElementById(id); if (element) element.value = value ?? ""; };
    document.querySelectorAll('input[name="qqqAllocationMode"]').forEach((input) => { input.checked = input.value === (req.allocation_mode || "loss_budget"); });
    set("qqqMaxAccountLoss", req.max_account_loss_pct ?? 30);
    set("qqqStressDrop", req.qqq_stress_drop_pct ?? 70);
    set("qqqTargetRounding", req.target_rounding_pp ?? 5);
    set("qqqNewContribution", req.new_contribution_usd ?? 0);
    const cashFlow = document.getElementById("qqqCashFlowFirst");
    if (cashFlow) cashFlow.checked = req.cash_flow_first !== false;
    window.updateQqqTargetDisplay();
  };

  window.qqqReadRequest = function () {
    const request = base.readRequest();
    const mode = document.querySelector('input[name="qqqAllocationMode"]:checked')?.value || "loss_budget";
    const extended = {
      ...request,
      allocation_mode: mode,
      max_account_loss_pct: qqqNum("qqqMaxAccountLoss"),
      qqq_stress_drop_pct: qqqNum("qqqStressDrop"),
      target_rounding_pp: qqqNum("qqqTargetRounding"),
      new_contribution_usd: qqqNum("qqqNewContribution"),
      cash_flow_first: Boolean(document.getElementById("qqqCashFlowFirst")?.checked),
    };
    try {
      const target = deriveFromRequest(extended);
      extended.target_cash_pct = target.target_cash_weight_pct;
    } catch (error) {}
    return extended;
  };

  window.updateQqqTargetDisplay = function () {
    const mode = document.querySelector('input[name="qqqAllocationMode"]:checked')?.value || "loss_budget";
    const cashInput = document.getElementById("qqqTargetCashPct");
    const lossFields = document.getElementById("qqqLossBudgetFields");
    if (cashInput) cashInput.disabled = mode === "loss_budget";
    if (lossFields) lossFields.style.display = mode === "loss_budget" ? "grid" : "none";
    const request = {
      allocation_mode: mode,
      target_cash_pct: Number(cashInput?.value),
      max_account_loss_pct: Number(document.getElementById("qqqMaxAccountLoss")?.value),
      qqq_stress_drop_pct: Number(document.getElementById("qqqStressDrop")?.value),
      target_rounding_pp: Number(document.getElementById("qqqTargetRounding")?.value),
    };
    try {
      const target = deriveFromRequest(request);
      if (mode === "loss_budget" && cashInput) cashInput.value = target.target_cash_weight_pct.toFixed(2);
      const values = {
        qqqTargetQqqPct: target.target_qqq_weight_pct,
        qqqRawTargetPct: target.raw_qqq_weight_pct,
        qqqAppliedTargetPct: target.target_qqq_weight_pct,
        qqqAppliedCashPct: target.target_cash_weight_pct,
      };
      Object.entries(values).forEach(([id, value]) => { const element = document.getElementById(id); if (element) element.textContent = `${value.toFixed(2)}%`; });
      const stress = document.getElementById("qqqStressLossPct");
      if (stress) stress.textContent = target.simple_stress_loss_pct == null ? "직접 입력" : `${target.simple_stress_loss_pct.toFixed(2)}%`;
    } catch (error) {
      ["qqqTargetQqqPct", "qqqRawTargetPct", "qqqAppliedTargetPct", "qqqAppliedCashPct", "qqqStressLossPct"].forEach((id) => { const element = document.getElementById(id); if (element) element.textContent = "-"; });
    }
  };

  window.qqqValidate = function (req) {
    const errors = base.validate(req);
    if (req.new_contribution_usd < 0) errors.push("신규 자금은 음수일 수 없습니다.");
    try { deriveFromRequest(req); } catch (error) { errors.push(error.message); }
    return [...new Set(errors)];
  };

  function applyCandidate(plan, candidate) {
    return {
      ...plan,
      suggested_quantity: candidate.quantity,
      estimated_execution_price: candidate.execution_price,
      estimated_order_notional: candidate.estimated_order_notional,
      estimated_fee: candidate.estimated_fee,
      estimated_total_cash_flow: candidate.estimated_total_cash_flow,
      required_cash_equivalent_liquidation: candidate.required_cash_equivalent_liquidation,
      projected_usd_cash: candidate.projected_usd_cash,
      projected_qqq_value: candidate.projected_qqq_value,
      projected_qqq_weight: candidate.projected_qqq_weight,
      projected_cash_weight: candidate.projected_cash_weight,
      remaining_weight_drift: candidate.remaining_weight_drift,
    };
  }

  window.calculateQqqRebalance = function (request) {
    let target;
    try { target = deriveFromRequest(request); } catch (error) {
      const invalid = base.calculate({ ...request, target_cash_pct: request.target_cash_pct });
      return { ...invalid, reason: error.message, warnings: [...new Set([...(invalid.warnings || []), error.message])] };
    }
    const effective = {
      ...request,
      target_cash_pct: target.target_cash_weight_pct,
      usd_cash: qqqMoney(request.usd_cash + request.new_contribution_usd),
    };
    let plan = base.calculate(effective);
    const driftPp = plan.current_qqq_weight == null ? 0 : (plan.current_qqq_weight - plan.target_qqq_weight) * 100;
    const band = core.bandBounds(target.target_qqq_weight_pct, request.no_trade_band_percentage_points);
    const withinBand = plan.current_qqq_weight != null && Math.abs(driftPp) <= request.no_trade_band_percentage_points + 1e-9;
    const useContribution = core.shouldUseContribution({
      cash_flow_first: request.cash_flow_first,
      within_band: withinBand,
      drift_pp: driftPp,
      new_contribution_usd: request.new_contribution_usd,
    });

    if (plan.status !== "INVALID_INPUT" && useContribution) {
      const exec = qqqExecutionPrice("BUY", effective);
      const desiredNotional = Math.min(request.new_contribution_usd, Math.max(0, plan.raw_order_delta));
      const desiredQty = desiredNotional / exec;
      const contributionCandidate = qqqBestCandidate("BUY", desiredQty, effective, plan.target_qqq_weight, request.new_contribution_usd, false);
      const aboveMinimum = contributionCandidate.estimated_order_notional + 0.005 >= request.minimum_order_notional_usd;
      if (contributionCandidate.quantity > 0 && aboveMinimum) {
        plan = applyCandidate(plan, contributionCandidate);
        plan.status = "CASH_FLOW_BUY";
        plan.action = "BUY_QQQ";
        plan.reason = `무거래 밴드 안이지만 신규 자금 ${qqqUsd(request.new_contribution_usd)} 중 필요한 범위만 QQQ 부족분에 사용합니다.`;
        plan.warnings = [...(plan.warnings || []).filter((warning) => !warning.includes("최종 판단은 HOLD")), "기존 현금성 자산을 매도하지 않고 신규 자금만 사용합니다."];
      }
    }

    return {
      ...plan,
      allocation_mode: target.mode,
      raw_target_qqq_weight: target.raw_qqq_weight_pct / 100,
      simple_stress_loss: target.simple_stress_loss_pct == null ? null : target.simple_stress_loss_pct / 100,
      new_contribution_usd: request.new_contribution_usd,
      cash_flow_first: request.cash_flow_first,
      no_trade_band_lower: band.lower_pct / 100,
      no_trade_band_upper: band.upper_pct / 100,
      calculation_version: "30gogo-qqq-loss-budget-v2",
    };
  };

  window.qqqStatusLabel = function (status) {
    if (status === "CASH_FLOW_BUY") return "신규 자금 매수";
    return base.statusLabel(status);
  };
  window.qqqStatusTone = function (status) {
    if (status === "CASH_FLOW_BUY") return "";
    return base.statusTone(status);
  };

  window.qqqRenderPlan = function (payload) {
    base.render(payload);
    const { request, plan } = payload;
    const cards = document.getElementById("qqqResultCards");
    if (cards && plan.total_equity != null) {
      const mode = plan.allocation_mode === "loss_budget" ? "손실예산" : "직접 입력";
      const stress = plan.simple_stress_loss == null ? "-" : qqqPct(plan.simple_stress_loss);
      cards.innerHTML += [
        ["비중 산정", mode],
        ["무거래 구간", `${qqqPct(plan.no_trade_band_lower)} ~ ${qqqPct(plan.no_trade_band_upper)}`],
        ["이번 달 신규 자금", qqqUsd(plan.new_contribution_usd)],
        ["단순 스트레스 손실", stress],
      ].map((item) => `<div class="qqq-result-card"><span>${item[0]}</span><b>${item[1]}</b></div>`).join("");
    }
    const rows = document.getElementById("qqqPlanRows");
    if (rows && plan.exact_rebalance) {
      rows.innerHTML += [
        ["비중 산정 방식", plan.allocation_mode === "loss_budget" ? "손실예산" : "직접 입력", plan.allocation_mode === "loss_budget" ? "손실예산" : "직접 입력"],
        ["신규 자금", qqqUsd(request.new_contribution_usd), plan.status === "CASH_FLOW_BUY" ? `${qqqUsd(plan.estimated_order_notional)} 매수에 사용` : "현금 버킷에 반영"],
        ["무거래 구간", `${qqqPct(plan.no_trade_band_lower)} ~ ${qqqPct(plan.no_trade_band_upper)}`, qqqStatusLabel(plan.status)],
      ].map((item) => `<tr><td>${item[0]}</td><td>${item[1]}</td><td>${item[2]}</td></tr>`).join("");
    }
    const json = document.getElementById("qqqPlanJson");
    if (json) json.value = JSON.stringify(payload, null, 2);
  };

  window.qqqTicketText = function (payload) {
    const extra = [
      `비중 산정 방식: ${payload.plan.allocation_mode === "loss_budget" ? "손실예산" : "직접 입력"}`,
      `이번 달 신규 자금: ${qqqUsd(payload.request.new_contribution_usd)}`,
      `무거래 구간: ${qqqPct(payload.plan.no_trade_band_lower)} ~ ${qqqPct(payload.plan.no_trade_band_upper)}`,
      `현금흐름 우선: ${payload.request.cash_flow_first ? "사용" : "미사용"}`,
      "원화 생활비·비상금은 전략계좌 밖에서 별도 관리",
      "",
    ].join("\n");
    return `${extra}${base.ticketText(payload)}`;
  };

  window.qqqCsvText = function (payload) {
    const extra = [
      ["request", "allocation_mode", payload.request.allocation_mode],
      ["request", "max_account_loss_pct", payload.request.max_account_loss_pct],
      ["request", "qqq_stress_drop_pct", payload.request.qqq_stress_drop_pct],
      ["request", "target_rounding_pp", payload.request.target_rounding_pp],
      ["request", "new_contribution_usd", payload.request.new_contribution_usd],
      ["request", "cash_flow_first", payload.request.cash_flow_first],
      ["plan", "no_trade_band_lower", payload.plan.no_trade_band_lower],
      ["plan", "no_trade_band_upper", payload.plan.no_trade_band_upper],
      ["plan", "simple_stress_loss", payload.plan.simple_stress_loss],
    ];
    return `${base.csvText(payload)}\n${extra.map((row) => row.map(qqqCsvEscape).join(",")).join("\n")}`;
  };

  window.initQqqRebalancer = function () {
    base.init();
    const ids = ["qqqMaxAccountLoss", "qqqStressDrop", "qqqTargetRounding", "qqqNewContribution"];
    ids.forEach((id) => document.getElementById(id)?.addEventListener("input", () => {
      window.updateQqqTargetDisplay();
      if (qqqLastPayload) qqqClearResult();
    }));
    document.querySelectorAll('input[name="qqqAllocationMode"],#qqqCashFlowFirst').forEach((element) => element.addEventListener("change", () => {
      window.updateQqqTargetDisplay();
      if (qqqLastPayload) qqqClearResult();
    }));
    window.updateQqqTargetDisplay();
  };

  insertUpgradeUi();
})();
