(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  root.StockDetailCore=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  function number(value){
    const parsed=Number(value);
    return Number.isFinite(parsed)?parsed:0;
  }

  function normalizeCandles(rows){
    return (Array.isArray(rows)?rows:[]).map(row=>({
      timestamp:String(row?.timestamp||""),
      open:number(row?.openPrice),
      high:number(row?.highPrice),
      low:number(row?.lowPrice),
      close:number(row?.closePrice),
      volume:number(row?.volume),
      currency:String(row?.currency||""),
    })).filter(row=>row.timestamp&&row.close>0).sort((a,b)=>a.timestamp.localeCompare(b.timestamp));
  }

  function movingAverage(values,period){
    const source=(Array.isArray(values)?values:[]).map(number);
    const size=Math.max(1,Math.trunc(number(period)));
    let sum=0;
    return source.map((value,index)=>{
      sum+=value;
      if(index>=size)sum-=source[index-size];
      return index+1<size?null:sum/size;
    });
  }

  function selectRange(daily,intraday,range){
    const dayRows=normalizeCandles(daily);
    const minuteRows=normalizeCandles(intraday);
    if(range==="1D"&&minuteRows.length)return minuteRows;
    const limits={"1M":22,"3M":66,"6M":130,"1Y":200};
    return dayRows.slice(-Math.min(dayRows.length,limits[range]||limits["3M"]));
  }

  function rangeStats(rows){
    const normalized=normalizeCandles(rows);
    if(!normalized.length)return{open:0,high:0,low:0,close:0,volume:0,changeRate:0};
    const first=normalized[0],last=normalized[normalized.length-1];
    return{
      open:last.open,
      high:Math.max(...normalized.map(row=>row.high)),
      low:Math.min(...normalized.map(row=>row.low)),
      close:last.close,
      volume:last.volume,
      changeRate:first.close?(last.close-first.close)/first.close:0,
    };
  }

  return{normalizeCandles,movingAverage,selectRange,rangeStats};
});
