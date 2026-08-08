(function(){
  const core=()=>window.StockDetailCore;
  const state={context:null,ticker:"",detail:null,range:"3M",quotes:new Map(),bound:false,loading:false,timer:0};
  const priceFormatters={
    KRW:new Intl.NumberFormat("ko-KR",{style:"currency",currency:"KRW",maximumFractionDigits:0}),
    USD:new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}),
  };
  const compactPriceFormatters={
    KRW:new Intl.NumberFormat("ko-KR",{style:"currency",currency:"KRW",notation:"compact",maximumFractionDigits:2}),
    USD:new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",notation:"compact",maximumFractionDigits:2}),
  };
  const numberFormatter=new Intl.NumberFormat("ko-KR",{maximumFractionDigits:2});
  const compactFormatter=new Intl.NumberFormat("ko-KR",{notation:"compact",maximumFractionDigits:1});

  function normalizedCandles(rows){
    if(core()?.normalizeCandles)return core().normalizeCandles(rows);
    return (Array.isArray(rows)?rows:[]).map(row=>({timestamp:String(row?.timestamp||""),open:Number(row?.openPrice)||0,high:Number(row?.highPrice)||0,low:Number(row?.lowPrice)||0,close:Number(row?.closePrice)||0,volume:Number(row?.volume)||0,currency:String(row?.currency||"")})).filter(row=>row.timestamp&&row.close>0).sort((a,b)=>a.timestamp.localeCompare(b.timestamp));
  }

  function average(values,period){
    if(core()?.movingAverage)return core().movingAverage(values,period);
    let sum=0;
    return values.map((value,index)=>{sum+=Number(value)||0;if(index>=period)sum-=Number(values[index-period])||0;return index+1<period?null:sum/period});
  }

  function selectedRange(daily,intraday,range){
    if(core()?.selectRange)return core().selectRange(daily,intraday,range);
    const dayRows=normalizedCandles(daily),minuteRows=normalizedCandles(intraday);
    if(range==="1D"&&minuteRows.length)return minuteRows;
    const limits={"1M":22,"3M":66,"6M":130,"1Y":200};
    return dayRows.slice(-(limits[range]||66));
  }

  function candleStats(rows){
    const source=Array.isArray(rows)?rows:[];
    const values=source.some(row=>Number(row?.close)>0)?source:normalizedCandles(source);
    if(!values.length)return{open:0,high:0,low:0,close:0,volume:0,changeRate:0};
    return{open:values.at(-1).open,high:Math.max(...values.map(row=>row.high)),low:Math.min(...values.map(row=>row.low)),close:values.at(-1).close,volume:values.at(-1).volume,changeRate:values[0].close?(values.at(-1).close-values[0].close)/values[0].close:0};
  }

  function escapeHtml(value){
    return String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  }

  function heldAssets(){
    return (state.context?.getAssets?.()||[]).filter(asset=>asset.theme!=="Cash"&&asset.ticker!=="CASH");
  }

  function selectedAsset(){
    return heldAssets().find(asset=>asset.ticker===state.ticker)||heldAssets()[0]||null;
  }

  function guruRow(){
    return state.context?.getGuruRow?.(state.ticker)||null;
  }

  function iconText(asset){
    const words=String(asset.name||"").trim().split(/\s+/).filter(Boolean);
    if(words.length>1)return words.slice(0,2).map(word=>word[0]).join("").toUpperCase();
    return words[0]?.slice(0,2).toUpperCase()||String(asset.ticker||"").slice(0,2).toUpperCase();
  }

  function logoBackdrop(){
    return"#f7f8fa";
  }

  function companyMark(asset){
    const safeTicker=String(asset.ticker||"").replace(/[^A-Z0-9.-]/gi,"");
    const logo=safeTicker?`assets/company-logos/${encodeURIComponent(safeTicker)}.png`:"";
    const fallback=escapeHtml(iconText(asset));
    return `<span class="company-mark-fallback">${fallback}</span>${logo?`<img src="${escapeHtml(logo)}" alt="" loading="lazy" decoding="async">`:""}`;
  }

  function marketPrice(value,currency="KRW"){
    const amount=Number(value);
    if(!Number.isFinite(amount))return"-";
    return (priceFormatters[currency]||priceFormatters.KRW).format(amount);
  }

  function percent(value){
    const amount=Number(value);
    if(!Number.isFinite(amount))return"-";
    return `${amount>=0?"+":""}${(amount*100).toFixed(Math.abs(amount)>=.1?1:2)}%`;
  }

  function plainPercent(value){
    const amount=Number(value);
    return Number.isFinite(amount)?`${(amount*100).toFixed(Math.abs(amount)>=.1?1:2)}%`:"-";
  }

  function signedPrice(value,currency){
    const amount=Number(value);
    if(!Number.isFinite(amount))return"-";
    return `${amount>=0?"+":"-"}${marketPrice(Math.abs(amount),currency)}`;
  }

  function dateTime(value){
    if(!value)return"-";
    const date=new Date(value);
    return Number.isNaN(date.getTime())?String(value):date.toLocaleString("ko-KR",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false});
  }

  function metric(value,suffix=""){
    const amount=Number(value);
    return Number.isFinite(amount)?`${numberFormatter.format(amount)}${suffix}`:"-";
  }

  function renderRails(){
    const assets=heldAssets();
    const html=assets.map(asset=>{
      const quote=state.quotes.get(asset.ticker);
      const row=state.context?.getGuruRow?.(asset.ticker);
      const change=Number(quote?.changeRate??(row?.changePct!=null?Number(row.changePct)/100:null));
      const currency=quote?.currency||row?.currency||"KRW";
      const price=quote?.lastPrice??row?.price;
      const active=asset.ticker===state.ticker;
      return `<a class="holding-chip${active?" active":""}" href="#stocks/${encodeURIComponent(asset.ticker)}" data-stock-ticker="${escapeHtml(asset.ticker)}" aria-label="${escapeHtml(asset.name)} 상세 현황 열기" style="--stock-color:${escapeHtml(asset.color||"#42d7ff")};--logo-bg:${logoBackdrop(asset.ticker)}">
        <span class="company-mark">${companyMark(asset)}</span>
        <span class="holding-chip-copy"><b>${escapeHtml(asset.name)}</b><small>${escapeHtml(asset.ticker)}</small></span>
        <span class="holding-chip-price"><b>${price!=null?escapeHtml(marketPrice(price,currency)):"-"}</b><small class="${change>=0?"pos":"neg"}">${Number.isFinite(change)?escapeHtml(percent(change)):"시세 대기"}</small></span>
      </a>`;
    }).join("");
    ["holdingIconRail","stockWorkspaceRail"].forEach(id=>{
      const rail=document.getElementById(id);
      if(!rail)return;
      rail.innerHTML=html;
    });
  }

  function tickerFromHash(){
    const match=location.hash.match(/^#stocks\/([^/?]+)/);
    return match?decodeURIComponent(match[1]).toUpperCase():"";
  }

  function bindEvents(){
    if(state.bound)return;
    state.bound=true;
    document.addEventListener("click",event=>{
      const rangeButton=event.target.closest("[data-stock-range]");
      if(rangeButton){state.range=rangeButton.dataset.stockRange;renderRangeControls();renderPriceChart();renderMarketStats()}
    });
    document.addEventListener("error",event=>{
      if(event.target instanceof HTMLImageElement&&event.target.matches(".company-mark img,.stock-company-mark img"))event.target.remove();
    },true);
    document.getElementById("stockRefreshBtn")?.addEventListener("click",()=>loadDetail(true));
  }

  function renderRangeControls(){
    document.querySelectorAll("[data-stock-range]").forEach(button=>button.classList.toggle("active",button.dataset.stockRange===state.range));
  }

  function select(ticker,navigate=false){
    if(!heldAssets().some(asset=>asset.ticker===ticker))return;
    state.ticker=ticker;
    state.detail=null;
    try{localStorage.setItem("30gogo.stockDetail.ticker",ticker)}catch{}
    renderRails();
    renderAll();
    if(navigate)state.context?.setView?.("stocks",true);
    if(state.context?.isLocalRuntime?.())loadDetail();
  }

  function currentCandles(){
    return selectedRange(state.detail?.dailyCandles,state.detail?.intradayCandles,state.range);
  }

  function dailyChangeRate(){
    const rows=normalizedCandles(state.detail?.dailyCandles);
    if(rows.length>1)return rows.at(-2).close?(rows.at(-1).close-rows.at(-2).close)/rows.at(-2).close:0;
    return (Number(guruRow()?.changePct)||0)/100;
  }

  function renderHeader(){
    const asset=selectedAsset();
    if(!asset)return;
    const detail=state.detail||{};
    const quote=detail.quote;
    const stock=detail.stock;
    const row=guruRow();
    const currency=quote?.currency||stock?.currency||row?.currency||"KRW";
    const price=quote?.lastPrice??row?.price??(asset.quantity?asset.value/asset.quantity:0);
    const change=dailyChangeRate();
    const marketCap=Number(stock?.sharesOutstanding)*Number(price);
    const companyMarkElement=document.getElementById("stockCompanyMark");
    companyMarkElement.innerHTML=companyMark(asset);
    companyMarkElement.style.setProperty("--stock-color",asset.color||"#42d7ff");
    companyMarkElement.style.setProperty("--logo-bg",logoBackdrop(asset.ticker));
    document.getElementById("stockName").textContent=stock?.name||asset.name;
    document.getElementById("stockIdentity").textContent=[detail.symbol||asset.ticker,stock?.market,stock?.securityType].filter(Boolean).join(" · ");
    document.getElementById("stockLastPrice").textContent=marketPrice(price,currency);
    const changeElement=document.getElementById("stockDailyChange");
    changeElement.textContent=percent(change);
    changeElement.className=`stock-change ${change>=0?"pos":"neg"}`;
    document.getElementById("stockLiveStatus").textContent=detail.fetchedAt?"Toss 실시간":"암호화 스냅샷";
    document.getElementById("stockLiveStatus").className=`stock-live-pill ${detail.fetchedAt?"live":"snapshot"}`;
    document.getElementById("stockUpdatedAt").textContent=detail.fetchedAt?`갱신 ${dateTime(quote?.timestamp||detail.fetchedAt)}`:`스냅샷 ${dateTime(row?.marketAsOf||state.context?.getGeneratedAt?.())}`;
    document.getElementById("stockMarketCap").textContent=marketCap>0?`${(compactPriceFormatters[currency]||compactPriceFormatters.KRW).format(marketCap)} 시가총액`:"발행주식 정보 대기";
  }

  function renderPriceChart(){
    const rows=currentCandles();
    const canvas=document.getElementById("stockPriceChart");
    if(!canvas)return;
    if(!rows.length){state.context?.destroyChart?.("stockPriceChart");canvas.parentElement.classList.add("is-empty");return}
    canvas.parentElement.classList.remove("is-empty");
    const isMinute=state.range==="1D";
    const labels=rows.map(row=>new Date(row.timestamp).toLocaleString("ko-KR",isMinute?{hour:"2-digit",minute:"2-digit",hour12:false}:{month:"2-digit",day:"2-digit"}));
    const closes=rows.map(row=>row.close);
    const up=closes.at(-1)>=closes[0];
    const color=up?"#35d399":"#fb7185";
    const datasets=[
      {type:"line",label:"종가",data:closes,borderColor:color,backgroundColor:up?"rgba(53,211,153,.08)":"rgba(251,113,133,.08)",fill:true,tension:.2,pointRadius:0,borderWidth:2,yAxisID:"y"},
      {type:"line",label:"MA 5",data:average(closes,5),borderColor:"#f5c86b",pointRadius:0,borderWidth:1.2,tension:.18,yAxisID:"y"},
      {type:"line",label:"MA 20",data:average(closes,20),borderColor:"#42d7ff",pointRadius:0,borderWidth:1.2,tension:.18,yAxisID:"y"},
      {type:"bar",label:"거래량",data:rows.map(row=>row.volume),backgroundColor:"rgba(148,163,184,.2)",borderWidth:0,yAxisID:"volume",barPercentage:1,categoryPercentage:1},
    ];
    state.context?.makeChart?.("stockPriceChart",{type:"line",data:{labels,datasets},options:{maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{legend:{position:"bottom",labels:{color:"#aeb8ca",boxWidth:10,usePointStyle:true}},tooltip:{callbacks:{label:item=>item.dataset.yAxisID==="volume"?`거래량 ${compactFormatter.format(item.parsed.y)}`:`${item.dataset.label} ${marketPrice(item.parsed.y,rows.at(-1).currency||"KRW")}`}}},scales:{x:{ticks:{color:"#7f8ba3",maxTicksLimit:10,maxRotation:0},grid:{display:false}},y:{position:"right",ticks:{color:"#9da8bf",callback:value=>marketPrice(value,rows.at(-1).currency||"KRW")},grid:{color:"rgba(255,255,255,.065)"}},volume:{position:"left",display:false,beginAtZero:true,grid:{display:false},suggestedMax:Math.max(...rows.map(row=>row.volume))*4}}}});
  }

  function renderMarketStats(){
    const rows=currentCandles();
    const stats=candleStats(rows);
    const currency=rows.at(-1)?.currency||state.detail?.quote?.currency||guruRow()?.currency||"KRW";
    const daily=normalizedCandles(state.detail?.dailyCandles);
    const range=candleStats(daily);
    const items=[
      ["시가",marketPrice(stats.open,currency)],
      ["기간 고가",marketPrice(stats.high,currency)],
      ["기간 저가",marketPrice(stats.low,currency)],
      ["기간 등락",percent(stats.changeRate)],
      ["최근 거래량",compactFormatter.format(stats.volume||0)],
      ["200거래일 범위",range.low?`${marketPrice(range.low,currency)} - ${marketPrice(range.high,currency)}`:"-"],
    ];
    const panel=document.getElementById("stockMarketStats");
    panel.dataset.candleCount=String(rows.length);
    panel.dataset.dailyCandleCount=String(state.detail?.dailyCandles?.length||0);
    panel.innerHTML=items.map(([label,value])=>`<div><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`).join("");
  }

  function holdingAmount(container,key){
    const value=container?.[key];
    if(value==null)return null;
    return typeof value==="object"?(value.amountAfterCost??value.amount??null):value;
  }

  function renderHolding(){
    const asset=selectedAsset();
    if(!asset)return;
    const holding=state.detail?.holding;
    const currency=holding?.currency||"KRW";
    const live=Boolean(holding);
    const quantity=Number(holding?.quantity??asset.quantity);
    const average=live?Number(holding.averagePurchasePrice):(quantity?asset.cost/quantity:0);
    const marketValue=live?Number(holdingAmount(holding.marketValue,"amount")):Number(asset.value);
    const profit=live?Number(holdingAmount(holding.profitLoss,"amount")):Number(asset.profit);
    const profitRate=live?Number(holding.profitLoss?.rate):Number(asset.returnRate);
    const dailyProfit=live?Number(holdingAmount(holding.dailyProfitLoss,"amount")):null;
    const dailyRate=live?Number(holding.dailyProfitLoss?.rate):dailyChangeRate();
    document.getElementById("stockHoldingSummary").innerHTML=`
      <div class="stock-summary-row"><span>보유수량</span><b>${escapeHtml(numberFormatter.format(quantity))}주</b></div>
      <div class="stock-summary-row"><span>평균 매입가</span><b>${escapeHtml(marketPrice(average,currency))}</b></div>
      <div class="stock-summary-row"><span>평가금액</span><b>${escapeHtml(live?marketPrice(marketValue,currency):state.context.money(marketValue))}</b></div>
      <div class="stock-summary-row"><span>총 손익</span><b class="${profit>=0?"pos":"neg"}">${escapeHtml(live?signedPrice(profit,currency):`${profit>=0?"+":""}${state.context.money(profit)}`)} · ${escapeHtml(percent(profitRate))}</b></div>
      <div class="stock-summary-row"><span>오늘 손익</span><b class="${dailyRate>=0?"pos":"neg"}">${dailyProfit==null?"-":escapeHtml(signedPrice(dailyProfit,currency))} · ${escapeHtml(percent(dailyRate))}</b></div>
      <div class="stock-summary-row"><span>전체 비중</span><b>${escapeHtml(plainPercent(asset.weight))}</b></div>`;
  }

  function renderCompany(){
    const asset=selectedAsset();
    const stock=state.detail?.stock;
    const rows=[
      ["영문명",stock?.englishName||asset?.name],
      ["시장",stock?.market||"-"],
      ["증권 유형",stock?.securityType||asset?.theme||"-"],
      ["상장 상태",stock?.status||"-"],
      ["상장일",stock?.listDate||"-"],
      ["발행주식수",stock?.sharesOutstanding?numberFormatter.format(Number(stock.sharesOutstanding)):"-"],
      ["ISIN",stock?.isinCode||"-"],
      ["통화",stock?.currency||guruRow()?.currency||"KRW"],
    ];
    document.getElementById("stockCompanyInfo").innerHTML=rows.map(([label,value])=>`<div class="stock-summary-row"><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`).join("");
  }

  function renderOrderbook(){
    const book=state.detail?.orderbook;
    const currency=book?.currency||state.detail?.quote?.currency||"KRW";
    const asks=(book?.asks||[]).slice(0,7).reverse();
    const bids=(book?.bids||[]).slice(0,7);
    const maxVolume=Math.max(1,...asks.concat(bids).map(row=>Number(row.volume)||0));
    const rows=asks.map(row=>["ask",row]).concat(bids.map(row=>["bid",row]));
    document.getElementById("stockOrderbook").innerHTML=rows.length?rows.map(([side,row])=>`<div class="orderbook-row ${side}"><span>${side==="ask"?"매도":"매수"}</span><b>${escapeHtml(marketPrice(row.price,currency))}</b><span>${escapeHtml(compactFormatter.format(Number(row.volume)||0))}</span><i style="width:${Math.max(4,(Number(row.volume)||0)/maxVolume*100)}%"></i></div>`).join(""):'<div class="stock-empty">현재 호가 데이터가 없습니다.</div>';
  }

  function renderTrades(){
    const rows=(state.detail?.trades||[]).slice(0,12);
    document.getElementById("stockTrades").innerHTML=rows.length?`<table><thead><tr><th>시각</th><th>체결가</th><th>수량</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${escapeHtml(dateTime(row.timestamp))}</td><td>${escapeHtml(marketPrice(row.price,row.currency))}</td><td>${escapeHtml(numberFormatter.format(Number(row.volume)||0))}</td></tr>`).join("")}</tbody></table>`:'<div class="stock-empty">현재 체결 데이터가 없습니다.</div>';
  }

  function renderGuru(){
    const row=guruRow();
    const panel=document.getElementById("stockGuruSnapshot");
    if(!row){panel.innerHTML='<div class="stock-empty">평가 스냅샷이 없습니다.</div>';state.context?.destroyChart?.("stockGuruChart");return}
    const metrics=row.metrics||{};
    const metricRows=[
      ["PER",metric(metrics.pe,"배")],["PBR",metric(metrics.pb,"배")],["PSR",metric(metrics.ps,"배")],
      ["ROE",percent(metrics.roe)],["영업이익률",percent(metrics.operatingMargin)],["매출 성장",percent(metrics.revenueGrowth)],
      ["부채/자본",percent(metrics.debtEquity)],["배당수익률",percent(metrics.dividendYield)],
    ];
    panel.innerHTML=`<div class="stock-score-head"><div><span>종합 점수</span><b>${escapeHtml(row.finalScore??"-")} / 100</b></div><strong>${escapeHtml(row.signal||"점검")}</strong></div><div class="stock-metric-grid">${metricRows.map(([label,value])=>`<div><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`).join("")}</div><p>${escapeHtml(row.comment||"-")}</p><small>${escapeHtml(row.dataStatus||"snapshot")} · ${escapeHtml(row.marketAsOf||state.context.getGuruAsOf?.()||"-")} · 실시간 토스 시세와 별도 평가 스냅샷</small>`;
    const entries=Object.entries(row.scores||{});
    if(entries.length)state.context?.makeChart?.("stockGuruChart",{type:"radar",data:{labels:entries.map(([key])=>key),datasets:[{label:"평가 렌즈",data:entries.map(([,value])=>Number(value)||0),borderColor:"#f5c86b",backgroundColor:"rgba(245,200,107,.12)",pointBackgroundColor:"#f5c86b",borderWidth:1.5}]},options:{maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{r:{min:0,max:100,ticks:{display:false},grid:{color:"rgba(255,255,255,.1)"},angleLines:{color:"rgba(255,255,255,.1)"},pointLabels:{color:"#aeb8ca",font:{size:10}}}}}});
  }

  function renderPositionHistory(){
    const history=state.context?.getHistory?.()?.snapshots||[];
    const points=history.map(snapshot=>{
      const position=(snapshot.positions||[]).find(item=>item.ticker===state.ticker);
      return position?{time:snapshot.asOf,value:Number(position.valueKrw)||0,profit:Number(position.profitKrw)||0}:null;
    }).filter(Boolean);
    if(!points.length){state.context?.destroyChart?.("stockPositionChart");return}
    state.context?.makeChart?.("stockPositionChart",{type:"line",data:{labels:points.map(point=>dateTime(point.time)),datasets:[{label:"평가금액",data:points.map(point=>point.value),borderColor:selectedAsset()?.color||"#42d7ff",backgroundColor:"rgba(66,215,255,.07)",fill:true,pointRadius:0,borderWidth:1.6,tension:.15}]},options:{maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:item=>state.context.money(item.parsed.y)}}},scales:{x:{ticks:{color:"#7f8ba3",maxTicksLimit:8,maxRotation:0},grid:{display:false}},y:{position:"right",ticks:{color:"#9da8bf",callback:value=>state.context.compactMoney(value)},grid:{color:"rgba(255,255,255,.065)"}}}}});
  }

  function renderErrors(){
    const errors=state.detail?.errors||{};
    const messages=Object.values(errors).filter(Boolean);
    const notice=document.getElementById("stockDataNotice");
    if(!state.context?.isLocalRuntime?.())notice.textContent="GitHub Pages에서는 암호화 스냅샷만 표시합니다. 실시간 토스 데이터는 Mac 로컬 화면에서 연결됩니다.";
    else if(messages.length)notice.textContent=`일부 실시간 항목을 불러오지 못했습니다: ${messages.join(" · ")}`;
    else notice.textContent="시세·종목정보·캔들·호가·체결·보유현황은 토스 공식 OpenAPI를 읽기 전용으로 조회합니다.";
  }

  function renderAll(){
    renderHeader();renderRangeControls();renderPriceChart();renderMarketStats();renderHolding();renderCompany();renderOrderbook();renderTrades();renderGuru();renderPositionHistory();renderErrors();
  }

  async function loadPortfolioQuotes(){
    if(!state.context?.isLocalRuntime?.())return;
    try{
      const response=await fetch("/__local/portfolio-quotes",{cache:"no-store"});
      if(!response.ok)throw new Error("시세 목록 조회 실패");
      const payload=await response.json();
      state.quotes=new Map((payload.items||[]).map(item=>[item.ticker,item]));
      renderRails();
    }catch{}
  }

  async function loadDetail(force=false){
    if(state.loading||!state.ticker||!state.context?.isLocalRuntime?.())return;
    state.loading=true;
    document.getElementById("stockRefreshBtn")?.classList.add("loading");
    try{
      const response=await fetch(`/__local/stock-detail?ticker=${encodeURIComponent(state.ticker)}${force?`&refresh=${Date.now()}`:""}`,{cache:"no-store"});
      const payload=await response.json();
      if(!response.ok)throw new Error(payload.message||"종목 상세 조회 실패");
      state.detail=payload;
      if(payload.quote)state.quotes.set(state.ticker,{ticker:state.ticker,...payload.quote,changeRate:dailyChangeRate()});
      renderRails();
      renderAll();
    }catch(error){
      state.detail={errors:{detail:error.message}};
      renderAll();
    }finally{
      state.loading=false;
      document.getElementById("stockRefreshBtn")?.classList.remove("loading");
    }
  }

  function initialize(context){
    state.context=context;
    bindEvents();
    const saved=(()=>{try{return localStorage.getItem("30gogo.stockDetail.ticker")}catch{return""}})();
    const initial=heldAssets().some(asset=>asset.ticker===saved)?saved:heldAssets()[0]?.ticker;
    if(!state.ticker)state.ticker=initial||"";
    renderRails();
    renderAll();
    loadPortfolioQuotes();
    if(document.body.classList.contains("view-stocks"))loadDetail();
    if(!state.timer)state.timer=window.setInterval(()=>{
      if(document.body.classList.contains("view-stocks")){loadPortfolioQuotes();loadDetail(true)}
    },60_000);
  }

  function activate(){
    const hashTicker=tickerFromHash();
    if(hashTicker&&heldAssets().some(asset=>asset.ticker===hashTicker)&&hashTicker!==state.ticker){
      state.ticker=hashTicker;
      state.detail=null;
      try{localStorage.setItem("30gogo.stockDetail.ticker",hashTicker)}catch{}
    }
    renderRails();
    renderAll();
    loadPortfolioQuotes();
    loadDetail();
  }

  window.StockDetailUI={initialize,activate,refresh(){renderRails();renderHolding();renderPositionHistory()}};
})();
