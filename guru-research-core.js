(function(root,factory){const api=factory();if(typeof module==="object"&&module.exports)module.exports=api;else root.GuruResearchCore=api})(typeof globalThis!=="undefined"?globalThis:this,function(){
  const LENSES=["Buffett","Lynch","Graham","Greenblatt","Innovation","Momentum"];
  function number(value){if(value==null||value===""||typeof value==="boolean")return null;const parsed=Number(value);return Number.isFinite(parsed)?parsed:null}
  function percent(value,digits=1){const parsed=number(value);return parsed==null?"평가 대기":`${parsed>=0?"+":""}${(parsed*100).toFixed(digits)}%`}
  function score(value){const parsed=number(value);return parsed==null?"-":Math.round(parsed)}
  function tone(value){const parsed=number(value);if(parsed==null)return"waiting";if(parsed>=70)return"strong";if(parsed>=50)return"neutral";return"weak"}
  function escape(value){return String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[char])}
  function strongest(scores={}){return LENSES.filter(key=>number(scores[key])!=null).sort((a,b)=>Number(scores[b])-Number(scores[a]))}
  function remainingDays(metric={}){const total=Number(metric.tradingDays)||0,elapsed=Number(metric.elapsedTradingDays)||0;return Math.max(0,total-elapsed)}
  return{LENSES,number,percent,score,tone,escape,strongest,remainingDays};
});
