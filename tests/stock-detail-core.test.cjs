const test = require("node:test");
const assert = require("node:assert/strict");
const Core = require("../stock-detail-core.js");

const candles = Array.from({ length: 30 }, (_, index) => ({
  timestamp: `2026-07-${String(index + 1).padStart(2, "0")}T09:00:00+09:00`,
  openPrice: String(100 + index),
  highPrice: String(102 + index),
  lowPrice: String(99 + index),
  closePrice: String(101 + index),
  volume: String(1000 + index),
  currency: "USD",
}));

test("normalizeCandles sorts rows and converts decimal strings", () => {
  const rows = Core.normalizeCandles([candles[1], candles[0]]);
  assert.equal(rows[0].close, 101);
  assert.equal(rows[1].volume, 1001);
});

test("movingAverage waits for a complete window", () => {
  assert.deepEqual(Core.movingAverage([1, 2, 3, 4], 3), [null, null, 2, 3]);
});

test("selectRange prefers minute candles for one day and limits month rows", () => {
  const minuteRows = candles.slice(0, 3);
  assert.equal(Core.selectRange(candles, minuteRows, "1D").length, 3);
  assert.equal(Core.selectRange(candles, minuteRows, "1M").length, 22);
});

test("rangeStats reports range extremes and first-to-last change", () => {
  const stats = Core.rangeStats(candles.slice(0, 3));
  assert.equal(stats.low, 99);
  assert.equal(stats.high, 104);
  assert.equal(stats.close, 103);
  assert.equal(stats.changeRate, (103 - 101) / 101);
});
