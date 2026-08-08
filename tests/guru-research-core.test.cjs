const test=require("node:test");const assert=require("node:assert/strict");const core=require("../guru-research-core.js");
test("formats returns and pending values",()=>{assert.equal(core.percent(.12),"+12.0%");assert.equal(core.percent(null),"평가 대기")});
test("orders lens strengths without inventing missing scores",()=>{const keys=core.strongest({Buffett:70,Lynch:null,Graham:40,Momentum:90});assert.deepEqual(keys,["Momentum","Buffett","Graham"])});
test("calculates remaining trading days",()=>{assert.equal(core.remainingDays({tradingDays:63,elapsedTradingDays:21}),42)});
